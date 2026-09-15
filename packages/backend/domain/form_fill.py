"""Which figure goes in which line of Anlage N — and which figures do not fit.

The report has always been able to say "Anlage N Zeile 58"; this turns that sentence
into a placement. It is plain data, computed from the case and the year's form-line
table (`tax_years.py`), and it knows nothing about PDFs — the drawing lives in
`services/anlage_n_pdf.py`, and the split is what makes the mapping testable without
rendering anything.

Two rules, both about not lying on a tax document:

- A figure is placed only where the line is unambiguous. The three "Sonstiges"
  categories share Zeilen 62-63, each needing a written description next to its
  amount; their **total** goes in Zeile 64 and is placed, the descriptions are not,
  and each one is reported back as unplaced so the user writes them in themselves.
- Nothing is invented. A line whose value the case does not hold stays empty, which
  on a tax form is a meaningful state and not a gap to be filled with a zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from domain.fields import ExpenseCategory
from domain.tax_years import TaxYear, for_year

# The three categories the form has no line of its own for. They share the free
# "Sonstiges" rows, and only their sum can be placed without inventing a description.
SONSTIGES = (ExpenseCategory.telefon_internet,
             ExpenseCategory.umzugskosten,
             ExpenseCategory.bewerbungskosten)


@dataclass(frozen=True)
class FormEntry:
    """One value, and the line of the official form it belongs in."""

    line: str
    value: float
    kind: str   # "integer" | "km" | "eur" — how the box wants it written
    label: str  # plain words, for the report and for anything left unplaced


@dataclass(frozen=True)
class Unplaced:
    """A figure the form has no unambiguous single box for."""

    label: str
    amount_eur: float
    where: str


def entries_for(known: dict[str, Any], expenses: list[dict[str, Any]],
                year: Optional[TaxYear] = None) -> tuple[list[FormEntry], list[Unplaced]]:
    """The case as form lines: what can be placed, and what the user still writes."""
    year = year or for_year()
    amounts = {row["category"]: float(row["amount_eur"]) for row in expenses}
    entries: list[FormEntry] = []
    unplaced: list[Unplaced] = []

    def add(line: str, value: Any, kind: str, label: str) -> None:
        if value is None:
            return
        entries.append(FormEntry(line=line, value=float(value), kind=kind, label=label))

    commute = year.line_for(ExpenseCategory.entfernungspauschale).parts
    add(commute["days_attended"], known.get("commute.commuting_days"),
        "integer", "days the workplace was attended")

    distance = known.get("commute.distance_km")
    add(commute["distance_km_total"], distance, "km", "one-way distance")
    # The same distance again, in the line that says how it was travelled. The form
    # asks for both: the total, then the split by means of transport.
    if distance is not None:
        own_car = bool(known.get("commute.own_car"))
        add(commute["distance_km_own_car"] if own_car
            else commute["distance_km_public_or_bike_or_foot"],
            distance, "km",
            "distance by own car" if own_car else "distance by other means")
    add(commute["public_transport_cost"],
        known.get("commute.public_transport_cost_eur"),
        "eur", "public transport cost")

    homeoffice = amounts.get(ExpenseCategory.homeoffice_tagespauschale.value)
    if homeoffice is not None:
        days = known.get("homeoffice.homeoffice_days")
        parts = year.line_for(ExpenseCategory.homeoffice_tagespauschale).parts
        other_workplace = known.get("homeoffice.other_workplace_available")
        # Which of the two lines is not a detail: the same day may appear in one only,
        # and the answer decides which. Without it, neither line may be filled.
        if other_workplace is None:
            unplaced.append(Unplaced("home-office days", homeoffice,
                                     "Zeile 58 or 59 — depends on whether another "
                                     "workplace was available, which the case does not know"))
        else:
            add(parts["days_with_other_workplace_available"] if other_workplace
                else parts["days_without_other_workplace"],
                days, "integer", "home-office days")

    equipment = amounts.get(ExpenseCategory.arbeitsmittel.value)
    add(year.line_for(ExpenseCategory.arbeitsmittel).parts["sum"], equipment,
        "eur", "work equipment, total")

    education = amounts.get(ExpenseCategory.fortbildungskosten.value)
    add(year.line_for(ExpenseCategory.fortbildungskosten).lines, education,
        "eur", "further education")

    others = [(c, amounts[c.value]) for c in SONSTIGES if c.value in amounts]
    if others:
        total = sum(amount for _, amount in others)
        add(year.line_for(SONSTIGES[0]).parts["sum"], total, "eur",
            "other work expenses, total")
        for category, amount in others:
            unplaced.append(Unplaced(
                category.value, amount,
                f"Zeile {year.line_for(category).lines} — the free rows need a written "
                "description beside the amount, so only the total above is placed"))

    return entries, unplaced
