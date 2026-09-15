"""The LangGraph over the Tax Case: nodes, interrupts, and one checkpointer.

Everything intelligent in this graph existed and was measured before the graph did
(docs/SPRINT_AGENTIC_MVP.md, the work order): `decide` is the Interviewer the
harness scored, `review` is the Reviewer that caught the seeded defects,
`calculate` and `validate_tax_data` are the Sprint-2 calculators. The graph adds
the three things a harness cannot: pausing for a human, surviving the pause, and
the routing between the two agents.

Every pause is an `interrupt()` with a typed payload, so the API layer renders it
without guessing: a question to answer, a stop proposal to confirm, findings to
resolve, a report to approve. The state that crosses a pause is JSON only — ids
and dicts, never a Question or a Finding object — because the checkpointer has to
serialise it and a resumed session has to deserialise it a week later.

The checkpointer holds the paused run and nothing else. The case itself lives in
the Postgres tables (ADR 0005); wiring each answer into `db/cases.py` is the API
layer's job, not a node's.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.interviewer import (
    MAX_ROUNDS,
    Ask,
    Chat,
    Conclude,
    decide,
    decide_deterministically,
)
from agents.gap_finder import Justifier, find_candidates, plain_justifier
from agents.reviewer import ClaimedExpense, ReviewCase, review
from domain.fields import key_for
from domain.questions import BY_ID, BY_KEY
from domain.positions import (
    TaxPosition,
    UserDecision,
    assess_positions,
    fields_from_state,
    project_expenses,
    reconcile_positions,
)
from domain.compliance import check_position
from domain.tax_years import for_year

MAX_REVISION_ROUNDS = 2


def _policy_results(positions: list[TaxPosition]) -> list[dict]:
    """One policy check per position, evaluated once.

    It used to be called three times per position to fill three keys of one dict -
    the same deterministic answer computed twice for nothing.
    """
    out = []
    for position in positions:
        result = check_position(position)
        out.append({"position_id": position.position_id,
                    "action": result.action.value,
                    "reason": result.reason,
                    "code": result.code})
    return out


def case_thread_id(user_id: str, case_id: str) -> str:
    """The checkpointer's key for one user's run on one case.

    One definition because two callers computing it differently is the quiet kind
    of bug: the interview would write its run under one key and the delete would
    clear another, leaving the answers behind while the API reported success.

    The format is `<user_id>:<case_id>` and must not change. Every paused
    interview already sitting in `checkpoints` is filed under it; a new format
    without a migration orphans all of them at once.
    """
    return f"{user_id}:{case_id}"


def _still_applies(key: str, known: dict[str, Any]) -> bool:
    """Whether the question behind a carried-over key is relevant to this year.

    `relevant_questions` cannot answer this: it drops anything already answered, and
    a carried value is answered by definition. What is being asked here is only the
    profile condition — did this person commute at all this year.
    """
    question = BY_KEY.get(key)
    return question is not None and question.applies(known)


def read_stop_answer(answer: Any) -> tuple[bool, list[str]]:
    """Read the stop card's reply: (stop confirmed, keys of rejected carried values).

    Public because the pause contract has two readers by design: the node decides
    what the run does next, the API layer decides what the tables hold, and the two
    must not each invent their own parsing of the same reply.

    Two shapes, because the card grew a second thing to answer. A bare boolean is
    the original contract and still means exactly what it did; a dict carries the
    confirmation plus any carried-over value the user says is no longer true. The
    bare boolean is not deprecated — a card with nothing carried over sends one.
    """
    if isinstance(answer, dict):
        rejected = [str(k) for k in (answer.get("reject") or [])]
        return bool(answer.get("confirm", True)), rejected
    return bool(answer), []



class CaseState(TypedDict, total=False):
    """What crosses a pause. JSON-serialisable throughout, or the resume breaks."""

    tax_year: int
    known: dict[str, Any]
    # The provenance of each value in `known`, as `{key: {"provenance", "source"}}`.
    # Carried beside the values rather than merged into them because every calculator
    # takes plain values - and without it a figure read off a document arrives at the
    # report indistinguishable from one the user typed, which is the gap issues #16
    # and #17 are both about.
    provenance: dict[str, dict[str, str]]
    asked: list[str]
    rounds: int

    # set by decide_next, routes to ask_user / confirm_stop
    next_step: str                     # "ask" | "propose_stop"
    pending_question: dict[str, str]   # {"id", "rationale"}
    stop_reason: str
    stop_declined: bool

    expenses: list[dict[str, Any]]
    tax_positions: list[dict[str, Any]]
    policy_results: list[dict[str, str]]
    findings: list[dict[str, Any]]
    # Whether the last review ran with its own model, and why not when it did not.
    review_from_model: bool
    review_note: str
    revision_round: int
    escalated: bool
    # Who made the last decision: the model, the deterministic filter, or the gate
    # guard vetoing a premature stop. Recorded for the developer panel and for
    # anybody asking "why did it ask that" — which is the project's own promise.
    last_decision: dict[str, Any]
    # Deductions the profile points at that the case does not hold, computed when
    # a stop is proposed and shown on the stop card (AGENT_ARCHITECTURE §5).
    gap_candidates: list[dict[str, Any]]
    # Values carried over from this person's earlier case, seeded into `known` by the
    # API layer before the run starts (agents/profile_memory.py). They are in the case
    # already, but unconfirmed, and the stop card is where the user confirms or
    # rejects them — see confirm_stop for why that is the only honest place.
    carried_over: list[dict[str, Any]]

    status: str  # gathering | validating | reviewing | needs_user_input | finalized


def build_graph(
    interviewer_chat: Optional[Chat] = None,
    reviewer_chat: Optional[Chat] = None,
    checkpointer: Any = None,
    gap_justifier: Optional[Justifier] = None,
):
    """Compile the graph. Chats are injected so tests run scripted and offline."""
    justify = gap_justifier or plain_justifier

    async def decide_next(state: CaseState) -> CaseState:
        known = dict(state.get("known") or {})
        asked = frozenset(state.get("asked") or [])
        rounds = int(state.get("rounds") or 0) + 1

        if rounds > MAX_ROUNDS:
            # The promised escalation: the loop is not converging, so the human gets
            # the case with what was collected, never a silent stop.
            return {"rounds": rounds, "next_step": "propose_stop", "escalated": True,
                    "stop_reason": "the interview did not converge within its round "
                                   "limit; please review what has been collected"}

        if state.get("stop_declined"):
            # The user just declined a stop proposal. The very next question comes
            # from the filter, deterministically — otherwise the model, still seeing
            # the same state, proposes the same stop straight back.
            decision = decide_deterministically(known, asked)
            declined_flag = {"stop_declined": False}
        else:
            decision = await decide(known, asked, interviewer_chat)
            declined_flag = {}

        if isinstance(decision, Conclude):
            # Gaps are computed here and not in confirm_stop on purpose: a node
            # that pauses replays from its top on resume, and the justifier is a
            # provider call that must run once per proposal, not once per refresh.
            gaps = state.get("gap_candidates")
            if gaps is None:
                open_candidates = find_candidates(known)
                gaps = ([g.as_dict() for g in await justify(open_candidates, known)]
                        if open_candidates else [])
            return {"rounds": rounds, "next_step": "propose_stop",
                    "stop_reason": decision.reason,
                    "gap_candidates": gaps,
                    "last_decision": {"kind": "conclude",
                                      "from_model": decision.from_model},
                    **declined_flag}
        assert isinstance(decision, Ask)
        return {"rounds": rounds, "next_step": "ask",
                "pending_question": {"id": decision.question.id,
                                     "rationale": decision.rationale,
                                     # Which purchase, for a category that can hold
                                     # several. Zero for everything else (#35).
                                     "item_index": decision.item_index},
                "last_decision": {"kind": "ask",
                                  "from_model": decision.from_model,
                                  "forced_gate": decision.forced_gate,
                                  "question_id": decision.question.id},
                **declined_flag}

    def ask_user(state: CaseState) -> CaseState:
        pending = state["pending_question"]
        question = BY_ID[pending["id"]]
        spec = question.spec()
        item_index = int(pending.get("item_index") or 0)
        answer = interrupt({
            "type": "question",
            "question_id": question.id,
            # Qualified with the item, so the answer lands on the purchase it was
            # asked about rather than overwriting the first one (#35).
            "field": key_for(question.category, question.field, item_index),
            "item_index": item_index,
            # Which part of the case this belongs to. The agent chooses the order and
            # will move between topics mid-interview — that is the point of it — so
            # the screen has to say which topic a question is from, or a jump from
            # "did you receive a benefit?" to job-application costs and back reads as
            # the interview losing its place. None for a profile question.
            "category": question.category.value if question.category else None,
            "answer_type": spec.answer_type.value,
            "options": list(spec.options),
            "minimum": spec.minimum,
            "maximum": spec.maximum,
            "required": spec.required,
            "text": question.text,
            "rationale": pending["rationale"],
        })

        # Recorded by the qualified key, not the bare id: the same question about a
        # second purchase is a different ask, and a bare id would make the interview
        # believe it had already collected the second invoice.
        key = key_for(question.category, question.field, item_index)
        asked = list(state.get("asked") or []) + [key]
        known = dict(state.get("known") or {})
        value = (answer or {}).get("value") if isinstance(answer, dict) else answer
        if value is not None:  # None is "I don't know": asked, but no value lands
            known[key] = value
        return {"asked": asked, "known": known, "status": "gathering"}

    def confirm_stop(state: CaseState) -> CaseState:
        """The stop proposal, and with it whatever was carried over from last year.

        The carried values ride on this pause rather than on one of their own, and
        the reason is relevance. A value like the commute distance is only worth
        confirming if the commute category applies at all, and that is not known
        until every gate has been answered — which is exactly the precondition the
        gate guard already enforces before a stop may be proposed. Asked earlier,
        the card would show somebody who did not commute this year a distance they
        have no use for; asked later, the figure would already be in the report.

        A carried value the year turned out not to need is not shown and does not
        survive: it leaves `known` here and leaves the tables in the API layer. The
        alternative is a value nobody was ever shown sitting unconfirmed in the case,
        which is precisely what `finalize` refuses to write a report over.
        """
        known = dict(state.get("known") or {})
        carried = list(state.get("carried_over") or [])
        shown = [c for c in carried if _still_applies(c.get("key", ""), known)]
        stale = [c["key"] for c in carried if c not in shown]

        answer = interrupt({
            "type": "confirm_stop",
            "reason": state.get("stop_reason") or "",
            "escalated": bool(state.get("escalated")),
            "gaps": state.get("gap_candidates") or [],
            "carried_over": shown,
        })
        confirmed, rejected = read_stop_answer(answer)

        for key in stale + rejected:
            known.pop(key, None)

        if confirmed and not rejected:
            # Everything carried is now either confirmed or gone, so nothing is left
            # to put on a later card.
            return {"status": "validating", "stop_declined": False,
                    "known": known, "carried_over": []}
        # Rejecting anything reopens the interview whatever the confirm flag said:
        # there is now a question to ask, so stopping is no longer what was agreed.
        # A rejected value's question returns to the filter simply by being gone.
        return {"status": "gathering", "stop_declined": True, "known": known,
                "carried_over": [c for c in shown if c["key"] not in rejected]}

    def build_expenses(state: CaseState) -> CaseState:
        known = state.get("known") or {}
        year = for_year(int(state.get("tax_year") or 2025))
        old_positions = {
            position.position_id: position
            for position in (TaxPosition.from_dict(value)
                             for value in state.get("tax_positions") or [])
        }
        fields = fields_from_state(known, state.get("provenance"))
        positions = reconcile_positions(
            assess_positions(known, year, state.get("provenance")),
            old_positions.values(),
        )
        expenses = project_expenses(positions, fields, year)
        return {"expenses": expenses,
                "tax_positions": [position.as_dict() for position in positions],
                "status": "reviewing"}

    async def run_review(state: CaseState) -> CaseState:
        case = ReviewCase(
            tax_year=int(state.get("tax_year") or 2025),
            fields=dict(state.get("known") or {}),
            # One claim per purchase, not per category. The Reviewer's recompute tool
            # takes an item index and matches on it, so a category handed over as a
            # single row left it able to check the first purchase and nothing else -
            # three invoices, one of them wrong, and the review passes (#35).
            expenses=tuple(
                ClaimedExpense(e["category"], item["amount_eur"],
                               item_index=item["item_index"],
                               trace=tuple(e.get("trace") or ()),
                               document=e.get("document"))
                for e in state.get("expenses") or []
                for item in (e.get("items") or [{"item_index": 0,
                                                 "amount_eur": e["amount_eur"]}])
            ),
        )
        result = await review(case, reviewer_chat)
        return {
            # Carried out of the node so the API layer can store it: a rules-only pass
            # that raises nothing is otherwise indistinguishable from a clean
            # independent review (#29).
            "review_from_model": result.from_model,
            "review_note": getattr(result, "note", "") or "",
            "findings": [
                {"severity": f.severity, "title": f.title,
                 "reasoning": f.reasoning, "category": f.category,
                 "from_model": result.from_model}
                for f in result.findings
            ],
        }

    def resolve_findings(state: CaseState) -> CaseState:
        resolution = interrupt({
            "type": "findings",
            "findings": state.get("findings") or [],
        })
        action = (resolution or {}).get("action") if isinstance(resolution, dict) else resolution
        if action == "revise":
            return {"revision_round": int(state.get("revision_round") or 0) + 1,
                    "status": "gathering",
                    # The stop proposal was, in effect, accepted and then revised:
                    # let the next decision come deterministically again.
                    "stop_declined": True}
        return {"status": "needs_user_input"}

    def final_approval(state: CaseState) -> CaseState:
        positions = [TaxPosition.from_dict(value)
                     for value in state.get("tax_positions") or []]
        policy_results = _policy_results(positions)
        approved = interrupt({
            "type": "final_approval",
            "expenses": state.get("expenses") or [],
            "tax_positions": [position.as_dict() for position in positions],
            "policy_results": policy_results,
            "findings": state.get("findings") or [],
        })
        if isinstance(approved, dict):
            decisions = approved.get("decisions") or {}
            for position in positions:
                if position.position_id in decisions:
                    position.decide(UserDecision(str(decisions[position.position_id])))
            policy_results = _policy_results(positions)
            if approved.get("approve") and all(
                    position.assessment_status.value == "criteria_not_met"
                    or position.user_decision in (UserDecision.accepted, UserDecision.rejected)
                    for position in positions):
                if any(result["action"] in ("block", "requires_confirmation")
                       for result in policy_results):
                    return {"status": "gathering",
                            "tax_positions": [position.as_dict() for position in positions],
                            "policy_results": policy_results}
                return {"status": "finalized",
                        "tax_positions": [position.as_dict() for position in positions],
                        "policy_results": policy_results}
            return {"status": "gathering",
                    "tax_positions": [position.as_dict() for position in positions],
                    "policy_results": policy_results}
        if bool(approved) and not positions:
            return {"status": "finalized"}
        return {"status": "gathering", "stop_declined": True}

    # --- routing ------------------------------------------------------------------

    def after_decide(state: CaseState) -> str:
        return "confirm_stop" if state.get("next_step") == "propose_stop" else "ask_user"

    def after_confirm(state: CaseState) -> str:
        return "build_expenses" if state.get("status") == "validating" else "decide_next"

    def after_review(state: CaseState) -> str:
        blocking = any(f["severity"] == "blocking" for f in state.get("findings") or [])
        return "resolve_findings" if blocking else "final_approval"

    def after_resolve(state: CaseState) -> str:
        if state.get("status") != "gathering":
            return "final_approval"
        if int(state.get("revision_round") or 0) > MAX_REVISION_ROUNDS:
            # The revision loop is capped; past it, the human decides over the case
            # as it stands rather than the two agents ping-ponging forever.
            return "final_approval"
        return "decide_next"

    def after_final(state: CaseState) -> str:
        return END if state.get("status") == "finalized" else "decide_next"

    graph = StateGraph(CaseState)
    graph.add_node("decide_next", decide_next)
    graph.add_node("ask_user", ask_user)
    graph.add_node("confirm_stop", confirm_stop)
    graph.add_node("build_expenses", build_expenses)
    graph.add_node("review", run_review)
    graph.add_node("resolve_findings", resolve_findings)
    graph.add_node("final_approval", final_approval)

    graph.add_edge(START, "decide_next")
    graph.add_conditional_edges("decide_next", after_decide,
                                ["ask_user", "confirm_stop"])
    graph.add_edge("ask_user", "decide_next")
    graph.add_conditional_edges("confirm_stop", after_confirm,
                                ["build_expenses", "decide_next"])
    graph.add_edge("build_expenses", "review")
    graph.add_conditional_edges("review", after_review,
                                ["resolve_findings", "final_approval"])
    graph.add_conditional_edges("resolve_findings", after_resolve,
                                ["decide_next", "final_approval"])
    graph.add_conditional_edges("final_approval", after_final,
                                ["decide_next", END])

    return graph.compile(checkpointer=checkpointer or InMemorySaver())


_SAVER = None
_SAVER_POOL = None


async def checkpointer():
    """The process-wide checkpointer, on the shared async pool.

    One object for the life of the process, because the alternative — what this used
    to do — opened a Postgres connection for every advance of every interview and
    threw it away again. That handshake cost 0.38s of a 4s wait, next to 2.9s of the
    model actually deciding: not the headline, but a fifth of everything that was not
    the model.

    Table setup still happens once (`ensure_checkpoint_tables`); after that this is a
    dictionary lookup.
    """
    global _SAVER, _SAVER_POOL
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from db.connection import open_async_pool

    pool = await open_async_pool()
    # Rebuilt when the pool is not the one it was built on. A cached saver holding a
    # closed pool is the failure this prevents: shutdown drops the pool, the next
    # startup makes a new one, and a saver kept from before would go on writing into
    # the corpse. Two integration tests in the same process are enough to hit it.
    if _SAVER is None or _SAVER_POOL is not pool:
        _SAVER = AsyncPostgresSaver(pool)
        _SAVER_POOL = pool
    await ensure_checkpoint_tables(_SAVER)
    return _SAVER


def postgres_checkpointer():
    """A checkpointer on a connection of its own, opened and closed by the caller.

    Not what serves requests any more — `checkpointer()` above does, over the shared
    pool. This stays for the places that want their own connection and no dependency
    on the app's lifespan: the integration tests, and anything run as a script.

    The async saver, because the graph is invoked with `ainvoke` and the sync one
    leaves every `a*` method unimplemented — which surfaces as NotImplementedError
    on the first pause, not at construction. Session-mode pooler on purpose:
    transaction mode forbids the prepared statements this library uses
    (db/README.md). Use as an async context manager; call `.setup()` once per
    database to create the checkpoint tables.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from core.config import get_settings
    from db.connection import DatabaseNotConfigured

    dsn = get_settings().database_url
    if not dsn:
        raise DatabaseNotConfigured("the graph checkpointer needs DATABASE_URL")
    return AsyncPostgresSaver.from_conn_string(dsn)


_CHECKPOINT_TABLES_READY = False


async def ensure_checkpoint_tables(saver) -> None:
    """Create the checkpointer's own tables, once per process.

    `setup()` is idempotent but not free (a round-trip per call), so it runs on
    the first request and never again. Without this, the first interview on a
    fresh database — which is exactly what a new production project is — fails
    with "relation checkpoints does not exist"; the integration suite never saw
    it because its own setup() call had already created the tables in dev.
    """
    global _CHECKPOINT_TABLES_READY
    if not _CHECKPOINT_TABLES_READY:
        await saver.setup()
        _CHECKPOINT_TABLES_READY = True
