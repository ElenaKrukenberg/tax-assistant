import pytest
from pydantic import ValidationError

from domain.calculations import (
    ArbeitsmittelParams,
    CommuteParams,
    HomeofficeParams,
    PauschbetragParams,
    TelecomParams,
    CalculationType,
    calc_arbeitsmittel,
    calc_entfernungspauschale,
    calc_homeoffice_pauschale,
    calc_pauschbetrag_comparison,
    calc_telefon_internet,
    calculate,
)
from domain.checklist import ChecklistCategory, build_document_checklist
from domain.validation import TaxData, validate_tax_data


# --- Entfernungspauschale ---

def test_commute_two_tier_rate():
    # 25 km: 20 x 0.30 + 5 x 0.38 = 7.90/day; 220 days = 1738.00
    r = calc_entfernungspauschale(CommuteParams(commuting_days=220, distance_km=25))
    assert r.amount_eur == pytest.approx(1738.00)


def test_commute_short_distance_only_first_tier():
    # 15 km: 15 x 0.30 = 4.50/day; 100 days = 450.00
    r = calc_entfernungspauschale(CommuteParams(commuting_days=100, distance_km=15))
    assert r.amount_eur == pytest.approx(450.00)


def test_commute_cap_applies_without_own_car():
    # 100 km, 230 days: way above 4500 -> capped
    r = calc_entfernungspauschale(CommuteParams(commuting_days=230, distance_km=100, own_car=False))
    assert r.amount_eur == 4500.0


def test_commute_no_cap_with_own_car():
    r = calc_entfernungspauschale(CommuteParams(commuting_days=230, distance_km=100, own_car=True))
    assert r.amount_eur > 4500.0


def test_commute_public_transport_higher_wins():
    r = calc_entfernungspauschale(
        CommuteParams(commuting_days=100, distance_km=5, public_transport_cost_eur=800.0)
    )
    # allowance would be 100 x 1.50 = 150 -> actual tickets 800 win
    assert r.amount_eur == 800.0


def test_commute_implausible_days_warns_v01():
    r = calc_entfernungspauschale(CommuteParams(commuting_days=300, distance_km=10))
    assert any("V01" in w for w in r.warnings)


# --- Homeoffice ---

def test_homeoffice_basic():
    r = calc_homeoffice_pauschale(HomeofficeParams(homeoffice_days=100))
    assert r.amount_eur == 600.0


def test_homeoffice_cap_1260():
    r = calc_homeoffice_pauschale(HomeofficeParams(homeoffice_days=250))
    assert r.amount_eur == 1260.0
    assert any("V03" in w for w in r.warnings)


def test_homeoffice_day_double_counting_v02():
    r = calc_homeoffice_pauschale(HomeofficeParams(homeoffice_days=150, commuting_days=150))
    assert any("V02" in w for w in r.warnings)


# --- Arbeitsmittel ---

def test_arbeitsmittel_gwg_immediate():
    # 800 net exactly -> immediate full deduction
    r = calc_arbeitsmittel(ArbeitsmittelParams(price_eur=800, price_is_net=True, purchase_month=6))
    assert r.amount_eur == 800.0


def test_arbeitsmittel_gross_converts_to_net_for_gwg_check():
    # 952 gross = 800 net -> still GWG, deduct the gross price
    r = calc_arbeitsmittel(ArbeitsmittelParams(price_eur=952, price_is_net=False, purchase_month=6))
    assert r.amount_eur == 952.0


def test_arbeitsmittel_digital_full_first_year():
    # laptop 1500 net, digital -> 1-year useful life, full deduction
    r = calc_arbeitsmittel(
        ArbeitsmittelParams(price_eur=1500, price_is_net=True, purchase_month=11, is_digital=True)
    )
    assert r.amount_eur == 1500.0


def test_arbeitsmittel_afa_pro_rata():
    # desk 1200 (net, non-digital), bought in October, 3-year life:
    # annual 400, first year 3/12 = 100
    r = calc_arbeitsmittel(
        ArbeitsmittelParams(price_eur=1200, price_is_net=True, purchase_month=10, useful_life_years=3)
    )
    assert r.amount_eur == pytest.approx(100.0)


def test_arbeitsmittel_professional_share():
    r = calc_arbeitsmittel(
        ArbeitsmittelParams(price_eur=500, price_is_net=True, purchase_month=1, professional_share_pct=50)
    )
    assert r.amount_eur == 250.0
    assert any("share" in w.lower() or "18a" in w for w in r.warnings)


# --- Pauschbetrag comparison ---

