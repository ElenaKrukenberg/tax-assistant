"""Profile memory: what survives the tax year, and what may never be assumed to.

Three concerns, and only the first is about storage. The store round-trip is the
easy part; the ones worth testing are the invariant that keeps a gate out of the
carried set, and the stop card that is the single place a carried value is either
confirmed or dropped — because a carried value that reaches the report unlooked-at
is exactly the defect ADR 0010 exists to prevent.
"""

import asyncio
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agents import profile_memory
from agents.graph import build_graph, read_stop_answer
from domain.fields import CARRY_OVER_FIELDS, GATE_FIELDS, FieldValue, Provenance
from domain.questions import BY_KEY


def run(coro):
    return asyncio.run(coro)


def thread() -> dict:
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def pause(result) -> dict:
    assert "__interrupt__" in result, f"expected a pause, got: {list(result)}"
    return result["__interrupt__"][0].value


# --- what may carry ---------------------------------------------------------------

def test_no_gate_field_may_ever_carry_over():
    """The invariant that makes the whole feature safe, asserted from the outside.

    `domain/fields.py` raises at import if this is violated, so this test is what
    turns that import error into a named failure somebody can read.
    """
    assert set(GATE_FIELDS).isdisjoint(CARRY_OVER_FIELDS)


def test_every_carried_key_is_a_key_the_catalogue_actually_asks_for():
    """A carried key nobody asks about could never be confirmed or corrected."""
    for key in CARRY_OVER_FIELDS:
        assert key in BY_KEY, f"{key} carries over but no question fills it"


def test_a_repeating_field_cannot_be_marked_as_carrying():
    from domain.fields import AnswerType, FieldSpec

    with pytest.raises(ValueError, match="belongs to an item"):
        FieldSpec("price_eur", AnswerType.money, repeats=True, carries_over=True)


# --- the store round-trip ----------------------------------------------------------

def test_a_carried_answer_comes_back_for_the_same_user():
    store = InMemoryStore()
    run(profile_memory.remember(store, "u1", "commute.distance_km", 42, 2024))

    held = run(profile_memory.recall(store, "u1"))
    assert held == {"commute.distance_km": {"value": 42, "tax_year": 2024}}


def test_one_users_profile_never_reaches_another():
    store = InMemoryStore()
    run(profile_memory.remember(store, "u1", "commute.distance_km", 42, 2024))
    assert run(profile_memory.recall(store, "u2")) == {}


def test_only_marked_fields_are_remembered_at_all():
    store = InMemoryStore()
    run(profile_memory.remember(store, "u1", "profile.employed_months", 12, 2024))
    assert run(profile_memory.recall(store, "u1")) == {}


def test_an_older_year_never_overwrites_a_newer_one():
    """Filing 2024 after 2025 must not roll the commute back to the older figure."""
    store = InMemoryStore()
    key = "commute.distance_km"
    run(profile_memory.remember(store, "u1", key, 42, 2025))
    run(profile_memory.remember(store, "u1", key, 18, 2024))

    assert run(profile_memory.recall(store, "u1"))[key]["value"] == 42


def test_the_year_being_worked_on_is_not_offered_back_to_itself():
    store = InMemoryStore()
    run(profile_memory.remember(store, "u1", "commute.distance_km", 42, 2025))
    assert run(profile_memory.recall(store, "u1", exclude_year=2025)) == {}


def test_memory_that_cannot_be_reached_is_no_memory_rather_than_an_error():
    """An unreachable store must degrade, never raise: the interview outranks it."""

    class Broken:
        async def aget(self, *a, **k):
            raise RuntimeError("no database")

        async def aput(self, *a, **k):
            raise RuntimeError("no database")

        async def asearch(self, *a, **k):
            raise RuntimeError("no database")

    run(profile_memory.remember(Broken(), "u1", "commute.distance_km", 42, 2024))
    assert run(profile_memory.recall(Broken(), "u1")) == {}
    assert run(profile_memory.recall(None, "u1")) == {}


