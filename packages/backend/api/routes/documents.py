"""The Documents API: upload, confirm, discard - and never a file on disk.

The upload endpoint reads the **raw request body**, not a multipart form, and that
is a requirement rather than a simplification. Starlette's multipart parser spools
any part over 1 MiB into a real temporary file (`MultiPartParser.max_file_size`), so
a photographed Lohnsteuerbescheinigung - 2 to 5 MB - would be written to /tmp on its
way in, and ADR 0004 promises the opposite. Reading the stream ourselves also means
the size limit is enforced *while* reading: a limit checked after the body is in hand
has already been exceeded.

The workflow behind it is `workflows/document_intake.py`. This module's whole job is
the boundary: hold the case lock, count the spend, keep the bytes in memory for one
request, and let nothing into `field_values` that the user has not confirmed.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from core.auth import current_user
from core.case_lock import CaseBusy, hold
from core.config import get_settings
from core.dependencies import (
    get_vision_client,
    get_vision_fallback_client,
    require_schema,
)
from db import cases
from db.connection import DatabaseNotConfigured
from db.usage import QuotaExceeded, spend_document_read
from domain.questions import BY_KEY, LOCALES, text_for
from services.documents import extract, retention
from services.documents.confirm import category_problem
from services.documents.confirm import check as check_confirmation
from services.documents.intake import MAX_BYTES, MAX_PDF_PAGES
from services.documents.sensitivity import DocumentKind, may_be_sent_to_a_model
from workflows.document_intake import (
    IntakeContext,
    build_graph,
    categories_for_choice,
    intake_thread_id,
)

router = APIRouter(prefix="/api/v1/cases/{case_id}/documents", tags=["documents"],
                   dependencies=[Depends(require_schema)])
logger = structlog.get_logger(__name__)


class DocumentResponse(BaseModel):
    """One document as a screen needs it."""

    id: str
    file_name: str
    kind: Optional[str] = None
    state: str
    # Only ever present while the document waits for a decision.
    proposed: list[dict[str, Any]] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    category: Optional[str] = None
    category_reason: str = ""
    contradiction: Optional[str] = None
    category_choices: list[str] = Field(default_factory=list)
    # Which model read this document. Present while it waits for a decision, because
    # that is when the values it produced are on the screen - and when the two are
    # not the same thing, the configured model having been unreachable, the trace has
    # to be able to say so rather than name the model that did not answer.
    read_by: Optional[str] = None
    # What the read cost, once the document is stored (#39). Null while it is still
    # a pause in the intake run, and null for a model with no price on file - which
    # is a gap, not a zero.
    read_cost_usd: Optional[float] = None
    read_tokens: Optional[int] = None
    failure_code: Optional[str] = None
    failure_detail: Optional[str] = None


class ConfirmRequest(BaseModel):
    """What the user settled on. Keys and values are validated, never trusted."""

    values: dict[str, Any] = Field(default_factory=dict)
    category: Optional[str] = None


def _must_be_awaiting(document: cases.Document, act: str) -> None:
    """Refuse a document that is no longer waiting for a decision.

    Called twice per route on purpose - once early for a cheap, clear refusal, and
    once inside the case lock, which is the one that decides. Between the two a
    concurrent confirm or discard can settle the document, and a resume after that
    would act on a run that is already over.
    """
    if document.state != "awaiting_confirmation":
        detail = {
            "confirm": f"this document is {document.state}, so there is nothing to confirm",
            "discard": f"this document is already {document.state}",
            "categorise": (f"this document is {document.state}, so its category cannot "
                           "be changed"),
        }[act]
        raise HTTPException(409, detail=detail)


def _must_be_categorisable(document: cases.Document) -> None:
    """Refuse a document whose category is not the user's to choose."""
    _must_be_awaiting(document, "categorise")
    if document.doc_type != DocumentKind.rechnung.value:
        # A Lohnsteuerbescheinigung yields the employment period and no expense at
        # all, so it has no category to choose (services/documents/mapping.py).
        raise HTTPException(
            409, detail="a Lohnsteuerbescheinigung has no expense category to choose",
        )


