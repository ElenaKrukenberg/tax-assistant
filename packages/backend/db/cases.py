"""The only place that writes SQL about a Tax Case.

Everything else — API routes, the Interviewer, the report — calls these functions.
Keeping the SQL in one module is not tidiness: every query has to run as the user
(`as_user`, so row level security applies) *and* filter by user_id itself. Spread
across ten files, one of the two gets forgotten in the eleventh.

Values are stored one row per field in `field_values`, keyed by the same strings the
question catalogue uses ("profile.employed_months", "commute.commuting_days"),
each carrying where it came from (ADR 0010).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

from psycopg.errors import UniqueViolation
from psycopg.types.json import Json
from pydantic import BaseModel

from db.connection import as_user
from domain.fields import FieldValue, Provenance
from domain.positions import TaxPosition, UserDecision


class CaseNotFound(LookupError):
    """No such case for this user — which is also what another user's case looks like."""


class CaseIsFinalized(RuntimeError):
    """A finalized case is read-only until it is reopened."""


class TaxCase(BaseModel):
    id: str
    tax_year: int
    status: str
    # None until a review has run; False when it fell back to deterministic rules.
    last_review_from_model: Optional[bool] = None
    last_review_note: str = ""
    created_at: datetime
    updated_at: datetime
    finalized_at: Optional[datetime] = None


# The Reviewer's severities, which are its own vocabulary and not the validator's
# (CONTEXT.md). Mirrored from the check constraint in schema/0001.
_SEVERITIES = ("blocking", "warning", "suggestion")


class Document(BaseModel):
    """One uploaded document as the tables hold it - never the document itself.

    `extracted` is the confirmed, normalised result (ADR 0004 and the comment on the
    column): the two raw extraction passes are unconfirmed personal data and never
    reach this table.
    """

    id: str
    file_name: str
    doc_type: Optional[str] = None
    state: str
    extracted: dict = {}
    failure_code: Optional[str] = None
    failure_detail: Optional[str] = None
    # What reading it cost: the model that answered, both passes' tokens, and the
    # price at the provider's list rate when they ran. None for a document read
    # before this was recorded, and for a model with no price on file (#39).
    read_by_model: Optional[str] = None
    read_prompt_tokens: Optional[int] = None
    read_completion_tokens: Optional[int] = None
    read_cost_usd: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class Finding(BaseModel):
    """One Reviewer judgement as the tables hold it."""

    severity: str
    title: str
    reasoning: str
    category: str
    resolution: str


def create_case(user_id: str, tax_year: int) -> TaxCase:
    """Start a case, or return the one that already exists for that year.

    One case per user per year is a unique constraint in the schema, so this cannot
    race into two: the insert simply does nothing the second time.
    """
    with as_user(user_id) as cur:
        cur.execute(
            """
            insert into tax_cases (user_id, tax_year) values (%s, %s)
            on conflict (user_id, tax_year) do nothing
            returning id, tax_year, status, created_at, updated_at, finalized_at,
                      last_review_from_model, last_review_note
            """,
            (user_id, tax_year),
        )
        row = cur.fetchone()
        if row is None:  # already there
            cur.execute(
                """
                select id, tax_year, status, created_at, updated_at, finalized_at,
                   last_review_from_model, last_review_note
                from tax_cases where user_id = %s and tax_year = %s
                """,
                (user_id, tax_year),
            )
            row = cur.fetchone()
        return _case(row)


def get_case(user_id: str, case_id: str) -> TaxCase:
    with as_user(user_id) as cur:
        cur.execute(
            """
            select id, tax_year, status, created_at, updated_at, finalized_at,
                   last_review_from_model, last_review_note
            from tax_cases where id = %s and user_id = %s
            """,
            (case_id, user_id),
        )
        row = cur.fetchone()
    if row is None:
        raise CaseNotFound(case_id)
    return _case(row)


def list_cases(user_id: str) -> list[TaxCase]:
    """The case list screen, newest tax year first."""
    with as_user(user_id) as cur:
        cur.execute(
            """
            select id, tax_year, status, created_at, updated_at, finalized_at,
                   last_review_from_model, last_review_note
            from tax_cases where user_id = %s order by tax_year desc
            """,
            (user_id,),
        )
        return [_case(row) for row in cur.fetchall()]


