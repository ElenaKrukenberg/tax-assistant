"""Forgetting a person: the other half of deleting a case, and deliberately not it.

Profile memory is what makes a second tax return shorter than the first - the commute
distance, whether they drive it, whether the employer provides a desk. It belongs to
the *person*, outlives every case, and is the one thing `services/case_erasure.py`
leaves standing on purpose (ADR 0011). Which means that without this module the
product remembered things about someone that they had no way to make it forget.

So the two are separate operations, and that separation is the point rather than an
accident of implementation: someone finishing a year and deleting the case usually
wants next year to still be short, and someone who wants to be forgotten wants that
whether or not any case survives.

Where the memory lives: the `store` table that LangGraph's `AsyncPostgresStore`
creates in the same Supabase database, under `prefix = '<user_id>.profile'`. Not a
table of ours, and not covered by row level security - restricting it is the other
half of the same issue this closes.

Everything under the namespace goes, not only the keys the current release carries.
A value written by an older build, under a key `domain/fields.py` no longer knows
about, is still something the system remembers about a person: `profile_memory.recall`
filters those out of an interview, which is not the same as them being gone.
"""

from __future__ import annotations

import structlog

from agents import profile_memory
from core.case_lock import hold

logger = structlog.get_logger(__name__)

# The namespace is one person's profile and holds a handful of keys, so a page this
# size takes it in one round trip while the loop below still copes if it ever grows.
_PAGE = 100


def profile_lock_key(user_id: str) -> str:
    """The lock this shares with an interview advance.

    An interview teaches the memory as it goes (`_remember_answer`), so a delete
    landing mid-advance could be followed by the same answer being written straight
    back - the resurrection that `services/case_erasure.py` exists to prevent for a
    case, in the one store that module leaves alone. The advance takes this after its
    own case lock; the order is fixed in both places so the two can never deadlock.
    """
    return f"profile:{user_id}"


async def forget_profile(user_id: str) -> int:
    """Delete everything remembered about this person. Returns how many keys went.

    Zero is a normal answer, not a failure: somebody who has never finished an
    interview has nothing remembered about them, and "there was nothing to forget" is
    the same outcome they asked for.
    """
    async with hold(profile_lock_key(user_id)):
        store = await profile_memory.store()
        namespace = profile_memory.namespace(user_id)

        removed = 0
        while True:
            items = await store.asearch(namespace, limit=_PAGE)
            if not items:
                break
            for item in items:
                await store.adelete(namespace, item.key)
                removed += 1
            if len(items) < _PAGE:
                break

        logger.info("profile_memory_forgotten", keys=removed)
        return removed
