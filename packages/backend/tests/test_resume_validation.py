"""The boundary between a browser and a paused interview.

These are the payloads a hand-rolled client can send that the graph's own nodes
read without complaint - a string where a number belongs, an approval that is the
word "false", a rejection naming a key the card never showed. Each one lands
somewhere that matters: `field_values` under `Provenance.answer`, a cleared
field, or a finalized case.
"""

from __future__ import annotations

import pytest

from domain.questions import BY_ID
from domain.resume import ResumeInvalid, validate_resume


def question_pause(question_id: str) -> dict:
    """The pause `ask_user` interrupts with, reduced to what validation reads."""
    question = BY_ID[question_id]
    return {"type": "question", "question_id": question.id}


def refused(pause: dict, resume: object) -> str:
    with pytest.raises(ResumeInvalid) as raised:
        validate_resume(pause, resume)
    return str(raised.value)


# --- questions: the value has to be the kind of value the catalogue asked for ---


def test_a_number_typed_as_a_string_is_refused():
    # The frontend casts before it sends; anything that is not the frontend does
    # not. `working_days_total` reaches a calculator parameter typed int.
    pause = question_pause("profile.working_days_total")
    assert "whole number" in refused(pause, {"value": "220"})


def test_a_whole_number_field_refuses_a_fraction():
    pause = question_pause("profile.working_days_total")
    assert "whole number" in refused(pause, {"value": 220.5})


def test_money_takes_a_fraction():
    validate_resume(question_pause("equipment.price_eur"), {"value": 249.99})


def test_a_figure_below_the_minimum_is_refused():
    pause = question_pause("commute.distance_km")
    assert "below 1" in refused(pause, {"value": 0})


def test_a_figure_above_the_maximum_is_refused():
    # 400 commuting days in a 366-day year is the shape of an inflated claim.
    pause = question_pause("commute.commuting_days")
    assert "above 366" in refused(pause, {"value": 400})


def test_the_bounds_themselves_are_accepted():
    validate_resume(question_pause("commute.commuting_days"), {"value": 366})
    validate_resume(question_pause("commute.distance_km"), {"value": 1})


def test_a_choice_outside_the_catalogue_is_refused():
    pause = question_pause("profile.benefit_type")
    message = refused(pause, {"value": "wohngeld"})
    assert "kurzarbeitergeld" in message  # the answer names what is allowed


def test_a_listed_choice_is_accepted():
    validate_resume(question_pause("profile.benefit_type"), {"value": "kurzarbeitergeld"})


def test_a_boolean_field_refuses_a_truthy_string():
    # bool("no") is True. `works_remotely` is a gate: this one string opens or
    # closes the whole home-office category.
    pause = question_pause("profile.works_remotely")
    assert "yes or no" in refused(pause, {"value": "no"})


def test_a_boolean_field_refuses_the_number_one():
    assert refused(question_pause("profile.works_remotely"), {"value": 1})


def test_a_number_field_refuses_a_boolean():
    # True is an int in Python and would otherwise be stored as the figure 1.
    assert "a number" in refused(question_pause("profile.employer_count"), {"value": True})


def test_a_date_has_to_be_a_real_calendar_date():
    pause = question_pause("moving.move_date")
    assert "calendar date" in refused(pause, {"value": "2024-02-31"})
    assert "YYYY-MM-DD" in refused(pause, {"value": "31.02.2024"})
    validate_resume(pause, {"value": "2024-02-29"})


def test_a_month_outside_the_year_is_refused():
    pause = question_pause("equipment.purchase_month")
    assert "above 12" in refused(pause, {"value": 13})
    validate_resume(pause, {"value": 12})


def test_i_dont_know_is_an_answer_to_a_required_question():
    # Every card offers it, required or not; what a missing value blocks is
    # decided on the way to the stop card, not at this boundary.
    assert BY_ID["profile.working_days_total"].spec().required
    validate_resume(question_pause("profile.working_days_total"), {"value": None})


def test_a_bare_value_is_still_read():
    # `ask_user` accepts one; refusing it here would break a client that predates
    # the wrapper.
    validate_resume(question_pause("profile.works_remotely"), True)


