"""The rules of tax year 2025: rates, thresholds, and the lines of Anlage N 2025.

Its own file because a year's rules stop changing once they are written down. A
voluntary German return can be filed four years back, so somebody sitting down in
2026 may be filing 2025 for the first time and there will still be 2025 filers in
2027 - the numbers here are the record of what that year's law was.

The rule this file exists to make visible: **adding 2026 means adding
`tax_year_2026.py`, never editing this one.** A file holding several years is a file
edited every year, and every edit is a chance to move a number out from under a
return that already used it (issue #43; the rest of the year work is #37).

`tax_years.py` keeps what is shared - the shape of a year and the lookup that finds
one. Form lines are read from `KB/055-anleitung-anlage-n-2025.md`.
"""

from __future__ import annotations

from typing import Final

from domain.fields import ExpenseCategory
from domain.tax_years import ANLAGE_N, HAUPTVORDRUCK, FormLine, TaxYear


YEAR_2025: Final = TaxYear(
    year=2025,
    rate_km_first_20=0.30,
    rate_km_from_21=0.38,
    commute_cap_no_car=4500.0,
    homeoffice_rate=6.0,
    homeoffice_cap=1260.0,
    homeoffice_max_days=210,
    gwg_limit_net=800.0,
    pauschbetrag=1230.0,
    telecom_share=0.20,
    telecom_monthly_cap=20.0,
    typical_max_work_days=230,
    dhf_rent_cap_monthly=1000.0,
    fortbildung_attention_threshold=5000.0,
    # 31 July 2026 is a Friday, so it stands. 28 February 2027 is a Sunday and
    # rolls to the Monday. Voluntary filing runs to the end of 2029.
    filing_due="2026-07-31",
    filing_due_advised="2027-03-01",
    voluntary_filing_until="2029-12-31",
    form_lines={
        ExpenseCategory.entfernungspauschale: FormLine(
            ANLAGE_N, "27-50",
            parts={
                "workplace_and_period": "27",
                "days_per_week": "28",
                "days_attended": "29",
                "distance_km_total": "30",
                "distance_km_own_car": "31",
                "distance_km_employer_transport": "32",
                "distance_km_public_or_bike_or_foot": "33",
                "public_transport_cost": "34",
                "second_workplace_block": "35-42",
                "third_workplace_block": "43-50",
                "employer_reimbursement": "51",
                "agentur_fuer_arbeit_travel_subsidy": "52",
            },
            note="Three workplaces fit on the form, eight lines each: 27-34, 35-42, 43-50, so a "
                 "job change mid-year fills a second block. Zeile 51 carries the (e) marker: the "
                 "employer's figures reach the Finanzamt electronically, which makes asking the "
                 "user for them wasted effort",
        ),
        ExpenseCategory.homeoffice_tagespauschale: FormLine(
            ANLAGE_N, "58-59",
            parts={
                "days_with_other_workplace_available": "58",
                "days_without_other_workplace": "59",
            },
            note="Which of the two lines a day goes in depends on whether another workplace was "
                 "available, not on anything about the day, and the same day may appear in one "
                 "line only. Zeile 57 (Arbeitszimmer) must stay empty for the same period (V23)",
        ),
        ExpenseCategory.arbeitsmittel: FormLine(
            ANLAGE_N, "54-56", parts={"items": "54-55", "sum": "56"},
            note="Two described items fit, their total goes in 56. AfA on an item above the GWG "
                 "threshold is entered here too",
        ),
        ExpenseCategory.fortbildungskosten: FormLine(ANLAGE_N, "60"),
        ExpenseCategory.telefon_internet: FormLine(
            ANLAGE_N, "62-63", parts={"sum": "64"},
            note='Weitere Werbungskosten, the free "Sonstiges" rows, each with its own '
                 "description. Zeile 61 is not the generic row it looks like: it is ferry and "
                 "flight costs only",
        ),
        ExpenseCategory.umzugskosten: FormLine(
            ANLAGE_N, "62-63", parts={"sum": "64"},
            note='"Sonstiges" row. A move within a doppelte Haushaltsführung belongs in '
                 "Anlage N-DHF instead",
        ),
        ExpenseCategory.bewerbungskosten: FormLine(
            ANLAGE_N, "62-63", parts={"sum": "64"},
            note='"Sonstiges" row — the form prints Bewerbungskosten as its own example. '
                 "Deductible whether or not the application succeeded",
        ),
    },
    benefit_form_line=FormLine(
        HAUPTVORDRUCK, "35", parts={"eu_eea_switzerland": "36"},
        note="Einkommensersatzleistungen — the Hauptvordruck's term for ALG I, Elterngeld, "
             "Krankengeld and the rest. Normally nothing is entered at all: the amounts reach "
             "the Finanzamt electronically. Zeile 35 is filled only with a paper Leistungsnachweis "
             "or to deviate from the transmitted figure. They stay tax-free but raise the rate on "
             "other income (Progressionsvorbehalt, § 32b EStG)",
    ),
)
