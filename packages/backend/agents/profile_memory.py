"""Cross-case memory: the few facts about a person that the tax year does not change.

A second tax return should be shorter than the first. Almost nothing in a case
survives the year — days worked, amounts, purchases are all new — but a handful of
facts do: how far the person lives from work, whether they drive, whether the
employer gives them a desk. `domain/fields.py` marks those with `carries_over`, and
this module is the only place that moves them between cases.

Where they live is a LangGraph `Store`, not a table of ours, and the distinction is
deliberate. ADR 0005 says the case lives in tables and the checkpointer holds only
the paused run; a profile is neither — it belongs to the *person*, outlives every
case, and is keyed by user id exactly as the checkpointer's threads already are.
What lands in a case is a copy, written into `field_values` with provenance
`remembered`, so the case stays the single source of truth about itself and the
report can still say where every figure came from.

Only the interview teaches this memory. A value that reached the case from an
uploaded document or from the chat (ADR 0007) is not carried into the next year —
not because it would be wrong to, but because neither path has been measured, and a
figure in a tax return should not start travelling between years on the strength of
an untested guess. Widening it is a deliberate change, not an oversight.

Nothing here may break an interview. A store that is unreachable, a database that
has not had `schema/0003_remembered_values.sql` applied yet, a value whose shape
changed between releases — each degrades to "this user has no profile memory",
logged once, never raised. The feature is a shortcut; a shortcut that can fail the
thing it shortens is not worth having.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from domain.fields import CARRY_OVER_FIELDS

logger = structlog.get_logger(__name__)

# Second element of the namespace tuple. The first is the user id, which is what
# keeps one person's profile out of another's — the same guarantee, and the same
# mechanism, as the checkpointer's `f"{user_id}:{case_id}"` thread ids.
PROFILE = "profile"


def namespace(user_id: str) -> tuple[str, str]:
    return (str(user_id), PROFILE)


async def remember(store: Any, user_id: str, key: str, value: Any, tax_year: int) -> None:
    """Record an answer to a carrying field, if it is newer than what we hold.

    Newer by tax year, not by clock: somebody filing 2024 in 2026, after they have
    already done 2025, must not overwrite the 2025 commute with the older one.
    """
    if store is None or key not in CARRY_OVER_FIELDS or value is None:
        return
    try:
        held = await store.aget(namespace(user_id), key)
        if held is not None and int((held.value or {}).get("tax_year", 0)) > int(tax_year):
            return
        await store.aput(namespace(user_id), key,
                         {"value": value, "tax_year": int(tax_year)})
    except Exception:  # noqa: BLE001 — memory is a shortcut, never a dependency
        logger.warning("profile_memory_write_failed", key=key, exc_info=True)


async def recall(store: Any, user_id: str, exclude_year: Optional[int] = None) -> dict[str, dict]:
    """What we know about this person, as {key: {"value", "tax_year"}}.

    `exclude_year` drops anything learned in the year being worked on, so re-entering
    a case never offers it back its own answers as something to confirm.
    """
    if store is None:
        return {}
    try:
        # Room above the current set on purpose: a key from an older release still
        # sits in the store and would otherwise fill the page and hide a live one.
        items = await store.asearch(namespace(user_id),
                                    limit=max(2 * len(CARRY_OVER_FIELDS), 10))
    except Exception:  # noqa: BLE001
        logger.warning("profile_memory_read_failed", exc_info=True)
        return {}

    out: dict[str, dict] = {}
    for item in items:
        key = getattr(item, "key", None)
        payload = getattr(item, "value", None)
        if key not in CARRY_OVER_FIELDS or not isinstance(payload, dict):
            continue  # a key we no longer carry, or a shape from an older release
        if "value" not in payload:
            continue
        year = payload.get("tax_year")
        if exclude_year is not None and year == exclude_year:
            continue
        out[key] = {"value": payload["value"], "tax_year": year}
    return out


_STORE = None
_STORE_POOL = None


async def store():
    """The process-wide profile store, on the shared async pool.

    Same reasoning, and the same shape, as `agents.graph.checkpointer`: one object for
    the life of the process instead of a fresh Postgres connection per request, which
    was costing 0.46s of every interview advance.
    """
    global _STORE, _STORE_POOL
    from langgraph.store.postgres import AsyncPostgresStore

    from db.connection import open_async_pool

    pool = await open_async_pool()
    # Rebuilt on a new pool, for the same reason as the checkpointer: a cached store
    # over a closed pool fails on the next request and looks like a database outage.
    if _STORE is None or _STORE_POOL is not pool:
        _STORE = AsyncPostgresStore(pool)
        _STORE_POOL = pool
    await ensure_store_tables(_STORE)
    return _STORE


def postgres_store():
    """A store on a connection of its own, opened and closed by the caller.

    Not what serves requests any more — `store()` above does, over the shared pool.
    Kept for scripts and tests that want no dependency on the app's lifespan.

    Async, session-mode pooler, `.setup()` once per database — all three for the
    same reasons as `agents.graph.postgres_checkpointer`, which this deliberately
    mirrors rather than inventing a second convention. Use as an async context
    manager.
    """
    from langgraph.store.postgres import AsyncPostgresStore

    from core.config import get_settings
    from db.connection import DatabaseNotConfigured

    dsn = get_settings().database_url
    if not dsn:
        raise DatabaseNotConfigured("profile memory needs DATABASE_URL")
    return AsyncPostgresStore.from_conn_string(dsn)


_STORE_TABLES_READY = False


async def ensure_store_tables(store) -> None:
    """Create the store's own tables, once per process — as the checkpointer does."""
    global _STORE_TABLES_READY
    if not _STORE_TABLES_READY:
        await store.setup()
        _STORE_TABLES_READY = True
