# Database

Supabase provides both the Postgres a Tax Case lives in and the authentication that
keys it ([ADR 0003](../../../docs/adr/0003-supabase-for-auth-and-state.md)). There is
no local database: development runs against a second hosted project, and only the
connection variables differ between local, Vercel and Render.

Schema changes are numbered SQL files in `schema/`. An applied file is history - the
next change is a new file, never an edit to an old one. `0005` adds a
`schema_versions` ledger, and `schema_version.py` refuses to serve a Tax Case when
the database is behind the code.

## Applying migrations

```
python -m db.migrate --dry-run    # what it would do, against DATABASE_URL
python -m db.migrate              # apply it

# another project: libpq keyword form in single quotes, so a password containing
# $ or = reaches psycopg unmangled by the shell
python -m db.migrate --dry-run --db-url 'host=aws-0-<region>.pooler.supabase.com port=5432 user=postgres.<ref> password=<password> dbname=postgres'
```

The runner applies what is missing and records it, records a file the probes find
already in the database without re-running it (this is how 0001 to 0004 were
baselined), and refuses a database that contradicts its own ledger - choosing
between "run it again" and "fix the ledger" is not a script's decision. One
transaction per file, and a session advisory lock so two deploys cannot interleave.

The Supabase **SQL Editor** stays a valid path: paste the files in number order,
each assumes the ones before it. That is why every file since 0005 records itself as
its last statement, and a test enforces that it does.

## Loading the knowledge base

