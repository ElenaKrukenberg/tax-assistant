-- Usage counters: the money guards behind the public deployment (Q23).
--
-- Apply after 0001_tax_case.sql, through the Supabase SQL editor. One table,
-- deliberately in the database rather than in process memory: the monthly
-- ceiling is the wallet's last line, and a counter that resets on every deploy
-- is a ceiling in name only.
--
-- Counting is not billing. A row counts interview advances — provider-spending
-- requests — per scope and period; the limits themselves live in the backend's
-- configuration, so raising one is an environment change, not a migration.

create table usage_counters (
    scope   text not null,   -- 'user:<uuid>' or 'global'
    period  text not null,   -- '2026-08-22' for daily, '2026-08' for monthly
    count   integer not null default 0,
    primary key (scope, period)
);

comment on table usage_counters is
    'Interview advances per user-day and per project-month. The backend''s money guard.';

-- Backend-internal accounting: no user may read or write it. RLS with no
-- policies denies everything to authenticated/anon; the backend reaches it as
-- the table owner, which bypasses RLS — the one place that bypass is the point.
alter table usage_counters enable row level security;
