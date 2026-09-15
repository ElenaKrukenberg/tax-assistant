"""The document-intake workflow: check, read twice, compare, ask the human, save.

```
             (bytes live only here, in the runtime context)
   validate ─→ read twice ─→ compare ─┬─ agree ──→ propose ─→ review ─┬─ confirmed ─→ save
       │            │                 │              ↑                │
       └─ rejected ─┴─ failed ────────┴─ disagree ───┤                ├─ discarded ─→ end
                                                     │                │
                                       (another category) ←───────────┘ reclassify
```

Four things about the shape are requirements rather than style.

**The bytes are not state.** They travel in LangGraph's runtime context, which is
not checkpointed, while the state holds only what came *out* of the document. If
they were a state field, an uploaded Lohnsteuerbescheinigung would be written to the
`checkpoints` table in Postgres, and ADR 0004 promises the opposite. A handle into a
process-local cache would be no better: after a restart it points nowhere, so the
resume would look successful and read nothing.

**Everything that needs the bytes happens before the first `interrupt()`.** The
checks and both reads run in one pass through the graph; the pause comes after, when
only values remain. So the bytes exist for the duration of one request and no longer,
and a resume never needs them back.

**The human decision is a node, not a callback.** `interrupt()` puts the proposed
values in front of the user and stops. Nothing downstream of it can run until they
answer, which is what makes "no AI-extracted value enters the draft unreviewed" a
property of the graph rather than a promise in a docstring.

**Choosing a category goes back through `propose`.** An invoice's Fact keys are
keyed by the category it lands in - `equipment.price_eur#2` and
`fortbildung.amount_eur` are not the same values under two names - so a user who
picks a different category is not relabelling a proposal, they are asking for
another one. The `reclassify` answer therefore loops to `propose` and pauses again,
rather than carrying a category beside values that were mapped for a different one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from domain.fields import ExpenseCategory
from services.documents import classify, compare, extract, mapping
from services.documents.intake import CheckedUpload, Rejected, check, sniff
from services.documents.schemas import MODEL_FOR
from services.documents.sensitivity import DocumentKind

logger = structlog.get_logger(__name__)


def intake_thread_id(user_id: str, case_id: str, document_id: str) -> str:
    """The checkpointer's key for one document's intake.

    Prefixed and fully qualified, because these threads share a table with the
    interview's (`agents/graph.py:case_thread_id`, `<user_id>:<case_id>`) and the
    difference has to be visible to anything cleaning up - a delete that guessed
    wrongly here would clear a paused interview instead of an abandoned upload.
    """
    return f"document-intake:{user_id}:{case_id}:{document_id}"


@dataclass
class IntakeContext:
    """What the run needs and must never persist.

    A dataclass rather than a dict so the one dangerous field has a name a reader
    trips over. LangGraph does not checkpoint the context; it is handed to
    `ainvoke` per call and lives as long as the request does.
    """

    data: bytes
    read_twice: Callable[..., Awaitable[tuple[extract.Read, extract.Read]]]


class IntakeState(TypedDict, total=False):
    """What crosses a pause. JSON-serialisable, and never the document itself."""

    document_id: str
    file_name: str
    declared_format: str
    kind: str          # DocumentKind
    tax_year: int
    # Periods already confirmed by this case's other payslips, so several documents
    # add up instead of overwriting each other (services/documents/mapping.py).
    known_periods: list[list[str]]
    first_item_index: int

    pages: int
    size_bytes: int

    # What the two reads produced. Present after `read`, and the only trace of the
    # document that outlives the request.
    values: dict[str, Any]
    disagreements: list[str]
    # The model both passes came from - not always the configured one, since an
    # unreachable provider moves the read to the fallback (services/documents/extract.py).
    read_by: str

    proposed: list[dict[str, Any]]
    questions: list[str]
    # The category the user picked when the rules could not, or picked instead of the
    # one the rules proposed. It survives the pause because `propose` runs again with
    # it - the Fact keys an invoice yields are keyed by category
    # (`key_for(category, "price_eur", i)`), so choosing one is not a label on the
    # same values but a different proposal.
    chosen_category: Optional[str]
    category: Optional[str]
    category_reason: str
    category_by_rule: bool
    contradiction: Optional[str]

    # Set the moment anything goes wrong, and the only thing the API needs to render
    # a failed document: a code it can branch on and a sentence it can show.
    failure: Optional[dict[str, str]]

    confirmed: dict[str, Any]
    state: str  # reading | awaiting_confirmation | confirmed | discarded | failed


def _failed(code: str, detail: str) -> IntakeState:
    return {"failure": {"code": code, "detail": detail}, "state": "failed"}


def build_graph(checkpointer: Any = None):
    """Compile the intake graph. The reader is injected through the context."""

    async def validate(state: IntakeState, runtime: Runtime[IntakeContext]) -> IntakeState:
        """The file checks. Plain code, called from a node (AGENT_ARCHITECTURE §2)."""
        try:
            checked = check(
                runtime.context.data,
                file_name=state.get("file_name", ""),
                declared_format=state.get("declared_format") or None,
            )
        except Rejected as rejected:
            return _failed(rejected.code, rejected.detail)
        return {
            "pages": checked.pages,
            "size_bytes": checked.size_bytes,
            "state": "reading",
        }

    async def read(state: IntakeState, runtime: Runtime[IntakeContext]) -> IntakeState:
        """Two independent reads, then the bytes are done with.

        Both passes here rather than one per node: they are concurrent, and a node
        boundary between them would put the first pass's values into a checkpoint
        before the second could contradict them.
        """
        kind = DocumentKind(state["kind"])
        checked = CheckedUpload(
            file_name=state.get("file_name", "document"),
            file_format=sniff(runtime.context.data),
            size_bytes=state.get("size_bytes", 0),
            pages=state.get("pages", 1),
        )
        try:
            first, second = await runtime.context.read_twice(
                data=runtime.context.data, upload=checked, kind=kind,
            )
        except extract.ExtractionFailed as failed:
            return _failed(failed.code, failed.detail)

        mismatch = extract.document_type_matches(kind, first.values)
        if mismatch:
            return _failed("wrong_document_type", mismatch)

        disagreements = compare.compare(first.values, second.values)
        return {
            "values": first.values,
            "disagreements": [str(d) for d in disagreements],
            "read_by": first.model,
            "state": "reading",
        }

    def propose(state: IntakeState) -> IntakeState:
        """Turn one read into proposed Fact keys, or into questions.

        A disagreement between the passes is a gate, not a discount: nothing is
        proposed as a value, and the user is shown both readings (issue #5). Which is
        why this runs before the pause and not after - the pause has to know whether
        it is asking "is this right?" or "we could not read this, what is it?".
        """
        kind = DocumentKind(state["kind"])
        values = state.get("values") or {}
        parsed = MODEL_FOR[kind].model_validate(values)

        if state.get("disagreements"):
            return {
                "proposed": [],
                "questions": [
                    "The document was read twice and the two readings disagree, so "
                    "nothing has been filled in. Enter the values yourself, or upload "
                    "a clearer photo.",
                ],
                "state": "awaiting_confirmation",
            }

        if kind is DocumentKind.lohnsteuerbescheinigung:
            periods = [
                (mapping.parse_date(start), mapping.parse_date(end))
                for start, end in state.get("known_periods") or []
            ]
            proposal = mapping.payslip_proposal(
                parsed,  # type: ignore[arg-type]
                tax_year=state["tax_year"],
                periods_from_other_documents=[
                    (start, end) for start, end in periods if start and end
                ],
            )
            return {
                "proposed": [{"key": v.key, "value": v.value} for v in proposal.values],
                "questions": proposal.questions,
                "state": "awaiting_confirmation",
            }

        descriptions = [line.description or "" for line in (parsed.line_items or [])]  # type: ignore[union-attr]
        chosen = state.get("chosen_category")
        if chosen:
            # The user's choice wins over the rules, and is checked like any other:
            # a receipt that says "Restaurant" is questioned under Fortbildung
            # whoever proposed it, the user included.
            decided = classify.checked(
                ExpenseCategory(chosen), descriptions,
                "you chose this category", by_rule=False,
            )
        else:
            decided = classify.by_rules(descriptions)
            decided = classify.checked(
                decided.category, descriptions, decided.reason, by_rule=decided.by_rule,
            )
        if decided.category is None:
            return {
                "proposed": [],
                "questions": [
                    f"The category could not be decided from the document - "
                    f"{decided.reason}. Choose it yourself.",
                ],
                # Named rather than left unset: this node runs again when the user
                # picks a category, and a pause that says nothing about a field the
                # previous pass filled would show the screen the old answer.
                "category": None,
                "contradiction": None,
                "category_reason": decided.reason,
                "category_by_rule": False,
                "state": "awaiting_confirmation",
            }

        proposal = mapping.invoice_proposal(
            parsed,  # type: ignore[arg-type]
            category=decided.category,
            first_index=state.get("first_item_index", 0),
        )
        questions = list(proposal.questions)
        if decided.contradiction:
            questions.append(
                f"This looks like {decided.category.value}, but {decided.contradiction}. "
                "Confirm the category, or change it."
            )
        return {
            "proposed": [{"key": v.key, "value": v.value} for v in proposal.values],
            "questions": questions,
            "category": decided.category.value,
            "category_reason": decided.reason,
            "category_by_rule": decided.by_rule,
            "contradiction": decided.contradiction,
            "state": "awaiting_confirmation",
        }

    def review(state: IntakeState) -> IntakeState:
        """The pause. Nothing reaches the case except through the answer to this.

        The payload is deliberately everything the screen needs and nothing more:
        the proposed values, what could not be answered, and what the two reads
        disagreed about. The answer comes back as the values the *user* settled on -
        corrected, added to, or refused entirely.
        """
        answer = interrupt({
            "type": "confirm_document",
            "document_id": state.get("document_id"),
            "file_name": state.get("file_name"),
            "kind": state.get("kind"),
            "proposed": state.get("proposed") or [],
            "questions": state.get("questions") or [],
            "disagreements": state.get("disagreements") or [],
            "category": state.get("category"),
            "category_reason": state.get("category_reason", ""),
            "contradiction": state.get("contradiction"),
            "read_by": state.get("read_by", ""),
        })

        if (not isinstance(answer, dict)
                or answer.get("decision") not in {"confirm", "discard", "reclassify"}):
            # A resume payload that says neither is not interpreted generously: the
            # only two things a user can do here are confirm what they see and throw
            # it away, and guessing between them writes tax data nobody agreed to.
            return _failed(
                "unusable_answer",
                "The confirmation could not be read. Nothing was saved.",
            )

        if answer["decision"] == "reclassify":
            category = answer.get("category")
            if category not in {c.value for c in classify.CATEGORIES}:
                # Unreachable through the API, which refuses an unknown category with
                # a 422 before the run is resumed. Refused here too rather than
                # tolerated: the categories are what the Fact keys are built from, and
                # a value that is not one of them would key an invoice to nothing.
                return _failed(
                    "unusable_answer",
                    "That is not a category this case can hold. Nothing was saved.",
                )
            return {"chosen_category": category, "state": "awaiting_confirmation"}

        if answer["decision"] == "discard":
            return {"confirmed": {}, "state": "discarded"}

        values = answer.get("values")
        if not isinstance(values, dict) or not values:
            return {"confirmed": {}, "state": "discarded"}

        return {
            "confirmed": {"values": values, "category": answer.get("category")
                          or state.get("category")},
            "state": "confirmed",
        }

    def after_review(state: IntakeState) -> str:
        """Back to `propose` when the user changed the category, otherwise done.

        The loop is what makes a chosen category a real answer rather than a label:
        `propose` maps the invoice again under it and pauses again with the values
        that category actually yields.
        """
        if state.get("failure"):
            return END
        return "propose" if state.get("state") == "awaiting_confirmation" else END

    def after_validate(state: IntakeState) -> str:
        return END if state.get("failure") else "read"

    def after_read(state: IntakeState) -> str:
        return END if state.get("failure") else "propose"

    graph = StateGraph(IntakeState, context_schema=IntakeContext)
    graph.add_node("validate", validate)
    graph.add_node("read", read)
    graph.add_node("propose", propose)
    graph.add_node("review", review)

    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", after_validate, ["read", END])
    graph.add_conditional_edges("read", after_read, ["propose", END])
    graph.add_edge("propose", "review")
    graph.add_conditional_edges("review", after_review, ["propose", END])

    from langgraph.checkpoint.memory import InMemorySaver

    return graph.compile(checkpointer=checkpointer or InMemorySaver())


def categories_for_choice() -> list[str]:
    """The categories a user may pick when the rules could not decide.

    The same four the rules can propose - the commute, the home office and the phone
    line are day counts and a monthly bill, and no invoice for a thing evidences them.
    """
    return [c.value for c in classify.CATEGORIES]


__all__ = [
    "ExpenseCategory",
    "IntakeContext",
    "IntakeState",
    "build_graph",
    "categories_for_choice",
    "intake_thread_id",
]