def test_a_value_shaped_like_an_older_release_is_skipped():
    store = InMemoryStore()
    run(store.aput(profile_memory.namespace("u1"),
                   "commute.distance_km", {"km": 42}))
    assert run(profile_memory.recall(store, "u1")) == {}


# --- the stop card ------------------------------------------------------------------

def test_the_stop_card_reply_reads_both_of_its_shapes():
    assert read_stop_answer(True) == (True, [])
    assert read_stop_answer(False) == (False, [])
    assert read_stop_answer({"confirm": True}) == (True, [])
    assert read_stop_answer({"confirm": True, "reject": ["a.b"]}) == (True, ["a.b"])
    assert read_stop_answer({"confirm": False, "reject": []}) == (False, [])


CARRIED_COMMUTE = {
    "key": "commute.distance_km",
    "value": 42,
    "source": "carried over from your 2024 case",
    "text": BY_KEY["commute.distance_km"].text,
    "answer_type": "integer",
}


def commuter_state(carried) -> dict:
    """A case one question short of a stop, with every gate already answered."""
    return {
        "tax_year": 2025,
        "known": {
            "profile.employed_months": 12, "profile.employer_count": 1, "profile.working_days_total": 220,
            "profile.works_remotely": False, "profile.bought_work_equipment": False,
            "profile.claims_phone_internet": False, "profile.moved_for_work": False,
            "profile.searched_for_job": False, "profile.further_education": False,
            "commute.commuting_days": 200,
            "commute.distance_km": 42,
            "commute.own_car": True,
        },
        "asked": [],
        "carried_over": carried,
    }


def drive_to_stop(graph, config, carried):
    """Answer whatever is still open until the stop proposal appears."""
    result = run(graph.ainvoke(commuter_state(carried), config))
    for _ in range(20):
        payload = pause(result)
        if payload["type"] == "confirm_stop":
            return result, payload
        result = run(graph.ainvoke(Command(resume={"value": None}), config))
    raise AssertionError("the interview never proposed to stop")


def test_a_carried_value_is_shown_on_the_stop_card():
    graph = build_graph(checkpointer=InMemorySaver())
    config = thread()
    _, payload = drive_to_stop(graph, config, [CARRIED_COMMUTE])

    assert [c["key"] for c in payload["carried_over"]] == [CARRIED_COMMUTE["key"]]
    assert payload["carried_over"][0]["value"] == 42


def test_confirming_the_stop_leaves_nothing_carried_behind():
    graph = build_graph(checkpointer=InMemorySaver())
    config = thread()
    drive_to_stop(graph, config, [CARRIED_COMMUTE])
    run(graph.ainvoke(Command(resume={"confirm": True}), config))

    values = graph.get_state(config).values
    assert values["carried_over"] == []
    assert values["known"]["commute.distance_km"] == 42


def test_rejecting_a_carried_value_reopens_the_interview_and_forgets_it():
    graph = build_graph(checkpointer=InMemorySaver())
    config = thread()
    drive_to_stop(graph, config, [CARRIED_COMMUTE])
    result = run(graph.ainvoke(
        Command(resume={"confirm": True, "reject": [CARRIED_COMMUTE["key"]]}), config))

    values = graph.get_state(config).values
    assert "commute.distance_km" not in values["known"]
    assert pause(result)["type"] == "question"


def test_a_carried_value_this_year_does_not_need_is_never_shown_and_does_not_linger():
    """Somebody who did not work this year must not be shown last year's commute.

    And it must not survive either: an unconfirmed value nobody saw is what stops a
    report from being generated at all.
    """
    graph = build_graph(checkpointer=InMemorySaver())
    config = thread()
    state = commuter_state([CARRIED_COMMUTE])
    state["known"]["profile.employed_months"] = 0

    result = run(graph.ainvoke(state, config))
    for _ in range(20):
        payload = pause(result)
        if payload["type"] == "confirm_stop":
            break
        result = run(graph.ainvoke(Command(resume={"value": None}), config))
    else:
        raise AssertionError("the interview never proposed to stop")

    assert payload["carried_over"] == []
    run(graph.ainvoke(Command(resume=True), config))
    values = graph.get_state(config).values
    assert "commute.distance_km" not in values["known"]
