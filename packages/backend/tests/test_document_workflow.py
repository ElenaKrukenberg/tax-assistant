"""The intake workflow: the failure paths, the disagreement gate, and the pause.

Scripted readers throughout - no provider is reachable from the test suite
(`tests/conftest.py`), and these tests are about what the graph does with a read,
not about how well a model reads.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from services.documents.extract import ExtractionFailed, Read
from workflows.document_intake import IntakeContext, build_graph, intake_thread_id

JPEG = b"\xff\xd8\xff" + b"\x00" * 512

INVOICE = {
    "document_type": "rechnung",
    "price_basis": "net",
    "invoice_date": "2025-09-08",
    "net_total_eur": 781.5,
    "vat_rate_percent": 19.0,
    "vat_amount_eur": 148.49,
    "gross_total_eur": 929.99,
    "line_items": [
        {"description": "Schreibtisch Ergoline", "quantity": 1, "unit_price_eur": 689.0},
        {"description": "Monitorarm Duo", "quantity": 2, "unit_price_eur": 46.25},
    ],
}

PAYSLIP = {
    "document_type": "lohnsteuerbescheinigung",
    "tax_year": 2025,
    "employment_period_start": "2025-07-01",
    "employment_period_end": "2025-12-31",
}

USAGE = {"prompt_tokens": 3200, "completion_tokens": 300, "total_tokens": 3500}


def reader(first: dict, second: dict | None = None, *, raises: Exception | None = None):
    """A stand-in for two provider calls: what pass one and pass two returned."""

    async def read_twice(*, data, upload, kind):
        if raises is not None:
            raise raises
        return Read(first, USAGE), Read(second if second is not None else first, USAGE)

    return read_twice


def run(state: dict, *, data: bytes = JPEG, read_twice=None, saver=None, config=None):
    graph = build_graph(saver or InMemorySaver())
    config = config or {"configurable": {"thread_id": intake_thread_id("u", "c", "d")}}
    return asyncio.run(graph.ainvoke(
        state,
        config=config,
        context=IntakeContext(data=data, read_twice=read_twice or reader(INVOICE)),
    )), graph, config


def base(**overrides) -> dict:
    state = {
        "document_id": "d",
        "file_name": "rechnung.jpg",
        "declared_format": "image/jpeg",
        "kind": "rechnung",
        "tax_year": 2025,
    }
    state.update(overrides)
    return state


# --- demo 1: two reads agree ----------------------------------------------------

def test_a_good_document_pauses_with_values_and_a_reason_for_its_category():
    result, _, _ = run(base())

    assert result["state"] == "awaiting_confirmation"
    assert result["category"] == "arbeitsmittel"
    assert result["category_by_rule"] is True
    assert "schreibtisch" in result["category_reason"]
    assert result["disagreements"] == []

    proposed = {p["key"]: p["value"] for p in result["proposed"]}
    assert proposed["equipment.price_eur"] == 689.0
    assert proposed["equipment.price_eur#2"] == 46.25   # quantity 2, expanded
    assert proposed["equipment.price_is_net"] is True


def test_nothing_is_saved_until_the_answer_comes_back():
    """The pause is the guarantee, so this is the test that states it.

    The run stops at `review` with the values *proposed*, and the case-facing result
    - `confirmed` - stays empty until a human answers. There is no path through this
    graph that fills it otherwise.
    """
    saver = InMemorySaver()
    result, graph, config = run(base(), saver=saver)
    assert not result.get("confirmed")

    resumed = asyncio.run(graph.ainvoke(
        Command(resume={"decision": "confirm",
                        "values": {"equipment.price_eur": 689.0}}),
        config=config,
        context=IntakeContext(data=b"", read_twice=reader(INVOICE)),
    ))
    assert resumed["state"] == "confirmed"
    assert resumed["confirmed"]["values"] == {"equipment.price_eur": 689.0}
    assert resumed["confirmed"]["category"] == "arbeitsmittel"


def test_the_user_may_correct_the_amount_before_it_is_saved():
    """Demo 3: the correction replaces the proposal, and only the correction is saved."""
    saver = InMemorySaver()
    _, graph, config = run(base(), saver=saver)

    resumed = asyncio.run(graph.ainvoke(
        Command(resume={"decision": "confirm",
                        "values": {"equipment.price_eur": 1032.00}}),
        config=config,
        context=IntakeContext(data=b"", read_twice=reader(INVOICE)),
    ))
    assert resumed["confirmed"]["values"] == {"equipment.price_eur": 1032.00}
    assert 689.0 not in resumed["confirmed"]["values"].values()


def test_an_invoice_the_rules_cannot_place_asks_rather_than_guesses():
    """Two categories named equally often: a real invoice, and not a tie to break."""
    both = dict(INVOICE, line_items=[
        {"description": "Bürostuhl Ergoline", "quantity": 1, "unit_price_eur": 689.0},
        {"description": "Seminar Steuerrecht", "quantity": 1, "unit_price_eur": 240.0},
    ])
    result, _, _ = run(base(), read_twice=reader(both))

    assert result["state"] == "awaiting_confirmation"
    assert result["category"] is None
    assert result["proposed"] == []
    assert "two categories" in result["questions"][0]


def test_the_category_the_user_picks_produces_the_values_it_keys():
    """The point of the loop: a chosen category is another proposal, not a label.

    The invoice below names nothing the rules know, so nothing is proposed until the
    user picks - and what they pick decides the Fact keys, because
    `fortbildung.amount_eur` and `equipment.price_eur#1` are different values rather
    than one value under two names.
    """
    unknown = dict(INVOICE, net_total_eur=240.0, vat_amount_eur=45.6,
                   gross_total_eur=285.6, line_items=[
                       {"description": "Jahresbeitrag", "quantity": 1,
                        "unit_price_eur": 240.0},
                   ])
    saver = InMemorySaver()
    result, graph, config = run(base(), read_twice=reader(unknown), saver=saver)
    assert result["category"] is None and result["proposed"] == []

    chosen = asyncio.run(graph.ainvoke(
        Command(resume={"decision": "reclassify", "category": "fortbildungskosten"}),
        config=config,
        context=IntakeContext(data=b"", read_twice=reader(unknown)),
    ))

    assert chosen["state"] == "awaiting_confirmation"
    assert chosen["category"] == "fortbildungskosten"
    assert chosen["category_by_rule"] is False
    assert chosen["category_reason"] == "you chose this category"
    assert {p["key"]: p["value"] for p in chosen["proposed"]} == {
        "education.amount_eur": 240.0
    }
    # And it is still only a proposal: nothing is confirmed by choosing.
    assert not chosen.get("confirmed")


def test_choosing_a_category_again_re_keys_what_the_rules_had_proposed():
    """The rules said Arbeitsmittel; the user says Fortbildung, and the keys follow."""
    saver = InMemorySaver()
    result, graph, config = run(base(), saver=saver)
    assert result["category"] == "arbeitsmittel"
    assert "equipment.price_eur" in {p["key"] for p in result["proposed"]}

    chosen = asyncio.run(graph.ainvoke(
        Command(resume={"decision": "reclassify", "category": "fortbildungskosten"}),
        config=config,
        context=IntakeContext(data=b"", read_twice=reader(INVOICE)),
    ))

    assert chosen["category"] == "fortbildungskosten"
    keys = {p["key"] for p in chosen["proposed"]}
    assert keys == {"education.amount_eur"}
    assert not any(key.startswith("equipment.") for key in keys)


def test_a_chosen_category_is_checked_against_the_content_like_any_other():
    """A restaurant line under Fortbildung is questioned, the user's choice included."""
    dinner = dict(INVOICE, line_items=[
        {"description": "Restaurant Abendessen", "quantity": 1, "unit_price_eur": 96.0},
    ])
    saver = InMemorySaver()
    run(base(), read_twice=reader(dinner), saver=saver)
    config = {"configurable": {"thread_id": intake_thread_id("u", "c", "d")}}
    graph = build_graph(saver)

    chosen = asyncio.run(graph.ainvoke(
        Command(resume={"decision": "reclassify", "category": "fortbildungskosten"}),
        config=config,
        context=IntakeContext(data=b"", read_twice=reader(dinner)),
    ))

    assert chosen["category"] == "fortbildungskosten"
    assert "restaurant" in (chosen["contradiction"] or "")
    assert any("restaurant" in question for question in chosen["questions"])


