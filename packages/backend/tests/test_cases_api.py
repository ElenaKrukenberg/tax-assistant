"""The Tax Case API end to end, against the real database.

One test walks the whole product path through HTTP: create a case, answer the
interview question by question, confirm the stop proposal, approve the report,
watch the case finalize — and along the way checks the things the product
promises: answers land in the tables with their provenance the moment they are
given, a reconnect returns the same pause instead of advancing, and somebody
else's token sees nothing.

No LLM anywhere: the model dependencies are overridden with None, so the
Interviewer is the deterministic filter and the Reviewer is the rules-only pass.
What the models add is measured elsewhere (eval/); what this proves is that the
pipe they sit in holds water.
"""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest

from tests import dbguard
from fastapi import Request
from fastapi.testclient import TestClient

from agents import profile_memory
from agents.graph import build_graph, case_thread_id
from core import auth
from core.config import get_settings
from core.dependencies import get_llm_client, get_retriever, get_reviewer_client
from core.rate_limit import enforce_rate_limit
from db import cases
from db.connection import as_owner
from domain.fields import FieldValue, Provenance
from domain.positions import AssessmentStatus, UserDecision, assess_positions
from domain.tax_years import for_year
from eval.baseline import load_profiles
from main import app

pytestmark = pytest.mark.integration

settings = get_settings()
USER = dbguard.require_test_database()
STRANGER = str(uuid.uuid4())
# The API refuses a year it has no rules for, so unlike the repository tests this
# suite has to use the real one — the fixture deletes the case afterwards, and the
# dedicated TEST_USER exists for exactly this.
YEAR = 2025

P03 = next(p for p in load_profiles() if p.id.startswith("p03"))


@pytest.fixture
def client():
    # The graph runs without models: chats of None mean the filter interviews and
    # the rules review. Auth is replaced by a header-named user so one suite can
    # act as two people without minting real tokens.
    app.dependency_overrides[get_llm_client] = lambda: None
    app.dependency_overrides[get_reviewer_client] = lambda: None
    # Explicit, so the isolation is visible rather than inherited: with no model
    # there are no Gap candidates to justify, so nothing asks the retriever anything.
    # These overrides only started taking effect once the routes declared the three
    # with `Depends` - a plain call to the factory goes straight past
    # `app.dependency_overrides`, which is why this suite spent months making real
    # provider calls while claiming to make none.
    app.dependency_overrides[get_retriever] = lambda: None

    async def user_from_header(request: Request):
        # The annotation is load-bearing: unannotated, FastAPI reads `request` as a
        # required query parameter and every route 422s before it is reached.
        return request.headers.get("x-test-user", USER)

    app.dependency_overrides[auth.current_user] = user_from_header
    # The per-IP limit is 10/minute and a full interview is ~16 calls from one
    # client. The limiter has its own suite (test_rate_limit.py); here it is off.
    app.dependency_overrides[enforce_rate_limit] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def case_id(client):
    case = client.post("/api/v1/cases", json={"tax_year": YEAR}).json()
    yield case["id"]
    # Through the API on purpose, not `cases.delete_case`: the repository clears the
    # tables only, so a teardown that called it directly left this suite's own
    # checkpoints behind - orphaned graph state holding the answers these tests just
    # gave. It also runs in the app's event loop, which is where the async pool the
    # checkpointer uses was opened.
    client.delete(f"/api/v1/cases/{case['id']}")


def approve_everything(pause: dict) -> dict:
    """The resume value the final gate now takes: approve, plus a decision each.

    A bare `True` used to be enough. Since Tax Positions, the gate refuses to
    finalize while any position is still undecided (`final_approval` in
    `agents/graph.py`), so the answer has to say what the user decided about each
    one - the authority rule the table exists to enforce, not a formality to route
    around.

    The decision is not the same for every position, and that asymmetry is the
    domain's, not this helper's. Only an identified position may be accepted -
    `TaxPosition.decide` refuses anything else - so an unclear one is rejected here,
    and one whose criteria were not met needs no decision at all: the gate already
    treats it as settled.
    """
    decisions = {}
    for position in pause.get("tax_positions") or []:
        status = position.get("assessment_status")
        if status == AssessmentStatus.identified.value:
            decisions[position["position_id"]] = UserDecision.accepted.value
        elif status == AssessmentStatus.unclear.value:
            decisions[position["position_id"]] = UserDecision.rejected.value
    return {"approve": True, "decisions": decisions}