def delete_case(user_id: str, case_id: str) -> None:
    """Remove a case and everything in it.

    The product promises this: documents are never stored, and a case can be deleted
    outright (Q11). Every child table cascades from tax_cases, so this is the whole
    of it.
    """
    with as_user(user_id) as cur:
        cur.execute("delete from tax_cases where id = %s and user_id = %s", (case_id, user_id))
        if cur.rowcount == 0:
            raise CaseNotFound(case_id)


# --- field values ---------------------------------------------------------------

def set_field(
    user_id: str,
    case_id: str,
    key: str,
    value: FieldValue,
    item_index: int = 0,
) -> None:
    """Write one value, replacing whatever was there.

    Raises CaseIsFinalized rather than letting the database's own error surface: the
    trigger in schema/0001 is the guard, this is only a readable name for it.
    """
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        cur.execute(
            """
            insert into field_values
                (case_id, key, item_index, value, provenance, source, confirmed)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (case_id, key, item_index) do update
                set value = excluded.value,
                    provenance = excluded.provenance,
                    source = excluded.source,
                    confirmed = excluded.confirmed,
                    updated_at = now()
            """,
            (case_id, key, item_index, Json(value.value),
             value.provenance.value, value.source, value.confirmed),
        )


def correct_field(user_id: str, case_id: str, key: str, value: Any,
                  item_index: int = 0) -> FieldValue:
    """Replace one value in place, remembering what it replaced.

    The editable unit is the fact, never the computed total (#12): a figure is a read
    over `field_values`, and editing the rendered number would leave the trace saying a
    formula produced something it did not.

    Three things happen together, which is why this is one function and not three calls:

    * the corrected value becomes an `answer`, because that is what it now is - a value
      a model read off a document does not stay a document value once a person has
      overridden it;
    * the old value and its provenance are kept, so the trace can say the figure was
      changed by hand and what it was before;
    * the Reviewer's findings are dropped, because every one of them was raised against
      the old figure. Leaving them would put stale objections next to a number nobody
      has reviewed yet, which is worse than an empty Review screen saying so.

    Tax positions are deliberately *not* touched here. Their `assessment_fingerprint`
    stops matching the moment a dependent fact changes, which is what turns an accepted
    decision into `needs_reconfirmation` - the user is asked again rather than having
    their approval silently carried onto a different number.
    """
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        cur.execute(
            """
            select value, provenance from field_values v join tax_cases c on c.id = v.case_id
            where v.case_id = %s and c.user_id = %s and v.key = %s and v.item_index = %s
            """,
            (case_id, user_id, key, item_index),
        )
        row = cur.fetchone()
        if row is None:
            raise KeyError(key)
        old_value, old_provenance = row

        cur.execute(
            """
            update field_values
               set value = %s,
                   provenance = 'answer',
                   confirmed = true,
                   superseded_value = %s,
                   superseded_provenance = %s,
                   corrected_at = now(),
                   updated_at = now()
             where case_id = %s and key = %s and item_index = %s
            """,
            (Json(value), Json(old_value), old_provenance, case_id, key, item_index),
        )
        cur.execute(
            """
            delete from findings f using tax_cases c
            where f.case_id = c.id and f.case_id = %s and c.user_id = %s
            """,
            (case_id, user_id),
        )
        cur.execute(
            """
            update tax_cases set last_review_from_model = null, last_review_note = ''
            where id = %s and user_id = %s
            """,
            (case_id, user_id),
        )
    return FieldValue(value, Provenance.answer, source="corrected", confirmed=True)