Separate from any deploy, on purpose. A backend deploy used to run this and rebuild
every embedding, which made deploys slow, left nothing behind between them, and let an
indexing failure take a healthy backend down (issue #32).

```
python ingest.py --dry-run                       # chunk only, free, no database
python ingest.py --release-id 2026-09-13         # load ../../KB into DATABASE_URL
```

Against another project, the same way migrations go there - `DATABASE_URL` in the
environment for that one run:

```
DATABASE_URL='host=aws-0-<region>.pooler.supabase.com port=5432 user=postgres.<ref> password=<password> dbname=postgres' \
  python ingest.py --release-id 2026-09-13
```

The whole corpus is replaced inside one transaction, so an interrupted run leaves the
previous one intact and serving. Embedding 775 chunks costs well under a cent.

**Order matters when both a migration and a load are due.** Apply `0014` and load the
documents *before* deploying a backend that no longer builds an index at all -
otherwise the search is empty between the two.

## Adding a migration

1. Add `schema/<next number>_<slug>.sql`; never edit a file that has been applied.
2. End it with `insert into schema_versions (version) values ('<number>') on conflict (version) do nothing;`.
3. Add a probe to `PROBES` in `schema_version.py` - one boolean expression checking what the code needs from that file.
4. `python -m db.migrate --dry-run`, then `python -m db.migrate`, against **every** project.
5. Confirm: `nothing to do: the schema is current`.

**Rolling back.** There are no down scripts. A file that fails rolls back on its own
- one transaction per file. A file that succeeds and turns out wrong is undone by the
next file forward, never by editing it. Dropped data is gone either way, so
migrations add; a removal is a separate decision with a backup taken first.

## The schema check

`schema_version.py` asks two questions and keeps them apart: what the
`schema_versions` ledger claims, and what one probe per version finds in the
catalogue. Where they disagree, the disagreement is the finding - recorded but
absent means an applied file was edited, present but unrecorded means it was pasted
in by hand. Only "not applied" and "recorded but absent" block a Tax Case.

- **Startup** logs `schema_ok` or `schema_drift` with the file names.
- **`GET /api/v1/tax/health`** reports it under `schema`, and stays 200 while
  drifted: it is Render's health path, and drift stops Tax Cases without stopping
  the chat tab.
- **Every `/api/v1/cases` route** answers 503 with the file to apply.

A healthy answer is cached for the life of the process; a drifted one expires after
30 seconds, so applying the missing file brings the product back with no restart.

Two of the three tables the backend uses are not in `schema/` and are not meant to
be: the LangGraph checkpointer and the profile store create their own on first use
(`ensure_checkpoint_tables`, `ensure_store_tables`), because that is the library's
schema and a migration of ours would be wrong the first time it changed. And until
0003 is applied nothing carries over - the backend logs `profile_memory_seed_failed`
and the interview runs as before, deliberately rather than as an untested fallback.

Not ours does not mean out of reach, though. `0007` writes to both, guarded by
`to_regclass` so it does nothing where the library has not created them yet: it
renames the keys profile memory holds, because a remembered value under a name the
code no longer knows is not forgotten, only unreachable
(`services/profile_erasure.py` is the module that insists on the difference), and it
deletes the checkpoint rows of paused interviews, because a paused run keeps its own
copy of the case and would resume with keys the graph cannot read.

## The four values the backend needs

Into `packages/backend/.env`:

```
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=<anon key>
SUPABASE_JWT_SECRET=<JWT secret>
```

Plus one more if you want to run the integration suite - see **The database the tests
are allowed to touch** below:

```
TEST_USER_ID=<a user created by hand in the development project>
```

All four come from **Connect** in the dashboard header, or from **Project Settings →
Database / API**. Two things about `DATABASE_URL` are not preferences:

- It must be the **pooler** host (`pooler.supabase.com`), not the direct
  `db.<ref>.supabase.co`, which resolves over IPv6 only - it works on a laptop and
  fails on Render, whose free plan has no IPv6.
- Port **5432**, the pooler's session mode, not 6543. Transaction mode forbids
  prepared statements, and the LangGraph Postgres checkpointer relies on them.

The anon key is public by design and safe in the frontend. Never the `service_role`
key: it bypasses row level security, one of the two locks on somebody else's salary
and address.

## Row level security applies to the backend too, but only on purpose

The policies in `0001_tax_case.sql` are enforced against `auth.uid()`, and the role a
Supabase connection string uses owns the tables - and a table owner bypasses RLS.
Left alone, the policies would protect only the path where the frontend talks to
Supabase directly, while every query from this backend sailed past them.

So the connection layer holds to a contract: each request runs inside a transaction
that first drops to the user's role and installs their claims.

```sql
set local role authenticated;
set local "request.jwt.claims" = '{"sub": "<user id from the verified JWT>"}';
```

From there `auth.uid()` returns that user and the policies bite. Both modes of the
pooler allow it, because `set local` is scoped to the transaction.

The backend still filters by `user_id` in its own SQL. Two locks, deliberately: a
forgotten `WHERE` should not be the only thing between two users' tax data - and with
RLS in force a forgotten filter shows up as an empty result in a test rather than as
somebody else's salary on a screen.

And for the frontend, `packages/frontend/.env.local`:

```
NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>
```

`.env` and `.env.local` are both git-ignored. Nothing here belongs in a commit.

## Two projects

The free tier allows two, which is exactly the arrangement: one for development, one
for the deployed demo. Same schema, applied twice - so a schema file that only ever
ran against development is a schema file that will surprise you on the day you
submit.

## The database the tests are allowed to touch

Two projects and one `DATABASE_URL` used to mean the integration suite ran against
whatever that string named. It creates and deletes Tax Cases, clears checkpoints,
writes and wipes profile memory, and `tests/test_migrate.py` borrows a row out of the
`schema_versions` ledger and puts it back - so a DSN left pointed at the deployed
project after an afternoon's debugging was one `pytest -m integration` away from doing
all of that to real data. Two things now stand in the way (issue #90).

The fix is a marker inside the database rather than a second variable. A second DSN
would only prove which *string* the tests used, which is not the question - one copied
from the wrong project satisfies it perfectly - and two strings to keep in step after
a password change is its own trap.

So apply `db/test_database_marker.sql` **to the development project only**, through
that project's SQL editor in the dashboard or with:

```
psql "$DATABASE_URL" -f db/test_database_marker.sql
```

`tests/dbguard.py` then asks the database it actually connected to whether it carries
the row, and skips the whole suite with an instruction when it does not. The deployed
project answers no because nobody ever applied it there - which is the point, and the
reason the file is deliberately **not** in `db/schema/`: `db/migrate.py` applies
everything it finds in there, and this must never reach production.
