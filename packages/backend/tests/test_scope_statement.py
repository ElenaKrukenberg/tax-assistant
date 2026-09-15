"""The scope statement says what the build does, not what it was written to say.

Every claim here is one a visitor acts on: which years they can file, whether a
Tax Case will open, what the demo will cut them off at. A statement maintained by
hand goes stale the release after it is written, so these tests hold it to the
modules it claims to describe - add a tax year and the endpoint grows a year, turn
off the database and the mode closes, with nobody remembering to edit a paragraph.

No database and no provider: the route reads settings and the already-cached schema
answer, which is the whole point of it being able to report that either is missing.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import meta
from core.config import get_settings
from domain.tax_years import DEFAULT_TAX_YEAR, TAX_YEARS


@pytest.fixture
def client() -> TestClient:
    """The router alone, at the URL it carries with it.

    Not `main.app`: importing it drags in the graph, the vector store and a
    provider client, and none of them has anything to do with a statement made
    out of settings and constants. The prefix lives on the router, so the path
    exercised here is the path the application serves.
    """
    app = FastAPI()
    app.include_router(meta.router)
    return TestClient(app)


def scope(client: TestClient) -> dict:
    response = client.get("/api/v1/meta/scope")
    assert response.status_code == 200
    return response.json()


def mode(body: dict, mode_id: str) -> dict:
    return next(m for m in body["modes"] if m["id"] == mode_id)


def test_the_statement_is_public(client: TestClient) -> None:
    """A landing page asks this before anyone has logged in."""
    assert client.get("/api/v1/meta/scope").status_code == 200


def test_both_modes_are_named(client: TestClient) -> None:
    """The point of the ticket: two modes, neither of them implied."""
    ids = [m["id"] for m in scope(client)["modes"]]
    assert ids == ["chat", "tax_case"]


def test_only_the_tax_case_keeps_answers_on_the_server(client: TestClient) -> None:
    """The difference a visitor most needs before choosing a box to type in."""
    body = scope(client)
    assert mode(body, "chat")["storage"]["server"] == meta.SERVER_REQUEST_LOGS_ONLY
    assert mode(body, "chat")["requires_account"] is False
    assert mode(body, "tax_case")["storage"]["server"] == meta.SERVER_CASE_UNTIL_DELETED
    assert mode(body, "tax_case")["requires_account"] is True


def test_no_mode_answers_the_storage_question_with_one_word(client: TestClient) -> None:
    """The bug this replaced: `stores_data: false` read on screen as "keeps nothing".

    It was false for the chat because no Tax Case is written - while the browser was
    holding twenty conversations and replaying sixteen turns into the next request.
    A single boolean has nowhere to put that, so there is no longer a single boolean.
    """
    for entry in scope(client)["modes"]:
        assert "stores_data" not in entry
        assert set(entry["storage"]) == {"server", "profile_memory", "tracing"}
        assert all(entry["storage"].values()), "an unnamed store is an unanswered question"


def test_only_the_interview_remembers_the_person(client: TestClient) -> None:
    """Profile memory outlives a case, so the page may not fold it into the case."""
    body = scope(client)
    assert mode(body, "chat")["storage"]["profile_memory"] == meta.PROFILE_MEMORY_NONE
    assert (mode(body, "tax_case")["storage"]["profile_memory"]
            == meta.PROFILE_MEMORY_OUTLIVES_THE_CASE)


def test_an_untraced_instance_says_so(client: TestClient, monkeypatch) -> None:
    """No key means `core/tracing.py` sends nothing, and the statement agrees."""
    settings = get_settings()
    monkeypatch.setattr(settings, "langsmith_api_key", "", raising=False)

    for entry in scope(client)["modes"]:
        assert entry["storage"]["tracing"] == meta.TRACING_NONE


def test_the_traced_region_is_the_configured_one(client: TestClient, monkeypatch) -> None:
    """An empty endpoint is the SDK's US default, not "no region" - so it is not EU."""
    settings = get_settings()
    monkeypatch.setattr(settings, "langsmith_api_key", "ls-test", raising=False)

    monkeypatch.setattr(settings, "langsmith_endpoint",
                        "https://eu.api.smith.langchain.com", raising=False)
    assert mode(scope(client), "chat")["storage"]["tracing"] == meta.TRACING_LANGSMITH_EU

    monkeypatch.setattr(settings, "langsmith_endpoint", "", raising=False)
    assert mode(scope(client), "chat")["storage"]["tracing"] == meta.TRACING_LANGSMITH_US