def advance(client, case_id, resume=None, expect=200):
    response = client.post(f"/api/v1/cases/{case_id}/interview",
                           json={"resume": resume})
    assert response.status_code == expect, response.text
    return response.json()


def test_the_whole_path_from_creation_to_finalized(client, case_id):
    # The interview starts by itself and pauses on the first question.
    step = advance(client, case_id)
    assert step["pause"]["type"] == "question"
    assert step["pause"]["question_id"] == "profile.employed_months"

    # A reconnect without a resume returns the same pause, it does not advance:
    # refreshing the page must never eat a question.
    again = advance(client, case_id)
    assert again["pause"]["question_id"] == step["pause"]["question_id"]

    # Answer everything from the profile until the stop proposal.
    for _ in range(40):
        if step["pause"]["type"] != "question":
            break
        value = P03.answers.get(step["pause"]["field"])
        step = advance(client, case_id, resume={"value": value})
    assert step["pause"]["type"] == "confirm_stop"

    # By now every answer is already in the tables, with its provenance.
    detail = client.get(f"/api/v1/cases/{case_id}").json()
    field = detail["fields"]["commute.distance_km"]
    assert field["value"] == 4
    assert field["provenance"] == "answer"

    # Confirm the stop; p03 reviews clean of blocking findings, so the next pause
    # is the final gate, expenses attached, each with its trace.
    step = advance(client, case_id, resume=True)
    assert step["pause"]["type"] == "final_approval"
    expense = step["pause"]["expenses"][0]
    assert expense["category"] == "entfernungspauschale"
    assert expense["amount_eur"] == 252.0
    assert expense["trace"], "a figure travels with how it was computed"

    # Approve: the case finalizes, and the tables agree.
    step = advance(client, case_id, resume=approve_everything(step["pause"]))
    assert step["done"] is True
    assert step["status"] == "finalized"
    assert cases.get_case(USER, case_id).status == "finalized"

    # A finalized case refuses further *answers*, and says so. Merely reconnecting
    # gets the finished state back instead, because revisiting the Interview tab on a
    # finished case is not an error — see the dedicated test below.
    advance(client, case_id, resume={"value": 1}, expect=409)
    assert advance(client, case_id)["done"] is True

    # The Reviewer's judgement outlived the run it was made in. p03 reviews clean of
    # *blocking* findings — that is what let the walk reach the final gate — but the
    # rules-only pass does raise warnings, and those are the record.
    detail = client.get(f"/api/v1/cases/{case_id}").json()
    assert detail["findings"], "the review left no record"
    assert not [f for f in detail["findings"] if f["severity"] == "blocking"]
    assert all(f["title"] and f["resolution"] == "open" for f in detail["findings"])


def test_a_strangers_token_sees_no_case(client, case_id):
    headers = {"x-test-user": STRANGER}
    assert client.get("/api/v1/cases", headers=headers).json() == []
    assert client.get(f"/api/v1/cases/{case_id}", headers=headers).status_code == 404
    assert client.delete(f"/api/v1/cases/{case_id}", headers=headers).status_code == 404


# The three tables the checkpointer keeps for itself, and the five that hang off a
# case. Named rather than discovered, so a table added by a library upgrade shows up
# as a failing assertion here instead of quietly going unchecked.
CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
CASE_CHILD_TABLES = ("field_values", "documents", "expenses", "answers", "findings")


def checkpoint_rows(thread_id: str) -> dict[str, int]:
    """How much of a paused run is physically left.

    `as_owner`, because these are the library's tables: they carry no row level
    security and are not reachable as the user. Counting rows rather than asking the
    graph for its state is the point - `aget_state` returning nothing would also be
    true of a checkpoint whose blobs and pending writes were still sitting there.
    """
    with as_owner() as cur:
        counts = {}
        for table in CHECKPOINT_TABLES:  # fixed names, never user input
            cur.execute(f"select count(*) from {table} where thread_id = %s", (thread_id,))
            counts[table] = cur.fetchone()[0]
        return counts


def case_rows(case_id: str) -> dict[str, int]:
    """How much of a case is physically left, table by table."""
    with as_owner() as cur:
        counts = {}
        cur.execute("select count(*) from tax_cases where id = %s", (case_id,))
        counts["tax_cases"] = cur.fetchone()[0]
        for table in CASE_CHILD_TABLES:
            cur.execute(f"select count(*) from {table} where case_id = %s", (case_id,))
            counts[table] = cur.fetchone()[0]
        return counts


