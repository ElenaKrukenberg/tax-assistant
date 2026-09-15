"""One lock per Tax Case, so two operations on the same case cannot interleave.

The race this exists for is real and was reachable in production. An interview
advance checks that the case exists, then spends seconds inside a model, then
writes its checkpoint. A delete arriving in that window found nothing to stop it:
it cleared the checkpoint and the tables, returned 204, and the advance that was
still running wrote a fresh checkpoint afterwards. The user's answers came back
from the dead, under a case that the interface had already said was gone.

So every operation that reads-then-writes one case takes this lock first: the two
interview endpoints, the step back, and the erasure in `services/case_erasure.py`.

**This is process-local, and that is only enough because Render runs one Uvicorn
worker.** `render.yaml` starts `uvicorn main:app` with no `--workers`, so there is
one event loop and one dictionary. A second worker or a second instance puts the
two halves of the race in different processes and this stops covering it; that
needs advisory locks in Postgres, or a tombstone the interview re-reads before it
writes. Do not add workers without doing one of the two.

The dictionary holds weak references on purpose. A caller takes the lock object
*before* it awaits, so the local variable is a strong reference for as long as it
holds or waits on the lock, and the entry cannot be evicted from under a waiter.
When the last of them leaves, the entry collects itself. That is why there is no
reference count here: the language already keeps one.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator
from weakref import WeakValueDictionary

# How long an operation waits for a case that is busy. An interview advance holds
# the lock across a provider call, so this has to outlast a slow one; a delete
# that waited forever would instead hang until the client gave up, and the user
# would never learn why.
DEFAULT_TIMEOUT_SECONDS = 30.0


class CaseBusy(RuntimeError):
    """Another operation is working on this case and did not finish in time."""


_locks: "WeakValueDictionary[str, asyncio.Lock]" = WeakValueDictionary()


def lock_for(key: str) -> asyncio.Lock:
    """The lock for one key, created on first use.

    There is no `await` between the lookup and the insert, so on a single event
    loop two callers cannot both find it missing and build two different locks.
    """
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


@asynccontextmanager
async def hold(key: str,
               timeout: float = DEFAULT_TIMEOUT_SECONDS) -> AsyncIterator[None]:
    """Hold the case's lock for the block, or raise CaseBusy.

    Use this in a plain coroutine, never inside an async generator that a caller
    might abandon: `advance_interview` used to return from inside its `async for`,
    which leaves the generator unclosed until the garbage collector reaches it -
    and a lock released by the collector is a lock held past the response.
    """
    lock = lock_for(key)  # strong reference, held for the whole block
    try:
        await asyncio.wait_for(lock.acquire(), timeout)
    except asyncio.TimeoutError:
        raise CaseBusy(key) from None
    try:
        yield
    finally:
        lock.release()
