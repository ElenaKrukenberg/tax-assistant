"""Whether the database in front of us is the one this code was written against.

Two questions, deliberately kept apart, because they fail in different ways:

- **What ran here?** The ledger in `schema_versions` (0005), written by each schema
  file as its last statement.
- **Is it actually there?** A probe per version that asks the catalogue for the one
  thing the code needs from that file - the column, the constraint, the tables.

Either alone would be worth less. A ledger is bookkeeping and can be wrong; a probe
is truth but cannot see a file that changed nothing the probe looks at. Where the
two disagree, that disagreement is the finding: a version recorded but absent means
somebody edited history, and a version present but unrecorded means it was pasted
into the SQL editor by hand.

The point of all of it is `require_schema` in core/dependencies.py, which is what
makes the invariant enforceable rather than documented: the Tax Case routes refuse a
database that is behind the code, and say which file is missing. Before this, the
same fact was a sentence in db/README.md and the product's answer to a missing 0004
was to drop every Reviewer finding on insert while looking perfectly healthy. This
module stays free of FastAPI so that the check can be run from a script or a test
with no app around it.

The chat tab is untouched by drift on purpose. It needs no database at all
(`DatabaseNotConfigured` - "the chat tab works without one; Tax Cases do not"), so
taking the whole service down over a missing migration would cost more than it
protects.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic

import structlog

from db.connection import DatabaseNotConfigured, as_owner

logger = structlog.get_logger(__name__)

SCHEMA_DIR = Path(__file__).parent / "schema"


# What each file has to have left behind, as one boolean SQL expression per version.
#
# Each probe asks for the thing the *code* needs, not for everything the file did:
# 0003 exists so a value can be provenance 'remembered', 0004 so a finding can carry
# a category. That is the difference between a probe and a checksum, and it is the
# reason a probe is worth writing by hand - it states the dependency.
#
# A version with no probe here is checked against the ledger only. That is what a
# future file gets until somebody writes its probe, and it is reported as such
# rather than silently counted as verified.
PROBES: dict[str, str] = {
    "0001": """
        to_regclass('public.tax_cases')   is not null and
        to_regclass('public.field_values') is not null and
        to_regclass('public.documents')   is not null and
        to_regclass('public.expenses')    is not null and
        to_regclass('public.answers')     is not null and
        to_regclass('public.findings')    is not null
    """,
    "0002": "to_regclass('public.usage_counters') is not null",
    # The fourth provenance. Read off the constraint definition because that is
    # where the value lives - there is no enum to look up.
    "0003": """
        exists (
            select 1 from pg_constraint
            where conrelid = to_regclass('public.field_values')
              and conname = 'field_values_provenance_check'
              and pg_get_constraintdef(oid) like '%remembered%'
        )
    """,
    # Without this column no finding can be stored at all, which is the failure that
    # started this module.
    "0004": """
        exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'findings'
              and column_name = 'category'
        )
    """,
    "0005": "to_regclass('public.schema_versions') is not null",
    "0006": """
        to_regclass('public.tax_positions') is not null and
        exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'tax_positions'
              and column_name = 'provenance'
        )
    """,
    # Data only, so there is no table or column to look for - the evidence is the
    # absence of the old spelling. An empty `field_values` satisfies it, which is
    # correct: there is nothing there to be keyed the old way. What it does catch is a
    # database still holding facts under a category name or a bare profile name, which
    # is exactly the state the code can no longer read.
    "0007": """
        not exists (
            select 1 from field_values
            where key not like '%.%'
               or split_part(key, '.', 1) in (
                    'entfernungspauschale', 'homeoffice_tagespauschale', 'arbeitsmittel',
                    'telefon_internet', 'fortbildungskosten', 'umzugskosten',
                    'bewerbungskosten'
                  )
        )
    """,
    # A comment is all this file changes, so the comment is the probe: the column
    # describes itself as holding a Fact key rather than a category-qualified one.
    "0008": """
        col_description(
            to_regclass('public.field_values'),
            (select attnum from pg_attribute
              where attrelid = to_regclass('public.field_values') and attname = 'key')
        ) like '%Fact key%'
    """,
    # The idempotency key is the column the upload route cannot work without, and the
    # `discarded` state is the one the workflow writes; either one missing means an
    # upload fails at the first request rather than at some later branch.
    "0009": """
        exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'documents'
              and column_name = 'idempotency_key'
        ) and exists (
            select 1 from pg_constraint
            where conrelid = to_regclass('public.documents')
              and conname = 'documents_state_check'
              and pg_get_constraintdef(oid) like '%discarded%'
        )
    """,
    # Without this column a position is written and read back without the thing it was
    # assessed against, so a rule-version change cannot invalidate an accepted
    # decision. The probe is the column itself: there is nothing else in the file.
    "0010": """
        exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'tax_positions'
              and column_name = 'assessment_fingerprint'
        )
    """,
    # Without this the Review screen cannot tell a rules-only pass from a full
    # independent review, which is the one thing that screen has to be honest about.
    "0011": """
        exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'tax_cases'
              and column_name = 'last_review_from_model'
        )
    """,
    # Without this a correction overwrites what it replaced, and the trace can no
    # longer say a figure was changed by hand after a model read it.
    "0012": """
        exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'field_values'
              and column_name = 'superseded_value'
        )
    """,
    # The knowledge base's own table. Deliberately **not** part of what closes the Tax
    # Case routes: it serves the chat, and a missing corpus must not shut down the tax
    # cases that do not depend on it (#32). Probed so drift is still reported.
    "0014": """
        to_regclass('kb.chunks') is not null
    """,
    # Without this the only record of what a paid document read cost is a log line.
    "0013": """
        exists (
            select 1 from information_schema.columns
            where table_schema = 'public' and table_name = 'documents'
              and column_name = 'read_cost_usd'
        )
    """,
}


# Versions whose absence is reported but does not close a Tax Case route. There is one
# so far: `kb.chunks` serves the chat, and a knowledge base nobody has loaded must not
# shut down the tax cases, which never touch it (#32). Reported all the same - drift is
# still drift, and the startup log and /health both name it.
ADVISORY: frozenset[str] = frozenset({"0014"})


@dataclass(frozen=True)
class SchemaStatus:
    """What the database has, against what the code expects.

    `ok` is the only field a caller has to look at. The rest exist so the log line
    and /health can say which file, which is the whole difference between this and
    the warning it replaces.
    """

    database: str  # ok | not_configured | error
    ledger: str  # present | missing | unreadable
    expected: tuple[str, ...] = ()
    applied: tuple[str, ...] = ()
    # Expected, and neither recorded nor found by its probe. The actionable list.
    missing: tuple[str, ...] = ()
    # Recorded in the ledger but its probe says the objects are not there. Someone
    # edited an applied file, or a hand-run paste failed halfway.
    contradicted: tuple[str, ...] = ()
    # Found by its probe but absent from the ledger. Applied by hand before 0005
    # existed, which is exactly how this database got here.
    unrecorded: tuple[str, ...] = ()
    # Expected, recorded, and with no probe to confirm it independently.
    unverified: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether a Tax Case can be served truthfully.

        Advisory versions are excluded: they are reported as missing everywhere a
        person reads this, and they do not close a route that does not depend on them.
        """
        return (not [v for v in self.missing if v not in ADVISORY]
                and not [v for v in self.contradicted if v not in ADVISORY])

    def as_health(self) -> dict:
        """The shape /health reports. Terse when there is nothing to say."""
        out: dict = {"status": "ok" if self.ok else "drift", "ledger": self.ledger}
        for name in ("missing", "contradicted", "unrecorded", "unverified"):
            values = getattr(self, name)
            if values:
                out[name] = list(values)
        return out

    def complaint(self) -> str:
        """One sentence naming the files, for a 503 body and for the startup log."""
        parts = []
        if self.missing:
            parts.append("not applied: " + ", ".join(_filename(v) for v in self.missing))
        if self.contradicted:
            parts.append(
                "recorded but absent from the database: "
                + ", ".join(_filename(v) for v in self.contradicted)
            )
        return "; ".join(parts) or "the schema matches"


