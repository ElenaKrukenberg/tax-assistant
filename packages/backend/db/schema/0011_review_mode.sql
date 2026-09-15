-- Whether the last review was the independent one it appears to be.
--
-- The Reviewer falls back to deterministic rules when no model is configured, when the
-- provider fails mid-review, and when no verdict settles within its round limit
-- (`agents/reviewer.py`). Each fallback carries a note saying which, and `ReviewResult`
-- has said `from_model` since it was written - but nothing was ever stored, so a
-- rules-only pass and a full independent review left the case looking identical.
--
-- On the case and not on `findings`, which is where the flag was already travelling in
-- the graph state. A finding row only exists when something was raised, and the worst
-- version of this failure is the quiet one: a degraded review that raises nothing, and
-- a screen that says "the Reviewer raised nothing" over it.

alter table tax_cases
    add column if not exists last_review_from_model boolean,
    add column if not exists last_review_note text not null default '';

comment on column tax_cases.last_review_from_model is
    'True when the last review ran with its own model, false when it fell back to '
    'deterministic rules, null when no review has run. The Review screen says which, '
    'because a rules-only pass is not an independent second opinion.';
comment on column tax_cases.last_review_note is
    'Why the last review was degraded, in the Reviewer''s own words: no model '
    'configured, provider failed mid-review, or no verdict within the round limit.';

insert into schema_versions (version) values ('0011')
on conflict (version) do nothing;