def get_fields(user_id: str, case_id: str) -> dict[str, FieldValue]:
    """Everything the case knows, keyed as the catalogue keys it.

    A repeating category's second item comes back as "equipment.price_eur#1", so
    a caller that does not care about repetition can ignore the suffix and a caller
    that does can split on it.
    """
    with as_user(user_id) as cur:
        cur.execute(
            """
            select v.key, v.item_index, v.value, v.provenance, v.source, v.confirmed,
                   v.superseded_value, v.superseded_provenance
            from field_values v join tax_cases c on c.id = v.case_id
            where v.case_id = %s and c.user_id = %s
            order by v.key, v.item_index
            """,
            (case_id, user_id),
        )
        out: dict[str, FieldValue] = {}
        for (key, item_index, value, provenance, source, confirmed,
             superseded, superseded_provenance) in cur.fetchall():
            name = key if item_index == 0 else f"{key}#{item_index}"
            # Built in one go: `FieldValue` is frozen, which is the right shape for a
            # value that travels through calculators, and a corrected one is still one
            # value - what it replaced is a second sentence the trace prints beside it.
            out[name] = FieldValue(
                value, Provenance(provenance), source, confirmed,
                superseded_value=superseded,
                superseded_provenance=superseded_provenance,
            )
        return out


def answered_count(user_id: str, case_id: str) -> int:
    """How many questions this person has actually answered.

    Counted from `field_values` rather than kept in the browser, which is what made a
    refresh reset the number to zero while the answers themselves were still there
    (#53). Only `answer` provenance counts: a value read from a document, assumed by
    the system or carried over from last year is not a question somebody answered, and
    counting it would make the number go up without anybody being asked anything.
    """
    with as_user(user_id) as cur:
        cur.execute(
            """
            select count(*) from field_values v join tax_cases c on c.id = v.case_id
            where v.case_id = %s and c.user_id = %s and v.provenance = 'answer'
            """,
            (case_id, user_id),
        )
        return int(cur.fetchone()[0])


def values_awaiting_confirmation(user_id: str, case_id: str) -> list[str]:
    """Values still waiting for the user. A report may not be generated over these.

    Two provenances qualify and for the same reason: neither an assumption the system
    offered nor a value carried over from last year's case is something the user has
    actually said about this tax year.
    """
    with as_user(user_id) as cur:
        cur.execute(
            """
            select v.key from field_values v join tax_cases c on c.id = v.case_id
            where v.case_id = %s and c.user_id = %s
              and v.provenance in ('assumed', 'remembered') and not v.confirmed
            order by v.key
            """,
            (case_id, user_id),
        )
        return [row[0] for row in cur.fetchall()]


def confirm_values(user_id: str, case_id: str, keys: list[str]) -> None:
    """Mark values the user has now looked at as confirmed.

    Only ever narrows: a key that is not in the case, or is already confirmed, is a
    no-op. Carried-over values reach here from the stop card, which is the first
    screen on which the user actually sees them.
    """
    if not keys:
        return
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        cur.execute(
            """
            update field_values v set confirmed = true, updated_at = now()
            from tax_cases c
            where v.case_id = %s and c.id = v.case_id and c.user_id = %s
              and v.key = any(%s) and not v.confirmed
            """,
            (case_id, user_id, list(keys)),
        )


def remove_item(user_id: str, case_id: str, category: str, item_index: int) -> int:
    """Delete one purchase of a repeating category, every field of it.

    A category can hold three invoices, and one of them can be wrong in a way that
    correcting a value cannot fix - the wrong thing was uploaded, or a line was read
    off a receipt that turned out to be private. Without this the only way out is
    deleting the case (#35).

    Item zero is refused. Removing it would renumber nothing and leave a category
    whose first purchase is `#1`, which every caller that starts at zero would then
    read as empty; correcting its values is the operation for "this one is wrong".

    Findings go with it for the same reason a correction drops them: each was raised
    against a total that included this purchase.
    """
    if item_index <= 0:
        raise ValueError("item 0 is the category itself; correct its values instead")
    # Values are keyed by what they *mean*, not by the category that consumes them
    # (#61): a purchase under `arbeitsmittel` is stored as `equipment.price_eur`.
    # Matching on the category name would quietly delete nothing at all.
    from domain.fields import ExpenseCategory, namespace_of

    prefix = f"{namespace_of(ExpenseCategory(category))}.%"
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        cur.execute(
            """
            delete from field_values v using tax_cases c
            where v.case_id = %s and c.id = v.case_id and c.user_id = %s
              and v.key like %s and v.item_index = %s
            """,
            (case_id, user_id, prefix, item_index),
        )
        removed = cur.rowcount
        if removed:
            cur.execute(
                """
                delete from findings f using tax_cases c
                where f.case_id = c.id and f.case_id = %s and c.user_id = %s
                """,
                (case_id, user_id),
            )
    return removed


