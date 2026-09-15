"""The developer panel's data block: present in DEBUG, absent outside it.

The absence test is the one that matters: the block leaks how the agent thinks,
and production is off exactly as long as this stays red on a regression.
"""

import pytest

from api.routes.cases import _debug_of
from core.config import get_settings


STATE = {
    "known": {"profile.employed_months": 12, "profile.employer_count": 1, "profile.working_days_total": 224,
              "profile.works_remotely": False, "profile.has_minijob": False, "profile.benefit_type": "none",
              "profile.bought_work_equipment": False, "profile.claims_phone_internet": False,
              "profile.moved_for_work": False, "profile.searched_for_job": False,
              "profile.further_education": False,
              "commute.commuting_days": 210,
              "commute.distance_km": 4,
              "commute.own_car": True},
    "asked": ["profile.employed_months", "commute.commuting_days"],
    "rounds": 5,
    "last_decision": {"kind": "ask", "from_model": True,
                      "question_id": "commute.commuting_days"},
}


@pytest.fixture
def debug_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "debug", True)


@pytest.fixture
def debug_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "debug", False)


def test_outside_debug_there_is_nothing(debug_off):
    assert _debug_of(STATE, {"type": "question"}) is None


def test_the_block_mirrors_the_graph_state(debug_on):
    block = _debug_of(STATE, {"type": "question"})
    assert block["node"] == "ask_user"
    assert block["rounds"] == 5
    assert block["asked"] == 2
    assert block["total_eur"] == 252.0
    assert block["pauschbetrag_eur"] == 1230.0
    assert block["last_decision"]["from_model"] is True


def test_every_pause_maps_to_its_node(debug_on):
    for pause_type, node in [("question", "ask_user"), ("confirm_stop", "confirm_stop"),
                             ("findings", "resolve_findings"),
                             ("final_approval", "final_approval")]:
        assert _debug_of(STATE, {"type": pause_type})["node"] == node
    assert _debug_of(STATE, None, done=True)["node"] == "finalized"


def test_an_empty_state_is_still_renderable(debug_on):
    block = _debug_of({}, {"type": "question"})
    assert block["asked"] == 0
    assert block["total_eur"] == 0.0
    assert block["last_decision"] is None
