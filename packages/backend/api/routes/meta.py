"""What this build actually offers, in one place the product cannot contradict.

The two modes look alike from the outside - both are a box you type into - and
until now nothing told a visitor that one answers questions from a knowledge base
while the other opens a Tax Case that is stored, resumable and erasable, or that
a Tax Case needs a database that this instance may not have. The scope statement
is that answer, and it is served rather than written down so it cannot drift: the
years come from `domain/tax_years.py`, the forms and how sure the build is of
their line numbers from the same year blocks, the limits from settings, and a
mode's availability - and whether it is traced - from the configuration the
request will actually meet.

It answers facts, not sentences: ids, numbers, booleans, ISO dates. The product
speaks four languages and the wording belongs in the frontend catalogue, so every
string here is a stable identifier to look up, never prose to display.

Deliberately unauthenticated, unlimited and offline: a landing page asks this
before anyone logs in, it reads process-local constants and the schema answer that
is already cached, and it must be able to report that the database is missing -
which a route holding `require_schema` could not do.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter
from pydantic import BaseModel

from core.config import get_settings
from db.schema_version import cached_status
from domain.tax_years import DEFAULT_TAX_YEAR, TAX_YEARS

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


# Why a mode is closed. Empty when it is open. The frontend renders each of these
# as a sentence; adding one here without adding it there shows the visitor a code.
NO_PROVIDER_KEY: Final = "no_provider_key"
DATABASE_NOT_CONFIGURED: Final = "database_not_configured"
SCHEMA_DRIFT: Final = "schema_drift"
SCHEMA_NOT_CHECKED: Final = "schema_not_checked"
DATABASE_UNREACHABLE: Final = "database_unreachable"

# Where a mode leaves something behind. Four stores, because one boolean could not
# tell them apart: it said "stores data: no" for a chat whose history the browser
# keeps, and "stores data: yes" for a Tax Case whose deletion does not reach the
# profile memory or the traces. Each of these is an id the frontend turns into a
# sentence; the browser's own history is not here, because this process cannot
# observe it - `lib/conversation-history.ts` states that one from its own constants.

# Server storage.
SERVER_REQUEST_LOGS_ONLY: Final = "request_logs_only"
SERVER_CASE_UNTIL_DELETED: Final = "case_until_deleted"

# Profile memory - the LangGraph Store, which outlives the case on purpose (ADR 0011)
# and has a delete of its own (`DELETE /api/v1/profile`).
PROFILE_MEMORY_NONE: Final = "none"
PROFILE_MEMORY_OUTLIVES_THE_CASE: Final = "outlives_the_case"

# Tracing, read from the same two settings `core/tracing.py` reads. An empty
# endpoint is not "no region": it is LangSmith's US default, which is a different
# answer to give a visitor than the EU one, so it gets an id of its own.
TRACING_NONE: Final = "none"
TRACING_LANGSMITH_EU: Final = "langsmith_eu"
TRACING_LANGSMITH_US: Final = "langsmith_us"

# What this build does not do, as ids the frontend spells out. Kept from the
# "Explicitly outside the current Capstone" section of docs/KNOWN_LIMITATIONS.md:
# these are decisions, not gaps waiting to be filled, and the statement is only
# honest if it names them before a visitor assumes otherwise.
NOT_SUPPORTED: Final[tuple[str, ...]] = (
    "electronic_submission",  # nothing is filed with the Finanzamt; the PDF is a draft
    "tax_advice",  # § 2 StBerG - this is preparation, not advice
    "capital_income",  # Anlage KAP and friends
    "self_employment",  # Anlage S/G - the filer modelled here is employed
    "corporate_or_non_resident",
    "progressionsvorbehalt_rate",  # the benefit is captured, the rate is not recomputed
    "joint_assessment",  # one filer per case
    "document_archive",  # ADR 0004 - documents are read, then discarded
)


class DataScope(BaseModel):
    """What using a mode leaves behind, named one store at a time.

    Three fields rather than one boolean, and the fourth store - the browser's own
    chat history - deliberately absent: this process cannot see a localStorage and
    must not claim anything about it.
    """

    server: str
    profile_memory: str
    tracing: str


class ModeScope(BaseModel):
    """One of the two things a visitor can do, and whether they can do it here."""

    id: str  # "chat" or "tax_case"
    available: bool
    # One of the codes above, or empty. Usually the thing that closed the mode,
    # but `schema_not_checked` rides along with an open one: the instance has not
    # verified its schema yet, and neither promising nor refusing would be true.
    reason: str = ""
    requires_account: bool
    storage: DataScope


class FormScope(BaseModel):
    """A form this build can place figures on, and how sure it is of the lines."""

    form: str
    categories: list[str]
    # False where a line number is this build's best reading rather than a checked
    # one. A draft is still produced; the number above the figure may move.
    lines_verified: bool


class TaxYearScope(BaseModel):
    """A year this build has rules for, with the period it may be filed in."""

    year: int
    filing_due: str
    filing_due_advised: str
    voluntary_filing_until: str
    forms: list[FormScope]


class ScopeResponse(BaseModel):
    """The whole statement. One request, everything a visitor is owed up front."""

    modes: list[ModeScope]
    tax_years: list[TaxYearScope]
    default_tax_year: int
    # Demo ceilings, named as settings so the number on screen is the number
    # enforced. Zero means the limit is off in this deployment.
    limits: dict[str, int]
    not_supported: list[str]


@router.get("/scope", response_model=ScopeResponse)
async def scope_statement() -> ScopeResponse:
    """What this build covers and what it refuses, computed from the build itself.

    Never asks the database. `cached_status` is what the startup check and the
    health poll already filled in, so an instance that has not finished starting
    reports `schema_not_checked` rather than blocking on a connection.
    """
    settings = get_settings()
    has_provider = bool(settings.openrouter_api_key)
    tracing = _tracing_scope(settings)

    # The chat needs the database too, since #32: the knowledge base moved out of the
    # deploy and into Postgres, so there is nothing to search without one. Reported
    # rather than glossed over - this page exists to say what this instance can do.
    chat_blocker = ("" if has_provider else NO_PROVIDER_KEY) or (
        "" if settings.database_url else DATABASE_NOT_CONFIGURED)
    chat = ModeScope(
        id="chat",
        available=not chat_blocker,
        reason=chat_blocker,
        requires_account=False,
        storage=DataScope(
            # The question and its answer are logged as any request is; no Tax Case,
            # no field values, nothing keyed to a person. What the *browser* keeps is
            # a separate claim, and the frontend makes it.
            server=SERVER_REQUEST_LOGS_ONLY,
            # Profile memory is written by the interview only. A question asked here
            # is not remembered for the next one.
            profile_memory=PROFILE_MEMORY_NONE,
            tracing=tracing,
        ),
    )

    blocker = _tax_case_reason(has_provider, bool(settings.database_url))
    tax_case = ModeScope(
        id="tax_case",
        # An unchecked schema is not a closed door. The startup check fills the
        # cache in seconds, and a landing page that asked first would otherwise
        # tell every early visitor the product does not work.
        available=blocker in ("", SCHEMA_NOT_CHECKED),
        reason=blocker,
        requires_account=True,
        storage=DataScope(
            server=SERVER_CASE_UNTIL_DELETED,
            # Deleting the case does not reach this, on purpose (ADR 0011,
            # `services/case_erasure.py`), which is exactly why the page may not
            # say a deletion takes everything with it.
            profile_memory=PROFILE_MEMORY_OUTLIVES_THE_CASE,
            tracing=tracing,
        ),
    )

    return ScopeResponse(
        modes=[chat, tax_case],
        tax_years=[_year_scope(year) for year in sorted(TAX_YEARS)],
        default_tax_year=DEFAULT_TAX_YEAR,
        limits={
            "cases_per_user": settings.cases_per_user,
            "interview_calls_per_user_per_day": settings.interview_calls_per_user_per_day,
            "interview_calls_global_per_month": settings.interview_calls_global_per_month,
            "document_reads_per_user_per_day": settings.document_reads_per_user_per_day,
            "document_reads_global_per_month": settings.document_reads_global_per_month,
            "document_confirmation_ttl_hours": settings.document_confirmation_ttl_hours,
        },
        not_supported=list(NOT_SUPPORTED),
    )


def _tracing_scope(settings) -> str:
    """Whether this instance uploads traces, and to which region.

    The same two settings `core/tracing.py` acts on, read the same way: no key means
    nothing is sent at all, and an endpoint that is not the EU one means the SDK's US
    default. A visitor asking where their data goes is owed the second distinction as
    much as the first - see `docs/TRACING_POLICY.md`.
    """
    if not settings.langsmith_api_key:
        return TRACING_NONE
    if "eu." in settings.langsmith_endpoint:
        return TRACING_LANGSMITH_EU
    return TRACING_LANGSMITH_US


def _tax_case_reason(has_provider: bool, has_database: bool) -> str:
    """The first thing standing in the way of opening a Tax Case here."""
    if not has_provider:
        return NO_PROVIDER_KEY
    if not has_database:
        return DATABASE_NOT_CONFIGURED

    current = cached_status()
    if current is None:
        return SCHEMA_NOT_CHECKED
    if current.database == "not_configured":
        return DATABASE_NOT_CONFIGURED
    if current.database != "ok":
        return DATABASE_UNREACHABLE
    return "" if current.ok else SCHEMA_DRIFT


def _year_scope(year: int) -> TaxYearScope:
    """One year's filing period and the forms its categories land on."""
    rules = TAX_YEARS[year]

    placements = [(c.value, line) for c, line in rules.form_lines.items()]
    if rules.benefit_form_line is not None:
        # Not an expense category - it is the Einkommensersatzleistung declared on
        # the Hauptvordruck. It still names a sheet this build writes on, which is
        # what a visitor is asking, so it earns its row.
        placements.append(("einkommensersatzleistung", rules.benefit_form_line))

    forms: dict[str, FormScope] = {}
    for category, placement in placements:
        entry = forms.setdefault(
            placement.form,
            FormScope(form=placement.form, categories=[], lines_verified=True),
        )
        entry.categories.append(category)
        # One unverified line makes the whole form unverified: a visitor deciding
        # whether to trust the draft is deciding about the sheet, not about a row.
        if not placement.verified:
            entry.lines_verified = False

    for entry in forms.values():
        entry.categories.sort()

    return TaxYearScope(
        year=rules.year,
        filing_due=rules.filing_due,
        filing_due_advised=rules.filing_due_advised,
        voluntary_filing_until=rules.voluntary_filing_until,
        forms=[forms[name] for name in sorted(forms)],
    )