def clear_field(user_id: str, case_id: str, key: str) -> None:
    """Remove a value from the case, every item of it.

    Used when the user says a carried-over value is no longer true: the case must
    forget it completely, so the interview asks for it again rather than keeping a
    stale figure marked as rejected.
    """
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        cur.execute(
            """
            delete from field_values v using tax_cases c
            where v.case_id = %s and c.id = v.case_id and c.user_id = %s and v.key = %s
            """,
            (case_id, user_id, key),
        )


# --- tax positions -------------------------------------------------------------

# --- Documents -------------------------------------------------------------------

_DOCUMENT_COLUMNS = ("id, file_name, doc_type, state, extracted, failure_code, "
                     "failure_detail, created_at, updated_at, read_by_model, "
                     "read_prompt_tokens, read_completion_tokens, read_cost_usd")


def _document(row) -> Document:
    return Document(
        id=str(row[0]), file_name=row[1], doc_type=row[2], state=row[3],
        extracted=row[4] or {}, failure_code=row[5], failure_detail=row[6],
        created_at=row[7], updated_at=row[8],
        read_by_model=row[9], read_prompt_tokens=row[10],
        read_completion_tokens=row[11],
        read_cost_usd=float(row[12]) if row[12] is not None else None,
    )


def create_document(
    user_id: str, case_id: str, *, file_name: str, doc_type: str,
    idempotency_key: Optional[str] = None,
) -> tuple[Document, bool]:
    """Start a document, or return the one this key already started.

    The bool says which. A retried upload - a dropped connection, a second click -
    must not become a second Document and two more paid model calls, and the
    uniqueness that guarantees it is the partial index from schema/0009 rather than a
    check-then-insert here, which two concurrent requests would both pass.
    """
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        if idempotency_key:
            cur.execute(
                f"select {_DOCUMENT_COLUMNS} from documents "
                "where case_id = %s and idempotency_key = %s",
                (case_id, idempotency_key),
            )
            row = cur.fetchone()
            if row:
                return _document(row), False

    # A savepoint, not `on conflict`: the uniqueness is a *partial* index (only rows
    # that have a key), and Postgres cannot infer a partial index from a plain
    # `on conflict (case_id, idempotency_key)` - it refuses the statement outright.
    # So the insert is attempted and the violation is caught, which is also the only
    # form that is correct under concurrency.
    with as_user(user_id) as cur:
        cur.execute("savepoint before_document")
        try:
            cur.execute(
                f"""
                insert into documents
                    (case_id, file_name, doc_type, state, idempotency_key)
                values (%s, %s, %s, 'reading', %s)
                returning {_DOCUMENT_COLUMNS}
                """,
                (case_id, file_name, doc_type, idempotency_key),
            )
            return _document(cur.fetchone()), True
        except UniqueViolation:
            # The insert lost a race with an identical request. The other one won and
            # its document is the answer, not an error.
            cur.execute("rollback to savepoint before_document")
            cur.execute(
                f"select {_DOCUMENT_COLUMNS} from documents "
                "where case_id = %s and idempotency_key = %s",
                (case_id, idempotency_key),
            )
            return _document(cur.fetchone()), False


def get_document(user_id: str, case_id: str, document_id: str) -> Document:
    with as_user(user_id) as cur:
        cur.execute(
            f"""
            select {_DOCUMENT_COLUMNS} from documents d
             where d.id = %s and d.case_id = %s
               and exists (select 1 from tax_cases c
                            where c.id = d.case_id and c.user_id = %s)
            """,
            (document_id, case_id, user_id),
        )
        row = cur.fetchone()
    if row is None:
        raise CaseNotFound(f"no document {document_id} in case {case_id}")
    return _document(row)


def list_documents(user_id: str, case_id: str) -> list[Document]:
    with as_user(user_id) as cur:
        cur.execute(
            f"""
            select {_DOCUMENT_COLUMNS} from documents d
             where d.case_id = %s
               and exists (select 1 from tax_cases c
                            where c.id = d.case_id and c.user_id = %s)
             order by d.created_at
            """,
            (case_id, user_id),
        )
        return [_document(row) for row in cur.fetchall()]


