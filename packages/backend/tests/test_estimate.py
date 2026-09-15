"""The running estimate the Interviewer judges by.

Numbers here are checked by hand rather than against the code that produced them,
because the whole point of the estimate is to be right about when asking more cannot
change anything.
"""

import pytest

from domain.estimate import estimate, to_params
from domain.fields import ExpenseCategory
from eval.baseline import load_profiles, run_filter

PROFILES = {p.id.split("-")[0]: p for p in load_profiles()}


def known_for(prefix: str) -> dict:
    return run_filter(PROFILES[prefix]).known


# --- the arithmetic -------------------------------------------------------------

def test_a_full_case_adds_up_to_the_hand_computed_figure():
    # p01: 18 km one way, all of it under the 20 km tier, so 18 x 0.30 = 5.40 a day
    #      over 88 commuting days = 475.20
    #      132 home-office days x 6.00 = 792.00
    #      a 1,400 EUR laptop, digital, so deducted in full
    e = estimate(known_for("p01"))
    assert e.per_category[ExpenseCategory.entfernungspauschale].amount_eur == 475.20
    assert e.per_category[ExpenseCategory.homeoffice_tagespauschale].amount_eur == 792.00
    assert e.per_category[ExpenseCategory.arbeitsmittel].amount_eur == 1400.00
    assert e.total_eur == 2667.20
    assert e.beats_pauschbetrag


def test_training_costs_are_reduced_by_what_was_reimbursed():
    # p08 pays 2,400 for a course and gets 600 back. The Anleitung to Zeile 60 says
    # reimbursements must be subtracted; forgetting it overstates the claim by 600.
    e = estimate(known_for("p08"))
    assert e.per_category[ExpenseCategory.fortbildungskosten].amount_eur == 1800.00


def test_a_short_commute_and_nothing_else_falls_short_of_the_allowance():
    # p03: 4 km x 0.30 x 210 days = 252.00 against an allowance of 1,230
    e = estimate(known_for("p03"))
    assert e.total_eur == 252.00
    assert not e.beats_pauschbetrag
    assert e.gap_to_pauschbetrag == pytest.approx(978.0)


def test_half_of_the_profiles_cannot_reach_the_allowance():
    """Recorded because it shapes what the Interviewer is for.

    On these the honest answer is that itemising gains nothing, whatever else is
    still unasked — and saying so early is the one thing the relevance filter cannot
    do, since relevance and effect on the outcome are different questions.
    """
    short = [p.id for p in load_profiles()
             if not estimate(run_filter(p).known).beats_pauschbetrag]
    assert len(short) == 5
    assert all(p.startswith(("p03", "p04", "p05", "p07", "p10")) for p in short)


def test_nothing_known_estimates_to_nothing_rather_than_failing():
    e = estimate({})
    assert e.total_eur == 0.0
    assert e.per_category == {}
    assert not e.beats_pauschbetrag


# --- translation into calculator parameters -------------------------------------

def test_a_categorys_answers_reach_its_calculator_under_their_own_names():
    """The rename is done: there is nothing left to translate but the namespace.

    `work_days` used to mean the yearly total in `validation.py` and the commute
    count in `calculations.py`, and a `maps_to` on the field bridged the two names
    (issue #36). Now the field, the parameter and the key agree, so the only work
    left here is stripping `commute.` off the front.
    """
    params, missing = to_params(ExpenseCategory.entfernungspauschale, known_for("p01"))
    assert params["commuting_days"] == 88
    assert "work_days" not in params
    assert not any("." in name for name in params), "a parameter never carries a namespace"
    assert missing == []


def test_a_field_filled_from_another_resolves_without_being_asked():
    # Homeoffice needs the commute's day count for the same-day check, and it is the
    # same fact under the same name now - `filled_by` reaches across the namespace.
    params, missing = to_params(ExpenseCategory.homeoffice_tagespauschale, known_for("p01"))
    assert params["commuting_days"] == 88
    assert missing == []


def test_an_incomplete_category_is_reported_rather_than_guessed():
    partial = {"equipment.price_eur": 500.0}
    params, missing = to_params(ExpenseCategory.arbeitsmittel, partial)
    assert params == {"price_eur": 500.0}
    assert "equipment.purchase_month" in missing

    e = estimate(partial)
    entry = e.per_category[ExpenseCategory.arbeitsmittel]
    assert not entry.computable
    assert entry.amount_eur == 0.0
    assert e.open_categories == [ExpenseCategory.arbeitsmittel]


def test_repeated_purchases_are_summed_item_by_item():
    """Each item goes through the calculator on its own, because AfA depends on both
    the price and the month — which is why the case stores them separately."""
    known = {
        "equipment.price_eur": 380.0,
        "equipment.price_is_net": False,
        "equipment.purchase_month": 11,
        "equipment.is_digital": True,
        "equipment.price_eur#1": 129.0,
        "equipment.price_is_net#1": False,
        "equipment.purchase_month#1": 9,
        "equipment.is_digital#1": True,
    }
    assert estimate(known).per_category[ExpenseCategory.arbeitsmittel].amount_eur == 509.00
