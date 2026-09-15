"""The Documents API end to end, against the real database.

No provider: `get_vision_client` is overridden with a scripted reader, so what these
tests exercise is the pipe - the raw-body upload, the case lock, the idempotency key,
the provenance each confirmed value lands with, and the intake thread being gone
afterwards. How well a model reads a document is measured in `eval/vision_sweep`,
not here.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from core import auth
from core.config import get_settings
from core.dependencies import get_vision_client, get_vision_fallback_client
from core.rate_limit import enforce_rate_limit
from db import cases
from main import app
from tests import dbguard
from workflows.document_intake import intake_thread_id

pytestmark = pytest.mark.integration

USER = dbguard.require_test_database()
STRANGER = str(uuid.uuid4())
YEAR = 2025

JPEG = b"\xff\xd8\xff" + b"\x00" * 2048

INVOICE = {
    "document_type": "rechnung",
    "price_basis": "net",
    "invoice_date": "2025-09-08",
    "net_total_eur": 781.50,
    "vat_rate_percent": 19.0,
    "vat_amount_eur": 148.49,
    "gross_total_eur": 929.99,
    "line_items": [
        {"description": "Schreibtisch Ergoline", "quantity": 1, "unit_price_eur": 689.00},
        {"description": "Monitorarm Duo", "quantity": 2, "unit_price_eur": 46.25},
    ],
}


# Nothing on it names a category the rules know, which is the case the user has to
# settle: `by_rules` refuses to guess rather than putting the money somewhere.
UNPLACEABLE = dict(
    INVOICE,
    net_total_eur=240.0, vat_amount_eur=45.6, gross_total_eur=285.6,
    line_items=[{"description": "Jahresbeitrag", "quantity": 1, "unit_price_eur": 240.0}],
)


class ScriptedVision:
    """Stands in for the vision model: what pass one and pass two returned."""

    def __init__(self, first: dict, second: dict | None = None,
                 model: str = "google/gemini-3.7-flash"):
        self.first = first
        self.second = second if second is not None else first
        self.calls = 0
        self.model = model
        # Set to an exception to make the provider refuse, as an outage does.
        self.fails: Exception | None = None

    async def read_document(self, **kwargs):
        if self.fails is not None:
            raise self.fails
        self.calls += 1
        payload = self.first if self.calls % 2 else self.second
        return json.dumps(payload), {"prompt_tokens": 3200, "completion_tokens": 300}


@pytest.fixture
def vision():
    """Both vision clients, because the route now takes both.

    The fallback is a fake for the same reason the primary is: `conftest.py` refuses
    to let any test build a real provider client, and a dependency nobody overrode is
    a real one. It answers the same invoice under a different model name, so a test
    that makes the primary fail can tell which of the two produced the values.
    """
    scripted = ScriptedVision(INVOICE)
    scripted.fallback = ScriptedVision(INVOICE, model="x-ai/grok-4.5")
    app.dependency_overrides[get_vision_client] = lambda: scripted
    app.dependency_overrides[get_vision_fallback_client] = lambda: scripted.fallback
    yield scripted


@pytest.fixture
def budget():
    """The upload quota, off for the suite.

    Not a convenience: `usage_counters` lives in the database and survives the run,
    so a suite that spends the real budget passes the first time and fails the third
    - which is exactly what it did (20 uploads a day, and this file makes 13 of
    them). The limits have their own coverage; here they are set to 0, which
    `spend_document_read` treats as "no limit" and skips the counter entirely.
    """
    settings = get_settings()
    kept = (settings.document_reads_per_user_per_day,
            settings.document_reads_global_per_month)
    settings.document_reads_per_user_per_day = 0
    settings.document_reads_global_per_month = 0
    yield
    (settings.document_reads_per_user_per_day,
     settings.document_reads_global_per_month) = kept


@pytest.fixture
def client(vision, budget):
    async def user_from_header(request: Request):
        return request.headers.get("x-test-user", USER)

    app.dependency_overrides[auth.current_user] = user_from_header
    app.dependency_overrides[enforce_rate_limit] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def case_id(client):
    case = client.post("/api/v1/cases", json={"tax_year": YEAR}).json()
    yield case["id"]
    client.delete(f"/api/v1/cases/{case['id']}")


def upload(client, case_id, *, data=JPEG, kind="rechnung", name="rechnung.jpg",
           key=None, user=None):
    headers = {"Content-Type": "image/jpeg"}
    if key:
        headers["Idempotency-Key"] = key
    if user:
        headers["x-test-user"] = user
    return client.post(
        f"/api/v1/cases/{case_id}/documents",
        params={"kind": kind, "file_name": name},
        content=data,
        headers=headers,
    )


def test_an_upload_is_read_twice_and_waits_for_the_user(client, case_id, vision):
    response = upload(client, case_id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["state"] == "awaiting_confirmation"
    assert vision.calls == 2, "two independent passes, not one"
    assert body["category"] == "arbeitsmittel"
    assert "schreibtisch" in body["category_reason"]
    assert body["disagreements"] == []

    proposed = {item["key"]: item["value"] for item in body["proposed"]}
    assert proposed["equipment.price_eur"] == 689.0
    assert proposed["equipment.price_eur#2"] == 46.25

    # And nothing is in the case yet.
    assert cases.get_fields(USER, case_id) == {}


def test_a_reloaded_screen_still_has_the_values_to_confirm(client, case_id, vision):
    """The failure this guards: a card with a Confirm button and nothing to confirm.

    The proposed values live in the paused run, never in `documents`, so a screen
    that is reopened rather than uploaded to has to be told them again. Before this
    the list answered with an empty proposal, and the only thing a returning user
    could do with their own upload was discard it.
    """
    uploaded = upload(client, case_id).json()

    listed = client.get(f"/api/v1/cases/{case_id}/documents").json()
    assert len(listed) == 1
    reloaded = listed[0]

    assert reloaded["state"] == "awaiting_confirmation"
    assert reloaded["proposed"] == uploaded["proposed"]
    assert reloaded["category"] == uploaded["category"]
    assert reloaded["category_reason"] == uploaded["category_reason"]
    assert reloaded["category_choices"] == uploaded["category_choices"]
    assert vision.calls == 2, "reading the list must not re-read the document"

    # And it is still confirmable from what the list alone said.
    confirmed = client.post(
        f"/api/v1/cases/{case_id}/documents/{reloaded['id']}/confirm",
        json={"values": {item["key"]: item["value"] for item in reloaded["proposed"]}},
    )
    assert confirmed.status_code == 200, confirmed.text


def test_a_settled_document_offers_nothing_to_confirm(client, case_id):
    """The other half: once decided, the pause is gone and the list says nothing."""
    body = upload(client, case_id).json()
    client.post(f"/api/v1/cases/{case_id}/documents/{body['id']}/discard")

    listed = client.get(f"/api/v1/cases/{case_id}/documents").json()
    assert listed[0]["state"] == "discarded"
    assert listed[0]["proposed"] == []
    assert listed[0]["category_choices"] == []


def test_one_document_can_be_fetched_on_its_own(client, case_id, vision):
    uploaded = upload(client, case_id).json()

    fetched = client.get(f"/api/v1/cases/{case_id}/documents/{uploaded['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == uploaded
    assert vision.calls == 2

    missing = client.get(f"/api/v1/cases/{case_id}/documents/{uuid.uuid4()}")
    assert missing.status_code == 404

    stranger = client.get(f"/api/v1/cases/{case_id}/documents/{uploaded['id']}",
                          headers={"x-test-user": STRANGER})
    assert stranger.status_code == 404


def test_confirming_writes_the_values_with_honest_provenance(client, case_id):
    body = upload(client, case_id).json()
    document_id = body["id"]
    proposed = {item["key"]: item["value"] for item in body["proposed"]}

    # One value left as read, one corrected by hand.
    values = dict(proposed)
    values["equipment.price_eur"] = 1032.00

    confirmed = client.post(
        f"/api/v1/cases/{case_id}/documents/{document_id}/confirm",
        json={"values": values},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["state"] == "confirmed"

    fields = cases.get_fields(USER, case_id)
    corrected = fields["equipment.price_eur"]
    untouched = fields["equipment.price_eur#1"]

    assert corrected.value == 1032.00
    assert corrected.provenance.value == "answer", "a corrected value is not a document value"
    assert "corrected by the user" in corrected.source

    assert untouched.value == 46.25
    assert untouched.provenance.value == "document"
    assert untouched.source == document_id


def test_the_intake_thread_is_gone_once_the_document_is_settled(client, case_id):
    """The two readings live in the checkpoint, so settling has to clear it."""
    from agents.graph import checkpointer

    body = upload(client, case_id).json()
    document_id = body["id"]
    values = {item["key"]: item["value"] for item in body["proposed"]}

    client.post(f"/api/v1/cases/{case_id}/documents/{document_id}/confirm",
                json={"values": values})

    async def remaining():
        saver = await checkpointer()
        config = {"configurable": {"thread_id": intake_thread_id(USER, case_id, document_id)}}
        return [c async for c in saver.alist(config)]

    import asyncio

    assert asyncio.run(remaining()) == []


def test_discarding_writes_nothing_and_says_so(client, case_id):
    document_id = upload(client, case_id).json()["id"]
    discarded = client.post(f"/api/v1/cases/{case_id}/documents/{document_id}/discard")

    assert discarded.status_code == 200
    assert discarded.json()["state"] == "discarded"
    assert cases.get_fields(USER, case_id) == {}
    # The row stays: the case can still say an upload was made and rejected.
    assert [d["id"] for d in client.get(f"/api/v1/cases/{case_id}/documents").json()] == [
        document_id
    ]


def test_a_retried_upload_is_not_a_second_document_or_a_second_pair_of_calls(client, case_id, vision):
    first = upload(client, case_id, key="upload-1")
    second = upload(client, case_id, key="upload-1")

    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert vision.calls == 2, "the retry must not pay to read the same page again"
    assert second.json()["state"] == "awaiting_confirmation"
    assert second.json()["proposed"], "the retry answers with the first read's proposal"


def test_a_file_too_large_is_refused_while_it_is_read(client, case_id, vision):
    from services.documents.intake import MAX_BYTES

    response = upload(client, case_id, data=b"\xff\xd8\xff" + b"\x00" * MAX_BYTES)
    assert response.status_code == 413
    assert vision.calls == 0


def test_an_unsupported_kind_never_reaches_a_model(client, case_id, vision):
    response = upload(client, case_id, kind="arztrechnung")
    assert response.status_code == 400
    assert vision.calls == 0
    assert cases.list_documents(USER, case_id) == []


def test_an_invoice_the_rules_cannot_place_is_categorised_by_the_user(client, case_id, vision):
    """The whole path for an invoice no word rule can place: ask, choose, confirm.

    Before the category endpoint this was a dead end - the screen said "choose it
    yourself" and offered nowhere to do it, and the document could only be discarded.
    """
    vision.first = vision.second = UNPLACEABLE
    uploaded = upload(client, case_id).json()

    assert uploaded["category"] is None
    assert uploaded["proposed"] == []
    assert uploaded["category_choices"] == [
        "arbeitsmittel", "fortbildungskosten", "umzugskosten", "bewerbungskosten",
    ]

    chosen = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/category",
        json={"category": "fortbildungskosten"},
    )
    assert chosen.status_code == 200, chosen.text
    body = chosen.json()
    assert body["state"] == "awaiting_confirmation"
    assert body["category"] == "fortbildungskosten"
    assert {item["key"]: item["value"] for item in body["proposed"]} == {
        "education.amount_eur": 240.0
    }
    assert vision.calls == 2, "choosing a category must not re-read the document"
    # Still only a proposal: choosing writes nothing into the case.
    assert cases.get_fields(USER, case_id) == {}

    confirmed = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/confirm",
        json={"values": {"education.amount_eur": 240.0},
              "category": "fortbildungskosten"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert cases.get_fields(USER, case_id)["education.amount_eur"].value == 240.0


def test_choosing_a_category_re_keys_what_the_rules_had_proposed(client, case_id):
    """The rules said Arbeitsmittel; the user disagrees, and the keys follow."""
    uploaded = upload(client, case_id).json()
    assert uploaded["category"] == "arbeitsmittel"

    body = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/category",
        json={"category": "fortbildungskosten"},
    ).json()

    keys = {item["key"] for item in body["proposed"]}
    assert keys == {"education.amount_eur"}
    assert not any(key.startswith("equipment.") for key in keys)


def test_a_category_no_case_can_hold_is_refused_and_costs_the_document_nothing(client, case_id):
    uploaded = upload(client, case_id).json()

    refused = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/category",
        json={"category": "urlaub"},
    )
    assert refused.status_code == 422
    assert "not a category" in refused.text

    # The upload survives its own refusal: still waiting, still confirmable.
    still = client.get(f"/api/v1/cases/{case_id}/documents/{uploaded['id']}").json()
    assert still["state"] == "awaiting_confirmation"
    assert still["proposed"] == uploaded["proposed"]

    # And the confirmation refuses the same category, so it cannot arrive that way.
    assert client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/confirm",
        json={"values": {"equipment.price_eur": 689.0}, "category": "urlaub"},
    ).status_code == 422


def test_a_payslip_has_no_category_to_choose(client, case_id, vision):
    vision.first = vision.second = {
        "document_type": "lohnsteuerbescheinigung", "tax_year": YEAR,
        "employment_period_start": f"{YEAR}-01-01", "employment_period_end": f"{YEAR}-12-31",
    }
    uploaded = upload(client, case_id, kind="lohnsteuerbescheinigung",
                      name="lohn.jpg").json()

    assert uploaded["category_choices"] == [], "the screen must not offer the choice"

    refused = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/category",
        json={"category": "arbeitsmittel"},
    )
    assert refused.status_code == 409
    assert "Lohnsteuerbescheinigung" in refused.text


def test_a_settled_document_keeps_the_category_it_was_saved_with(client, case_id):
    uploaded = upload(client, case_id).json()
    client.post(f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/confirm",
                json={"values": {"equipment.price_eur": 689.0}})

    refused = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/category",
        json={"category": "fortbildungskosten"},
    )
    assert refused.status_code == 409
    assert "confirmed" in refused.text


def test_two_readings_that_disagree_offer_no_category_either(client, case_id, vision):
    """Nothing can be proposed under any category, so none is offered."""
    vision.first = INVOICE
    vision.second = dict(INVOICE, net_total_eur=99.0)

    uploaded = upload(client, case_id).json()

    assert uploaded["disagreements"], "the two reads differ on the total"
    assert uploaded["proposed"] == []
    assert uploaded["category_choices"] == []


def test_a_category_the_content_argues_against_is_questioned_not_refused(client, case_id, vision):
    """Allowed, and asked about. The user may have a reason; only they can give it."""
    vision.first = vision.second = dict(
        INVOICE,
        net_total_eur=96.0, vat_amount_eur=18.24, gross_total_eur=114.24,
        line_items=[{"description": "Restaurant Abendessen", "quantity": 1,
                     "unit_price_eur": 96.0}],
    )
    uploaded = upload(client, case_id).json()

    body = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/category",
        json={"category": "fortbildungskosten"},
    ).json()

    assert body["category"] == "fortbildungskosten"
    assert "restaurant" in (body["contradiction"] or "")
    assert any("restaurant" in question for question in body["questions"])
    # Questioned, not blocked: the values are still there to confirm.
    assert {item["key"] for item in body["proposed"]} == {"education.amount_eur"}


def test_a_second_invoice_starts_after_the_items_the_first_one_left(client, case_id, vision):
    """The index the upload computed is stale by the time a category is chosen.

    The second invoice is uploaded while the rules cannot place it, so its category -
    and with it its Fact keys - is decided after the first invoice's two items are
    already in the case. An index computed at upload would key it to `#0` and `#2`
    and overwrite them.
    """
    first = upload(client, case_id, name="rechnung-1.jpg").json()

    vision.first = vision.second = UNPLACEABLE
    second = upload(client, case_id, name="rechnung-2.jpg").json()
    assert second["category"] is None

    # Only now is the first invoice confirmed: two items, indexes 0 and 2.
    client.post(
        f"/api/v1/cases/{case_id}/documents/{first['id']}/confirm",
        json={"values": {item["key"]: item["value"] for item in first["proposed"]}},
    )
    held = cases.get_fields(USER, case_id)
    assert {"equipment.price_eur", "equipment.price_eur#2"} <= set(held)

    body = client.post(
        f"/api/v1/cases/{case_id}/documents/{second['id']}/category",
        json={"category": "arbeitsmittel"},
    ).json()

    keys = {item["key"] for item in body["proposed"]}
    assert "equipment.price_eur#3" in keys, keys
    assert not keys & set(held), "a second invoice must add items, never overwrite them"

    client.post(f"/api/v1/cases/{case_id}/documents/{second['id']}/confirm",
                json={"values": {item["key"]: item["value"] for item in body["proposed"]}})
    after = cases.get_fields(USER, case_id)
    assert after["equipment.price_eur"].value == 689.0, "the first invoice survived"
    assert after["equipment.price_eur#3"].value == 240.0


def test_a_document_settled_while_a_category_was_being_chosen(client, case_id, monkeypatch):
    """The check that decides is the one inside the case lock, not the one before it.

    Deterministic stand-in for the race: the document is settled between the early
    refusal check and the lock, which is exactly the window a concurrent confirm or
    discard occupies. Resuming after that would put a settled document back to
    `awaiting_confirmation` with its values already written.
    """
    import contextlib

    from api.routes import documents as route

    uploaded = upload(client, case_id).json()
    settled = False

    @contextlib.asynccontextmanager
    async def settle_then_hold(name: str):
        nonlocal settled
        if not settled:
            settled = True
            cases.set_document_state(USER, case_id, uploaded["id"], "discarded")
        async with real_hold(name):
            yield

    real_hold = route.hold
    monkeypatch.setattr(route, "hold", settle_then_hold)

    refused = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/category",
        json={"category": "fortbildungskosten"},
    )
    assert refused.status_code == 409
    assert client.get(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}"
    ).json()["state"] == "discarded"
    assert cases.get_fields(USER, case_id) == {}


def test_an_upload_past_its_deadline_is_gone_from_every_route(client, case_id):
    """The TTL is a promise about data, so no route may answer around it.

    `expire_abandoned` used to run when the documents were listed and nowhere else,
    which made the single-document GET - and the category and confirm routes - a way
    to reach a reading the deadline had already taken away (ADR 0004).
    """
    settings = get_settings()
    uploaded = upload(client, case_id).json()
    assert uploaded["proposed"]

    kept = settings.document_confirmation_ttl_hours
    settings.document_confirmation_ttl_hours = 0
    try:
        fetched = client.get(
            f"/api/v1/cases/{case_id}/documents/{uploaded['id']}").json()
        assert fetched["state"] == "failed"
        assert fetched["failure_code"] == "expired"
        assert fetched["proposed"] == []

        assert client.post(
            f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/category",
            json={"category": "fortbildungskosten"},
        ).status_code == 409
        assert client.post(
            f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/confirm",
            json={"values": {"equipment.price_eur": 689.0}},
        ).status_code == 409
    finally:
        settings.document_confirmation_ttl_hours = kept

    assert cases.get_fields(USER, case_id) == {}


def test_a_document_whose_readings_disagree_has_no_category_to_choose(client, case_id, vision):
    vision.first = INVOICE
    vision.second = dict(INVOICE, net_total_eur=99.0)
    uploaded = upload(client, case_id).json()
    assert uploaded["disagreements"]

    refused = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/category",
        json={"category": "arbeitsmittel"},
    )
    assert refused.status_code == 409
    assert "disagree" in refused.text


def test_a_confirmation_the_catalogue_cannot_hold_is_refused(client, case_id):
    document_id = upload(client, case_id).json()["id"]
    refused = client.post(
        f"/api/v1/cases/{case_id}/documents/{document_id}/confirm",
        json={"values": {"equipment.price_eur": "quite a lot", "made.up": 1}},
    )
    assert refused.status_code == 422
    assert "expects an amount" in refused.text
    assert cases.get_fields(USER, case_id) == {}


def test_a_confirmation_whose_category_contradicts_its_values_is_refused(client, case_id):
    """The third way to write a document that lies about itself.

    The category is one of the four and the key is one the catalogue holds, so both
    halves pass their own validation. What they cannot do is disagree: this would
    record a Fortbildung document whose only value is an Arbeitsmittel price.
    """
    uploaded = upload(client, case_id).json()
    assert uploaded["category"] == "arbeitsmittel"

    refused = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/confirm",
        json={"values": {"equipment.price_eur": 689.0},
              "category": "fortbildungskosten"},
    )
    assert refused.status_code == 422
    assert "arbeitsmittel" in refused.text
    assert cases.get_fields(USER, case_id) == {}

    # And the document is untouched, so the right confirmation still works.
    assert client.get(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}"
    ).json()["state"] == "awaiting_confirmation"
    assert client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/confirm",
        json={"values": {"equipment.price_eur": 689.0}, "category": "arbeitsmittel"},
    ).status_code == 200


def test_the_keys_of_the_category_left_behind_cannot_be_confirmed_after_a_change(
    client, case_id,
):
    """After a change of category, the old category's keys are no longer this document's."""
    uploaded = upload(client, case_id).json()
    client.post(f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/category",
                json={"category": "fortbildungskosten"})

    refused = client.post(
        f"/api/v1/cases/{case_id}/documents/{uploaded['id']}/confirm",
        json={"values": {"equipment.price_eur": 689.0},
              "category": "fortbildungskosten"},
    )
    assert refused.status_code == 422
    assert cases.get_fields(USER, case_id) == {}


def test_the_fields_are_labelled_rather_than_keyed(client, case_id):
    """What the user reads over each input, and which item it belongs to.

    `equipment.price_eur#2` is a Fact key, not a question. The wording comes from the
    Question catalogue, so the confirmation screen and the interview call the same
    value the same thing.
    """
    uploaded = upload(client, case_id).json()

    labelled = {item["key"]: item for item in uploaded["proposed"]}
    assert labelled["equipment.price_eur"]["label"] == "What did the work equipment cost?"
    # Three prices - a desk and two monitor arms - numbered from one for the reader.
    assert labelled["equipment.price_eur"]["item"] == 1
    assert labelled["equipment.price_eur#2"]["item"] == 3
    # The key is still there: it is what the confirmation sends back.
    assert labelled["equipment.price_eur#2"]["key"] == "equipment.price_eur#2"

    german = client.get(
        f"/api/v1/cases/{case_id}/documents",
        headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"},
    ).json()[0]
    assert "Kaufpreis des Arbeitsmittels" in german["proposed"][0]["label"]

    # Turkish has no catalogue text yet (issue #54), so it reads English rather than
    # nothing at all.
    turkish = client.get(
        f"/api/v1/cases/{case_id}/documents", headers={"Accept-Language": "tr"},
    ).json()[0]
    assert turkish["proposed"][0]["label"] == "What did the work equipment cost?"


def test_a_payslip_labels_the_one_fact_it_yields(client, case_id, vision):
    vision.first = vision.second = {
        "document_type": "lohnsteuerbescheinigung", "tax_year": YEAR,
        "employment_period_start": f"{YEAR}-02-01", "employment_period_end": f"{YEAR}-09-30",
    }
    uploaded = upload(client, case_id, kind="lohnsteuerbescheinigung",
                      name="lohn.jpg").json()

    [month_count] = uploaded["proposed"]
    assert month_count["label"] == "For how many months of 2025 were you in employment?"
    # Not a repeating value, so there is no item number to show.
    assert month_count["item"] is None
    assert month_count["value"] == 8


def test_the_answer_says_which_model_read_the_document(client, case_id):
    """Which model produced the values is part of what the screen is looking at."""
    uploaded = upload(client, case_id).json()
    assert uploaded["read_by"] == "google/gemini-3.7-flash"

    reloaded = client.get(f"/api/v1/cases/{case_id}/documents/{uploaded['id']}").json()
    assert reloaded["read_by"] == "google/gemini-3.7-flash"


def test_an_unreachable_provider_is_read_by_the_fallback(client, case_id, vision):
    """VISION_FALLBACK_MODEL, which was a setting nothing read until now."""
    from core.llm import LLMError

    vision.fails = LLMError("502 from the provider")
    fallback = vision.fallback

    body = upload(client, case_id).json()

    assert body["state"] == "awaiting_confirmation"
    assert body["read_by"] == "x-ai/grok-4.5"
    assert fallback.calls == 2, "both passes move together, or the gate means nothing"
    # And it is a whole reading, not a degraded one: the same three prices the
    # primary model would have produced from the same invoice.
    prices = {item["key"]: item["value"] for item in body["proposed"]
              if item["key"].startswith("equipment.price_eur")}
    assert prices == {
        "equipment.price_eur": 689.0,
        "equipment.price_eur#1": 46.25,
        "equipment.price_eur#2": 46.25,
    }


def test_both_providers_down_is_a_failed_document_with_a_reason(client, case_id, vision):
    from core.llm import LLMError

    vision.fails = LLMError("502 from the provider")
    vision.fallback.fails = LLMError("503 from the other provider")

    body = upload(client, case_id).json()

    assert body["state"] == "failed"
    assert body["failure_code"] == "provider_unavailable"
    assert cases.get_fields(USER, case_id) == {}


def test_somebody_elses_document_does_not_exist(client, case_id):
    document_id = upload(client, case_id).json()["id"]
    seen = client.get(f"/api/v1/cases/{case_id}/documents",
                      headers={"x-test-user": STRANGER})
    assert seen.status_code in (200, 404)
    assert seen.json() in ([], {"detail": "no such case or document"})

    refused = client.post(
        f"/api/v1/cases/{case_id}/documents/{document_id}/discard",
        headers={"x-test-user": STRANGER},
    )
    assert refused.status_code == 404


def test_two_payslips_add_up_to_the_year(client, case_id, vision):
    """The failure this guards: the second payslip overwriting the first one's months."""
    first_half = {
        "document_type": "lohnsteuerbescheinigung", "tax_year": YEAR,
        "employment_period_start": f"{YEAR}-01-01", "employment_period_end": f"{YEAR}-06-30",
    }
    second_half = dict(first_half,
                       employment_period_start=f"{YEAR}-07-01",
                       employment_period_end=f"{YEAR}-12-31")

    vision.first = vision.second = first_half
    body = upload(client, case_id, kind="lohnsteuerbescheinigung", name="lohn-1.jpg").json()
    assert {i["key"]: i["value"] for i in body["proposed"]} == {"profile.employed_months": 6}
    client.post(f"/api/v1/cases/{case_id}/documents/{body['id']}/confirm",
                json={"values": {"profile.employed_months": 6}})

    vision.first = vision.second = second_half
    body = upload(client, case_id, kind="lohnsteuerbescheinigung", name="lohn-2.jpg").json()
    assert {i["key"]: i["value"] for i in body["proposed"]} == {"profile.employed_months": 12}