def test_an_answer_without_a_value_is_refused():
    assert "carry a value" in refused(question_pause("profile.works_remotely"), {})


def test_an_answer_carrying_an_extra_key_is_refused():
    # Anything beside `value` is dropped unread by `_persist_answer`.
    pause = question_pause("profile.works_remotely")
    assert "confirmed" in refused(pause, {"value": True, "confirmed": True})


def test_a_question_no_longer_in_the_catalogue_is_refused():
    pause = {"type": "question", "question_id": "profile.retired_early"}
    assert "catalogue" in refused(pause, {"value": True})


# --- the stop card: a rejection clears a stored field ---


def stop_pause(*keys: str) -> dict:
    return {"type": "confirm_stop",
            "carried_over": [{"key": key} for key in keys]}


def test_a_rejection_naming_an_unshown_key_is_refused():
    # The key is cleared from `field_values`; unshown means the user never saw
    # the value being thrown away.
    pause = stop_pause("commute.distance_km")
    message = refused(pause, {"confirm": True, "reject": ["profile.employed_months"]})
    assert "profile.employed_months" in message


def test_a_rejection_of_a_shown_key_is_accepted():
    pause = stop_pause("commute.distance_km", "commute.own_car")
    validate_resume(pause, {"confirm": False, "reject": ["commute.own_car"]})


def test_the_stop_card_refuses_a_non_boolean_confirmation():
    assert "yes or no" in refused(stop_pause(), {"confirm": "yes"})


def test_the_stop_card_still_takes_a_bare_boolean():
    validate_resume(stop_pause(), True)


def test_a_stop_card_reply_may_omit_the_confirmation():
    # `read_stop_answer` defaults a missing flag to True; a reply that only
    # rejects relies on that.
    validate_resume(stop_pause("commute.own_car"), {"reject": ["commute.own_car"]})


def test_the_rejected_keys_have_to_be_a_list_of_keys():
    assert "list" in refused(stop_pause("commute.own_car"), {"reject": "commute.own_car"})


# --- the review card: an unknown action waves the review through ---


def test_an_unknown_action_is_refused():
    # `resolve_findings` reads everything that is not "revise" as a dismissal.
    assert "revise or dismiss" in refused({"type": "findings"}, {"action": "ignore"})


def test_both_actions_are_accepted():
    validate_resume({"type": "findings"}, {"action": "revise"})
    validate_resume({"type": "findings"}, {"action": "dismiss"})


# --- the approval card: this is the one that finalizes a case ---


def approval_pause(*position_ids: str) -> dict:
    return {"type": "final_approval",
            "tax_positions": [{"position_id": p} for p in position_ids]}


def test_an_approval_that_is_a_string_is_refused():
    # bool("false") is True: a return filed by a typo.
    pause = approval_pause("p1")
    assert "yes or no" in refused(pause, {"approve": "false", "decisions": {"p1": "accepted"}})


def test_an_approval_is_required():
    assert "approve or decline" in refused(approval_pause(), {"decisions": {}})


def test_a_decision_on_a_position_that_is_not_on_the_card_is_refused():
    pause = approval_pause("p1")
    assert "p2" in refused(pause, {"approve": True, "decisions": {"p2": "accepted"}})


def test_only_accepted_and_rejected_are_decisions():
    # `pending` and `needs_reconfirmation` are states the assessment sets; a
    # client sending one would reset the decision it is being asked for.
    pause = approval_pause("p1")
    assert "accepted or rejected" in refused(
        pause, {"approve": True, "decisions": {"p1": "needs_reconfirmation"}})


def test_a_complete_approval_is_accepted():
    pause = approval_pause("p1", "p2")
    validate_resume(pause, {"approve": True,
                            "decisions": {"p1": "accepted", "p2": "rejected"}})


def test_the_approval_card_refuses_a_bare_boolean():
    # It carries per-position decisions; a bare True would leave them unset.
    assert refused(approval_pause("p1"), True)


# --- the pause itself ---


def test_an_unrecognised_pause_type_is_refused():
    assert refused({"type": "something_new"}, {"value": 1})