def set_document_state(
    user_id: str, case_id: str, document_id: str, state: str, *,
    failure: Optional[tuple[str, str]] = None,
    extracted: Optional[dict] = None,
    reading: Optional[dict] = None,
) -> None:
    """Move a document to its next state, with the reason if it failed.

    `reading` is what the model read cost - model, tokens, price (#39). Written here
    rather than in its own call because it is known at exactly the moment the state
    changes, and two writes would leave a window where a document is confirmed and
    the case cannot say what it paid.
    """
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        cur.execute(
            """
            update documents
               set state = %s,
                   failure_code = %s,
                   failure_detail = %s,
                   extracted = coalesce(%s::jsonb, extracted),
                   read_by_model = coalesce(%s, read_by_model),
                   read_prompt_tokens = coalesce(%s, read_prompt_tokens),
                   read_completion_tokens = coalesce(%s, read_completion_tokens),
                   read_cost_usd = coalesce(%s, read_cost_usd)
             where id = %s and case_id = %s
            """,
            (state, failure[0] if failure else None, failure[1] if failure else None,
             Json(extracted) if extracted is not None else None,
             (reading or {}).get("model"),
             (reading or {}).get("prompt_tokens"),
             (reading or {}).get("completion_tokens"),
             (reading or {}).get("cost_usd"),
             document_id, case_id),
        )
        if cur.rowcount == 0:
            raise CaseNotFound(f"no document {document_id} in case {case_id}")


def confirmed_employment_periods(
    user_id: str, case_id: str, *, except_document: Optional[str] = None,
) -> list[tuple[str, str]]:
    """The employment periods this case's other payslips already established.

    Read back out of `extracted` rather than derived from `profile.employed_months`,
    because a month count cannot be un-added: two half-year jobs are twelve months
    and one of them re-uploaded is still twelve, which needs the periods themselves
    (`services/documents/mapping.py`).
    """
    with as_user(user_id) as cur:
        cur.execute(
            """
            select extracted from documents d
             where d.case_id = %s and d.state = 'confirmed'
               and d.doc_type = 'lohnsteuerbescheinigung'
               and (%s::uuid is null or d.id <> %s::uuid)
               and exists (select 1 from tax_cases c
                            where c.id = d.case_id and c.user_id = %s)
            """,
            (case_id, except_document, except_document, user_id),
        )
        rows = cur.fetchall()

    periods: list[tuple[str, str]] = []
    for (extracted,) in rows:
        start = (extracted or {}).get("employment_period_start")
        end = (extracted or {}).get("employment_period_end")
        if start and end:
            periods.append((start, end))
    return periods


def next_item_index(user_id: str, case_id: str, prefix: str) -> int:
    """Where a new document's items start for a repeating category.

    `prefix` is the Fact key without its item suffix ("equipment.price_eur"), and the
    answer is one past the highest index the case already holds - so a second invoice
    adds items rather than overwriting the first invoice's.
    """
    with as_user(user_id) as cur:
        cur.execute(
            """
            select coalesce(max(item_index), -1) + 1 from field_values v
             where v.case_id = %s and v.key = %s
               and exists (select 1 from tax_cases c
                            where c.id = v.case_id and c.user_id = %s)
            """,
            (case_id, prefix, user_id),
        )
        return int(cur.fetchone()[0])


def expire_stale_documents(user_id: str, case_id: str, older_than_hours: int) -> list[str]:
    """Fail every upload left waiting for a decision longer than that.

    "Temporary until the user decides" has to have an end, or an abandoned upload
    keeps two unconfirmed readings of somebody's payslip in a checkpoint for as long
    as the case lives - and a case lives for years. The ids come back so the caller
    can delete the intake threads that belong to them.
    """
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        cur.execute(
            """
            update documents
               set state = 'failed',
                   failure_code = 'expired',
                   failure_detail = %s
             where case_id = %s and state in ('reading', 'awaiting_confirmation')
               and updated_at < now() - make_interval(hours => %s)
            returning id
            """,
            ("This upload waited too long for a decision and was discarded. "
             "Upload it again if you still need it.", case_id, older_than_hours),
        )
        return [str(row[0]) for row in cur.fetchall()]


