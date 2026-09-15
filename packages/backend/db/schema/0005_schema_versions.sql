-- A ledger of which schema files have been applied to this database.
--
-- Until now that answer lived in a human's memory and in a sentence in
-- db/README.md ("until 0004 is applied no finding can be stored"). A warning in a
-- README is not a check: the deployment checklist said to apply 0001 and 0002 while
-- four files existed, and the missing 0004 meant every Reviewer finding was dropped
-- on insert while the interview carried on looking healthy.
--
-- So the database now says what it has, and db/schema_version.py refuses to serve a
-- Tax Case when what it has is not what the code was written against.
--
-- Applying this file is what records 0001 to 0005: it can only run after them, so
-- its own presence is the evidence for the four before it. Every later file ends
-- with an insert of its own version - one statement, in the same file, so a
-- migration cannot be applied without saying so.

create table if not exists schema_versions (
    -- The file's numeric prefix, not its whole name: "0004". The name can be
    -- corrected, the version is the identity.
    version text primary key,
    applied_at timestamptz not null default now()
);

comment on table schema_versions is
    'Which files in packages/backend/db/schema have been applied here. Written by '
    'the files themselves, read by db/schema_version.py.';

-- Enabled with no policy at all, which denies every row to `authenticated` and to
-- `anon`. That is deliberate rather than lazy: this table is in the public schema,
-- so without RLS it would be readable through the REST API with the anon key, and
-- the shape of a system's migrations is not something to hand to the internet. The
-- backend reads it through `as_owner()`, and a table owner bypasses RLS.
alter table schema_versions enable row level security;

insert into schema_versions (version) values
    ('0001'), ('0002'), ('0003'), ('0004'), ('0005')
on conflict (version) do nothing;
