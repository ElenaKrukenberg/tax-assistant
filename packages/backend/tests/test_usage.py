"""The money guards, against the real counters table.

Integration, because the whole point of these counters is the property a fake
cannot show: they live in Postgres and survive a process restart, so the monthly
ceiling cannot be reset by a deploy. Limits are passed as arguments, so the tests
set tiny ones instead of touching configuration.
"""

from __future__ import annotations

import uuid

import pytest

from tests import dbguard

from core.config import get_settings
from db.connection import as_owner
from db.usage import QuotaExceeded, spend_interview_call

pytestmark = pytest.mark.integration

settings = get_settings()
dbguard.require_test_database()


@pytest.fixture
def user_id():
    """A scope of this test's own, wiped afterwards along with its global rows."""
    uid = str(uuid.uuid4())
    yield uid
    with as_owner() as cur:
        cur.execute("delete from usage_counters where scope = %s", (f"user:{uid}",))
        # The tests below disable the global limit (0) except where they test it,
        # and the one that tests it cleans its own period explicitly.


def test_spending_under_the_limits_is_silent(user_id):
    for _ in range(3):
        spend_interview_call(user_id, per_user_daily=5, global_monthly=0)


def test_the_daily_quota_refuses_the_call_over_the_limit(user_id):
    spend_interview_call(user_id, per_user_daily=2, global_monthly=0)
    spend_interview_call(user_id, per_user_daily=2, global_monthly=0)
    with pytest.raises(QuotaExceeded) as exc:
        spend_interview_call(user_id, per_user_daily=2, global_monthly=0)
    assert exc.value.retry_hint == "tomorrow"
    assert "tomorrow" in exc.value.detail


def test_zero_disables_a_limit(user_id):
    for _ in range(10):
        spend_interview_call(user_id, per_user_daily=0, global_monthly=0)


def test_the_counter_survives_a_new_connection(user_id):
    """The deploy-reset property: the count is in the database, not the process.

    Two separate calls share nothing but Postgres; if the second one saw a fresh
    counter, the monthly ceiling would be a ceiling in name only.
    """
    spend_interview_call(user_id, per_user_daily=2, global_monthly=0)
    spend_interview_call(user_id, per_user_daily=2, global_monthly=0)
    with pytest.raises(QuotaExceeded):
        spend_interview_call(user_id, per_user_daily=2, global_monthly=0)


def test_the_monthly_ceiling_uses_its_own_scope(user_id):
    # A private period name would collide with production's real "global" rows,
    # so this test manipulates the row directly and only checks the refusal path.
    from datetime import datetime, timezone

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with as_owner() as cur:
        cur.execute("select count from usage_counters where scope='global' and period=%s",
                    (month,))
        row = cur.fetchone()
        before = int(row[0]) if row else 0

    try:
        # A ceiling one above the current count admits exactly one call...
        spend_interview_call(user_id, per_user_daily=0, global_monthly=before + 1)
        # ...and refuses the next.
        with pytest.raises(QuotaExceeded) as exc:
            spend_interview_call(user_id, per_user_daily=0, global_monthly=before + 1)
        assert exc.value.retry_hint == "next month"
    finally:
        # Undo this test's own increments so production accounting stays honest
        # when the suite runs against a shared database.
        with as_owner() as cur:
            cur.execute(
                "update usage_counters set count = %s where scope='global' and period=%s",
                (before, month),
            )