def test_every_storage_answer_is_one_the_frontend_knows(client: TestClient) -> None:
    """An unrecognised id reaches the visitor as an id, same as an unknown reason."""
    known = {
        "server": {meta.SERVER_REQUEST_LOGS_ONLY, meta.SERVER_CASE_UNTIL_DELETED},
        "profile_memory": {meta.PROFILE_MEMORY_NONE,
                           meta.PROFILE_MEMORY_OUTLIVES_THE_CASE},
        "tracing": {meta.TRACING_NONE, meta.TRACING_LANGSMITH_EU,
                    meta.TRACING_LANGSMITH_US},
    }
    for entry in scope(client)["modes"]:
        for store, value in entry["storage"].items():
            assert value in known[store]


def test_an_available_mode_gives_no_reason(client: TestClient) -> None:
    """`reason` explains a closed door; an open one has nothing to explain."""
    for entry in scope(client)["modes"]:
        if entry["available"] and entry["reason"]:
            assert entry["reason"] == meta.SCHEMA_NOT_CHECKED


def test_a_closed_mode_always_says_why(client: TestClient) -> None:
    """Greying something out without a reason is the failure this ticket is about."""
    for entry in scope(client)["modes"]:
        if not entry["available"]:
            assert entry["reason"]


def test_every_reason_is_one_the_frontend_knows(client: TestClient) -> None:
    """An unrecognised code reaches the visitor as a code."""
    known = {
        meta.NO_PROVIDER_KEY,
        meta.DATABASE_NOT_CONFIGURED,
        meta.DATABASE_UNREACHABLE,
        meta.SCHEMA_DRIFT,
        meta.SCHEMA_NOT_CHECKED,
        "",
    }
    assert {m["reason"] for m in scope(client)["modes"]} <= known


def test_a_missing_database_closes_both_modes(client: TestClient, monkeypatch) -> None:
    """It used to close only the Tax Case, and since #32 it closes the chat too.

    The knowledge base left the deploy and moved into Postgres - which is what stopped
    every deploy rebuilding 775 embeddings - so a chat with no database has nothing to
    search. Said here rather than left to be discovered: this page exists to state what
    an instance can actually do.
    """
    monkeypatch.setattr(meta, "cached_status", lambda: None)
    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", "", raising=False)
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-test", raising=False)

    body = scope(client)
    assert mode(body, "chat")["available"] is False
    assert mode(body, "chat")["reason"] == meta.DATABASE_NOT_CONFIGURED
    assert mode(body, "tax_case")["available"] is False
    assert mode(body, "tax_case")["reason"] == meta.DATABASE_NOT_CONFIGURED


def test_a_missing_provider_key_closes_both(client: TestClient, monkeypatch) -> None:
    """Neither mode has anything to answer with; say so for both."""
    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "", raising=False)

    for entry in scope(client)["modes"]:
        assert entry["available"] is False
        assert entry["reason"] == meta.NO_PROVIDER_KEY


def test_schema_drift_closes_the_tax_case(client: TestClient, monkeypatch) -> None:
    """`require_schema` would 503 the interview; the statement must agree in advance."""
    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "database_url", "postgresql://host/db", raising=False)

    class Drifted:
        database = "ok"
        ok = False

    monkeypatch.setattr(meta, "cached_status", lambda: Drifted())

    entry = mode(scope(client), "tax_case")
    assert entry["available"] is False
    assert entry["reason"] == meta.SCHEMA_DRIFT


