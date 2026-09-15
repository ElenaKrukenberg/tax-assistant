-- A corrected value remembers what it replaced.
--
-- Until now the only correction was stepping back through the interview, and a value
-- rewritten by any other path simply overwrote the old one. That breaks the promise
-- the product is built on twice over: the trace beside a figure could no longer say a
-- number had been changed by hand after a model read it off a document, and nothing
-- distinguished "the user typed 145" from "the user corrected 154 to 145".
--
-- Kept on the row rather than in a history table. One correction per value is what the
-- product needs to state - "changed after extraction, from X" - and a full audit trail
-- of every edit is #88's shape, not this one's. The superseded provenance travels with
-- the superseded value, because that is the pair the sentence needs: a document value
-- corrected by hand is a different claim from an answer corrected by hand.

alter table field_values
    add column if not exists superseded_value jsonb,
    add column if not exists superseded_provenance text,
    add column if not exists corrected_at timestamptz;

comment on column field_values.superseded_value is
    'What this value was before the user corrected it in place, or null if it has '
    'never been corrected. The trace prints it so a figure can say it was changed.';
comment on column field_values.superseded_provenance is
    'Where the superseded value came from. A document value corrected by hand is a '
    'different statement from a typed answer corrected by hand.';

insert into schema_versions (version) values ('0012')
on conflict (version) do nothing;
