"""The schema check: what it concludes, and what the product does about it.

The judgement (`classify`) is pure, so most of this runs offline - which is the
point of splitting it out. The one test that needs a database only asks it to
confirm that the probes are valid SQL and that the dev project really is up to date.
"""

from __future__ import annotations

import pytest

from tests import dbguard
from fastapi import HTTPException

from core.config import get_settings
from core.dependencies import require_schema
from db import schema_version as sv


@pytest.fixture(autouse=True)
def no_cached_answer():
    """Each case asks fresh: a cached status is process-wide by design."""
    sv._reset_cache()
    yield
    sv._reset_cache()


# --- what is expected ------------------------------------------------------------

def test_expected_versions_are_read_off_the_directory():
    versions = sv.expected_versions()
    assert versions == tuple(sorted(versions)), "order is the apply order"
    assert "0001" in versions and "0005" in versions
    # Every expected version needs a probe, or drift in it can only be detected by
    # the ledger - which is the half that can be wrong. A new file failing here is
    # the reminder to write its probe.
    assert set(versions) <= set(sv.PROBES), "a schema file with no probe"


def test_every_file_since_the_ledger_records_itself():
    """The convention the ledger rests on, guarded.

    A file applied through the SQL editor records itself or it records nothing: the
    runner is not the only path, so the line cannot be assumed. Forgetting it fails
    quietly - the version lands in `unrecorded`, which does not block - so the guard
    has to be here, where forgetting it costs a red test instead of a wrong ledger.

    0001 to 0004 are exempt: they were applied long before there was a ledger, and
    0005 is what records them.
    """
    for path in sorted(sv.SCHEMA_DIR.glob("[0-9]*.sql")):
        version = path.name.split("_", 1)[0]
        if version < "0005":
            continue
        sql = path.read_text()
        assert "insert into schema_versions" in sql, f"{path.name} records nothing"
        assert f"('{version}')" in sql, f"{path.name} does not record its own version"


# --- the judgement ---------------------------------------------------------------

def test_recorded_and_present_is_healthy():
    status = sv.classify(("0001",), {"0001"}, {"0001": True})
    assert status.ok
    assert status.missing == () and status.contradicted == ()


def test_neither_recorded_nor_present_is_missing():
    status = sv.classify(("0001", "0004"), {"0001"}, {"0001": True, "0004": False})
    assert not status.ok
    assert status.missing == ("0004",)


def test_recorded_but_absent_is_contradicted():
    """The ledger claiming a file whose objects are not there. Someone edited it."""
    status = sv.classify(("0004",), {"0004"}, {"0004": False})
    assert not status.ok
    assert status.contradicted == ("0004",) and status.missing == ()


def test_present_but_unrecorded_is_not_a_failure():
    """How both live projects look today: applied by hand, before a ledger existed."""
    status = sv.classify(("0001",), set(), {"0001": True})
    assert status.ok
    assert status.unrecorded == ("0001",)


def test_a_version_with_no_probe_rests_on_the_ledger():
    recorded = sv.classify(("0006",), {"0006"}, {})
    assert recorded.ok and recorded.unverified == ("0006",)

    unrecorded = sv.classify(("0006",), set(), {})
    assert not unrecorded.ok and unrecorded.missing == ("0006",)


def test_the_complaint_names_the_file_to_apply():
    status = sv.classify(("0004",), set(), {"0004": False})
    assert "schema/0004_finding_category.sql" in status.complaint()


# --- what the product does about it ----------------------------------------------

def test_tax_case_routes_refuse_a_drifted_database(monkeypatch):
    drifted = sv.classify(("0004",), set(), {"0004": False})
    monkeypatch.setattr(sv, "status", lambda *a, **k: drifted)

    with pytest.raises(HTTPException) as raised:
        require_schema()
    assert raised.value.status_code == 503
    assert "0004_finding_category.sql" in raised.value.detail


def test_a_healthy_database_passes(monkeypatch):
    monkeypatch.setattr(sv, "status",
                        lambda *a, **k: sv.classify(("0001",), {"0001"}, {"0001": True}))
    require_schema()  # raises nothing


def test_an_unconfigured_database_is_not_this_checks_business(monkeypatch):
    """The routes' own 503 says that better, and says which."""
    monkeypatch.setattr(sv, "status", lambda *a, **k: sv.SchemaStatus(
        database="not_configured", ledger="missing"))
    require_schema()


# --- the cache -------------------------------------------------------------------

def test_health_reports_nothing_before_anyone_has_looked(client):
    """And asks no database to say so: the default test run works offline."""
    body = client.get("/api/v1/tax/health").json()
    assert body["status"] == "ok"
    assert body["schema"] == {"status": "not_checked"}


def test_a_drifted_answer_goes_stale_so_applying_the_file_recovers():
    sv._CACHED = sv.classify(("0004",), set(), {"0004": False})
    sv._CACHED_AT = 0.0  # long ago
    assert sv.cached_status() is None, "a stale complaint must not be reported as news"


def test_a_healthy_answer_is_kept_for_the_life_of_the_process():
    sv._CACHED = sv.classify(("0001",), {"0001"}, {"0001": True})
    sv._CACHED_AT = 0.0
    assert sv.cached_status() is sv._CACHED


# --- against the real database ---------------------------------------------------

@pytest.mark.integration
def test_the_probes_are_valid_sql_and_the_dev_project_is_current():
    if not get_settings().database_url:
        dbguard.require_test_database()

    status = sv.status(refresh=True)
    assert status.database == "ok", status
    # 0001 to 0004 were applied by hand long before the ledger existed, so they may
    # be unrecorded here - but they must be *present*, because the product has been
    # running on them.
    for version in ("0001", "0002", "0003", "0004"):
        assert version not in status.missing, status.complaint()
        assert version not in status.contradicted, status.complaint()