def remembered(key: str):
    """Read the profile store on a connection of its own.

    `profile_memory.store()` runs on the pool the app opened in its own event loop;
    this opens its own so a synchronous test can look, which is exactly what
    `postgres_store()` is kept for.
    """
    async def go():
        async with profile_memory.postgres_store() as store:
            await store.setup()
            item = await store.aget(profile_memory.namespace(USER), key)
            return None if item is None else item.value

    return asyncio.run(go())


def remember(key: str, value) -> None:
    async def go():
        async with profile_memory.postgres_store() as store:
            await store.setup()
            await store.aput(profile_memory.namespace(USER), key,
                             {"value": value, "tax_year": YEAR})

    asyncio.run(go())


def forget(key: str) -> None:
    async def go():
        async with profile_memory.postgres_store() as store:
            await store.adelete(profile_memory.namespace(USER), key)

    asyncio.run(go())


def test_deleting_a_case_empties_both_stores_that_hold_the_answers(client, case_id):
    """The promise the confirmation dialog makes, checked against the rows.

    Before this, the route cleared the tables and left the paused run behind holding
    the same answers, and said 204 anyway.
    """
    step = advance(client, case_id)
    for _ in range(6):
        if step["pause"]["type"] != "question":
            break
        value = P03.answers.get(step["pause"]["field"])
        step = advance(client, case_id, resume={"value": value})

    thread = case_thread_id(USER, case_id)
    assert checkpoint_rows(thread)["checkpoints"] > 0, "no run to delete; test is void"
    assert case_rows(case_id)["field_values"] > 0, "no answers stored; test is void"

    assert client.delete(f"/api/v1/cases/{case_id}").status_code == 204

    assert checkpoint_rows(thread) == dict.fromkeys(CHECKPOINT_TABLES, 0)
    assert case_rows(case_id) == {"tax_cases": 0,
                                  **dict.fromkeys(CASE_CHILD_TABLES, 0)}

    # And it stays gone: a later request must not quietly rebuild the run.
    assert client.post(f"/api/v1/cases/{case_id}/interview",
                       json={"resume": None}).status_code == 404
    assert checkpoint_rows(thread) == dict.fromkeys(CHECKPOINT_TABLES, 0)


def test_deleting_a_case_keeps_what_we_remember_about_the_person(client, case_id):
    """Profile memory outlives the case on purpose (ADR 0011).

    Deleting a case and forgetting a person are separate choices, and the second one
    does not exist yet (#23). If this ever fails, someone made the delete tidier than
    the product promises.
    """
    key = "commute.distance_km"
    sentinel = 4242
    remember(key, sentinel)
    try:
        assert client.delete(f"/api/v1/cases/{case_id}").status_code == 204
        assert (remembered(key) or {}).get("value") == sentinel
    finally:
        forget(key)


def test_forgetting_the_person_empties_the_store_and_leaves_the_case(client, case_id):
    """The counterpart of the test above, and the reason both exist.

    Deleting a case keeps the profile memory; forgetting the person keeps the case.
    Two operations, neither implying the other (ADR 0011).
    """
    key = "commute.distance_km"
    remember(key, 4242)
    assert (remembered(key) or {}).get("value") == 4242

    assert client.delete("/api/v1/profile/memory").status_code == 204

    assert remembered(key) is None
    assert case_rows(case_id)["tax_cases"] == 1


def test_forgetting_a_person_with_nothing_remembered_still_succeeds(client):
    assert client.delete("/api/v1/profile/memory",
                         headers={"x-test-user": STRANGER}).status_code == 204


def test_deleting_a_case_that_is_already_gone_is_a_404(client, case_id):
    assert client.delete(f"/api/v1/cases/{case_id}").status_code == 204
    assert client.delete(f"/api/v1/cases/{case_id}").status_code == 404


def test_a_finalized_case_can_still_be_deleted(client, case_id):
    """Read-only is not undeletable: approving a report must not trap the data."""
    step = advance(client, case_id)
    for _ in range(40):
        if step["pause"]["type"] != "question":
            break
        step = advance(client, case_id,
                       resume={"value": P03.answers.get(step["pause"]["field"])})
    step = advance(client, case_id, resume=True)          # confirm the stop
    advance(client, case_id, resume=approve_everything(step["pause"]))
    assert cases.get_case(USER, case_id).status == "finalized"

    assert client.delete(f"/api/v1/cases/{case_id}").status_code == 204
    assert case_rows(case_id)["tax_cases"] == 0


