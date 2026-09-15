"""The person, as distinct from their cases.

One route so far: forget what is remembered about me. It lives outside
`/api/v1/cases` on purpose, because that is the distinction it exists to make -
profile memory belongs to the person and outlives every case (ADR 0011), so an
operation on it is not an operation on a case and should not read like one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.auth import current_user
from core.case_lock import CaseBusy
from db.connection import DatabaseNotConfigured
from services import profile_erasure

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.delete("/memory", status_code=204)
async def forget_me(user_id: str = Depends(current_user)):
    """Delete everything the system remembers about this person between years.

    Deliberately not part of deleting a case, and deliberately not implied by it.
    Someone who finishes a year and deletes the case usually still wants next year to
    be short; someone who wants to be forgotten wants that whether or not a case
    survives. `services/case_erasure.py` leaves this store alone for the same reason.

    204 with nothing remembered is the right answer, not an error: they asked for
    there to be nothing, and there is nothing.

    No `require_schema` here, unlike the case router. This store is LangGraph's own
    table, created by the library rather than by a file in `db/schema/`, so the
    schema ledger has nothing to say about it - and refusing to forget somebody
    because an unrelated migration is outstanding would be the wrong way round.
    """
    try:
        await profile_erasure.forget_profile(user_id)
    except CaseBusy:
        raise HTTPException(409, detail="an interview is running; try again in a moment")
    except DatabaseNotConfigured:
        raise HTTPException(503, detail="the database is not configured")