def test_an_unstarted_instance_does_not_claim_drift(client: TestClient, monkeypatch) -> None:
    """Before the startup check runs there is no answer yet, which is not a failure."""
    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "database_url", "postgresql://host/db", raising=False)
    monkeypatch.setattr(meta, "cached_status", lambda: None)

    entry = mode(scope(client), "tax_case")
    assert entry["available"] is True
    assert entry["reason"] == meta.SCHEMA_NOT_CHECKED


def test_the_years_are_the_years_with_rules(client: TestClient) -> None:
    """Adding a tax year must widen the statement without anyone editing prose."""
    body = scope(client)
    assert [y["year"] for y in body["tax_years"]] == sorted(TAX_YEARS)
    assert body["default_tax_year"] == DEFAULT_TAX_YEAR


def test_every_year_carries_its_filing_period(client: TestClient) -> None:
    """A year in scope is useless without the dates it may be filed in."""
    for year in scope(client)["tax_years"]:
        rules = TAX_YEARS[year["year"]]
        assert year["filing_due"] == rules.filing_due
        assert year["filing_due_advised"] == rules.filing_due_advised
        assert year["voluntary_filing_until"] == rules.voluntary_filing_until


def test_filing_dates_are_iso_and_in_order(client: TestClient) -> None:
    """A date the frontend cannot parse is a date the visitor never sees."""
    import datetime

    for year in scope(client)["tax_years"]:
        due = datetime.date.fromisoformat(year["filing_due"])
        advised = datetime.date.fromisoformat(year["filing_due_advised"])
        voluntary = datetime.date.fromisoformat(year["voluntary_filing_until"])
        assert due.year > year["year"]
        assert due < advised < voluntary


def test_the_forms_are_the_forms_the_year_places_figures_on(client: TestClient) -> None:
    """Claiming a form this build cannot fill is the exact overclaim under review."""
    for year in scope(client)["tax_years"]:
        rules = TAX_YEARS[year["year"]]
        expected = {line.form for line in rules.form_lines.values()}
        if rules.benefit_form_line is not None:
            expected.add(rules.benefit_form_line.form)
        assert {f["form"] for f in year["forms"]} == expected


def test_every_category_of_the_year_appears_on_some_form(client: TestClient) -> None:
    """A category with no sheet would be an expense the draft silently drops."""
    for year in scope(client)["tax_years"]:
        rules = TAX_YEARS[year["year"]]
        placed = {c for f in year["forms"] for c in f["categories"]}
        assert {c.value for c in rules.form_lines} <= placed


def test_an_unverified_line_marks_its_whole_form(client: TestClient) -> None:
    """The honest half of the claim: which sheet's line numbers are a best reading."""
    for year in scope(client)["tax_years"]:
        rules = TAX_YEARS[year["year"]]
        lines = list(rules.form_lines.values())
        if rules.benefit_form_line is not None:
            lines.append(rules.benefit_form_line)
        for form in year["forms"]:
            verified = all(l.verified for l in lines if l.form == form["form"])
            assert form["lines_verified"] is verified


def test_the_limits_are_the_limits_that_are_enforced(client: TestClient) -> None:
    """A demo ceiling on screen that differs from the one in force is a lie twice."""
    settings = get_settings()
    limits = scope(client)["limits"]
    assert limits["cases_per_user"] == settings.cases_per_user
    assert limits["interview_calls_per_user_per_day"] == settings.interview_calls_per_user_per_day
    assert limits["interview_calls_global_per_month"] == settings.interview_calls_global_per_month
    assert limits["document_reads_per_user_per_day"] == settings.document_reads_per_user_per_day
    assert limits["document_reads_global_per_month"] == settings.document_reads_global_per_month
    assert limits["document_confirmation_ttl_hours"] == settings.document_confirmation_ttl_hours


def test_the_refusals_are_named(client: TestClient) -> None:
    """The two a visitor is most likely to assume, and most harmed by assuming."""
    refused = scope(client)["not_supported"]
    assert "electronic_submission" in refused
    assert "tax_advice" in refused
    assert refused == list(meta.NOT_SUPPORTED)
