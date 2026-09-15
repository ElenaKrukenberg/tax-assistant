"""The money guards: who may spend, and how much is left this month.

Three limits from Q23, each against a different failure. Cases per user stops
somebody hoarding workspaces; the per-user daily quota stops one enthusiast
spending the key all day; the global monthly ceiling is the wallet's actual
limit — when it is reached the workspace goes read-only and says so, and the
chat (with its own limits) is untouched.

Counters live in Postgres (schema/0002_usage.sql), not in process memory: the
per-IP limiter may reset on deploy, the monthly ceiling must not. Increment and
check are one atomic UPSERT — two racing requests both count, and the loser of
the race is refused on the next call rather than sneaking under the ceiling.
"""

from __future__ import annotations

from datetime import datetime, timezone

from db.connection import as_owner


class QuotaExceeded(Exception):
    """A limit was hit. Carries what to tell the user, never internals."""

    def __init__(self, detail: str, retry_hint: str):
        super().__init__(detail)
        self.detail = detail
        self.retry_hint = retry_hint  # "tomorrow" | "next month"


def _bump(cur, scope: str, period: str) -> int:
    cur.execute(
        """
        insert into usage_counters (scope, period, count) values (%s, %s, 1)
        on conflict (scope, period) do update set count = usage_counters.count + 1
        returning count
        """,
        (scope, period),
    )
    return int(cur.fetchone()[0])


def spend_document_read(user_id: str, per_user_daily: int, global_monthly: int) -> None:
    """Count one document read - two provider calls - against its own budget.

    Its own counters rather than the interview's, because the two spend at different
    rates and for different reasons: an interview turn is a few tenths of a cent of
    text, a document is two vision passes at roughly 0.31 cents each (issue #65). A
    shared counter would let a handful of uploads close the interview for the day,
    which is the wrong failure - the interview is the product, the upload is a
    shortcut through it.
    """
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")

    with as_owner() as cur:
        if per_user_daily > 0:
            used = _bump(cur, f"documents:user:{user_id}", day)
            if used > per_user_daily:
                raise QuotaExceeded(
                    "Daily upload limit reached for this account. Enter the values by "
                    "hand today, or upload again tomorrow.",
                    retry_hint="tomorrow",
                )
        if global_monthly > 0:
            used = _bump(cur, "documents:global", month)
            if used > global_monthly:
                raise QuotaExceeded(
                    "This demo's monthly budget for reading documents is used up. The "
                    "interview still works, and values can be entered by hand.",
                    retry_hint="next month",
                )


def spend_interview_call(user_id: str, per_user_daily: int, global_monthly: int) -> None:
    """Count one provider-spending request, refusing over either limit.

    Owner connection on purpose: accounting is the backend's, not the user's,
    and the RLS-less table is unreachable for anybody else (0002_usage.sql).
    """
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")

    with as_owner() as cur:
        if per_user_daily > 0:
            used = _bump(cur, f"user:{user_id}", day)
            if used > per_user_daily:
                raise QuotaExceeded(
                    "Daily limit reached for this account. The interview continues "
                    "tomorrow; nothing you entered is lost.",
                    retry_hint="tomorrow",
                )
        if global_monthly > 0:
            used = _bump(cur, "global", month)
            if used > global_monthly:
                raise QuotaExceeded(
                    "This demo's monthly budget is used up, so the interview is "
                    "paused until next month. Your case stays readable.",
                    retry_hint="next month",
                )