class CategoryRequest(BaseModel):
    """The category the user picked for a document still waiting for a decision."""

    category: str


def _checked_category(category: Optional[str]) -> Optional[str]:
    """One of the four, or a refusal. Never whatever the client wrote.

    The category is not a label on an invoice, it is what its Fact keys are built
    from (`domain/fields.key_for`), so an unknown one would key the amounts to
    nothing and land in `documents.extracted` as a category no calculator has.
    """
    if category is None or category in categories_for_choice():
        return category
    raise HTTPException(
        422,
        detail=(f"{category!r} is not a category a document can land in. Pick one of "
                f"{', '.join(categories_for_choice())}."),
    )


def _known_error(exc: Exception) -> HTTPException:
    if isinstance(exc, cases.CaseNotFound):
        return HTTPException(404, detail="no such case or document")
    if isinstance(exc, cases.CaseIsFinalized):
        return HTTPException(409, detail="the case is finalized; reopen it first")
    if isinstance(exc, DatabaseNotConfigured):
        return HTTPException(503, detail=str(exc))
    if isinstance(exc, CaseBusy):
        return HTTPException(409, detail=str(exc))
    if isinstance(exc, QuotaExceeded):
        return HTTPException(429, detail=exc.detail)
    raise exc


async def _body_within_limit(request: Request) -> bytes:
    """The whole body, or a refusal before it is all in memory.

    The stream is read chunk by chunk and abandoned the moment it goes over the
    limit, so an oversized upload costs the limit plus one chunk of memory rather
    than however much the client felt like sending.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(
                413,
                detail=(
                    f"The file is larger than {MAX_BYTES // 1024 // 1024} MB. A photo "
                    "of one page is well under it."
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


def request_locale(
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
) -> str:
    """Which language to write the field labels in.

    From the header, because a Tax Case does not carry a locale yet - making it one
    is issue #47, and this is the one screen that needs a translated label today.
    English for anything the catalogue has no text in, Turkish included (issue #54).
    """
    for tag in (accept_language or "").split(","):
        code = tag.split(";")[0].strip().lower()[:2]
        if code in LOCALES:
            return code
    return "en"


def _labelled(proposed: dict, locale: str) -> dict:
    """One proposed value with the words a person reads it by.

    The label comes from the Question catalogue rather than from a list kept here:
    the catalogue is where a Fact key's wording already lives, and a second list
    would be one to keep in step. `key` stays in the payload - it is what the
    confirmation sends back, and what an exported case is read by.
    """
    key = str(proposed.get("key", ""))
    base, _, suffix = key.partition("#")
    question = BY_KEY.get(base)
    repeats = bool(question and question.spec().repeats)
    return {
        **proposed,
        # Never blank: a key the catalogue does not hold is shown as itself rather
        # than as an empty label over an input nobody can interpret.
        "label": text_for(key, locale) or key,
        # Counted from 1 for a category that can hold several of the same thing, and
        # absent otherwise - "item 1 of 1" is noise, and the screens say which item
        # in their own words rather than having a number pressed into the label.
        "item": (int(suffix) + 1 if suffix.isdigit() else 1) if repeats else None,
    }


def _pause_of(state: Any) -> dict:
    """The payload of the pending `interrupt`, or an empty dict."""
    for task in getattr(state, "tasks", ()) or ():
        for pause in getattr(task, "interrupts", ()) or ():
            if isinstance(pause.value, dict):
                return pause.value
    return {}


async def _pause_for(graph, user_id: str, case_id: str, document: cases.Document) -> dict:
    """What one document is waiting to be asked about, read from its own run.

    The proposed values live in the paused run and nowhere else (ADR 0004), so any
    route that shows a document waiting for a decision has to go and get them. A
    document in any other state has no pause and is not looked up: a confirmed or
    discarded run has already been deleted, and asking would be one checkpointer
    round trip per row for an answer that is always empty.
    """
    if document.state != "awaiting_confirmation":
        return {}
    config = {"configurable": {
        "thread_id": intake_thread_id(user_id, case_id, document.id)}}
    return _pause_of(await graph.aget_state(config))


def _choices_for(document: cases.Document, pause: dict) -> list[str]:
    """The categories this document can be moved to, and an empty list otherwise.

    Empty for three of them, and none of the three is an oversight: a document that
    is no longer waiting has nothing to choose, a Lohnsteuerbescheinigung yields an
    employment period rather than an expense, and an invoice whose two reads
    disagreed proposes no values at all - so a category would be a choice about
    nothing (`workflows/document_intake.py`).
    """
    if document.state != "awaiting_confirmation":
        return []
    if document.doc_type != DocumentKind.rechnung.value:
        return []
    if pause.get("disagreements"):
        return []
    return categories_for_choice()


def _response(document: cases.Document, pause: dict, locale: str = "en") -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        file_name=document.file_name,
        kind=document.doc_type,
        state=document.state,
        proposed=[_labelled(item, locale) for item in (pause.get("proposed") or [])],
        questions=pause.get("questions") or [],
        disagreements=pause.get("disagreements") or [],
        category=pause.get("category"),
        category_reason=pause.get("category_reason", ""),
        contradiction=pause.get("contradiction"),
        category_choices=_choices_for(document, pause),
        # From the pause while the run is still open, from the row once it is stored:
        # the same fact, and the pause is gone by the time the document is listed.
        read_by=pause.get("read_by") or document.read_by_model,
        read_cost_usd=document.read_cost_usd,
        read_tokens=(
            (document.read_prompt_tokens or 0) + (document.read_completion_tokens or 0)
            if document.read_prompt_tokens is not None
            else None
        ),
        failure_code=document.failure_code,
        failure_detail=document.failure_detail,
    )


@router.post("", response_model=DocumentResponse, status_code=201)
async def upload_document(
    case_id: str,
    request: Request,
    kind: str,
    file_name: str = "document",
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user_id: str = Depends(current_user),
    locale: str = Depends(request_locale),
    vision=Depends(get_vision_client),
    vision_fallback=Depends(get_vision_fallback_client),
):
    """Read one document and stop, waiting for the user to confirm what it said.

    Everything that needs the bytes - the format checks and both extraction passes -
    happens inside this request. The run then pauses, and the bytes go out of scope
    with it (ADR 0004).
    """
    if not may_be_sent_to_a_model(kind):
        raise HTTPException(
            400,
            detail=(
                f"Only {', '.join(k.value for k in DocumentKind)} can be read. Anything "
                "else is not sent to a model at all."
            ),
        )

    settings = get_settings()
    data = await _body_within_limit(request)

    try:
        case = cases.get_case(user_id, case_id)
        document, created = cases.create_document(
            user_id, case_id, file_name=file_name, doc_type=kind,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    if not created:
        # The retry of an upload that already happened. Answer with what the first
        # one produced instead of reading - and paying for - the same page twice.
        graph = build_graph(await _saver())
        return _response(document, await _pause_for(graph, user_id, case_id, document), locale)

    try:
        spend_document_read(
            user_id,
            settings.document_reads_per_user_per_day,
            settings.document_reads_global_per_month,
        )
    except Exception as exc:  # noqa: BLE001
        cases.set_document_state(user_id, case_id, document.id, "failed",
                                 failure=("quota", getattr(exc, "detail", str(exc))))
        raise _known_error(exc)

    periods = cases.confirmed_employment_periods(user_id, case_id,
                                                 except_document=document.id)
    first_index = cases.next_item_index(user_id, case_id, "equipment.price_eur")

    saver = await _saver()
    graph = build_graph(saver)
    config = {"configurable": {
        "thread_id": intake_thread_id(user_id, case_id, document.id)}}

    # Filled by the closure below and read after the graph returns: the cost is known
    # inside the call the graph makes, and the row that was paid for is written
    # outside it. Threading it through the graph state would put token counts into a
    # checkpoint that exists to hold a paused run (#39).
    reading: dict = {}

    async def read_twice(*, data: bytes, upload, kind):
        first, second = await extract.read_twice(vision, data, upload, kind,
                                                 fallback=vision_fallback)
        reading.update(extract.reading_record(first, second, vision.model))
        return first, second

    try:
        async with hold(f"case:{case_id}"):
            result = await graph.ainvoke(
                {
                    "document_id": document.id,
                    "file_name": file_name,
                    "declared_format": request.headers.get("content-type", ""),
                    "kind": kind,
                    "tax_year": case.tax_year,
                    "known_periods": [[start, end] for start, end in periods],
                    "first_item_index": first_index,
                },
                config=config,
                context=IntakeContext(data=data, read_twice=read_twice),
            )
    except CaseBusy as busy:
        raise _known_error(busy)
    finally:
        # Not a comment about garbage collection: the name is the only reference this
        # request holds to a stranger's payslip, and the next line is where the
        # response is built.
        del data

    failure = result.get("failure")
    state = result.get("state", "failed")
    try:
        cases.set_document_state(
            user_id, case_id, document.id, state,
            failure=(failure["code"], failure["detail"]) if failure else None,
            reading=reading or None,
        )
        document = cases.get_document(user_id, case_id, document.id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    if failure:
        logger.info("document_failed", case_id=case_id, document_id=document.id,
                    code=failure["code"])

    return _response(document, _pause_of(await graph.aget_state(config)), locale)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    case_id: str,
    user_id: str = Depends(current_user),
    locale: str = Depends(request_locale),
):
    """This case's documents, expiring any that waited too long for a decision.

    Each document still waiting carries its proposed values with it. Answering
    without them would make a reloaded screen a dead end: the card would offer a
    Confirm button and no fields to confirm, and the empty confirmation it sent is
    refused - correctly, but the user has done nothing wrong.
    """
    settings = get_settings()
    try:
        # The sweep is a write, so it refuses a finalized case - and refusing the
        # whole listing with it turned "your case is finished" into a red error over
        # an empty screen that never stopped loading. A finished case has nothing to
        # expire anyway: an upload waiting for a decision is exactly what stops it
        # being finalized. So the sweep is skipped and the documents are still shown.
        if cases.get_case(user_id, case_id).status != "finalized":
            await retention.expire_abandoned(
                user_id, case_id, settings.document_confirmation_ttl_hours,
            )
        documents = cases.list_documents(user_id, case_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    if not any(document.state == "awaiting_confirmation" for document in documents):
        return [_response(document, {}, locale) for document in documents]

    graph = build_graph(await _saver())
    return [
        _response(document, await _pause_for(graph, user_id, case_id, document), locale)
        for document in documents
    ]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    case_id: str,
    document_id: str,
    user_id: str = Depends(current_user),
    locale: str = Depends(request_locale),
):
    """One document, with whatever it is waiting to be asked about.

    Through the same expiry sweep as the list, and that is the whole reason this
    route cannot be two lines: the values it returns are unconfirmed readings of
    somebody's payslip, kept only until the user decides or the TTL runs out
    (ADR 0004). A route that fetched one document without sweeping would hand back
    a reading the deadline had already taken away - the TTL would hold for the
    screen that lists documents and not for the one that shows a document.
    """
    settings = get_settings()
    try:
        await retention.expire_abandoned(
            user_id, case_id, settings.document_confirmation_ttl_hours,
        )
        document = cases.get_document(user_id, case_id, document_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    graph = build_graph(await _saver())
    return _response(document, await _pause_for(graph, user_id, case_id, document), locale)


@router.post("/{document_id}/category", response_model=DocumentResponse)
async def choose_category(
    case_id: str,
    document_id: str,
    request: CategoryRequest,
    user_id: str = Depends(current_user),
    locale: str = Depends(request_locale),
):
    """Map this document again under the category the user picked.

    Not a field on the confirmation, and not a label written over the proposal: the
    values an invoice yields are keyed by category, so the run goes back through
    `propose` and pauses again with what this category actually gives
    (`workflows/document_intake.py`). Nothing is written to the case here - the user
    still has to confirm what comes back.
    """
    category = _checked_category(request.category)
    settings = get_settings()

    try:
        # An upload past its TTL is expired before it is looked at, so a category
        # cannot be chosen for a reading the deadline has already taken away.
        await retention.expire_abandoned(
            user_id, case_id, settings.document_confirmation_ttl_hours,
        )
        document = cases.get_document(user_id, case_id, document_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    _must_be_categorisable(document)

    from langgraph.types import Command

    graph = build_graph(await _saver())
    config = {"configurable": {"thread_id": intake_thread_id(user_id, case_id, document_id)}}

    try:
        async with hold(f"case:{case_id}"):
            # Read again inside the lock. The check above is worth making early for
            # the error message, but it is not the one that decides: a confirmation
            # or a discard can finish between the two, and resuming a settled run
            # would put a `confirmed` document back to `awaiting_confirmation` with
            # its values already written into the case.
            document = cases.get_document(user_id, case_id, document_id)
            _must_be_categorisable(document)

            pause = await _pause_for(graph, user_id, case_id, document)
            if pause.get("disagreements"):
                # The same answer the empty `category_choices` gives: two readings
                # that differ propose no values under any category, so there is
                # nothing here to categorise.
                raise HTTPException(
                    409,
                    detail=("the two readings of this document disagree, so it has no "
                            "values to categorise. Enter them yourself, or upload a "
                            "clearer photo."),
                )

            result = await graph.ainvoke(
                Command(
                    resume={"decision": "reclassify", "category": category},
                    # Where this document's items start, as the case stands *now*.
                    # The index the upload computed can be stale by the time a
                    # category is chosen - another invoice may have been confirmed
                    # in between - and a stale one overwrites that invoice's items
                    # instead of adding to them.
                    update={"first_item_index": cases.next_item_index(
                        user_id, case_id, "equipment.price_eur")},
                ),
                config=config,
                # The document is gone; a re-mapping needs no bytes and gets none.
                context=IntakeContext(data=b"", read_twice=_no_reader),
            )
            failure = result.get("failure")
            # The state is written back even when it has not changed: `updated_at`
            # is what the abandonment sweep reads, and a user who just picked a
            # category is not a user who walked away (services/documents/retention.py).
            cases.set_document_state(
                user_id, case_id, document_id,
                "failed" if failure else "awaiting_confirmation",
                failure=(failure["code"], failure["detail"]) if failure else None,
            )
            document = cases.get_document(user_id, case_id, document_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    logger.info("document_reclassified", case_id=case_id, document_id=document_id,
                category=category)
    return _response(document, await _pause_for(graph, user_id, case_id, document), locale)


@router.post("/{document_id}/confirm", response_model=DocumentResponse)
async def confirm_document(
    case_id: str,
    document_id: str,
    request: ConfirmRequest,
    user_id: str = Depends(current_user),
    locale: str = Depends(request_locale),
):
    """Write the values the user settled on, and forget the document.

    The provenance of each value is decided here from the paused run's own proposal,
    not from the request: a reading left as it stands is a `document` value, a
    corrected or typed one is an `answer` (issue #12). A client cannot claim
    otherwise, because it is not asked.
    """
    saver = await _saver()
    graph = build_graph(saver)
    config = {"configurable": {"thread_id": intake_thread_id(user_id, case_id, document_id)}}
    settings = get_settings()

    try:
        # An upload past its TTL is expired before it is read, so a confirmation
        # cannot write values the deadline has already taken away (ADR 0004).
        await retention.expire_abandoned(
            user_id, case_id, settings.document_confirmation_ttl_hours,
        )
        document = cases.get_document(user_id, case_id, document_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    _must_be_awaiting(document, "confirm")

    category = _checked_category(request.category)

    pause = _pause_of(await graph.aget_state(config))
    proposed = {item["key"]: item["value"] for item in (pause.get("proposed") or [])}

    checked, problems = check_confirmation(
        request.values, proposed=proposed, document_id=document_id,
    )
    if problems:
        raise HTTPException(422, detail="; ".join(problems))
    if not checked:
        raise HTTPException(
            422,
            detail="nothing was confirmed. Enter at least one value, or discard the document.",
        )

    # The category and the keys have to be the same claim. Each passes its own
    # validation - one of the four, and a key the catalogue holds - so
    # `fortbildungskosten` alongside `equipment.price_eur` gets through both and
    # stores a document whose category contradicts its own values.
    mismatch = category_problem(
        checked, recorded=category, proposed=pause.get("category"),
    )
    if mismatch:
        raise HTTPException(422, detail=mismatch)

    from langgraph.types import Command

    try:
        async with hold(f"case:{case_id}"):
            # Read again under the lock: a discard - or another confirmation - can
            # finish between the check above and this line, and resuming a run that
            # is already settled would write its values a second time.
            _must_be_awaiting(cases.get_document(user_id, case_id, document_id), "confirm")
            result = await graph.ainvoke(
                Command(resume={
                    "decision": "confirm",
                    "values": request.values,
                    "category": category,
                }),
                config=config,
                # The document is gone; the resume needs no bytes and gets none.
                context=IntakeContext(data=b"", read_twice=_no_reader),
            )

            for value in checked:
                cases.set_field(user_id, case_id, value.key, value.value,
                                item_index=value.item_index)

            cases.set_document_state(
                user_id, case_id, document_id, "confirmed",
                extracted=_confirmed_record(result, checked),
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    await retention.forget_run(user_id, case_id, document_id)
    logger.info("document_confirmed", case_id=case_id, document_id=document_id,
                values=len(checked))
    return _response(cases.get_document(user_id, case_id, document_id), {}, locale)


@router.post("/{document_id}/discard", response_model=DocumentResponse)
async def discard_document(
    case_id: str,
    document_id: str,
    user_id: str = Depends(current_user),
    locale: str = Depends(request_locale),
):
    """Throw the reading away. The row stays, saying an upload was rejected."""
    saver = await _saver()
    graph = build_graph(saver)
    config = {"configurable": {"thread_id": intake_thread_id(user_id, case_id, document_id)}}

    from langgraph.types import Command

    def _still_discardable(document: cases.Document) -> cases.Document:
        # A failed or still-reading upload may be thrown away; a settled one is
        # already an answer, and re-settling it would say the user decided twice.
        if document.state in {"confirmed", "discarded"}:
            raise HTTPException(409, detail=f"this document is already {document.state}")
        return document

    try:
        _still_discardable(cases.get_document(user_id, case_id, document_id))
        async with hold(f"case:{case_id}"):
            # Under the lock is where it counts: a confirmation running concurrently
            # can settle the document between the check above and this one.
            document = _still_discardable(cases.get_document(user_id, case_id, document_id))
            if document.state == "awaiting_confirmation":
                await graph.ainvoke(
                    Command(resume={"decision": "discard"}),
                    config=config,
                    context=IntakeContext(data=b"", read_twice=_no_reader),
                )
            cases.set_document_state(user_id, case_id, document_id, "discarded")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    await retention.forget_run(user_id, case_id, document_id)
    return _response(cases.get_document(user_id, case_id, document_id), {}, locale)


# --- the bits that touch the checkpointer ---------------------------------------

async def _saver():
    """The same checkpointer the interview uses (agents/graph.py).

    One store for both, which is what lets `services/case_erasure.py` clear a case's
    runs without knowing how many kinds of run there are.
    """
    from agents.graph import checkpointer

    return await checkpointer()


async def _no_reader(**_):
    raise AssertionError("a resumed run must not read the document again")


def _confirmed_record(result: dict, checked) -> dict:
    """What `documents.extracted` keeps: the confirmed, normalised result.

    Never the two passes and never what they disagreed about - two unconfirmed
    readings of somebody's payslip are not something to keep once the user has
    decided (schema/0009). The employment period is kept in the shape
    `confirmed_employment_periods` reads back, so several payslips add up.
    """
    values = {f"{value.key}#{value.item_index}" if value.item_index else value.key:
              value.value.value for value in checked}
    record: dict[str, Any] = {"values": values}

    confirmed = result.get("confirmed") or {}
    if confirmed.get("category"):
        record["category"] = confirmed["category"]

    read = result.get("values") or {}
    for field in ("employment_period_start", "employment_period_end", "tax_year",
                  "invoice_date", "price_basis"):
        if read.get(field) is not None:
            record[field] = read[field]
    return record


__all__ = ["MAX_PDF_PAGES", "router"]
