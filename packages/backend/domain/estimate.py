"""What the case is worth so far, from whatever is known.

The Interviewer needs this to do the one thing a relevance filter cannot: stop when
more questions cannot change the outcome. A case whose total cannot reach the
Pauschbetrag is finished whatever else is still unanswered, because the flat
allowance is granted anyway and itemising would gain nothing.

Nothing here is a tax figure to put on a form. It is an estimate over partial data,
used to decide what to ask next; the figures that reach the report come from the same
calculators over complete, confirmed values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from domain.calculations import CalculationType, calculate
from domain.fields import CATEGORY_FIELDS, ExpenseCategory, FieldSpec, key_for, namespace_of
from domain.tax_years import TaxYear, for_year

# Categories with a formula, and the calculator that owns it.
CALCULATORS: dict[ExpenseCategory, CalculationType] = {
    ExpenseCategory.entfernungspauschale: CalculationType.entfernungspauschale,
    ExpenseCategory.homeoffice_tagespauschale: CalculationType.homeoffice_pauschale,
    ExpenseCategory.arbeitsmittel: CalculationType.arbeitsmittel,
    ExpenseCategory.telefon_internet: CalculationType.telefon_internet,
}

# Categories that are the sum of receipts. Fortbildungskosten has to subtract what
# was reimbursed: the Anleitung to Zeile 60 says so explicitly, and forgetting it
# would overstate the claim.
SUMMED: dict[ExpenseCategory, tuple[str, Optional[str]]] = {
    ExpenseCategory.fortbildungskosten: ("amount_eur", "reimbursed_eur"),
    ExpenseCategory.umzugskosten: ("amount_eur", None),
    ExpenseCategory.bewerbungskosten: ("amount_eur", None),
}


@dataclass
class CategoryEstimate:
    category: ExpenseCategory
    amount_eur: float = 0.0
    computable: bool = False
    missing: list[str] = field(default_factory=list)
    # Which branches of the calculator ran, across every item of the category, in the
    # order first seen. Collected here because this is the only place that calls the
    # calculator and knows the answer; `assess_positions` turns them into the
    # citations a position stores (`domain/rule_citations.py`).
    applied_rule_ids: list[str] = field(default_factory=list)


@dataclass
class Estimate:
    total_eur: float
    pauschbetrag: float
    per_category: dict[ExpenseCategory, CategoryEstimate]

    @property
    def beats_pauschbetrag(self) -> bool:
        return self.total_eur > self.pauschbetrag

    @property
    def gap_to_pauschbetrag(self) -> float:
        """How much more is needed before itemising is worth anything."""
        return max(self.pauschbetrag - self.total_eur, 0.0)

    @property
    def open_categories(self) -> list[ExpenseCategory]:
        """Categories the case has started but cannot yet compute."""
        return [c for c, e in self.per_category.items() if not e.computable and e.missing]


def estimate(known: dict[str, Any], year: Optional[TaxYear] = None) -> Estimate:
    """Add up what can be computed, and say what is missing for the rest."""
    year = year or for_year()
    per_category: dict[ExpenseCategory, CategoryEstimate] = {}
    total = 0.0

    for category in ExpenseCategory:
        if not _started(category, known):
            continue
        result = (_summed(category, known) if category in SUMMED
                  else _calculated(category, known, year))
        per_category[category] = result
        total += result.amount_eur

    return Estimate(round(total, 2), year.pauschbetrag, per_category)


def to_params(category: ExpenseCategory, known: dict[str, Any],
              item_index: int = 0) -> tuple[dict[str, Any], list[str]]:
    """Read the calculator's parameters out of the case, and name what is absent.

    There is no renaming left to do here: a field's name in `domain/fields.py` is the
    parameter's name in `calculations.py`, which is what issue #36 bought by splitting
    `work_days` into `commuting_days`, `homeoffice_days` and `working_days_total`. What
    this still does is strip the namespace and resolve a field filled from another one,
    so the calculator never sees a gap the interview deliberately did not ask about.
    """
    params: dict[str, Any] = {}
    missing: list[str] = []

    for spec in CATEGORY_FIELDS[category]:
        if spec.interview_only:
            # Asked, stored, and never a calculator parameter - "did you buy anything
            # else?" belongs to the conversation, not to the purchase (#35).
            continue
        value = _value(category, spec, known, item_index)
        if value is None:
            if spec.required and not spec.filled_by:
                missing.append(key_for(category, spec.name))
            continue
        params[spec.name] = value

    return params, missing


# --- internals ------------------------------------------------------------------

def _value(category: ExpenseCategory, spec: FieldSpec, known: dict[str, Any],
           item_index: int) -> Any:
    if spec.filled_by:
        # The same fact in another namespace: homeoffice's commuting_days is
        # commute.commuting_days, asked once and read twice.
        return known.get(spec.filled_by)
    key = key_for(category, spec.name, item_index)
    return known.get(key)


def _started(category: ExpenseCategory, known: dict[str, Any]) -> bool:
    return any(k.startswith(f"{namespace_of(category)}.") for k in known)


def _calculated(category: ExpenseCategory, known: dict[str, Any],
                year: TaxYear) -> CategoryEstimate:
    """Sum every item of a category through its calculator, skipping incomplete ones."""
    out = CategoryEstimate(category)
    total = 0.0
    computed_any = False

    for item_index in item_indexes(category, known):
        params, missing = to_params(category, known, item_index)
        if missing:
            out.missing.extend(missing if item_index == 0 else
                               [f"{m}#{item_index}" for m in missing])
            continue
        try:
            result = calculate(CALCULATORS[category], params, year.year)
            total += result.amount_eur
            for rule_id in result.applied_rule_ids:
                # Three invoices in one category can take three different branches, and
                # a repeated branch is still one rule: the trace shows each provision
                # once, in the order the case first met it.
                if rule_id not in out.applied_rule_ids:
                    out.applied_rule_ids.append(rule_id)
            computed_any = True
        except Exception:  # noqa: BLE001 — a partial case is not an error here
            out.missing.append(f"{category.value} (values out of range)")

    out.amount_eur = round(total, 2)
    out.computable = computed_any
    return out


def _summed(category: ExpenseCategory, known: dict[str, Any]) -> CategoryEstimate:
    amount_field, minus_field = SUMMED[category]
    out = CategoryEstimate(category)
    total = 0.0
    computed_any = False

    for item_index in item_indexes(category, known):
        amount = known.get(key_for(category, amount_field, item_index))
        if amount is None:
            out.missing.append(key_for(category, amount_field, item_index))
            continue
        reimbursed = 0.0
        if minus_field:
            reimbursed = known.get(key_for(category, minus_field, item_index)) or 0.0
        total += max(float(amount) - float(reimbursed), 0.0)
        computed_any = True

    out.amount_eur = round(total, 2)
    out.computable = computed_any
    return out


def expense_rows(known: dict[str, Any], year: Optional[TaxYear] = None) -> list[dict[str, Any]]:
    """The case's computable expenses as rows: amount, trace, category.

    One shape for both consumers — the graph's build_expenses node and the case
    detail endpoint — so the dashboard shows exactly what the review will audit.
    """
    year = year or for_year()
    rows: list[dict[str, Any]] = []
    for category, entry in estimate(known, year).per_category.items():
        if not entry.computable:
            continue
        trace: list[str] = []
        if category in CALCULATORS:
            params, missing = to_params(category, known)
            if not missing:
                trace = calculate(CALCULATORS[category], params, year.year).breakdown
        rows.append({
            "category": category.value,
            "amount_eur": entry.amount_eur,
            "form_line": f"{year.line_for(category).form} {year.line_for(category).lines}",
            "trace": trace,
            "document": None,
        })
    return rows


def item_indexes(category: ExpenseCategory, known: dict[str, Any]) -> list[int]:
    """0, plus every repeated item the case holds for this category."""
    prefix = f"{namespace_of(category)}."
    indexes = {0}
    for key in known:
        if key.startswith(prefix) and "#" in key:
            try:
                indexes.add(int(key.rsplit("#", 1)[1]))
            except ValueError:
                continue
    return sorted(indexes)