# Every part of a `TaxPosition` that survives a round trip, in the column order the
# statements below use. Declared rather than written out twice, because the two lists
# drifting apart is not a visible failure: `assessment_fingerprint` was on the
# dataclass from the start, never reached this list, and read back empty for months.
# `tests/test_positions.py` holds this against the dataclass, so a field added to one
# and not the other fails there rather than in a user's reloaded case.
PERSISTED_POSITION_COLUMNS: tuple[str, ...] = (
    "position_key", "category", "assessment_status", "user_decision",
    "dependent_facts", "source_refs", "calculator_version", "rule_version",
    "proposed_amount_eur", "origin", "missing_facts", "provenance",
    "assessment_fingerprint",
)

# Fields of `TaxPosition` that are deliberately not stored, with the reason, so the
# test above can tell "derived on purpose" from "forgotten".
DERIVED_POSITION_FIELDS: dict[str, str] = {
    "position_id": "stored as position_key",
    "proposed_amount": "stored as proposed_amount_eur",
}


def save_positions(user_id: str, case_id: str, positions: list[TaxPosition]) -> None:
    """Persist assessed positions without allowing a rebuild to erase authority."""
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        for position in positions:
            cur.execute(
                """
                insert into tax_positions
                    (case_id, position_key, category, assessment_status, user_decision,
                     dependent_facts, source_refs, calculator_version, rule_version,
                     proposed_amount_eur, origin, missing_facts, provenance,
                     assessment_fingerprint)
                 values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (case_id, position_key) do update set
                    category = excluded.category,
                    assessment_status = excluded.assessment_status,
                    dependent_facts = excluded.dependent_facts,
                    source_refs = excluded.source_refs,
                    calculator_version = excluded.calculator_version,
                    rule_version = excluded.rule_version,
                    proposed_amount_eur = excluded.proposed_amount_eur,
                    origin = excluded.origin,
                    missing_facts = excluded.missing_facts,
                    provenance = excluded.provenance,
                    assessment_fingerprint = excluded.assessment_fingerprint,
                    -- The fingerprint and not `dependent_facts`, which is what this
                    -- compared before and is a strict subset of it: the fingerprint
                    -- also covers the rule and calculator versions, so a new rule
                    -- version now invalidates a decision that was made under the old
                    -- one. An empty stored fingerprint is a row from before 0010 and
                    -- is not treated as a change, or every such row would demand
                    -- reconfirmation on the next save for no reason the user can see.
                    --
                    -- Both answers, not only 'accepted'. A refusal is an answer about
                    -- a particular figure under particular rules, and the reason for
                    -- it may be the very thing that moved - 180 EUR declined as not
                    -- worth the paperwork is not 1,800 declined. `domain/positions.py:
                    -- reconcile_positions` holds the same rule for the graph's path.
                    user_decision = case
                        when tax_positions.user_decision in ('accepted', 'rejected')
                             and tax_positions.assessment_fingerprint <> ''
                             and tax_positions.assessment_fingerprint
                                 <> excluded.assessment_fingerprint
                        then 'needs_reconfirmation'
                        when tax_positions.user_decision in ('accepted', 'rejected')
                             and tax_positions.dependent_facts <> excluded.dependent_facts
                        then 'needs_reconfirmation'
                        when tax_positions.user_decision = 'needs_reconfirmation'
                        then 'needs_reconfirmation'
                        else tax_positions.user_decision
                    end,
                    updated_at = now()
                """,
                (case_id, position.position_id, position.category,
                 position.assessment_status.value, position.user_decision.value,
                 Json([dependency.__dict__ for dependency in position.dependent_facts]),
                 Json([asdict(citation) for citation in position.source_refs]),
                 position.calculator_version,
                 position.rule_version, position.proposed_amount, position.origin.value,
                     Json(position.missing_facts),
                     Json([entry.__dict__ | {"origin": entry.origin.value}
                         for entry in position.provenance]),
                     position.assessment_fingerprint),
            )