def test_a_category_no_case_can_hold_is_refused_rather_than_stored():
    saver = InMemorySaver()
    _, graph, config = run(base(), saver=saver)

    refused = asyncio.run(graph.ainvoke(
        Command(resume={"decision": "reclassify", "category": "urlaub"}),
        config=config,
        context=IntakeContext(data=b"", read_twice=reader(INVOICE)),
    ))

    assert refused["state"] == "failed"
    assert refused["failure"]["code"] == "unusable_answer"


def test_discarding_saves_nothing():
    saver = InMemorySaver()
    _, graph, config = run(base(), saver=saver)
    resumed = asyncio.run(graph.ainvoke(
        Command(resume={"decision": "discard"}),
        config=config,
        context=IntakeContext(data=b"", read_twice=reader(INVOICE)),
    ))
    assert resumed["state"] == "discarded"
    assert resumed["confirmed"] == {}


def test_an_answer_that_says_neither_is_refused_rather_than_interpreted():
    saver = InMemorySaver()
    _, graph, config = run(base(), saver=saver)
    resumed = asyncio.run(graph.ainvoke(
        Command(resume={"looks": "fine"}),
        config=config,
        context=IntakeContext(data=b"", read_twice=reader(INVOICE)),
    ))
    assert resumed["state"] == "failed"
    assert resumed["failure"]["code"] == "unusable_answer"


