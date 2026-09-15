"""The Interviewer: which question to ask next, and when to stop asking.

This is the one place in the system where a model, not code, decides what happens
next — and its autonomy is narrow on purpose. The candidates come from
`relevant_questions`, which is deterministic and tested; the wording comes from the
catalogue (ADR 0001); the model chooses among the candidates, writes the one sentence
that introduces the question, and decides when the interview is over.

`decide` is a pure function of the state. The measurement harness calls it in a loop,
a graph node will call it between two interrupts, and neither has to know about the
other (docs/SPRINT_AGENTIC_MVP.md, on the work order).

What it is expected to do better than the filter alone, which is what
`eval/agent_score.py` measures:

- stop when itemising cannot beat the Pauschbetrag, however much is still unasked.
  Half the profiles in the evaluation set are in that position, and no filter can
  see it: relevance and effect on the outcome are different questions;
- ask the questions that decide most of the amount first, which matters when
  somebody abandons the interview halfway;
- treat "I don't know" as information rather than as a question still open.

Everything the model can get wrong is guarded here rather than trusted: a question id
outside the candidate list is refused, a repeat is refused, and a failed call falls
back to the filter's own choice so that an interview never dies of a provider error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from domain.estimate import Estimate, estimate
from domain.fields import GATE_FIELDS
from domain.questions import BY_ID, CATALOGUE, Question, open_items, relevant_questions

MAX_ROUNDS = 40
"""A safety net, not a working range.

The number comes from the catalogue rather than from taste: the deterministic filter
needs up to 26 questions on the busiest evaluation profile, so a limit of 20 — which
is what this said before the catalogue existed — cut a legitimate interview short and
scored the truncation as the agent asking fewer questions. Forty leaves room for the
repeated items the catalogue does not collect yet.

Reaching it means the loop is not converging. The case is then escalated to the user
with whatever has been collected, never silently finished.
"""


@dataclass(frozen=True)
class Ask:
    question: Question
    rationale: str
    # Which purchase of a repeating category this asks about. Decided by code and
    # never by the model: the model chooses *what* to ask, and which of three invoices
    # is still missing a price is arithmetic (#35).
    item_index: int = 0
    from_model: bool = True
    # True when the code vetoed a premature conclusion and substituted a gate
    # question. Not a provider failure and not the model's choice: its own column
    # in the measurement.
    forced_gate: bool = False


@dataclass(frozen=True)
class Conclude:
    reason: str
    from_model: bool = True


Decision = Ask | Conclude


class Chat(Protocol):
    """The provider call this module needs, and nothing more.

    Narrow on purpose: the tests pass a fake, and no test in the ordinary suite talks
    to a provider.
    """

    async def chat_raw(self, messages: list[dict],
                       tools: Optional[list[dict]] = None) -> tuple[dict, dict]:
        ...


TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "ask_question",
            "description": (
                "Ask the user one of the listed candidate questions. Choose the one "
                "that most affects the deductible total, or that closes off the "
                "largest number of further questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "string",
                        "description": "Exactly one id from the candidate list.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": (
                            "One sentence to the user explaining why this is being "
                            "asked, in their language. No tax advice, no figures the "
                            "case does not contain."
                        ),
                    },
                },
                "required": ["question_id", "rationale"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "conclude_interview",
            "description": (
                "Propose ending the interview; the user confirms or declines. Use it "
                "when every relevant question is answered, or when the deductible "
                "total cannot plausibly reach the Pauschbetrag so that further "
                "questions cannot change the outcome. Unavailable until every gate "
                "question is answered — the code will substitute the missing gate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "One sentence for the user on why it is over.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]

SYSTEM = """You conduct a short interview to prepare the deductible work expenses
(Werbungskosten) section of a German income tax return, Anlage N, for tax year 2025.

You do not write questions. You choose one from the candidate list you are given, or
you end the interview. The candidates are already filtered: every one of them is
relevant to this user and unanswered, so there is no such thing as an irrelevant
choice here — only a better or worse ordered one.

Judge by two things:

- Money. A question that can move the total by hundreds of euros comes before one
  worth twenty. If the user stops answering halfway, what they answered should be
  the part that mattered.
- Whether it is worth continuing at all. The flat allowance (Pauschbetrag) of
  1,230 EUR is granted without any proof. If the itemised total cannot plausibly
  reach it, the honest thing is to end the interview and say so: the user gains
  nothing by answering more, and being told that early is worth more than a longer
  interview. Do not end it merely because the current total is low — end it when the
  categories still open could not realistically close the gap.

Ending the interview is a proposal, not a decision: the user confirms it or carries
on. And it is only open to you once every gate question — bought anything for work,
own phone used, moved, applied for jobs, paid for training, worked from home — has
been answered. Before that you do not know what remains; you would be guessing, and
a wrong guess here costs the user money.