def test_pauschbetrag_itemising_wins():
    r = calc_pauschbetrag_comparison(PauschbetragParams(total_werbungskosten_eur=2000))
    assert r.amount_eur == 770.0


def test_pauschbetrag_flat_wins():
    r = calc_pauschbetrag_comparison(PauschbetragParams(total_werbungskosten_eur=900))
    assert r.amount_eur == 0.0
    assert "no benefit" in r.breakdown[0]


# --- Telecom ---

def test_telecom_20_percent():
    # 50/month: 20% = 10 < 20 cap -> 120/year
    r = calc_telefon_internet(TelecomParams(monthly_bill_eur=50))
    assert r.amount_eur == 120.0


def test_telecom_monthly_cap():
    # 150/month: 20% = 30 -> capped at 20 -> 240/year
    r = calc_telefon_internet(TelecomParams(monthly_bill_eur=150))
    assert r.amount_eur == 240.0


# --- dispatcher ---

def test_calculate_dispatcher_roundtrip():
    r = calculate(CalculationType.homeoffice_pauschale, {"homeoffice_days": 10})
    assert r.amount_eur == 60.0


def test_calculate_dispatcher_rejects_bad_params():
    with pytest.raises(ValidationError):
        calculate(CalculationType.entfernungspauschale, {"commuting_days": 0, "distance_km": 10})


# --- validation tool ---

def test_validation_v02_double_counting_is_error():
    report = validate_tax_data(TaxData(working_days_total=220, homeoffice_days=150, commuting_days=120))
    assert not report.valid
    assert any(f.rule_id == "V02" and f.severity == "error" for f in report.findings)


def test_validation_partial_data_only_checks_present_fields():
    report = validate_tax_data(TaxData(homeoffice_days=100))
    assert report.valid
    assert "V03" in report.checked_rules
    assert "V12" not in report.checked_rules


def test_validation_caps():
    report = validate_tax_data(TaxData(
        homeoffice_amount_eur=2000, dhf_rent_monthly_eur=1500, arbeitsmittel_immediate_net_eur=1000,
    ))
    ids = {f.rule_id for f in report.findings}
    assert {"V10", "V12", "V15"} <= ids
    assert not report.valid


def test_validation_v23_xor():
    report = validate_tax_data(TaxData(arbeitszimmer_actual_costs=True, homeoffice_pauschale_claimed=True))
    assert any(f.rule_id == "V23" for f in report.findings)


def test_validation_wrong_year():
    report = validate_tax_data(TaxData(expense_year=2024))
    assert any(f.rule_id == "V26" and f.severity == "error" for f in report.findings)


def test_validation_all_good():
    report = validate_tax_data(TaxData(working_days_total=220, homeoffice_days=80, commuting_days=140,
                                       total_werbungskosten_eur=2000))
    assert report.valid
    assert report.findings == []


# --- checklist tool ---

def test_checklist_known_categories():
    lists = build_document_checklist([ChecklistCategory.arbeitsmittel, ChecklistCategory.umzugskosten])
    assert len(lists) == 2
    assert any(i.required for i in lists[0].items)
    assert all(l.general_note for l in lists)


def test_checklist_all_categories_have_content():
    lists = build_document_checklist(list(ChecklistCategory))
    assert len(lists) == len(ChecklistCategory)
    assert all(len(l.items) >= 1 for l in lists)


def test_a_year_lives_in_its_own_file_so_adding_one_never_edits_another():
    """The rule #43 exists to make visible, as something that can fail.

    A year's rules stop changing once written: a voluntary German return can be filed
    four years back, so there will still be 2025 filers in 2027. A file holding
    several years is a file edited every year, and every edit is a chance to move a
    number out from under a return that already used it.
    """
    from pathlib import Path

    import domain.tax_years as shared

    module = Path(shared.__file__).read_text(encoding="utf-8")
    # The shape and the lookup live here; the content of a year does not.
    assert "rate_km_first_20=0.30" not in module, (
        "a year's numbers are back in tax_years.py - they belong in tax_year_<year>.py"
    )
    assert "class TaxYear" in module and "def for_year" in module

    for year in shared.TAX_YEARS:
        assert (Path(shared.__file__).parent / f"tax_year_{year}.py").exists(), (
            f"{year} is in the lookup with no tax_year_{year}.py behind it"
        )


def test_an_unknown_year_fails_loudly_and_says_which_years_exist():
    """Silently answering with another year's rates would put a wrong number on a
    tax return, which is the one outcome this project treats as unacceptable."""
    import pytest

    from domain.tax_years import for_year

    with pytest.raises(ValueError) as refused:
        for_year(2031)
    assert "2031" in str(refused.value) and "2025" in str(refused.value)
