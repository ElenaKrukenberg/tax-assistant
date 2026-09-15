-- The one thing a stored tax position could not say: what it was assessed against.
--
-- `TaxPosition.assessment_fingerprint` has existed in the domain since 0006 and was
-- never a column, so `save_positions` dropped it and `get_positions` read back an
-- empty string. `dependencies_are_current` has a fallback for exactly that case - it
-- compares each dependent fact's version one by one - and the fallback is weaker than
-- it looks: the fingerprint also covers `rule_version` and `calculator_version`, and
-- those are invisible to a per-fact comparison. So a new rule version for 2025 could
-- ship while every position a user had already accepted went on looking current, with
-- the figure behind it recomputed under rules they never saw.
--
-- Hence the second half of this file: the upsert's own staleness rule moves onto this
-- column. `db/cases.py:save_positions` compares the stored fingerprint with the
-- incoming one and turns the user's decision into `needs_reconfirmation` when they
-- differ, which is a superset of the `dependent_facts` comparison it used before.
--
-- Both answers, not only `accepted`. A refusal is an answer about a particular figure
-- under particular rules, and the reason for it can be the very thing that moved:
-- 180 EUR declined as not worth the paperwork is not 1,800 declined. Carrying a `no`
-- across a changed assessment would answer the new question on the user's behalf and
-- never show it to them.
--
-- Backfilled with '' rather than a computed value on purpose. A fingerprint invented
-- by a migration would claim an assessment that never happened; an empty one keeps
-- the documented meaning - "this position predates the column" - and
-- `dependencies_are_current` already treats it as the signal to fall back.

alter table tax_positions
    add column if not exists assessment_fingerprint text not null default '';

comment on column tax_positions.assessment_fingerprint is
    'SHA-256 over the dependent facts with their versions, the rule version and the '
    'calculator version, as of the assessment that produced this row. Empty means the '
    'row predates 0010, and staleness falls back to comparing fact versions one by '
    'one. A change here turns the user decision - accepted or rejected - into '
    'needs_reconfirmation.';

insert into schema_versions (version) values ('0010')
on conflict (version) do nothing;
