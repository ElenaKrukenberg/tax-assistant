# Supabase provides both authentication and the Postgres a Tax Case lives in

A Tax Case that survives for a year needs durable storage, and the free Render
plan the backend runs on has no persistent disk, so state cannot stay on the
instance. Supabase was chosen over Neon-plus-Clerk and over rolling our own JWT
because it is one free tier, one dashboard and one set of credentials for both
concerns: the FastAPI backend verifies Supabase JWTs in a single dependency, and
the LangGraph checkpointer connects to the same Postgres. Sign-in is a
passwordless email link only — no passwords, no OAuth applications to register —
which is the cheapest authentication that still gives a real user identity to key
cases on. The lock-in is accepted knowingly: it is an auth provider plus a
database, the two things hardest to swap later, traded for the setup hours a
three-week sprint does not have.

There is no local database. Development runs against a second hosted Supabase
project — the free tier allows exactly two — and only the connection variables
differ between local, Vercel and Render. The alternative, a local stack through
the Supabase CLI, is the vendor's intended workflow and gives versioned
migrations and full parity, but it requires Docker Desktop, which is not
installed and is half a day with problems of its own. Sign-in is the reason the
choice matters at all: Supabase Auth is hosted, so a local Postgres could not
exercise the magic-link flow, and JWT verification would first be tested after
deployment. The cost accepted is network latency on every development query,
which is irrelevant for a handful of Tax Cases, and one constraint on the test
suite: the existing tests touch no database and must stay that way, so
database-backed tests become a separate group that is skipped by default and run
against the development project on purpose.

**The Supabase CLI is closed, not merely postponed.** The paragraph above rejects
it for needing Docker, which is a reason about the local stack and would not have
survived the observation that `db push`, `migration list` and `migration repair`
work against a hosted project without it. It is rejected a second time and on its
own merits: schema management is now solved here without a Node toolchain in a
Python service. The ledger is ours - `schema_versions`, created by
`db/schema/0005_schema_versions.sql`, which every later file writes to as its last
statement - and the runner is `db/migrate.py`, which decides what to do by asking
the catalogue rather than by trusting the ledger: a file the probes find already
present is recorded and not re-run, and a database that contradicts its own ledger
is refused outright. Adopting the CLI now would mean a second ledger in its own
schema and a second definition of what "applied" means, for a problem that has an
answer. Do not raise it again for migrations; if it ever returns, it returns for
the local stack, and Docker is still the question.

What this buys, and it is the reason the ledger exists rather than a README
sentence: `db/schema_version.py` refuses the Tax Case routes when the database is
behind the build, and names the file to apply. The refusal is narrow on purpose -
the chat tab needs no database at all, so drift must not take the whole service
down.