def get_positions(user_id: str, case_id: str) -> list[TaxPosition]:
    """Read material positions under the case owner's row-level security."""
    with as_user(user_id) as cur:
        cur.execute(
            """
            select position_key, category, assessment_status, user_decision,
                   dependent_facts, source_refs, calculator_version, rule_version,
                   proposed_amount_eur, origin, missing_facts, provenance,
                   assessment_fingerprint
            from tax_positions p join tax_cases c on c.id = p.case_id
            where p.case_id = %s and c.user_id = %s
            order by p.position_key
            """,
            (case_id, user_id),
        )
        positions = []
        for row in cur.fetchall():
            positions.append(TaxPosition.from_dict({
                "position_id": row[0], "category": row[1],
                "assessment_status": row[2], "user_decision": row[3],
                "dependent_facts": row[4], "source_refs": row[5],
                "calculator_version": row[6], "rule_version": row[7],
                "proposed_amount": float(row[8]) if row[8] is not None else None,
                "origin": row[9], "missing_facts": row[10], "provenance": row[11],
                "assessment_fingerprint": row[12],
            }))
        return positions


def decide_position(user_id: str, case_id: str, position_id: str, decision: str) -> None:
    """Record only an explicit user decision for one position."""
    _require_open(user_id, case_id)
    position = next((p for p in get_positions(user_id, case_id)
                     if p.position_id == position_id), None)
    if position is None:
        raise KeyError(position_id)
    from domain.positions import UserDecision
    position.decide(UserDecision(decision))
    with as_user(user_id) as cur:
        cur.execute(
            """update tax_positions set user_decision = %s, updated_at = now()
               where case_id = %s and position_key = %s""",
            (position.user_decision.value, case_id, position_id),
        )


def apply_position_decisions(
    user_id: str, case_id: str, decisions: dict[str, str], facts: dict,
) -> None:
    """Apply only decisions explicitly supplied by the final approval pause."""
    for position in get_positions(user_id, case_id):
        if position.position_id not in decisions:
            continue
        position.mark_dependencies_stale(facts)
        position.decide(UserDecision(decisions[position.position_id]))
        with as_user(user_id) as cur:
            cur.execute(
                """update tax_positions set user_decision = %s, updated_at = now()
                   where case_id = %s and position_key = %s""",
                (position.user_decision.value, case_id, position.position_id),
            )


# --- lifecycle ------------------------------------------------------------------

def finalize(user_id: str, case_id: str) -> TaxCase:
    """Approve the case, which makes it read-only.

    Refuses while a value is unconfirmed: an assumption — or a figure carried over
    from an earlier year — reaching the report unlooked-at is a defect, not a
    shortcut (ADR 0010).
    """
    pending = values_awaiting_confirmation(user_id, case_id)
    if pending:
        raise CaseIsFinalized(
            f"{len(pending)} value(s) still unconfirmed: {', '.join(pending)}"
        )
    with as_user(user_id) as cur:
        cur.execute(
            """select position_key from tax_positions
               where case_id = %s
                 and assessment_status in ('identified', 'unclear')
                 and user_decision <> 'accepted'
                 and user_decision <> 'rejected'""",
            (case_id,),
        )
        unresolved_positions = [row[0] for row in cur.fetchall()]
    if unresolved_positions:
        raise CaseIsFinalized(
            "tax positions still need a decision: " + ", ".join(unresolved_positions)
        )
    with as_user(user_id) as cur:
        cur.execute(
            """
            update tax_cases set status = 'finalized', finalized_at = now()
            where id = %s and user_id = %s and status <> 'finalized'
            returning id, tax_year, status, created_at, updated_at, finalized_at,
                      last_review_from_model, last_review_note
            """,
            (case_id, user_id),
        )
        row = cur.fetchone()
    if row is None:
        raise CaseNotFound(case_id)
    return _case(row)


def set_status(user_id: str, case_id: str, status: str) -> TaxCase:
    """Move the case between its states, finalized excluded.

    Finalizing goes through `finalize` and nothing else: it is the only transition
    with a precondition (no unconfirmed assumptions) and a side effect (the
    read-only lock), and a generic setter that could reach it would be a way to
    skip both.
    """
    if status == "finalized":
        raise ValueError("finalized is reached through finalize(), not set_status()")
    with as_user(user_id) as cur:
        cur.execute(
            """
            update tax_cases set status = %s
            where id = %s and user_id = %s and status <> 'finalized'
            returning id, tax_year, status, created_at, updated_at, finalized_at,
                      last_review_from_model, last_review_note
            """,
            (status, case_id, user_id),
        )
        row = cur.fetchone()
    if row is None:
        raise CaseNotFound(case_id)
    return _case(row)