def expected_versions() -> tuple[str, ...]:
    """Every file in schema/, by its numeric prefix.

    Read off the directory rather than listed in code, so adding a file is enough to
    make it expected. The alternative - a constant here - is a second place to
    remember, and forgetting the second place is the bug this module exists for.
    """
    versions = sorted(p.name.split("_", 1)[0] for p in SCHEMA_DIR.glob("[0-9]*.sql"))
    return tuple(versions)


_CACHED: SchemaStatus | None = None
_CACHED_AT: float = 0.0

# How long an unhealthy answer is trusted before asking again. It is the recovery
# time of the whole mechanism: apply the missing file and the product comes back
# within this, with no restart and nobody redeploying. Short enough to be that, long
# enough that a health check polled every few seconds is not a query every few
# seconds. A healthy answer never expires - it cannot change without a deploy or a
# migration, and a migration is what invalidates it by making the check fail.
RECHECK_AFTER_S = 30.0


def status(refresh: bool = False) -> SchemaStatus:
    """What the database has, asking it only when the cached answer is stale."""
    global _CACHED, _CACHED_AT

    if _CACHED is not None and not refresh:
        if _CACHED.ok or (monotonic() - _CACHED_AT) < RECHECK_AFTER_S:
            return _CACHED

    expected = expected_versions()
    try:
        with as_owner() as cur:
            applied, ledger = _read_ledger(cur)
            probed = _run_probes(cur, expected)
        result = classify(expected, applied, probed, ledger)
    except DatabaseNotConfigured:
        # Not drift. The Tax Case routes already answer this with their own 503, and
        # they say it better: the database is not configured at all.
        result = SchemaStatus(database="not_configured", ledger="missing",
                              expected=expected)
    except Exception:  # noqa: BLE001 - a check that raises is worse than one that reports
        logger.warning("schema_check_failed", exc_info=True)
        result = SchemaStatus(database="error", ledger="unreadable", expected=expected)

    _CACHED, _CACHED_AT = result, monotonic()
    return result


