"""Apply the schema files this database is missing, and record what was applied.

    python -m db.migrate --dry-run          # what it would do, against DATABASE_URL
    python -m db.migrate
    python -m db.migrate --db-url "postgresql://..."   # the other project

What makes this more than a loop over a directory is that it does not trust the
ledger alone to decide what to run. `schema_version.py` already asks the database
two questions - what the ledger claims, and what the catalogue actually has - and
this reads the answer:

- **not applied**: run the file, then record it.
- **present but unrecorded**: record it and run nothing. That is the baseline case,
  and it is derived from evidence rather than from somebody asserting that 0001 to
  0004 went in. Running them again would fail on `create table` anyway.
- **recorded but absent**: stop. A file was edited after it was applied, and
  guessing between "run it again" and "fix the ledger" is not a script's decision.

One transaction per file, so a file that fails halfway leaves nothing behind - DDL
is transactional in Postgres, which is the whole reason this can be honest. A
session-level advisory lock around the run, so two deploys cannot interleave.

Its own connection, not the app's pool, for the same reason `postgres_checkpointer`
keeps one: a script should not depend on the app's lifespan, and `--db-url` has to
be able to point somewhere else entirely.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

from db.schema_version import PROBES, SCHEMA_DIR, classify, expected_versions

# One fixed key so every runner competes for the same lock. Arbitrary, but it has to
# stay the same: a new number is a new lock and therefore no lock at all.
ADVISORY_LOCK_KEY = 5_070_005


@dataclass(frozen=True)
class Step:
    version: str
    action: str  # apply | record
    reason: str

    @property
    def path(self) -> Path:
        for candidate in SCHEMA_DIR.glob(f"{self.version}_*.sql"):
            return candidate
        raise FileNotFoundError(f"no file for schema version {self.version}")


class MigrationRefused(RuntimeError):
    """The database is in a state a script must not resolve on its own."""


def plan(expected, applied, probed) -> list[Step]:
    """What to do, from what the ledger and the probes say. Pure, so it is testable.

    Ordered by version, because each file assumes the ones before it.
    """
    status = classify(expected, applied, probed)
    if status.contradicted:
        raise MigrationRefused(
            "recorded but absent from the database: "
            + ", ".join(status.contradicted)
            + " - an applied file was edited. Fix it by hand: either re-apply the "
              "change as a new file, or delete the row from schema_versions."
        )

    steps = [Step(v, "apply", "not applied") for v in status.missing]
    steps += [Step(v, "record", "already in the database, never recorded")
              for v in status.unrecorded]
    return sorted(steps, key=lambda s: s.version)


def read_state(cur, expected) -> tuple[set[str], dict[str, bool]]:
    """The two questions, against an open cursor.

    Duplicated from schema_version's private helpers on purpose: those run on the
    app's pool through `as_owner`, and this runs on a connection of its own that may
    not even be the app's database.
    """
    cur.execute("select to_regclass('public.schema_versions') is not null")
    applied: set[str] = set()
    if cur.fetchone()[0]:
        cur.execute("select version from schema_versions")
        applied = {row[0] for row in cur.fetchall()}

    probed_versions = [v for v in expected if v in PROBES]
    if not probed_versions:
        return applied, {}
    columns = ", ".join(f"({PROBES[v]}) as v{v}" for v in probed_versions)
    cur.execute(f"select {columns}")  # noqa: S608 - literal SQL from PROBES
    row = cur.fetchone()
    return applied, {v: bool(value) for v, value in zip(probed_versions, row)}


def run(dsn: str, dry_run: bool = False, out=sys.stdout) -> list[Step]:
    """Apply and record what is missing. Returns the steps taken (or planned)."""
    expected = expected_versions()

    with psycopg.connect(dsn, connect_timeout=20) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("select pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
            try:
                applied, probed = read_state(cur, expected)
                steps = plan(expected, applied, probed)
                if not steps:
                    print("nothing to do: the schema is current", file=out)
                    return []

                for step in steps:
                    if dry_run:
                        print(f"would {step.action} {step.path.name} "
                              f"({step.reason})", file=out)
                        continue
                    _do(conn, cur, step)
                    print(f"{step.action}ed {step.path.name}", file=out)
                return steps
            finally:
                cur.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))


def _do(conn, cur, step: Step) -> None:
    """One file, in one transaction: the DDL and the ledger row together or neither.

    The insert is unconditional even though a file since 0005 records itself, and
    `on conflict do nothing` is what makes that safe. Belt and braces on purpose:
    the run must not depend on the file having remembered.
    """
    sql = step.path.read_text() if step.action == "apply" else ""
    with conn.transaction():
        if sql:
            cur.execute(sql)
        cur.execute(
            "insert into schema_versions (version) values (%s) "
            "on conflict (version) do nothing",
            (step.version,),
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db-url", help="target database; defaults to DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would happen and change nothing")
    args = parser.parse_args(argv)

    dsn = args.db_url
    if not dsn:
        from core.config import get_settings
        dsn = get_settings().database_url
    if not dsn:
        print("no database: pass --db-url or set DATABASE_URL "
              "(see db/README.md)", file=sys.stderr)
        return 2

    try:
        run(dsn, dry_run=args.dry_run)
    except MigrationRefused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as failure:
        # A traceback here says nothing a person can act on, and the useful part -
        # what was tried and why it did not work - is one line inside it. The hint
        # has to match the failure: telling someone to check the host when the host
        # answered and refused the password sends them to the wrong place, which is
        # exactly what the first version of this did.
        first = str(failure).splitlines()[0]
        print(f"cannot connect: {first}", file=sys.stderr)
        print(_hint(first), file=sys.stderr)
        return 3
    return 0


def _hint(message: str) -> str:
    if "resolve host" in message or "Name or service not known" in message:
        return ("The host was not found. Use the session pooler "
                "(pooler.supabase.com, port 5432): the direct host "
                "db.<ref>.supabase.co resolves over IPv6 only. See db/README.md.")
    if "password authentication failed" in message or "Tenant or user not found" in message:
        return ("The host answered and rejected the credentials, so the host and "
                "port are fine. Two usual causes: the placeholder was left in the "
                "string (it arrives as [YOUR-PASSWORD] and has to be replaced), or "
                "the password contains characters a URL treats specially. In a URI, "
                "% @ : / ? # have to be percent-encoded and [ ] are not allowed at "
                "all. To avoid encoding entirely, pass libpq keyword form instead: "
                "--db-url \"host=... port=5432 user=postgres.<ref> "
                "password='...' dbname=postgres\".")
    if "ECIRCUITBREAKER" in message or "too many authentication failures" in message:
        return ("Supavisor has temporarily blocked new connections after repeated "
                "authentication failures. Wait a few minutes and do not retry in "
                "the meantime - each attempt extends the window.")
    return "See db/README.md for the connection string this project needs."


if __name__ == "__main__":
    raise SystemExit(main())