def reopen(user_id: str, case_id: str, status: str = "gathering") -> TaxCase:
    """Lift the lock so the case can be edited again.

    tax_cases carries no read-only trigger for exactly this reason: it is the one
    table that has to be able to unlock the rest.
    """
    with as_user(user_id) as cur:
        cur.execute(
            """
            update tax_cases set status = %s, finalized_at = null
            where id = %s and user_id = %s
            returning id, tax_year, status, created_at, updated_at, finalized_at,
                      last_review_from_model, last_review_note
            """,
            (status, case_id, user_id),
        )
        row = cur.fetchone()
    if row is None:
        raise CaseNotFound(case_id)
    return _case(row)


# --- internals ------------------------------------------------------------------

def _case(row) -> TaxCase:
    return TaxCase(
        id=str(row[0]), tax_year=row[1], status=row[2],
        created_at=row[3], updated_at=row[4], finalized_at=row[5],
        last_review_from_model=row[6] if len(row) > 6 else None,
        last_review_note=(row[7] if len(row) > 7 else "") or "",
    )


def _require_open(user_id: str, case_id: str) -> None:
    case = get_case(user_id, case_id)
    if case.status == "finalized":
        raise CaseIsFinalized(f"case {case_id} is finalized; reopen it first")


# --- the Reviewer's own record ---------------------------------------------------

def save_review_mode(user_id: str, case_id: str, from_model: bool, note: str) -> None:
    """Record whether the last review was the independent one it looks like.

    On the case rather than on the findings, because the worst version of this is the
    quiet one: a rules-only pass that raises nothing leaves no finding row to carry a
    flag, and the screen says "the Reviewer raised nothing" over it.
    """
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        cur.execute(
            """
            update tax_cases set last_review_from_model = %s, last_review_note = %s
            where id = %s and user_id = %s
            """,
            (from_model, note or "", case_id, user_id),
        )


def save_findings(user_id: str, case_id: str, findings: list[dict]) -> None:
    """Replace the case's findings with the ones the Reviewer just produced.

    Replace rather than append, and called only at the two moments a review has just
    run: the state in the graph checkpoint is the authoritative set, and a revision
    round that clears a finding has to clear the row too. An empty list is therefore
    a meaningful argument — it means the re-review raised nothing.
    """
    _require_open(user_id, case_id)
    with as_user(user_id) as cur:
        cur.execute(
            """
            delete from findings f using tax_cases c
            where f.case_id = c.id and f.case_id = %s and c.user_id = %s
            """,
            (case_id, user_id),
        )
        for finding in findings:
            severity = str(finding.get("severity") or "suggestion")
            if severity not in _SEVERITIES:
                # The check constraint would reject it; a Reviewer that invents a
                # severity should not lose the finding over the vocabulary.
                severity = "suggestion"
            cur.execute(
                """
                insert into findings (case_id, severity, title, reasoning, category)
                values (%s, %s, %s, %s, %s)
                """,
                (case_id, severity, str(finding.get("title") or ""),
                 str(finding.get("reasoning") or ""),
                 str(finding.get("category") or "")),
            )


def get_findings(user_id: str, case_id: str) -> list[Finding]:
    """What the Reviewer raised, worst first — the order the Review screen reads in."""
    with as_user(user_id) as cur:
        cur.execute(
            """
            select f.severity, f.title, f.reasoning, f.category, f.resolution
            from findings f join tax_cases c on c.id = f.case_id
            where f.case_id = %s and c.user_id = %s
            order by case f.severity
                     when 'blocking' then 0 when 'warning' then 1 else 2 end,
                     f.created_at
            """,
            (case_id, user_id),
        )
        return [Finding(severity=s, title=t, reasoning=r, category=c, resolution=res)
                for s, t, r, c, res in cur.fetchall()]