Never invent a question, a figure or a rule. Never give tax advice. One tool call per
turn."""


GATE_QUESTIONS = {q.key: q for q in CATALOGUE
                  if q.category is None and q.key in GATE_FIELDS}


def _forced_gate(known: dict[str, Any], asked: frozenset[str]) -> Optional[Ask]:
    """The code's veto on ending too early.

    A conclusion is only meaningful once every gate is addressed — answered, or asked
    and met with "I don't know". Until then the set of remaining categories is not
    known but guessed, and the first live run showed what the guess costs: the model
    ended profile p08 at 743 EUR, never having asked the education gate that hid an
    1,800 EUR category. A gate that does not yet apply (works_remotely before the
    employment months are known) cannot be forced and is not: the deterministic
    fallback asks its prerequisite instead.
    """
    for gate in GATE_FIELDS:
        question = GATE_QUESTIONS[gate]
        if (known.get(gate) is None and question.id not in asked
                and question.applies(known)):
            return Ask(question, "", from_model=False, forced_gate=True)
    return None


def decide_deterministically(known: dict[str, Any], asked: frozenset[str]) -> Decision:
    """What the filter would do: the first open candidate, or stop.

    Used as the fallback when the model cannot be reached or answers unusably, and as
    the control arm the agent is measured against.
    """
    for candidate in open_items(known):
        if candidate.key not in asked:
            return Ask(candidate.question, "", item_index=candidate.item_index,
                       from_model=False)
    return Conclude("every relevant question is answered", from_model=False)


async def decide(
    known: dict[str, Any],
    asked: frozenset[str],
    chat: Optional[Chat] = None,
) -> Decision:
    """Choose the next question, or conclude. One provider call.

    With no `chat` this is the deterministic filter, which is what keeps the module
    importable and testable without a provider.
    """
    # Keyed by the qualified key, not by the question id: the same question about a
    # second purchase is a different ask, and an `asked` set of bare ids would make
    # the interview believe it had already collected the second invoice.
    open_now = [o for o in open_items(known) if o.key not in asked]
    # One entry per question for the model, lowest open purchase first. It picks what
    # to ask; the code picks which item, which is not a judgement.
    by_id: dict[str, int] = {}
    for candidate in open_now:
        by_id.setdefault(candidate.question.id, candidate.item_index)
    candidates = [BY_ID[qid] for qid in by_id]
    if not candidates:
        return Conclude("every relevant question is answered", from_model=False)
    if chat is None:
        return decide_deterministically(known, asked)

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": _state_prompt(known, asked, candidates)},
    ]

    try:
        message, _usage = await chat.chat_raw(messages, tools=TOOLS)
    except Exception:  # noqa: BLE001 — a provider failure must not end the interview
        return decide_deterministically(known, asked)

    return _read_decision(message, candidates, known, asked, by_id)


# --- prompt ---------------------------------------------------------------------

def _state_prompt(known: dict[str, Any], asked: frozenset[str],
                  candidates: list[Question]) -> str:
    est = estimate(known)
    lines = [
        f"Answered so far: {len(asked)} questions.",
        f"Deductible total from what is known: {est.total_eur:.2f} EUR.",
        f"Pauschbetrag: {est.pauschbetrag:.0f} EUR.",
    ]
    if not est.beats_pauschbetrag:
        lines.append(
            f"Still {est.gap_to_pauschbetrag:.2f} EUR short of being worth itemising."
        )
    else:
        lines.append("Already worth itemising.")

    if est.per_category:
        lines.append("")
        lines.append("Per category so far:")
        for category, entry in est.per_category.items():
            state = f"{entry.amount_eur:.2f} EUR" if entry.computable else "incomplete"
            lines.append(f"- {category.value}: {state}")

    lines.append("")
    lines.append("Known values:")
    lines.extend(f"- {key} = {value!r}" for key, value in sorted(known.items()))

    lines.append("")
    lines.append("Candidate questions, any of which may be asked next:")
    for question in candidates:
        spec = question.spec()
        where = question.category.value if question.category else "profile"
        lines.append(
            f"- {question.id} [{where}, {spec.answer_type.value}"
            f"{', optional' if not spec.required else ''}]: {question.text['en']}"
        )
    return "\n".join(lines)


# --- reading the model's answer -------------------------------------------------

def _read_decision(message: dict, candidates: list[Question],
                   known: dict[str, Any], asked: frozenset[str],
                   item_of: Optional[dict[str, int]] = None) -> Decision:
    """Take the tool call apart, refusing anything the model was not offered.

    A model naming a question outside the candidate list is the failure this guards
    against: without the check it would ask something already answered, or irrelevant
    to this profile, and both would show up in the measurement as the agent's own
    doing rather than as a bug.
    """
    calls = message.get("tool_calls") or []
    by_id = {q.id: q for q in candidates}
    # Which purchase each offered question is about, worked out before the call. The
    # model picks the question; the item is not its decision to make (#35).
    item_of = item_of or {}

    for call in calls:
        function = call.get("function") or {}
        name = function.get("name")
        try:
            args = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            continue

        if name == "conclude_interview":
            forced = _forced_gate(known, asked)
            if forced is not None:
                return forced
            return Conclude(str(args.get("reason") or "").strip() or "the interview is over")

        if name == "ask_question":
            question = by_id.get(str(args.get("question_id") or "").strip())
            if question is None:
                continue  # not on offer; try the next call, then fall back
            rationale = str(args.get("rationale") or "").strip()
            return Ask(question, rationale, item_index=item_of.get(question.id, 0))

    return decide_deterministically(known, asked)


# --- for the harness ------------------------------------------------------------

def summarise(known: dict[str, Any]) -> Estimate:
    """The estimate the Interviewer judged by, for a transcript to record."""
    return estimate(known)


def question_by_id(question_id: str) -> Question:
    return BY_ID[question_id]