def cached_status() -> SchemaStatus | None:
    """What is already known, without touching the database. None until asked once.

    /health reports this rather than calling `status`, for two reasons: it is the
    path Render polls, and the default test run has to work offline - a health check
    that opened a connection would make every unit test need a database (ADR 0003
    fixed the opposite constraint). The startup check in main.py is what fills this
    in, and `RECHECK_AFTER_S` is what keeps a drifted answer from going stale.
    """
    if _CACHED is not None and not _CACHED.ok and (monotonic() - _CACHED_AT) >= RECHECK_AFTER_S:
        return None
    return _CACHED


def classify(expected, applied, probed, ledger: str = "present") -> SchemaStatus:
    """Sort every expected version by what the ledger and its probe say about it.

    Pure, so the six combinations are unit-testable without a database. The order of
    the branches is the whole judgement, so it reads as prose: a version the ledger
    claims and the probe denies is worse than one nobody claims.
    """
    missing, contradicted, unrecorded, unverified = [], [], [], []
    for version in expected:
        recorded = version in applied
        probe = probed.get(version)  # None where no probe is written
        if probe is False and recorded:
            contradicted.append(version)
        elif probe is False or (not recorded and probe is None):
            missing.append(version)
        elif probe is True and not recorded:
            unrecorded.append(version)
        elif probe is None:
            unverified.append(version)

    return SchemaStatus(
        database="ok", ledger=ledger, expected=tuple(expected),
        applied=tuple(sorted(applied)), missing=tuple(missing),
        contradicted=tuple(contradicted), unrecorded=tuple(unrecorded),
        unverified=tuple(unverified),
    )


def _reset_cache() -> None:
    """For tests, which need each case to ask the database again."""
    global _CACHED, _CACHED_AT
    _CACHED, _CACHED_AT = None, 0.0


def _read_ledger(cur) -> tuple[set[str], str]:
    """Applied versions, and whether the ledger exists at all.

    A missing table is the expected state of any database last touched before 0005,
    including both live projects on the day this lands - so it is a state to report,
    not an error to raise.
    """
    cur.execute("select to_regclass('public.schema_versions') is not null")
    if not cur.fetchone()[0]:
        return set(), "missing"
    cur.execute("select version from schema_versions")
    return {row[0] for row in cur.fetchall()}, "present"


def _run_probes(cur, expected: tuple[str, ...]) -> dict[str, bool]:
    """Every probe for the expected versions, in one round trip.

    One query with a column per version: the checks are all catalogue lookups, and
    five sequential round trips to Frankfurt to answer one question would be five
    times the latency for none of the information.
    """
    probed = [v for v in expected if v in PROBES]
    if not probed:
        return {}
    columns = ", ".join(f"({PROBES[v]}) as v{v}" for v in probed)
    cur.execute(f"select {columns}")  # noqa: S608 - literal SQL from PROBES, no input
    row = cur.fetchone()
    return {version: bool(value) for version, value in zip(probed, row)}


def _filename(version: str) -> str:
    """The file a version came from, for a message a person can act on."""
    for path in SCHEMA_DIR.glob(f"{version}_*.sql"):
        return f"schema/{path.name}"
    return f"schema/{version}"
