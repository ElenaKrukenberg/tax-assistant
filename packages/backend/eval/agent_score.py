"""Agent against filter against form, on the same profiles.

Three arms, because two would flatter the agent (ADR 0009). The form asks all 35
catalogue questions; the filter alone asks 14 to 26 with no model involved. The only
number that says anything about the agent is the difference between it and the
filter — and the difference has to be paid for in questions saved *without* losing a
required field, or it is not a saving.

What the agent is expected to do that the filter cannot:

- end the interview when itemising cannot beat the Pauschbetrag. Five of the ten
  profiles are in that position, and the filter cannot see it, because relevance and
  effect on the outcome are different things;
- ask the questions that decide most of the amount first.

Run it:
    python -m eval.agent_score                        # every profile
    python -m eval.agent_score p03 p07                # only these
    python -m eval.agent_score --no-llm               # the filter as the agent, wiring
    python -m eval.agent_score --label after-x        # a second run of the same model

Results land in eval/results/agent-score-<model>[-<label>].json, next to the RAG runs.
An existing file is never overwritten: a run of the same model on a different day is a
new measurement, and the old one is the evidence for whatever a document already claims
about it. Without a label the second run stops and asks for one.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from agents.interviewer import MAX_ROUNDS, Ask, Conclude, decide
from core.config import get_settings
from core.llm import OpenRouterClient
from core.pricing import cost_usd
from domain.estimate import estimate
from domain.questions import relevant_questions
from eval.baseline import (
    DONT_KNOW,
    Profile,
    Transcript,
    load_profiles,
    run_filter,
    run_questionnaire,
)

RESULTS = Path(__file__).parent / "results"


@dataclass
class AgentRun:
    """One agent interview, with what it cost and what it left undone."""

    profile_id: str
    asked: list[str] = field(default_factory=list)
    unanswered: list[str] = field(default_factory=list)
    known: dict[str, Any] = field(default_factory=dict)
    rationales: list[str] = field(default_factory=list)
    fell_back: int = 0
    gates_forced: int = 0
    concluded_by_model: bool = False
    hit_round_limit: bool = False
    conclude_reason: str = ""
    candidates_left_at_end: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0

    @property
    def question_count(self) -> int:
        return len(self.asked)


async def run_agent_interview(profile: Profile, chat: Optional[Any]) -> AgentRun:
    """Drive `decide` until it concludes, recording everything worth measuring."""
    run = AgentRun(profile_id=profile.id)
    started = time.monotonic()

    for _ in range(MAX_ROUNDS):
        decision = await decide(dict(run.known), frozenset(run.asked), chat)

        if isinstance(decision, Conclude):
            run.concluded_by_model = decision.from_model
            run.conclude_reason = decision.reason
            break

        if getattr(decision, "forced_gate", False):
            run.gates_forced += 1
        elif not decision.from_model:
            run.fell_back += 1

        question = decision.question
        run.asked.append(question.id)
        if decision.rationale:
            run.rationales.append(f"{question.id}: {decision.rationale}")

        answer = profile.answer(question)
        if answer is DONT_KNOW:
            run.unanswered.append(question.id)
        else:
            run.known[question.key] = answer
    else:
        # The loop ran out without anybody concluding: the interview was cut off, not
        # finished. Counting that as a saving is how a truncation becomes a flattering
        # number — which is exactly what happened the first time this ran, when the
        # limit was below what the busiest profile legitimately needs.
        run.hit_round_limit = True

    run.candidates_left_at_end = len(
        [q for q in relevant_questions(run.known) if q.id not in set(run.asked)]
    )
    run.seconds = round(time.monotonic() - started, 2)

    if chat is not None:
        # Usage is per call; the client returns it, so total it as we go rather than
        # guessing from token counts afterwards.
        run.prompt_tokens = getattr(chat, "prompt_tokens", 0)
        run.completion_tokens = getattr(chat, "completion_tokens", 0)
    return run


class CountingChat:
    """Wraps the provider client and adds up what the interview cost."""

    def __init__(self, client: OpenRouterClient):
        self.client = client
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0

    async def chat_raw(self, messages: list[dict], tools: Optional[list[dict]] = None):
        message, usage = await self.client.chat_raw(messages, tools=tools)
        self.calls += 1
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        return message, usage


# --- scoring --------------------------------------------------------------------

def score(profile: Profile, form: Transcript, filt: Transcript, agent: AgentRun) -> dict:
    """The comparison, with the agent's saving only counted when no figure was lost.

    Two kinds of unfilled field, split on purpose after the first live run: a
    missing amount field means a wrong figure; a missing placement or plausibility
    field is reported but not punished, because it could not have moved a euro.
    Stopping is a proposal the user confirms, so what is scored is whether the
    proposal was right — the profile says where stopping early is correct.
    """
    amount_missing = _missing_amount(agent.known)
    checks_missing = [k for k in _missing_required(agent.known) if k not in amount_missing]
    filter_missing = filt.missing_required()
    est_agent = estimate(agent.known)
    est_filter = estimate(filt.known)
    short = not est_filter.beats_pauschbetrag

    stopped_early = agent.concluded_by_model and agent.candidates_left_at_end > 0
    stop_early_ok = bool(profile.expected.get("stop_early_ok"))

    saved = filt.question_count - agent.question_count
    if agent.hit_round_limit:
        verdict = f"cut off by the round limit after {agent.question_count}"
        saved = 0
    elif amount_missing:
        verdict = f"a figure is wrong: {len(amount_missing)} amount field(s) never asked"
    elif stopped_early and not stop_early_ok:
        verdict = "proposed stopping where money remained"
    elif saved > 0:
        verdict = f"{saved} question(s) fewer than the filter" + (
            ", stop rightly proposed" if stopped_early else "")
    elif saved == 0:
        verdict = "no better than the filter"
    else:
        verdict = f"{-saved} question(s) more than the filter"

    return {
        "profile": profile.id,
        "below_pauschbetrag": short,
        "form_questions": form.question_count,
        "filter_questions": filt.question_count,
        "agent_questions": agent.question_count,
        "saved_vs_filter": saved,
        "agent_missing_amount": amount_missing,
        "agent_missing_checks": checks_missing,
        "filter_missing_required": filter_missing,
        "stopped_early": stopped_early,
        "stop_early_ok": stop_early_ok,
        "gates_forced": agent.gates_forced,
        "agent_total_eur": est_agent.total_eur,
        "filter_total_eur": est_filter.total_eur,
        "concluded_by_model": agent.concluded_by_model,
        "hit_round_limit": agent.hit_round_limit,
        "conclude_reason": agent.conclude_reason,
        "stopped_with_candidates_open": agent.candidates_left_at_end,
        "fell_back_to_filter": agent.fell_back,
        "dont_know": len(agent.unanswered),
        "seconds": agent.seconds,
        "verdict": verdict,
    }


def _missing_required(known: dict[str, Any]) -> list[str]:
    t = Transcript(arm="agent", profile_id="")
    t.known = dict(known)
    return t.missing_required()


def _missing_amount(known: dict[str, Any]) -> list[str]:
    t = Transcript(arm="agent", profile_id="")
    t.known = dict(known)
    return t.missing_amount_fields()


# --- reporting ------------------------------------------------------------------

def _table(rows: list[dict]) -> str:
    head = ["profile", "form", "filter", "agent", "saved", "short?", "lost", "stop", "verdict"]
    body = [[
        r["profile"],
        r["form_questions"],
        r["filter_questions"],
        r["agent_questions"],
        r["saved_vs_filter"],
        "yes" if r["below_pauschbetrag"] else "-",
        len(r["agent_missing_amount"]) or "-",
        ("ok" if r["stop_early_ok"] else "WRONG") if r["stopped_early"] else "-",
        r["verdict"],
    ] for r in rows]
    widths = [max(len(str(x[i])) for x in [head] + body) for i in range(len(head))]
    out = [" | ".join(str(h).ljust(w) for h, w in zip(head, widths))]
    out.append("-+-".join("-" * w for w in widths))
    for row in body:
        out.append(" | ".join(str(c).ljust(w) for c, w in zip(row, widths)))
    return "\n".join(out)


def _label(argv: list[str]) -> str:
    """The optional `--label x` (or `--label=x`) suffix for the output file."""
    for i, arg in enumerate(argv):
        if arg == "--label" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--label="):
            return arg.split("=", 1)[1]
    return ""


async def main(argv: list[str]) -> int:
    use_llm = "--no-llm" not in argv
    label = _label(argv)
    skip = {label} if label else set()
    wanted = [a for a in argv if not a.startswith("--") and a not in skip]
    profiles = [p for p in load_profiles()
                if not wanted or any(p.id.startswith(w) for w in wanted)]
    if not profiles:
        print("no matching profile")
        return 1

    settings = get_settings()
    model = settings.llm_model if use_llm else "none (filter as agent)"
    chat = None
    if use_llm:
        if not settings.openrouter_api_key:
            print("no OPENROUTER_API_KEY; run with --no-llm to check the wiring")
            return 1
        chat = CountingChat(OpenRouterClient(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            model=settings.llm_model,
        ))

    rows = []
    for profile in profiles:
        form = run_questionnaire(profile)
        filt = run_filter(profile)
        # One counting wrapper per profile would hide per-profile cost; reset instead.
        if chat is not None:
            before = (chat.prompt_tokens, chat.completion_tokens)
        agent = await run_agent_interview(profile, chat)
        if chat is not None:
            agent.prompt_tokens = chat.prompt_tokens - before[0]
            agent.completion_tokens = chat.completion_tokens - before[1]
        row = score(profile, form, filt, agent)
        row["prompt_tokens"] = agent.prompt_tokens
        row["completion_tokens"] = agent.completion_tokens
        row["rationales"] = agent.rationales
        rows.append(row)
        print(f"  {profile.id}: {row['verdict']}")

    print()
    print(_table(rows))

    total_cost = None
    if chat is not None:
        total_cost = cost_usd(settings.llm_model, chat.prompt_tokens, chat.completion_tokens)
        print(f"\n{chat.calls} provider calls, "
              f"{chat.prompt_tokens} prompt + {chat.completion_tokens} completion tokens"
              + (f", ${total_cost:.4f}" if total_cost is not None else ""))

    _summarise(rows)

    RESULTS.mkdir(exist_ok=True)
    slug = model.replace("/", "-").replace(" ", "-")
    out = RESULTS / f"agent-score-{slug}{'-' + label if label else ''}.json"
    if out.exists():
        # Refused rather than versioned automatically. This run cost real money and
        # so did the one already on disk, and which of the two a document is quoting
        # is not something a script can work out - the previous run silently became
        # the new one, and only a diff noticed.
        print(f"\n{out.name} already exists. This run was NOT saved.\n"
              f"Re-run with --label <something> to keep both, or move the old file "
              f"aside if it is genuinely superseded.")
        return 1
    out.write_text(json.dumps(
        {"model": model, "label": label, "cost_usd": total_cost, "profiles": rows},
        ensure_ascii=False, indent=2) + "\n")
    print(f"\nwritten to {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")
    return 0


def _summarise(rows: list[dict]) -> None:
    saved = sum(r["saved_vs_filter"] for r in rows)
    lost = [r["profile"] for r in rows if r["agent_missing_amount"]]
    wrong_stops = [r["profile"] for r in rows if r["stopped_early"] and not r["stop_early_ok"]]
    short = [r for r in rows if r["below_pauschbetrag"]]
    stopped_short = [r for r in short if r["saved_vs_filter"] > 0]
    forced = sum(r["gates_forced"] for r in rows)
    fallbacks = sum(r["fell_back_to_filter"] for r in rows)

    print()
    print(f"Against the filter: {saved:+d} questions over {len(rows)} profiles.")
    print(f"Wrong figures (amount fields lost): {len(lost)} profile(s)"
          + (f" — {', '.join(lost)}" if lost else ""))
    print(f"Stop proposed where money remained: {len(wrong_stops)}"
          + (f" — {', '.join(wrong_stops)}" if wrong_stops else ""))
    if forced:
        print(f"Premature stop vetoed by the gate guard: {forced} time(s).")
    if short:
        print(f"Of the {len(short)} profiles that cannot beat the Pauschbetrag, "
              f"the agent shortened {len(stopped_short)}.")
    if fallbacks:
        print(f"Decisions that came from the filter rather than the model: {fallbacks}"
              " — expected when run with --no-llm, a provider failure otherwise.")
    else:
        print("Every decision came from the model.")
    truncated = [r["profile"] for r in rows if r.get("hit_round_limit")]
    if truncated:
        print(f"Cut off by the round limit: {', '.join(truncated)} — not a saving.")
    print("\nThe agent earns its place where `saved` is positive, no figure is lost,"
          "\nand no stop is proposed where money remained.")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