def test_delete_all_takes_every_case_of_this_user_and_no_other(client, case_id):
    """The collection endpoint, over more than one case.

    The second case is made through the repository rather than the API: only 2025 has
    rules, and the API refuses any other year, so two cases cannot be created over
    HTTP by one user.
    """
    advance(client, case_id)                       # gives the first case a checkpoint
    second = cases.create_case(USER, 2091)
    threads = [case_thread_id(USER, case_id), case_thread_id(USER, second.id)]
    assert checkpoint_rows(threads[0])["checkpoints"] > 0

    assert client.delete("/api/v1/cases").status_code == 204

    assert client.get("/api/v1/cases").json() == []
    for case in (case_id, second.id):
        assert case_rows(case)["tax_cases"] == 0
    for thread in threads:
        assert checkpoint_rows(thread) == dict.fromkeys(CHECKPOINT_TABLES, 0)


def test_delete_all_with_a_strangers_token_leaves_this_user_alone(client, case_id):
    assert client.delete("/api/v1/cases",
                         headers={"x-test-user": STRANGER}).status_code == 204
    assert case_rows(case_id)["tax_cases"] == 1, "another user's delete-all reached in"


def test_a_year_without_rules_is_refused_with_the_years_we_have(client):
    response = client.post("/api/v1/cases", json={"tax_year": 2026})
    assert response.status_code == 422
    assert "2025" in response.json()["detail"]


def test_creating_the_same_year_twice_returns_the_same_case(client, case_id):
    second = client.post("/api/v1/cases", json={"tax_year": YEAR}).json()
    assert second["id"] == case_id


def test_without_auth_override_the_routes_demand_a_token(case_id):
    # A clean client, no overrides: the real dependency answers.
    app.dependency_overrides.pop(auth.current_user, None)
    with TestClient(app) as c:
        assert c.get("/api/v1/cases").status_code == 401


