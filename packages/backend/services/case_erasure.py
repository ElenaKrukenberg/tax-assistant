"""Deleting a Tax Case for real: the tables and the paused graph run, together.

A person's data does not live in one place, and until this module existed no single
operation cleared even the two places that hold the same answers. What the product
stores, and what each of these functions does about it:

| Where                                              | erase_case | erase_all_cases |
| -------------------------------------------------- | ---------- | --------------- |
| `tax_cases` + `field_values`, `documents`,          |            |                 |
| `expenses`, `answers`, `findings`, `tax_positions` | deleted    | deleted         |
| `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` | deleted | deleted         |
| the same three for each document's intake run           | deleted | deleted         |
| `store` - the profile memory                        | kept       | kept            |
| chat history in the browser's localStorage          | untouched  | untouched       |
| LangSmith traces                                    | untouched  | untouched       |

The profile memory is kept **on purpose**, not by omission: it belongs to the person
rather than to the case and is designed to outlive it (ADR 0011), so deleting a case
and forgetting a person have to be separate choices. The second one now exists beside
this: `services/profile_erasure.py`. The browser's chat history is issue #18; it holds no case data at
all. LangSmith traces carry no case id yet, so nothing there can be selected per case;
issue #73, and `docs/TRACING_POLICY.md` for where they are and how long they live.

**The checkpoint goes first.** These are two stores with two connection pools and no
shared transaction - `db/connection.py` keeps the repository's synchronous pool apart
from the checkpointer's async, autocommit one - so a failure between them is possible
and the order decides what it leaves behind. Checkpoint first means a failure there
deletes nothing at all, and a failure after it leaves the case whole in the tables,
which are the source of truth (ADR 0005): the interview simply rebuilds a run from
them. The other order would delete the visible case and strand the answers in graph
state, which is the exact bug this module was written to end.

Retrying is always safe. Both steps are deletes, and the second attempt finds the
checkpoint already gone.
"""

from __future__ import annotations

import structlog
from anyio import to_thread

from agents.graph import case_thread_id, checkpointer
from core.case_lock import hold
from db import cases
from services.documents import retention

logger = structlog.get_logger(__name__)


async def erase_case(user_id: str, case_id: str) -> None:
    """Delete one case from the tables and the checkpoint, or raise.

    Raises `cases.CaseNotFound` if the case is not this user's, which is also what a
    stranger's id looks like, and `core.case_lock.CaseBusy` if an interview on the
    same case is still running. Anything else means one of the two stores refused and
    the caller must not report success.
    """
    async with hold(case_thread_id(user_id, case_id)):
        # Ownership first, before anything is touched: a stranger must not be able to
        # clear a checkpoint by guessing an id. The thread id is built from the token's
        # user anyway, so the worst they could reach is their own, but the check also
        # turns a missing case into a 404 before either store is written to.
        await to_thread.run_sync(cases.get_case, user_id, case_id)
        await _erase_locked(user_id, case_id)


async def erase_all_cases(user_id: str) -> list[str]:
    """Delete every case this user has. Returns the ids that could not be deleted.

    Goes on after a failure rather than stopping at it. One case whose checkpoint the
    database will not give up must not stand between the user and deleting the rest -
    "delete all my data" that gives up on the first obstacle is the dishonest version.
    The caller reports how many are left; a retry finishes them.
    """
    listed = await to_thread.run_sync(cases.list_cases, user_id)
    failed: list[str] = []
    for case in listed:
        try:
            async with hold(case_thread_id(user_id, case.id)):
                await _erase_locked(user_id, case.id)
        except cases.CaseNotFound:
            continue  # deleted by something else in between, which is the wanted end
        except Exception:  # noqa: BLE001 - one stubborn case must not stop the rest
            logger.warning("case_not_erased", case_id=case.id, exc_info=True)
            failed.append(case.id)
    return failed


async def _erase_locked(user_id: str, case_id: str) -> None:
    """The two stores, in the order the module docstring argues for. Lock held."""
    saver = await checkpointer()
    await saver.adelete_thread(case_thread_id(user_id, case_id))
    # A case has more than one run: the interview's, under the id above, and one per
    # uploaded document. Deleting the row without them would leave a document's two
    # extraction passes behind in `checkpoints` after the case they belonged to was
    # gone - values the user never confirmed, outliving the thing they were read for.
    await retention.forget_every_run(user_id, case_id)
    await to_thread.run_sync(cases.delete_case, user_id, case_id)