# --- demo 2: the two reads disagree ---------------------------------------------

def test_a_disagreement_proposes_nothing_at_all():
    """Not a confidence percentage: a gate.

    The second pass reads 46.25 where the first read 689.00 - one amount out of a
    skewed row, which is the failure the cheap models make. Nothing is offered as a
    value; the user is told to type it or upload a better photo (issue #5).
    """
    second = json.loads(json.dumps(INVOICE))
    second["line_items"][0]["unit_price_eur"] = 46.25

    result, _, _ = run(base(), read_twice=reader(INVOICE, second))

    assert result["state"] == "awaiting_confirmation"
    assert result["proposed"] == []
    assert result["disagreements"]
    assert any("disagree" in q for q in result["questions"])


# --- the failure paths ----------------------------------------------------------

def test_a_file_that_is_not_a_document_never_reaches_a_model():
    called = False

    async def must_not_be_called(**_):
        nonlocal called
        called = True
        raise AssertionError("the model was called on a rejected file")

    result, _, _ = run(base(), data=b"GIF89a" + b"\x00" * 64,
                       read_twice=must_not_be_called)
    assert result["state"] == "failed"
    assert result["failure"]["code"] == "unsupported_format"
    assert called is False


def test_a_provider_failure_is_a_failed_document_not_an_exception():
    result, _, _ = run(base(), read_twice=reader(
        INVOICE, raises=ExtractionFailed("provider_unavailable", "not just now"),
    ))
    assert result["state"] == "failed"
    assert result["failure"]["code"] == "provider_unavailable"


def test_a_payslip_uploaded_as_an_invoice_is_refused_by_type():
    result, _, _ = run(base(), read_twice=reader(PAYSLIP))
    assert result["state"] == "failed"
    assert result["failure"]["code"] == "wrong_document_type"
    assert "lohnsteuerbescheinigung" in result["failure"]["detail"]


# --- several documents ----------------------------------------------------------

def test_a_second_payslip_adds_to_the_months_the_first_established():
    result, _, _ = run(
        base(kind="lohnsteuerbescheinigung", file_name="lohnsteuer.jpg",
             known_periods=[["2025-01-01", "2025-06-30"]]),
        read_twice=reader(PAYSLIP),
    )
    proposed = {p["key"]: p["value"] for p in result["proposed"]}
    assert proposed == {"profile.employed_months": 12}


def test_a_second_invoice_starts_where_the_first_left_off():
    result, _, _ = run(base(first_item_index=3))
    assert {p["key"] for p in result["proposed"]} == {
        "equipment.price_eur#3", "equipment.price_is_net#3", "equipment.purchase_month#3",
        "equipment.price_eur#4", "equipment.price_is_net#4", "equipment.purchase_month#4",
        "equipment.price_eur#5", "equipment.price_is_net#5", "equipment.purchase_month#5",
    }


# --- ADR 0004 -------------------------------------------------------------------

def test_the_document_itself_is_never_written_to_a_checkpoint():
    """The promise ADR 0004 makes, checked against what was actually persisted.

    The bytes travel in the runtime context, which LangGraph does not checkpoint,
    and the state holds only what came out of the document. This searches every
    checkpoint the run wrote for the bytes themselves and for the base64 they would
    have been encoded as.
    """
    import base64

    marker = b"\xde\xad\xbe\xef" * 8
    data = b"\xff\xd8\xff" + marker + b"\x00" * 64
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": intake_thread_id("u", "c", "d")}}
    run(base(), data=data, saver=saver, config=config)

    written = json.dumps(
        [c.checkpoint for c in saver.list(config)], default=repr,
    ).encode()

    assert marker not in written
    assert base64.b64encode(marker) not in written
    assert base64.b64encode(data)[:32] not in written
    # And what *is* there is the extraction: values, not pictures.
    assert b"equipment.price_eur" in written


def test_the_thread_id_cannot_be_mistaken_for_an_interviews():
    """Two kinds of run share one `checkpoints` table (services/case_erasure.py)."""
    from agents.graph import case_thread_id

    intake = intake_thread_id("u", "c", "d")
    assert intake.startswith("document-intake:")
    assert intake != case_thread_id("u", "c")
    assert case_thread_id("u", "c") in intake  # the case is still findable in it