def test_the_stream_endpoint_tells_the_nodes_and_ends_with_the_same_result(client, case_id):
    """SSE: node events first, one result event last, same shape as the plain POST.

    The two endpoints share one generator, so this guards the transport, not the
    logic: events parse as JSON lines, the crossed nodes are real graph nodes, and
    the result equals what a plain reconnect then reports.
    """
    import json as _json

    with client.stream("POST", f"/api/v1/cases/{case_id}/interview/stream",
                       json={"resume": None}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(_json.loads(line[6:]))

    kinds = [e["type"] for e in events]
    assert kinds[-1] == "result"
    assert set(kinds[:-1]) == {"node"} or kinds[:-1] == []
    crossed = [e["node"] for e in events if e["type"] == "node"]
    assert "decide_next" in crossed, "the first advance crosses the decision node"

    result = events[-1]
    assert result["pause"]["type"] == "question"

    # A plain reconnect sees the same pending pause the stream left behind.
    again = advance(client, case_id)
    assert again["pause"]["question_id"] == result["pause"]["question_id"]


# --- the filled Anlage N, over HTTP --------------------------------------------------

def seed_commute(case_id: str) -> None:
    """A case with a commute in it, written the way an answered interview would.

    Fields alone stopped being enough once the form was drawn from Tax Positions
    rather than from raw fields: `download_anlage_n` refuses a case with no position
    that is identified, accepted, and still standing on current facts. So this runs
    the real assessment over the fields it just wrote and accepts what it finds,
    rather than hand-building a position - a fixture that constructs its own would
    stop resembling what the graph actually produces the moment the assessment
    changes.
    """
    facts = {}
    for key, value in (("profile.employed_months", 12),
                       ("profile.works_remotely", False),
                       ("commute.commuting_days", 210),
                       ("commute.distance_km", 42),
                       ("commute.own_car", True)):
        cases.set_field(USER, case_id, key, FieldValue(value, Provenance.answer, "seed"))
        facts[key] = value

    positions = assess_positions(facts, for_year(YEAR))
    commute = next(p for p in positions if p.category == "entfernungspauschale")
    assert commute.assessment_status is AssessmentStatus.identified, (
        "the fixture no longer describes a deductible commute")
    commute.decide(UserDecision.accepted)
    cases.save_positions(USER, case_id, positions)


def test_a_case_with_no_figures_is_refused_a_form_rather_than_given_an_empty_one(
        client, case_id):
    response = client.get(f"/api/v1/cases/{case_id}/anlage-n.pdf")
    assert response.status_code == 409
    assert "Anlage N" in response.json()["detail"]


def test_the_form_comes_back_as_a_pdf_with_the_case_in_it(client, case_id):
    seed_commute(case_id)
    response = client.get(f"/api/v1/cases/{case_id}/anlage-n.pdf")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert 'filename="anlage-n-2025-draft.pdf"' in response.headers["content-disposition"]
    assert response.headers["x-unplaced-count"] == "0"

    from pypdf import PdfReader
    text = "".join(page.extract_text()
                   for page in PdfReader(io.BytesIO(response.content)).pages)
    assert "210" in text and "42" in text        # the days and the distance
    assert "ENTWURF" in text                     # and it says it is a draft


def test_a_value_nobody_has_confirmed_stops_the_form_the_way_it_stops_the_report(
        client, case_id):
    """The same gate as finalize (ADR 0010): a tax document may not carry a guess."""
    seed_commute(case_id)
    cases.set_field(USER, case_id, "equipment.useful_life_years",
                    FieldValue(3, Provenance.assumed, "three years is usual"))

    response = client.get(f"/api/v1/cases/{case_id}/anlage-n.pdf")
    assert response.status_code == 409
    assert "unconfirmed" in response.json()["detail"]


def test_a_strangers_token_cannot_download_the_form(client, case_id):
    seed_commute(case_id)
    response = client.get(f"/api/v1/cases/{case_id}/anlage-n.pdf",
                          headers={"x-test-user": STRANGER})
    assert response.status_code == 404


def test_reopening_the_interview_on_a_finished_case_says_it_is_over(client, case_id):
    """A finished interview is a state, not an error.

    The Interview tab used to render the database's own refusal — "the case is
    finalized; reopen it first" — as a red error box, which is a sentence about the
    tables shown to somebody who only revisited a tab.
    """
    cases.finalize(USER, case_id)

    reconnect = client.post(f"/api/v1/cases/{case_id}/interview", json={})
    assert reconnect.status_code == 200
    body = reconnect.json()
    assert body["done"] is True
    assert body["pause"] is None
    assert body["status"] == "finalized"

    # Answering one is still refused: read-only means read-only.
    answered = client.post(f"/api/v1/cases/{case_id}/interview",
                           json={"resume": {"value": 12}})
    assert answered.status_code == 409


def test_a_finalized_case_can_be_reopened_and_answers_questions_again(client, case_id):
    """The way back out of a finished return, which the product did not have.

    Approving locks the case, and the lock is real: a position declined by mistake
    could not be reconsidered, and the API's own "reopen it first" named a door with
    nothing behind it. Reopening lifts the lock and deletes the finished run, so the
    next advance rebuilds the interview from the tables rather than resuming a graph
    that has already ended.
    """
    cases.set_field(USER, case_id, "commute.distance_km",
                    FieldValue(12, Provenance.answer, "seed", confirmed=True))
    cases.finalize(USER, case_id)
    assert client.post(f"/api/v1/cases/{case_id}/interview",
                       json={"resume": {"value": 12}}).status_code == 409

    reopened = client.post(f"/api/v1/cases/{case_id}/reopen")
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "gathering"
    assert cases.get_case(USER, case_id).status == "gathering"

    # The interview runs again, and what the tables already hold is not re-asked.
    step = client.post(f"/api/v1/cases/{case_id}/interview", json={}).json()
    assert step["done"] is False
    assert step["pause"] is not None
    assert step["pause"].get("question", {}).get("id") != "commute.distance_km"


def test_reopening_a_case_that_is_not_finalized_changes_nothing(client, case_id):
    """Two tabs, one button. The second click is not an error worth an alarm."""
    before = cases.get_case(USER, case_id).status

    response = client.post(f"/api/v1/cases/{case_id}/reopen")

    assert response.status_code == 200
    assert response.json()["status"] == before
    assert cases.get_case(USER, case_id).status == before


def test_a_strangers_token_cannot_reopen_this_case(client, case_id):
    cases.finalize(USER, case_id)

    refused = client.post(f"/api/v1/cases/{case_id}/reopen",
                          headers={"x-test-user": STRANGER})

    assert refused.status_code == 404
    assert cases.get_case(USER, case_id).status == "finalized"


def test_the_case_detail_carries_what_the_reviewer_raised(client, case_id):
    cases.save_findings(USER, case_id, [
        {"severity": "warning", "title": "Commuting days look high",
         "reasoning": "230 days against 11 employed months.",
         "category": "entfernungspauschale"},
    ])

    detail = client.get(f"/api/v1/cases/{case_id}").json()
    assert [f["title"] for f in detail["findings"]] == ["Commuting days look high"]
    assert detail["findings"][0]["category"] == "entfernungspauschale"
    assert detail["findings"][0]["resolution"] == "open"


def test_an_answer_with_no_question_pending_is_refused_before_it_costs_anything(
    client, case_id, monkeypatch
):
    """A resume with no pause to answer: 422, and nothing done on the way there.

    This case has never been advanced, so the graph holds no checkpoint and there is
    no pending question. The route used to read that as "start a fresh run", which
    skipped validation entirely - `validate_resume` is only reached with a pause in
    hand - and spent an interview call on a payload nobody had asked for. A tab left
    open across a cleared checkpoint sends exactly this.

    Each of the four things that must not happen is asserted, because the refusal is
    worth only as much as what it stops.
    """
    import api.routes.cases as route

    spent = []
    monkeypatch.setattr(route, "spend_interview_call",
                        lambda *a, **k: spent.append(a))

    started = []

    def no_run(*args, **kwargs):
        graph = build_graph(*args, **kwargs)

        class Guarded:
            # aget_state is how the route finds out there is no pause, so it has to
            # work; astream is the run itself, and reaching it is the bug.
            def __getattr__(self, name):
                return getattr(graph, name)

            def astream(self, *a, **k):
                started.append(a)
                raise AssertionError("the graph was started for an unanswerable resume")

        return Guarded()

    monkeypatch.setattr(route, "build_graph", no_run)

    response = client.post(f"/api/v1/cases/{case_id}/interview",
                           json={"resume": {"value": 220}})

    assert response.status_code == 422, response.text
    assert not spent, "a refused answer must not spend an interview call"
    assert not started, "a refused answer must not start the graph"
    assert cases.get_fields(USER, case_id) == {}, "a refused answer must not be stored"


def test_a_reloaded_case_gets_its_form_lines_formulas_and_documents_back(
    client, case_id
):
    """The bug #17 opened on: a case read back from the tables lost its Trace.

    `save_positions` wrote thirteen columns and none of them were `form_line`,
    `trace` or `documents`, while `GET /cases/{id}` built every expense row out of
    exactly those three. So the figures survived a reload and everything beside them
    - which line of Anlage N, how the number was reached, which document it came from
    - came back empty. It was invisible during a live interview, where the rows come
    from the graph rather than from the table.

    Written through the repository rather than through the interview so the test
    fails for one reason: what a save-then-read does to a position.
    """
    values = {
        "equipment.price_eur": FieldValue(689.0, Provenance.document,
                                          source="invoice-1", confirmed=True),
        "equipment.purchase_month": FieldValue(9, Provenance.document,
                                               source="invoice-1", confirmed=True),
        "equipment.price_is_net": FieldValue(False, Provenance.answer, source="q"),
        "equipment.is_digital": FieldValue(False, Provenance.answer, source="q"),
        "equipment.useful_life_years": FieldValue(3, Provenance.answer, source="q"),
        "equipment.professional_share_pct": FieldValue(100, Provenance.answer,
                                                       source="q"),
    }
    for key, held in values.items():
        cases.set_field(USER, case_id, key, held)
    facts = {key: held.value for key, held in values.items()}
    positions = assess_positions(facts, for_year(YEAR), values)
    cases.save_positions(USER, case_id, positions)
    for position in positions:
        if position.assessment_status is AssessmentStatus.identified:
            cases.decide_position(USER, case_id, position.position_id, "accepted")

    detail = client.get(f"/api/v1/cases/{case_id}").json()
    row = next(e for e in detail["expenses"] if e["category"] == "arbeitsmittel")

    assert row["form_line"], "the form line came back empty from a reloaded case"
    assert row["trace"], "the formula came back empty from a reloaded case"
    assert row["documents"] == ["invoice-1"]
