"""The year block and the field schema, and the wiring between them.

The point of most of these is to fail when the annual update is incomplete: a new
tax year or a new expense category that arrives without its form line should stop
the build, not surface later as a figure pointing at the wrong line of the form.
"""

import dataclasses

import pytest

from domain.calculations import (
    CommuteParams,
    HomeofficeParams,
    PauschbetragParams,
    calc_entfernungspauschale,
    calc_homeoffice_pauschale,
    calc_pauschbetrag_comparison,
)
from domain.fields import (
    CATEGORY_FIELDS,
    PROFILE_FIELDS,
    AnswerType,
    ExpenseCategory,
    FieldSpec,
    all_field_specs,
    required_fields,
)
from domain.tax_years import TAX_YEARS, YEAR_2025, for_year


# --- the year block ---

def test_every_category_has_a_form_line_in_every_year():
    for year, rules in TAX_YEARS.items():
        missing = [c.value for c in ExpenseCategory if c not in rules.form_lines]
        assert not missing, f"{year} has no form line for: {missing}"


def test_every_form_line_is_read_from_the_form_itself():
    # All of them were pinned against KB/Anlage_N_2025.pdf rather than inferred
    # from the Anleitung. An entry added later without that check should say so.
    unverified = {c.value for c, line in YEAR_2025.form_lines.items() if not line.verified}
    assert not unverified, f"not pinned against the form: {unverified}"


def test_unknown_year_fails_loudly_and_says_which_years_exist():
    with pytest.raises(ValueError, match="2026.*covers 2025"):
        for_year(2026)


def test_commute_block_repeats_in_eight_line_groups():
    # The form holds three workplaces: 27-34, 35-42, 43-50. A job change mid-year
    # fills the second group, which is what profile 6 in the sprint plan exercises.
    line = YEAR_2025.line_for(ExpenseCategory.entfernungspauschale)
    assert line.parts["days_attended"] == "29"
    assert line.parts["distance_km_total"] == "30"
    assert line.parts["distance_km_own_car"] == "31"
    assert line.parts["second_workplace_block"] == "35-42"
    assert line.parts["third_workplace_block"] == "43-50"


def test_homeoffice_has_a_line_for_each_workplace_situation():
    line = YEAR_2025.line_for(ExpenseCategory.homeoffice_tagespauschale)
    assert line.parts["days_with_other_workplace_available"] == "58"
    assert line.parts["days_without_other_workplace"] == "59"


def test_the_sonstiges_categories_share_the_rows_and_the_sum():
    sonstiges = (
        ExpenseCategory.telefon_internet,
        ExpenseCategory.umzugskosten,
        ExpenseCategory.bewerbungskosten,
    )
    for category in sonstiges:
        line = YEAR_2025.line_for(category)
        assert line.lines == "62-63", f"{category.value} is not a Sonstiges row"
        assert line.parts["sum"] == "64"


def test_benefits_point_at_the_hauptvordruck_not_at_anlage_n():
    line = YEAR_2025.benefit_form_line
    assert line.form == "hauptvordruck"
    assert line.lines == "35"
    assert "electronically" in line.note


# --- the wiring: calculations must read the year, not a leftover constant ---

DOUBLED = dataclasses.replace(
    YEAR_2025,
    year=2999,
    rate_km_first_20=0.60,
    rate_km_from_21=0.76,
    homeoffice_rate=12.0,
    pauschbetrag=2460.0,
)


def test_commute_uses_the_year_rates():
    p = CommuteParams(commuting_days=10, distance_km=10, own_car=True)
    assert calc_entfernungspauschale(p, YEAR_2025).amount_eur == pytest.approx(30.0)
    assert calc_entfernungspauschale(p, DOUBLED).amount_eur == pytest.approx(60.0)


def test_homeoffice_uses_the_year_rate():
    p = HomeofficeParams(homeoffice_days=100)
    assert calc_homeoffice_pauschale(p, YEAR_2025).amount_eur == 600.0
    assert calc_homeoffice_pauschale(p, DOUBLED).amount_eur == 1200.0


def test_pauschbetrag_comparison_uses_the_year_allowance():
    p = PauschbetragParams(total_werbungskosten_eur=2000.0)
    assert calc_pauschbetrag_comparison(p, YEAR_2025).amount_eur == 770.0
    # Same total, higher allowance: itemising stops being worthwhile
    assert calc_pauschbetrag_comparison(p, DOUBLED).amount_eur == 0.0


# --- the field schema ---

def test_field_names_are_unique_within_a_category():
    for category, specs in CATEGORY_FIELDS.items():
        names = [s.name for s in specs]
        assert len(names) == len(set(names)), f"{category.value} repeats a field name"


def test_profile_field_names_are_unique():
    names = [s.name for s in PROFILE_FIELDS]
    assert len(names) == len(set(names))


def test_required_fields_are_a_subset_of_all_of_them():
    for category in ExpenseCategory:
        assert set(required_fields(category)) <= set(CATEGORY_FIELDS[category])


def test_all_field_specs_covers_profile_and_every_category():
    total = len(PROFILE_FIELDS) + sum(len(v) for v in CATEGORY_FIELDS.values())
    assert len(all_field_specs()) == total


def test_a_choice_field_without_options_is_rejected():
    with pytest.raises(ValueError, match="needs options"):
        FieldSpec("benefit_type", AnswerType.choice)


def test_options_on_a_non_choice_field_are_rejected():
    with pytest.raises(ValueError, match="only apply to a choice field"):
        FieldSpec("work_days", AnswerType.integer, options=("a", "b"))
