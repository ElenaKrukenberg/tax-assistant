"""When an upload nobody decided about stops being kept.

"Temporary until the user decides" has to have an end, or it means "for as long as
the case lives" - and a Tax Case lives for years. Until the user confirms or
discards, the two extraction passes and their disagreements sit in the intake run's
checkpoint: unconfirmed readings of somebody's payslip, which is exactly the kind of
data ADR 0004 exists to keep short-lived.

So two limits rather than one. An upload is settled by the user, or the case is
deleted, or - whichever comes first - it expires: `DOCUMENT_CONFIRMATION_TTL_HOURS`
after it was last touched the document becomes `failed` with the code `expired` and
its intake thread is deleted. Re-uploading is one click; keeping a stranger's
extracted salary indefinitely is not recoverable at all.

There is no scheduler on the free tier this is deployed to, so the sweep runs where
it is cheap and certain to happen: when the case's documents are listed, which is
what opening the screen does.
"""

from __future__ import annotations

import structlog

from db import cases
from workflows.document_intake import intake_thread_id

logger = structlog.get_logger(__name__)


async def expire_abandoned(user_id: str, case_id: str, ttl_hours: int) -> list[str]:
    """Expire every upload that has waited too long, and forget what it read."""
    expired = cases.expire_stale_documents(user_id, case_id, ttl_hours)
    for document_id in expired:
        await forget_run(user_id, case_id, document_id)
    if expired:
        logger.info("documents_expired", case_id=case_id, count=len(expired))
    return expired


async def forget_run(user_id: str, case_id: str, document_id: str) -> None:
    """Delete one document's intake thread - the only place its readings lived.

    Failure is logged and swallowed on purpose. By the time this runs the values are
    in the tables and the document is marked, so raising would report a failure for
    work that succeeded; what is left behind is a checkpoint row, which case deletion
    and the next sweep both clear.
    """
    from agents.graph import checkpointer

    try:
        saver = await checkpointer()
        await saver.adelete_thread(intake_thread_id(user_id, case_id, document_id))
    except Exception:  # noqa: BLE001
        logger.warning("intake_thread_not_deleted", case_id=case_id,
                       document_id=document_id, exc_info=True)


async def forget_every_run(user_id: str, case_id: str) -> None:
    """Delete the intake threads of every document in the case.

    Called when the case itself goes (`services/case_erasure.py`). Without it a
    deleted case would leave its uploads' readings behind in `checkpoints`: the
    interview's thread is one id the eraser knows, and each document's is another it
    has to be told about.
    """
    for document in cases.list_documents(user_id, case_id):
        await forget_run(user_id, case_id, document.id)
