"""The gate every integration module goes through, so none of them can reach production.

There are two Supabase projects and one `database_url`. Before this, an integration
module ran as soon as `DATABASE_URL` and `TEST_USER_ID` were both set, and nothing
asked which project the string named - so a DSN left pointed at production after an
afternoon's debugging turned the next `pytest -m integration` into writes against real
filers' data. The suite creates and deletes Tax Cases, clears checkpoints, writes and
wipes profile memory, and `test_migrate.py` borrows a row out of the `schema_versions`
ledger and puts it back. All of it would simply have run.

So the database is asked whether it is a test database, and that is the whole check.
A second variable holding a second copy of the DSN was the other candidate and it was
dropped on purpose: it would only prove which *string* the tests used, which is not
the question - a DSN copied from the wrong project satisfies it perfectly - and two
strings to keep in step after a password change is the very mistake that started this.

`db/test_database_marker.sql` is applied by hand to the development project and to
nothing else, so the deployed project answers no because the row was never put there.

Skipping, not failing, when the answer is no: a fresh checkout with no `.env` should
find the integration suite absent, which is what it already did. What must never
happen is the suite running somewhere nobody chose.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from core.config import get_settings

_NO_DSN = "needs DATABASE_URL and TEST_USER_ID - see packages/backend/db/README.md."

_NO_MARKER = (
    "the database DATABASE_URL points at does not identify itself as a test database. "
    "Apply packages/backend/db/test_database_marker.sql to the *development* project "
    "and nothing else, then run this again. If you expected this to pass, check which "
    "project DATABASE_URL names before applying anything."
)

_UNREACHABLE = (
    "the database DATABASE_URL points at could not be reached: {detail}. The suite is "
    "skipped rather than retried - a run that keeps reconnecting is how failed "
    "authentications pile up until Supabase's pooler blocks new connections for "
    "everyone. Fix the connection, then run this again."
)

# Told apart on purpose. "Not a test database" and "no database answered" are
# different problems with different fixes, and reporting the first for the second
# sends you off applying SQL to a host that is not listening.
_MISSING = "missing"


@lru_cache(maxsize=1)
def _marker() -> str:
    """The label the connected database calls itself, `_MISSING`, or a failure string.

    One connection for the whole run: six integration modules ask at import time and
    the answer cannot change inside a run. `as_owner` because this is the backend's
    own bookkeeping and carries nothing about anybody - and it inherits the short
    pool timeouts `conftest.py` sets, so an unreachable host costs seconds, not the
    library's default five minutes of retrying.
    """
    from db.connection import as_owner

    try:
        with as_owner() as cur:
            cur.execute("select label from test_database_marker limit 1")
            row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 - the message is the diagnosis
        name = type(exc).__name__
        if "UndefinedTable" in name or "does not exist" in str(exc):
            return _MISSING  # reachable, but not a database we were told to test
        return f"unreachable: {name}"
    return _MISSING if row is None else str(row[0])


def require_test_database() -> str:
    """Skip the calling module unless it is configured to reach a database at all.

    Configuration only - this runs at import, and an import must not open a
    connection. A plain `pytest` run imports every test module including the
    integration ones, so a probe here would cost one connection attempt on every
    offline run, which is exactly the kind of pointless authentication attempt that
    trips the pooler's circuit breaker when the password is stale.

    Whether the database is the *right* one is checked by `check_marker` below, from
    an autouse fixture that only fires for a test actually marked integration.

    Call at module level:

        pytestmark = pytest.mark.integration
        USER = dbguard.require_test_database()
    """
    settings = get_settings()
    if not settings.database_url or not settings.test_user_id:
        pytest.skip(_NO_DSN, allow_module_level=True)
    return settings.test_user_id


def check_marker() -> None:
    """Skip this test unless the database it would touch says it is a test database.

    One connection for the whole run, and only when an integration test is about to
    run. Skips rather than fails: a checkout that has never applied the marker should
    find the suite absent, not broken.
    """
    label = _marker()
    if label == _MISSING:
        pytest.skip(_NO_MARKER)
    if label.startswith("unreachable: "):
        pytest.skip(_UNREACHABLE.format(detail=label))
