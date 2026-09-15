-- Proof, held by the database itself, that it is safe to run the tests against.
--
-- Apply this to the development project and to nothing else. It is deliberately not
-- in `db/schema/`: `db/schema_version.py` discovers migrations with
-- `glob("[0-9]*.sql")` and `db/migrate.py` applies what it finds, so a file in there
-- would eventually be applied to production - which is the one place this row must
-- never exist.
--
-- Why a row and not just a separate `TEST_DATABASE_URL`. The variable proves which
-- *string* the tests used; it cannot prove which *database* that string named. A DSN
-- pasted in from the wrong project satisfies the variable perfectly. This does not:
-- the integration suite asks the database it actually connected to whether it is a
-- test database, and production answers no because nobody ever applied this file
-- there.
--
-- The integration suite skips with an instruction when this is missing, so a fresh
-- checkout is inconvenient rather than dangerous.

create table if not exists test_database_marker (
    -- One row, forced: `id` may only be true, and true is the primary key.
    id    boolean primary key default true check (id),
    label text not null,
    noted timestamptz not null default now()
);

comment on table test_database_marker is
    'Present only in the development project. The integration suite refuses to run '
    'against a database without it. Never add this to db/schema/.';

insert into test_database_marker (label)
values ('TaxAssistant development project - safe for the integration suite')
on conflict (id) do nothing;

-- No row level security: the backend reads it through `as_owner()`, and it holds
-- nothing about anybody.
