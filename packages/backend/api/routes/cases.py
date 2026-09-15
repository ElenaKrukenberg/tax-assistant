"""The Tax Case API: the case itself, and the interview that fills it.

Every route requires a verified Supabase token (core/auth.py) and passes the user
id into the repository, which runs its SQL under row level security. The two locks
from db/README.md both live below this file; the route's own job is to never take
an id from anywhere but the token.

The interview is one endpoint advancing the graph by one pause. The graph pauses
with a typed payload (question / confirm_stop / findings / final_approval), the
frontend renders it, POSTs the resume value, and the graph runs to the next pause.
Each provider decision takes a few seconds, so the call is synchronous; the run_id
plus SSE machinery from the plan arrives with the long review step, not here.

Answers are persisted twice on purpose and not by accident: into `field_values`
with their provenance the moment they arrive — the tables are the source of truth
(ADR 0005) — and into the graph state, which is only the paused run.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import structlog
from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agents import profile_memory
from agents.gap_finder import FALLBACK_RATIONALE, find_candidates, kb_justifier
from agents.graph import build_graph, case_thread_id, checkpointer, read_stop_answer
from core.auth import current_user
from core.case_lock import CaseBusy, hold
from core.dependencies import (
    get_llm_client,
    get_retriever,
    get_reviewer_client,
    require_schema,
)
from core.rate_limit import enforce_rate_limit
from core.config import get_settings
from db import cases
from db.connection import DatabaseNotConfigured
from db.usage import QuotaExceeded, spend_interview_call
from services import case_erasure, profile_erasure
from domain.fields import ExpenseCategory, FieldValue, Provenance
from domain.positions import includable_positions, project_expenses
from domain.questions import BY_ID, BY_KEY
from domain.resume import ResumeInvalid, validate_resume
from domain.tax_years import TAX_YEARS, for_year

# require_schema on the router, not on each route: a Tax Case cannot be served
# truthfully by a database that is behind this build, and that is true of all of
# them. Declaring it per route would be one more thing to remember when a route is
# added - which is the class of mistake the check itself exists to catch.
router = APIRouter(prefix="/api/v1/cases", tags=["cases"],
                   dependencies=[Depends(require_schema)])
logger = structlog.get_logger(__name__)


class CreateCaseRequest(BaseModel):
    tax_year: int = Field(..., ge=2020, le=2100)


class CaseResponse(BaseModel):
    id: str
    tax_year: int
    status: str


class CaseDetailResponse(CaseResponse):
    fields: dict[str, Any]
    # Assumptions and values carried over from an earlier year, both waiting for the
    # user to look at them. A report may not be generated while this is non-empty.
    unconfirmed_values: list[str]
    # Computed on read from the same code the review audits (domain/estimate.py):
    # the dashboard never shows a figure the graph would disagree with.
    expenses: list[dict[str, Any]]
    proposed_expenses: list[dict[str, Any]]
    tax_positions: list[dict[str, Any]]
    total_eur: float
    proposed_total_eur: float
    pauschbetrag_eur: float
    # Rule-only gap hints for the dashboard: no model, no cost, no citation. The
    # cited version appears on the stop card, where a model justifies each one.
    gaps: list[dict[str, Any]]
    # What the Reviewer raised, worst first. Empty until the review has run, which
    # is why the Review screen distinguishes "nothing raised" from "not yet looked
    # at" by the case status rather than by this list being empty.
    findings: list[dict[str, Any]]
    # Whether the last review ran with its own model. None before any review; False
    # means deterministic rules only, and the Review screen says so rather than
    # letting a degraded pass look like an independent second opinion (#29).
    review_from_model: Optional[bool] = None
    review_note: str = ""


class InterviewRequest(BaseModel):
    # None on the first call; afterwards, whatever the pending pause asks for:
    # {"value": ...} for a question, true/false for confirmations,
    # {"action": "revise"|"dismiss"} for findings.
    resume: Optional[Any] = None


class InterviewResponse(BaseModel):
    status: str
    pause: Optional[dict] = None  # absent exactly when the case is finalized
    done: bool = False
    # How many questions have been answered, from the tables rather than from the
    # browser's memory of this session: a refresh used to reset the visible count to
    # zero while the answers were still there (#53).
    answered: int = 0
    # Present only when the backend runs with DEBUG=true: what the developer panel
    # renders. Off in production by the same flag, so the panel cannot exist there.
    debug: Optional[dict] = None


def _known_error(exc: Exception) -> HTTPException:
    if isinstance(exc, cases.CaseNotFound):
        return HTTPException(404, detail="no such case")
    if isinstance(exc, cases.CaseIsFinalized):
        return HTTPException(409, detail=str(exc))
    if isinstance(exc, DatabaseNotConfigured):
        return HTTPException(503, detail="the database is not configured")
    if isinstance(exc, CaseBusy):
        # Not the user's doing: an interview on this case is still inside a provider
        # call and holds the lock. Retrying is the right advice.
        return HTTPException(409, detail="the case is busy; try again in a moment")
    raise exc


@router.post("", response_model=CaseResponse, status_code=201)
def create_case(request: CreateCaseRequest, user_id: str = Depends(current_user)):
    if request.tax_year not in TAX_YEARS:
        known = ", ".join(str(y) for y in sorted(TAX_YEARS))
        raise HTTPException(422, detail=f"no tax rules for {request.tax_year}; "
                                        f"this build covers {known}")
    limit = get_settings().cases_per_user
    try:
        existing = cases.list_cases(user_id)
        if limit > 0 and len(existing) >= limit and request.tax_year not in {
            c.tax_year for c in existing
        }:
            # Re-opening an existing year is always allowed; only new years count.
            raise HTTPException(
                409, detail=f"this demo allows {limit} cases per account; "
                            "delete one to start another")
        case = cases.create_case(user_id, request.tax_year)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)
    return CaseResponse(id=case.id, tax_year=case.tax_year, status=case.status)


@router.get("", response_model=list[CaseResponse])
def list_cases(user_id: str = Depends(current_user)):
    try:
        return [CaseResponse(id=c.id, tax_year=c.tax_year, status=c.status)
                for c in cases.list_cases(user_id)]
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)


@router.get("/{case_id}", response_model=CaseDetailResponse)
def get_case(case_id: str, user_id: str = Depends(current_user)):
    try:
        case = cases.get_case(user_id, case_id)
        fields = cases.get_fields(user_id, case_id)
        pending = cases.values_awaiting_confirmation(user_id, case_id)
        findings = cases.get_findings(user_id, case_id)
        positions = cases.get_positions(user_id, case_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)
    # Flattened for the calculators, which take values; `fields` goes on to
    # `assess_positions` as well, because that is where a value's provenance turns
    # into the evidence beside a figure (domain/positions.py:documents_behind).
    known = {k: v.value for k, v in fields.items()}
    year = for_year(case.tax_year)
    included = includable_positions(positions, known)
    # Recomputed here rather than read out of the row: the form line, the formula and
    # the documents are functions of the facts and the year, and the position never
    # stored them. Before this they came back empty on every reloaded case.
    proposed_expenses = project_expenses(positions, fields, year)
    expenses = project_expenses(included, fields, year)
    return CaseDetailResponse(
        id=case.id, tax_year=case.tax_year, status=case.status,
        fields={k: {"value": v.value, "provenance": v.provenance.value,
                    "confirmed": v.confirmed,
                    # Present only on a value somebody changed by hand, which is what
                    # lets the screen say "corrected from 154" rather than showing 145
                    # as though nobody had touched it (#28).
                    "superseded_value": v.superseded_value,
                    "superseded_provenance": v.superseded_provenance}
                for k, v in fields.items()},
        unconfirmed_values=pending,
        expenses=expenses,
        proposed_expenses=proposed_expenses,
        tax_positions=[position.as_dict() for position in positions],
        total_eur=round(sum(row["amount_eur"] for row in expenses), 2),
        proposed_total_eur=round(sum(row["amount_eur"] for row in proposed_expenses), 2),
        pauschbetrag_eur=year.pauschbetrag,
        gaps=[{"category": c.value, "rationale": FALLBACK_RATIONALE[c]}
              for c in find_candidates(known)],
        findings=[f.model_dump() for f in findings],
        review_from_model=case.last_review_from_model,
        review_note=case.last_review_note,
    )


class CorrectionRequest(BaseModel):
    # The new value, in whatever shape the question's answer type has. Validated
    # against the catalogue below rather than trusted: this endpoint writes straight
    # into `field_values`, with no interview round to catch a wrong type.
    value: Any
    item_index: int = Field(default=0, ge=0)


@router.patch("/{case_id}/fields/{key}", response_model=CaseDetailResponse)
def correct_field(case_id: str, key: str, request: CorrectionRequest,
                  user_id: str = Depends(current_user)):
    """Correct one fact in place, without walking back through the interview.

    The gap this closes is the one that makes "human in the loop" untrue: the only
    correction available was undoing the last answer, so a wrong value three questions
    back, or one wrong item among several purchases, could be seen and not changed.

    The editable unit is the fact and never the computed total (#12). Everything
    downstream is a read over the facts, so the whole case moves with the corrected
    value on the next GET - including the tax positions, whose fingerprint stops
    matching and whose accepted decisions therefore go back to the user rather than
    being carried onto a figure they never saw.
    """
    question = BY_KEY.get(key)
    if question is None:
        raise HTTPException(404, detail=f"{key} is not a fact this build knows")
    try:
        # The same validation an interview answer goes through. A correction is an
        # answer - it just arrives without a question on screen.
        validate_resume({"type": "question", "question_id": question.id,
                         "answer_type": question.answer_type,
                         "options": list(getattr(question, "options", ()) or []),
                         "minimum": getattr(question, "minimum", None),
                         "maximum": getattr(question, "maximum", None)},
                        {"value": request.value})
    except ResumeInvalid as exc:
        raise HTTPException(422, detail=str(exc)) from None

    try:
        cases.correct_field(user_id, case_id, key, request.value, request.item_index)
    except KeyError:
        raise HTTPException(404, detail=f"{key} is not set on this case") from None
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)
    return get_case(case_id, user_id)


@router.delete("/{case_id}/items/{category}/{item_index}",
               response_model=CaseDetailResponse)
def remove_item(case_id: str, category: str, item_index: int,
                user_id: str = Depends(current_user)):
    """Remove one purchase from a repeating category.

    Correcting a value covers a wrong number; this covers a wrong *thing* - an invoice
    uploaded by mistake, or a line read off a receipt that turned out to be private.
    Without it the only way out was deleting the whole case (#35).
    """
    if category not in {c.value for c in ExpenseCategory}:
        raise HTTPException(404, detail=f"{category} is not an expense category")
    try:
        removed = cases.remove_item(user_id, case_id, category, item_index)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)
    if not removed:
        raise HTTPException(404, detail=f"{category} has no item {item_index}")
    return get_case(case_id, user_id)


@router.post("/{case_id}/reopen", response_model=CaseResponse,
             dependencies=[Depends(enforce_rate_limit)])
async def reopen_case(case_id: str, user_id: str = Depends(current_user)):
    """Unlock a finalized case so a decision made at the end can be taken back.

    Approving the report finalizes the case, and the tables enforce that: the
    trigger in `schema/0001` refuses every later write, so a position declined by
    mistake could not be reconsidered and a figure could not be corrected. The
    database has always been able to lift the lock (`cases.reopen`); nothing could
    reach it, which made "reopen it first" advice with no door behind it.

    The finished run is deleted along with the lock. A graph that has reached its
    end has nothing left to resume, and the next advance rebuilds the run from the
    tables - which is the same path an interview picked up after a week takes
    (`_advance_events`), so the answers, documents and positions already recorded
    are carried back in rather than asked again.

    Reopening a case that is not finalized changes nothing and returns it as it is:
    the button lives on a screen two tabs can show at once, and the second click is
    not an error worth an alarm.
    """
    try:
        case = cases.get_case(user_id, case_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)
    if case.status != "finalized":
        return CaseResponse(id=case.id, tax_year=case.tax_year, status=case.status)

    try:
        # Both stores under one lock, in this order: the run goes first, so a failure
        # in between leaves a finalized case with no run - which the next advance
        # rebuilds - rather than an unlocked case still holding a finished one.
        async with hold(case_thread_id(user_id, case_id)):
            saver = await checkpointer()
            await saver.adelete_thread(case_thread_id(user_id, case_id))
            case = await to_thread.run_sync(cases.reopen, user_id, case_id)
    except CaseBusy as exc:
        raise _known_error(exc)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    logger.info("case_reopened", case_id=case_id)
    return CaseResponse(id=case.id, tax_year=case.tax_year, status=case.status)


@router.delete("", status_code=204)
async def delete_all_cases(user_id: str = Depends(current_user)):
    """Every Tax Case this user has, gone - tables and paused runs alike.

    Goes on past a case it cannot delete, so one stuck case does not stand between
    the user and the rest of theirs. 204 therefore means all of them; a 500 names how
    many are left and the request can simply be repeated.

    What it does not touch: the profile memory, which outlives cases on purpose
    (#23), and the chat history in this browser (#18). The confirmation text says so.
    """
    try:
        failed = await case_erasure.erase_all_cases(user_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)
    if failed:
        raise HTTPException(
            500, detail=f"{len(failed)} case(s) could not be deleted; try again")


@router.delete("/{case_id}", status_code=204)
async def delete_case(case_id: str, user_id: str = Depends(current_user)):
    """The product's promise made callable: a case and everything in it, gone.

    "Everything in it" now means both stores that hold the answers - the tables and
    the paused graph run - and 204 is returned only once both are clear. Deleting a
    case that is already gone is a 404, not a silent success: the caller asked about
    a case this user does not have, and that is worth saying.

    What survives is listed and argued for in `services/case_erasure.py`.
    """
    try:
        await case_erasure.erase_case(user_id, case_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)


# Printed in the margin of page one. German, because the form is: whoever picks the
# page up off a printer has to see what it is in the language they are reading it in.
DRAFT_NOTE = ("ENTWURF - erstellt vom German Tax Assistant. Bitte jede Zahl pruefen; "
              "dieses Blatt wurde nicht eingereicht.")

# The contract, decided in #30 and written into docs/AGENT_ARCHITECTURE.md: an export
# before the user approves the case is a draft and says so on the page. A case the user
# has approved exports without the banner - that is what approving it means - unless a
# figure could not be placed on the form, in which case the sheet is incomplete and an
# unmarked incomplete tax form is the worst of the three outcomes.
INCOMPLETE_NOTE = ("UNVOLLSTAENDIG - {count} Betrag/Betraege konnten auf diesem "
                   "Vordruck nicht eindeutig zugeordnet werden. Bitte die Begleitliste "
                   "pruefen, bevor Sie das Blatt verwenden.")

_GRAPH_STATUS = {"question": "gathering", "confirm_stop": "gathering",
                 "findings": "needs_user_input", "final_approval": "needs_user_input"}

# The two pauses a review has just run before. Findings are written to the tables at
# exactly these moments and at finalize, and nowhere else: writing on every advance
# would be a delete plus inserts per answered question, and writing only when the
# list is non-empty would leave a cleared finding on screen forever.
_REVIEW_PAUSES = ("findings", "final_approval")


def _save_findings(user_id: str, case_id: str, values: dict) -> None:
    """Record what the Reviewer raised, so the Review screen can show it later.

    Best effort: the findings the user is looking at came from the graph state and
    are already on their way to the screen. Losing the copy costs a later reread,
    which is not worth failing an interview advance over.
    """
    try:
        cases.save_findings(user_id, case_id, list(values.get("findings") or []))
        # Saved even when nothing was raised, which is the case that matters: a
        # rules-only pass with no findings is indistinguishable from a clean
        # independent review unless the mode itself is recorded (#29).
        cases.save_review_mode(
            user_id, case_id,
            from_model=bool(values.get("review_from_model", True)),
            note=str(values.get("review_note") or ""),
        )
    except Exception:  # noqa: BLE001
        logger.warning("findings_not_saved", case_id=case_id, exc_info=True)


async def _advance_events(case_id: str, user_id: str, resume,
                          llm=None, reviewer=None, retriever=None):
    """Advance the graph by one pause, yielding ("node", name) as nodes are crossed
    and finally ("result", InterviewResponse).

    The three collaborators arrive as arguments rather than being fetched here. They
    used to be plain calls to the factories in `core/dependencies.py`, which meant
    `app.dependency_overrides` never applied to them: FastAPI only intercepts what a
    route declares with `Depends`, and a direct call goes straight past it. So this
    suite's own override of the models to None had no effect for as long as it
    existed, and the integration tests were making real, paid provider calls while
    their docstring said no model was involved anywhere.

    One generator behind both endpoints: the plain POST drains it and returns the
    result, the SSE endpoint forwards every event — the two cannot disagree about
    what an advance does. The node events are the graph's own `updates` stream,
    which makes the developer panel's run-through real rather than reconstructed.
    """
    from langgraph.types import Command

    try:
        case = cases.get_case(user_id, case_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)
    if case.status == "finalized":
        # Opening the Interview tab on a finished case is not an error: the interview
        # is over, and "over" is what the screen should say. Only an attempt to
        # *answer* one is refused, which is the read-only promise the tables enforce
        # anyway (the trigger in schema/0001). Going back is refused too, in the
        # route below: that one is a write.
        if resume is not None:
            raise HTTPException(409, detail="the case is finalized; reopen it first")
        yield ("result", InterviewResponse(status=case.status, done=True,
                                   answered=cases.answered_count(user_id, case_id)))
        return

    settings = get_settings()
    config = {"configurable": {"thread_id": case_thread_id(user_id, case_id)}}

    try:
        saver = await checkpointer()
        store = await _open_profile_store()
        justifier = kb_justifier(retriever, llm) if llm is not None else None
        graph = build_graph(llm, reviewer, saver, gap_justifier=justifier)
        state = await graph.aget_state(config)
        pending = _pending_pause(state)

        if pending is None:
            if resume is not None:
                # An answer to a question nobody asked. Until this check the branch
                # fell straight through to starting a fresh run: `validate_resume` is
                # only ever reached with a pause in hand, so the payload went
                # unvalidated, the quota was spent, and the value disappeared into a
                # run that had asked nothing. A tab left open across a cleared
                # checkpoint sends exactly this.
                raise HTTPException(422, detail="no question is pending; reconnect first")
            _spend(user_id, settings)
            # No paused run: start one from what the tables already know, so an
            # interview picked up after a week does not re-ask what documents or
            # the chat already answered.
            fields = cases.get_fields(user_id, case_id)
            persisted_positions = cases.get_positions(user_id, case_id)
            known = {k: v.value for k, v in fields.items()}
            carried = await _seed_from_memory(store, user_id, case, known, fields)
            stream_input = {"tax_year": case.tax_year, "known": known,
                            "provenance": {
                                key: {"provenance": held.provenance.value,
                                      "source": held.source}
                                for key, held in fields.items()
                            },
                            "asked": [], "carried_over": carried,
                            "tax_positions": [position.as_dict()
                                              for position in persisted_positions]}
        elif resume is None:
            # A reconnect: hand back the pause we are still waiting on.
            # Free, uncounted: refreshing a page must not eat the quota.
            yield ("result", InterviewResponse(
                status=case.status, pause=pending,
                answered=cases.answered_count(user_id, case_id),
                debug=_debug_of(dict(getattr(state, "values", None) or {}), pending)))
            return
        else:
            # Before the quota, before anything is written: a refused reply spends
            # no interview quota and stores nothing. Not free, though - the request
            # still counts against the per-IP and global rate limiters, which are
            # enforced ahead of this handler.
            try:
                validate_resume(pending, resume)
            except ResumeInvalid as exc:
                raise HTTPException(422, detail=str(exc)) from None
            _spend(user_id, settings)
            _persist_answer(user_id, case_id, pending, resume)
            await _remember_answer(store, user_id, case, pending, resume)
            _apply_stop_answer(user_id, case_id, pending, resume)
            stream_input = Command(resume=resume)

        async for chunk in graph.astream(stream_input, config, stream_mode="updates"):
            for node_name in chunk:
                if not node_name.startswith("__"):
                    yield ("node", node_name)

        state = await graph.aget_state(config)
        pause = _pending_pause(state)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    values = dict(getattr(state, "values", None) or {})

    if values.get("tax_positions"):
        from domain.positions import TaxPosition
        cases.save_positions(
            user_id, case_id,
            [TaxPosition.from_dict(value) for value in values["tax_positions"]],
        )
        if isinstance(resume, dict) and isinstance(resume.get("decisions"), dict):
            fields = cases.get_fields(user_id, case_id)
            cases.apply_position_decisions(
                user_id, case_id, resume["decisions"],
                {key: value.value for key, value in fields.items()},
            )

    if pause is None:
        # Before finalize, not after: the case is still writable here, and keeping
        # the order explicit means the read-only lock never has to be worked around.
        _save_findings(user_id, case_id, values)
        case = cases.finalize(user_id, case_id)
        yield ("result", InterviewResponse(status=case.status, done=True,
                                           answered=cases.answered_count(user_id, case_id),
                                           debug=_debug_of(values, None, done=True)))
        return

    if pause.get("type") in _REVIEW_PAUSES:
        _save_findings(user_id, case_id, values)

    new_status = _GRAPH_STATUS.get(pause.get("type", ""), case.status)
    if new_status != case.status:
        cases.set_status(user_id, case_id, new_status)
    yield ("result", InterviewResponse(status=new_status, pause=pause,
                                       answered=cases.answered_count(user_id, case_id),
                                       debug=_debug_of(values, pause)))


@router.post(
    "/{case_id}/interview",
    response_model=InterviewResponse,
    dependencies=[Depends(enforce_rate_limit)],
)
async def advance_interview(case_id: str, request: InterviewRequest,
                            user_id: str = Depends(current_user),
                            llm=Depends(get_llm_client),
                            reviewer=Depends(get_reviewer_client),
                            retriever=Depends(get_retriever)):
    # Drained to the end rather than returned out of: leaving an async generator
    # unfinished defers its cleanup to the garbage collector, and the lock below
    # would then be released long after the response. The generator yields the
    # result last anyway, so finishing it costs nothing.
    result = None
    try:
        # Two locks, always in this order: the case, then the person. An advance
        # teaches the profile memory as it goes, so a delete of that memory has to
        # wait for it - and a fixed order is what stops the two ever deadlocking.
        async with hold(case_thread_id(user_id, case_id)), \
                   hold(profile_erasure.profile_lock_key(user_id)):
            async for kind, payload in _advance_events(
                    case_id, user_id, request.resume,
                    llm=llm, reviewer=reviewer, retriever=retriever):
                if kind == "result":
                    result = payload
    except CaseBusy as exc:
        raise _known_error(exc)
    if result is None:
        raise HTTPException(500, detail="the interview produced no result")
    return result


@router.post(
    "/{case_id}/interview/stream",
    # SSE over a POST body, because EventSource cannot send an Authorization
    # header. The frontend reads the stream with fetch; on any failure it falls
    # back to the plain endpoint above, which is the same generator anyway.
    dependencies=[Depends(enforce_rate_limit)],
)
async def advance_interview_stream(case_id: str, request: InterviewRequest,
                                   user_id: str = Depends(current_user),
                                   llm=Depends(get_llm_client),
                                   reviewer=Depends(get_reviewer_client),
                                   retriever=Depends(get_retriever)):
    from fastapi.responses import StreamingResponse

    async def events():
        try:
            # The lock lives here rather than inside `_advance_events`, which both
            # endpoints share: a generator's cleanup is not guaranteed to run at the
            # moment its consumer stops reading. This one Starlette does drive to the
            # end and close, so the `finally` in `hold` runs even on a disconnect.
            async with hold(case_thread_id(user_id, case_id)), \
                       hold(profile_erasure.profile_lock_key(user_id)):
                async for kind, payload in _advance_events(
                        case_id, user_id, request.resume,
                        llm=llm, reviewer=reviewer, retriever=retriever):
                    if kind == "node":
                        yield f"data: {json.dumps({'type': 'node', 'node': payload})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'result', **payload.model_dump()})}\n\n"
        except CaseBusy as exc:
            raise_as = _known_error(exc)
            yield f"data: {json.dumps({'type': 'error', 'status': raise_as.status_code, 'detail': raise_as.detail})}\n\n"
        except HTTPException as exc:
            # Inside a stream there is no status code left to send; the error
            # travels as an event and the frontend surfaces it.
            yield f"data: {json.dumps({'type': 'error', 'status': exc.status_code, 'detail': exc.detail})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/{case_id}/anlage-n.pdf")
def download_anlage_n(case_id: str, user_id: str = Depends(current_user)):
    """The case as the official Anlage N, filled in.

    The report has always been able to say "Zeile 58"; this is that sentence carried
    out. The figures are the same ones the dashboard shows and the Reviewer audited —
    `expense_rows` produces them once and everything downstream reads them — so the
    PDF cannot disagree with the screen.

    It is a draft and says so on the page. Nothing here files anything, the blank is
    the published form and not a facsimile, and any figure the form has no single
    unambiguous box for comes back in a header rather than being quietly dropped.
    """
    from fastapi.responses import Response

    from domain.form_fill import entries_for
    from services.anlage_n_pdf import BlankNotAvailable, fill

    try:
        case = cases.get_case(user_id, case_id)
        fields = cases.get_fields(user_id, case_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    pending = cases.values_awaiting_confirmation(user_id, case_id)
    if pending:
        # The same rule as finalize, and for the same reason (ADR 0010): a figure the
        # user has not looked at may not leave the workspace on a tax document.
        raise HTTPException(
            409, detail=f"{len(pending)} value(s) still unconfirmed: {', '.join(pending)}")

    known = {k: v.value for k, v in fields.items()}
    year = for_year(case.tax_year)
    positions = cases.get_positions(user_id, case_id)
    includable = includable_positions(positions, known)
    if not includable:
        raise HTTPException(409, detail="no confirmed tax position is available for Anlage N")
    expenses = project_expenses(includable, fields, year)
    draft_facts = {
        dependency.fact_id: known[dependency.fact_id]
        for position in includable
        for dependency in position.dependent_facts
        if dependency.fact_id in known
    }
    entries, unplaced = entries_for(draft_facts, expenses, year)
    if not entries:
        raise HTTPException(409, detail="this case has no figure that belongs on Anlage N yet")

    # Filled twice only in the sense that the note is decided before the stamp: what
    # goes in the margin depends on how many figures the form could not take, and that
    # is known only after the placement runs.
    final = case.status == "finalized"
    left_out = [f"{u.label}: {u.amount_eur:.2f} EUR — {u.where}" for u in unplaced]

    try:
        form = fill(entries, case.tax_year, note=None if final else DRAFT_NOTE)
        left_out += form.unplaced
        if left_out:
            # Unavoidable rather than advisory. It used to travel in a response header
            # the caller could ignore, which made "the PDF is complete" the easiest
            # assumption to make about a sheet that was not (#30).
            form = fill(entries, case.tax_year,
                        note=INCOMPLETE_NOTE.format(count=len(left_out))
                        if final else DRAFT_NOTE)
    except BlankNotAvailable as exc:
        raise HTTPException(503, detail=str(exc))

    kind = "final" if final and not left_out else "draft"
    return Response(
        content=form.pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="anlage-n-{case.tax_year}-{kind}.pdf"',
            # Kept as well as printed: the frontend lists what was left out beside the
            # download, which the page margin has no room for.
            "X-Unplaced-Count": str(len(left_out)),
            "X-Export-Kind": kind,
        },
    )


@router.post(
    "/{case_id}/interview/back",
    response_model=InterviewResponse,
    dependencies=[Depends(enforce_rate_limit)],
)
async def step_back(case_id: str, user_id: str = Depends(current_user),
                    llm=Depends(get_llm_client),
                    reviewer=Depends(get_reviewer_client)):
    """Undo the last answer and ask its question again.

    The checkpointer has been recording a snapshot per step since the first
    interview; this endpoint is the first thing to read it backwards. Going back
    means replaying the run from the checkpoint at which that question was on
    screen — the graph re-runs the paused node, pauses on the same question, and
    every later checkpoint is simply no longer the head. The answer itself is
    deleted from the case, so the tables and the run agree about what is known.

    No provider call happens: the replayed node is `ask_user`, which does nothing
    but pause. It is rate limited all the same, because it is still a write.
    """
    try:
        case = cases.get_case(user_id, case_id)
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)
    if case.status == "finalized":
        raise HTTPException(409, detail="the case is finalized; reopen it first")

    config = {"configurable": {"thread_id": case_thread_id(user_id, case_id)}}
    try:
        # Held across the replay for the same reason the advance holds it: this
        # rewinds the run and deletes an answer, and a delete arriving mid-replay
        # would leave the two stores disagreeing about what the case knows.
        async with hold(case_thread_id(user_id, case_id)):
            saver = await checkpointer()
            # No retriever: the replayed node is `ask_user`, which only pauses, so
            # nothing here looks for Gap candidates.
            graph = build_graph(llm, reviewer, saver)

            # The head is whatever is on screen now — a question, or the stop card
            # that followed one. Either way "back" means the most recent question
            # before it, which is the answer the user is asking to change.
            target, head_seen = None, False
            async for snapshot in graph.aget_state_history(config):
                payload = _pending_pause(snapshot)
                if payload is None or payload.get("type") != "question":
                    continue
                if not head_seen:
                    head_seen = True
                    continue
                target = snapshot
                break

            if target is None:
                raise HTTPException(
                    409, detail="there is no earlier question to go back to")

            question = BY_ID.get((_pending_pause(target) or {}).get("question_id", ""))
            if question is not None:
                cases.clear_field(user_id, case_id, question.key)

            await graph.ainvoke(None, target.config)
            state = await graph.aget_state(config)
            pause = _pending_pause(state)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _known_error(exc)

    if pause is None:  # pragma: no cover — a replayed question always pauses
        raise HTTPException(500, detail="going back produced no question")
    if case.status != "gathering":
        cases.set_status(user_id, case_id, "gathering")
    values = dict(getattr(state, "values", None) or {})
    return InterviewResponse(status="gathering", pause=pause,
                             answered=cases.answered_count(user_id, case_id),
                             debug=_debug_of(values, pause))


_PAUSE_NODE = {"question": "ask_user", "confirm_stop": "confirm_stop",
               "findings": "resolve_findings", "final_approval": "final_approval"}


def _debug_of(values: dict, pause: Optional[dict], done: bool = False) -> Optional[dict]:
    """What the developer panel shows, or None outside DEBUG.

    Built from the paused graph state only, so it can never disagree with what the
    graph actually did — the panel is a window, not a second bookkeeping.
    """
    from core.config import get_settings
    from domain.estimate import estimate as run_estimate
    from domain.questions import relevant_questions

    if not get_settings().debug:
        return None

    known = values.get("known") or {}
    asked = set(values.get("asked") or [])
    est = run_estimate(known)
    return {
        "node": "finalized" if done else _PAUSE_NODE.get((pause or {}).get("type", ""),
                                                         "decide_next"),
        "rounds": values.get("rounds") or 0,
        "asked": len(asked),
        "candidates_open": len([q for q in relevant_questions(known) if q.id not in asked]),
        "total_eur": est.total_eur,
        "pauschbetrag_eur": est.pauschbetrag,
        "revision_round": values.get("revision_round") or 0,
        "findings": len(values.get("findings") or []),
        "last_decision": values.get("last_decision") or None,
        "stop_declined": bool(values.get("stop_declined")),
        # How many values this run did not have to ask for because an earlier case
        # already answered them (ADR 0011). Zero for a first return, which is the
        # honest reading: the saving only exists on the second one.
        "carried_over": len(values.get("carried_over") or []),
    }


def _spend(user_id: str, settings) -> None:
    try:
        spend_interview_call(
            user_id,
            per_user_daily=settings.interview_calls_per_user_per_day,
            global_monthly=settings.interview_calls_global_per_month,
        )
    except QuotaExceeded as exc:
        raise HTTPException(429, detail=exc.detail,
                            headers={"X-Quota-Retry": exc.retry_hint})


def _pending_pause(state) -> Optional[dict]:
    """The interrupt payload a state — current or historical — is paused on.

    Works on any snapshot, which is what lets `step_back` walk the history with the
    same reader the live path uses.
    """
    for task in getattr(state, "tasks", ()) or ():
        for intr in getattr(task, "interrupts", ()) or ():
            return dict(intr.value)
    return None


def _response(status: str, pause: dict) -> InterviewResponse:
    return InterviewResponse(status=status, pause=pause)


async def _open_profile_store():
    """The profile store, or None if it cannot be had.

    None is a supported state, not an error path: the store's tables may not exist
    yet, the database may be busy, `schema/0003_remembered_values.sql` may not have
    been applied. Every one of those means this user gets no carried-over values on
    this run — never that the interview fails.
    """
    try:
        return await profile_memory.store()
    except Exception:  # noqa: BLE001
        logger.warning("profile_memory_unavailable", exc_info=True)
        return None


async def _seed_from_memory(store, user_id: str, case, known: dict,
                            fields: dict) -> list[dict]:
    """Fill what an earlier case already answered, and say what still needs looking at.

    Two things happen here and the second is not the first repeated. Seeding writes
    remembered values into the tables and into `known`, which is what makes a second
    return shorter than a first. What comes back is every remembered value in the
    case that is still unconfirmed — the ones just written *and* any left over from a
    run whose checkpoint was lost, because those have to reach the stop card again or
    `finalize` will later refuse over values the user was never shown.
    """
    remembered = await profile_memory.recall(store, user_id, exclude_year=case.tax_year)
    seeded: dict[str, tuple[Any, str]] = {}
    for key, held in sorted(remembered.items()):
        if known.get(key) is not None or key not in BY_KEY:
            continue
        year = held.get("tax_year")
        source = (f"carried over from your {year} case" if year
                  else "carried over from an earlier case")
        try:
            cases.set_field(user_id, case.id, key,
                            FieldValue(held["value"], Provenance.remembered, source=source))
        except Exception:  # noqa: BLE001 — an unmigrated database, most likely
            logger.warning("profile_memory_seed_failed", key=key, exc_info=True)
            continue
        known[key] = held["value"]
        seeded[key] = (held["value"], source)

    awaiting = dict(seeded)
    for key, field in fields.items():
        if (field.provenance is Provenance.remembered and not field.confirmed
                and key not in awaiting):
            awaiting[key] = (field.value, field.source)

    carried = []
    for key, (value, source) in sorted(awaiting.items()):
        question = BY_KEY.get(key)
        if question is None:
            continue
        carried.append({
            "key": key,
            "value": value,
            "source": source,
            "text": question.text,
            "answer_type": question.spec().answer_type.value,
        })
    return carried


async def _remember_answer(store, user_id: str, case, pause: dict, resume: Any) -> None:
    """Teach the profile whatever this answer says about the person, not the year."""
    if pause.get("type") != "question":
        return
    question = BY_ID.get(pause.get("question_id", ""))
    value = resume.get("value") if isinstance(resume, dict) else resume
    if question is None or value is None:
        return
    await profile_memory.remember(store, user_id, question.key, value, case.tax_year)


def _apply_stop_answer(user_id: str, case_id: str, pause: dict, resume: Any) -> None:
    """Land the stop card's verdict on the carried-over values in the tables.

    Mirrors `confirm_stop` exactly, and has to: the node decides what `known` holds,
    this decides what the case holds, and a disagreement between the two is a figure
    in the report that the graph does not know about.
    """
    if pause.get("type") != "confirm_stop":
        return
    confirmed, rejected = read_stop_answer(resume)
    for key in rejected:
        cases.clear_field(user_id, case_id, key)
    if not confirmed or rejected:
        return
    shown = {c["key"] for c in pause.get("carried_over") or []}
    cases.confirm_values(user_id, case_id, sorted(shown))
    # Anything remembered and unconfirmed that was *not* on the card is a value this
    # year turned out not to need. It leaves the case rather than blocking the report.
    # Assumptions are deliberately untouched here: they have their own confirmation
    # path and deleting one would silently drop a figure the case does need.
    for key, field in cases.get_fields(user_id, case_id).items():
        if (field.provenance is Provenance.remembered and not field.confirmed
                and key not in shown):
            cases.clear_field(user_id, case_id, key)


def _persist_answer(user_id: str, case_id: str, pause: dict, resume: Any) -> None:
    """An answered question lands in the tables the moment it is given.

    Only questions persist here: confirmations and finding resolutions change the
    run, not the case's values. None is "I don't know" — asked, but nothing lands.
    """
    if pause.get("type") != "question":
        return
    value = resume.get("value") if isinstance(resume, dict) else resume
    if value is None:
        return
    question = BY_ID.get(pause.get("question_id", ""))
    if question is None:
        return
    # The item the question was asked about, so a second purchase lands beside the
    # first rather than on top of it (#35).
    cases.set_field(user_id, case_id, question.key,
                    FieldValue(value, Provenance.answer, source=question.id),
                    item_index=int(pause.get("item_index") or 0))
