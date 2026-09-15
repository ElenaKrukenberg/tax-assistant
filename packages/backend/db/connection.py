"""Connections to the Tax Case database, and the contract every query runs under.

The contract is one thing: a query about a case runs inside a transaction that has
dropped to the `authenticated` role and installed the user's claims. Without it the
connection is the table owner, `auth.uid()` is null, and every row level security
policy in `schema/0001_tax_case.sql` is bypassed — silently, which is the dangerous
part. `as_user()` is therefore the only way this module hands out a cursor.

The repository still filters by user_id in its own SQL. Two locks (db/README.md): a
forgotten WHERE should not be all that stands between two people's tax data, and
with RLS in force a forgotten filter surfaces as an empty result in a test rather
than as somebody else's salary on a screen.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from core.config import get_settings


class DatabaseNotConfigured(RuntimeError):
    """No DATABASE_URL, and since #32 that closes both modes rather than one.

    It used to be only the Tax Cases: the knowledge base was a file the deploy built,
    so the chat answered without a database. Now the chunks live in Postgres, which is
    what took the rebuild out of every deploy - and the cost of that is this sentence
    no longer having an exception in it.
    """


_pool: Optional[ConnectionPool] = None
_async_pool: Optional[AsyncConnectionPool] = None


def _dsn() -> str:
    dsn = get_settings().database_url
    if not dsn:
        raise DatabaseNotConfigured(
            "DATABASE_URL is empty — see packages/backend/db/README.md. It has to be "
            "the Supabase session pooler string (port 5432), not the direct host."
        )
    return dsn


def pool() -> ConnectionPool:
    """The process-wide pool, opened on first use.

    Small on purpose: the free Render instance is one small container, and Supabase's
    pooler in session mode holds a server connection for as long as we hold a client
    one. Four is plenty for an interview that spends most of its time waiting on a
    model.
    """
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            _dsn(), min_size=1, max_size=4,
            timeout=settings.db_pool_timeout_seconds,
            # Stated rather than inherited, because the default is five minutes of
            # background retrying and that is how a wrong password turns into the
            # burst of failed authentications that trips Supabase's circuit breaker.
            reconnect_timeout=settings.db_reconnect_timeout_seconds,
            open=True, kwargs={"autocommit": False},
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def async_pool() -> AsyncConnectionPool:
    """The pool the LangGraph checkpointer and the profile store run on.

    A second pool, and async, because those two are the only async callers in the
    process — everything of ours is synchronous and goes through `pool()` above.

    It exists to stop the graph opening a fresh connection per request. Measured on a
    laptop against the Supabase pooler, an interview advance spent 0.38s opening one
    for the checkpointer and 0.46s more for the store, against 2.9s of the model
    actually thinking: a fifth of the wait, for nothing but handshakes.

    The keyword arguments are the checkpointer's requirements, not preferences.
    `from_conn_string` sets exactly these three when it opens its own connection, and
    a pooled connection without them fails in ways that look like data bugs rather
    than configuration: no autocommit and the checkpoint writes sit in an open
    transaction, no dict_row and the library reads its columns by name off a tuple.
    Prepared statements are off because Supabase's pooler forbids them (db/README.md).

    Smaller than the sync pool on purpose: the two of them share whatever the pooler
    allows this project, and the graph holds a connection for milliseconds either side
    of a call that takes seconds.
    """
    global _async_pool
    if _async_pool is None:
        settings = get_settings()
        _async_pool = AsyncConnectionPool(
            _dsn(), min_size=1, max_size=3,
            timeout=settings.db_pool_timeout_seconds,
            reconnect_timeout=settings.db_reconnect_timeout_seconds,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": None,
                    "row_factory": dict_row},
        )
    return _async_pool


async def open_async_pool() -> AsyncConnectionPool:
    """Open the async pool if it is not open yet. Idempotent."""
    p = async_pool()
    await p.open()
    return p


async def close_async_pool() -> None:
    global _async_pool
    if _async_pool is not None:
        await _async_pool.close()
        _async_pool = None


@contextmanager
def as_user(user_id: str) -> Iterator[psycopg.Cursor]:
    """A cursor inside a transaction that acts as `user_id`, with RLS in force.

    Commits when the block ends, rolls back if it raises. The role and the claims are
    set with `set local` / `set_config(..., true)`, so both are scoped to this
    transaction and cannot leak to whoever borrows the connection next — which is not
    hypothetical, the connection goes straight back into the pool.
    """
    if not user_id:
        raise ValueError("as_user needs a user id; there is no anonymous Tax Case")

    with pool().connection() as conn:
        with conn.cursor() as cur:
            # A literal, because SET takes no bind parameters; the value is a fixed
            # role name and never user input.
            cur.execute("set local role authenticated")
            # set_config is the parameterised form, and `true` means "this transaction
            # only". The claims have to be JSON: auth.uid() reads `sub` out of them.
            cur.execute(
                "select set_config('request.jwt.claims', %s, true)",
                (json.dumps({"sub": user_id, "role": "authenticated"}),),
            )
            yield cur


@contextmanager
def as_owner() -> Iterator[psycopg.Cursor]:
    """A cursor with row level security bypassed. For migrations and diagnostics only.

    Named so that it is obvious in a diff. Anything that serves a request uses
    `as_user`; if this appears in a route, that is the bug.
    """
    with pool().connection() as conn:
        with conn.cursor() as cur:
            yield cur


def health() -> dict:
    """Whether the database is reachable, for /health to report without leaking it."""
    try:
        with as_owner() as cur:
            cur.execute("select 1")
            cur.fetchone()
        return {"database": "ok"}
    except DatabaseNotConfigured:
        return {"database": "not_configured"}
    except Exception as exc:  # noqa: BLE001 — health never raises
        return {"database": "error", "detail": type(exc).__name__}
