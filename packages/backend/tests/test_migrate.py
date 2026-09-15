"""The migration runner: what it decides to do, and what it refuses to do.

The decision is pure (`plan`), so all of this runs offline except the one case that
proves the runner is a no-op against a current database.
"""

from __future__ import annotations

import io

import pytest

from tests import dbguard

from core.config import get_settings
from db import migrate


def test_a_file_neither_recorded_nor_present_is_applied():
    steps = migrate.plan(("0001",), set(), {"0001": False})
    assert [(s.version, s.action) for s in steps] == [("0001", "apply")]


def test_a_file_present_but_unrecorded_is_only_recorded():
    """The baseline case, and the reason this reads probes rather than a claim.

    0001 to 0004 are in both live projects and in no ledger. Running them again
    would fail on `create table`; recording them is the whole of what is owed.
    """
    steps = migrate.plan(("0001",), set(), {"0001": True})
    assert [(s.version, s.action) for s in steps] == [("0001", "record")]


def test_a_current_database_needs_nothing():
    assert migrate.plan(("0001",), {"0001"}, {"0001": True}) == []


def test_steps_run_in_version_order():
    """Each file assumes the ones before it, so the order is not cosmetic."""
    steps = migrate.plan(
        ("0001", "0002", "0003"),
        set(),
        {"0001": True, "0002": False, "0003": True},
    )
    # Interleaved on purpose: sorting by version has to beat grouping by action, or
    # 0002 would be applied after 0003 had already been recorded.
    assert [s.version for s in steps] == ["0001", "0002", "0003"]
    assert [s.action for s in steps] == ["record", "apply", "record"]


def test_it_refuses_a_database_that_contradicts_its_own_ledger():
    """Recorded but absent means an applied file was edited. Not a script's call."""
    with pytest.raises(migrate.MigrationRefused) as refused:
        migrate.plan(("0004",), {"0004"}, {"0004": False})
    assert "0004" in str(refused.value)
    assert "schema_versions" in str(refused.value)


def test_a_step_knows_its_file():
    step = migrate.Step("0005", "apply", "not applied")
    assert step.path.name == "0005_schema_versions.sql"


@pytest.fixture
def ledger_row_removed():
    """Take one version out of the ledger, and put it back whatever happens.

    0005 is the safe one to borrow: the row says the ledger table exists, and the
    probe for it looks at the table rather than at the row - so removing it produces
    exactly the "present but never recorded" state that 0001 to 0004 were in, on a
    table that holds no user data.
    """
    import psycopg

    dsn = get_settings().database_url

    def ledger():
        with psycopg.connect(dsn, connect_timeout=15) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("select version from schema_versions order by version")
                return [row[0] for row in cur.fetchall()]

    with psycopg.connect(dsn, connect_timeout=15) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("delete from schema_versions where version = '0005'")
    try:
        yield ledger
    finally:
        with psycopg.connect(dsn, connect_timeout=15) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("insert into schema_versions (version) values ('0005') "
                            "on conflict (version) do nothing")


@pytest.mark.integration
def test_the_runner_records_a_file_it_finds_already_applied(ledger_row_removed):
    """The write path, against a real database: plan, then do, then check.

    Everything else about the runner is either pure or read-only, so without this
    the one thing it exists for - changing something - would be untested.
    """
    if not get_settings().database_url:
        dbguard.require_test_database()

    assert "0005" not in ledger_row_removed(), "fixture did not take the row out"

    dry = io.StringIO()
    planned = migrate.run(get_settings().database_url, dry_run=True, out=dry)
    assert [(s.version, s.action) for s in planned] == [("0005", "record")]
    assert "would record 0005_schema_versions.sql" in dry.getvalue()
    assert "0005" not in ledger_row_removed(), "a dry run must change nothing"

    done = io.StringIO()
    taken = migrate.run(get_settings().database_url, out=done)
    assert [(s.version, s.action) for s in taken] == [("0005", "record")]
    assert "recorded 0005_schema_versions.sql" in done.getvalue()
    assert "0005" in ledger_row_removed()


@pytest.mark.integration
def test_the_runner_is_a_no_op_against_the_dev_project():
    if not get_settings().database_url:
        dbguard.require_test_database()

    out = io.StringIO()
    steps = migrate.run(get_settings().database_url, dry_run=True, out=out)
    assert steps == [], out.getvalue()
    assert "nothing to do" in out.getvalue()
