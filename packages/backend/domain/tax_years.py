"""Everything that changes with the tax year: rates, thresholds, form lines.

One block per year, and nothing year-dependent anywhere else — not in a
calculator, not in a prompt, not in the UI (ADR 0008). German rates and the
numbering of the form both move between years, so a figure is only meaningful
together with the year whose rules produced it.

The annual update, in order: fetch the new Anlage N and its Anleitung, update the
KB, check whether the Zeilen have shifted, update the rates, add a block below.
If anything outside this file needs touching, that is the defect to fix.

Form lines are read from KB/055-anleitung-anlage-n-2025.md. Where the Anleitung
names a line verbatim, `verified` is True. Where it only names the block a figure
belongs to — "Weitere Werbungskosten, Zeile 61 bis 64" — the block is recorded
and `verified` is False, because the exact line inside it can only be pinned
against the form itself. An unverified line is safe to show as a block reference
and must not be presented as a single line number.
"""

from dataclasses import dataclass, field
from typing import Final, Optional

from domain.fields import ExpenseCategory

ANLAGE_N: Final = "anlage_n"
HAUPTVORDRUCK: Final = "hauptvordruck"


@dataclass(frozen=True)
class FormLine:
    """Where a figure is entered on the official paper form."""

    form: str
    lines: str
    parts: dict[str, str] = field(default_factory=dict)
    verified: bool = True
    note: str = ""


@dataclass(frozen=True)
class TaxYear:
    """Every rate, threshold and form line for one tax year."""

    year: int

    # Entfernungspauschale — § 9 Abs. 1 Nr. 4 EStG
    rate_km_first_20: float
    rate_km_from_21: float
    commute_cap_no_car: float

    # Homeoffice-Tagespauschale
    homeoffice_rate: float
    homeoffice_cap: float
    homeoffice_max_days: int

    # Arbeitsmittel — geringwertige Wirtschaftsgüter vs AfA
    gwg_limit_net: float

    # Arbeitnehmer-Pauschbetrag — § 9a EStG
    pauschbetrag: float

    # Telefon / Internet without receipts — H 9.1 LStH
    telecom_share: float
    telecom_monthly_cap: float

    # Plausibility, not law: above this a working-day count needs justifying
    typical_max_work_days: int

    # Doppelte Haushaltsführung rent cap — § 9 Abs. 1 Nr. 5 EStG (Inland)
    dhf_rent_cap_monthly: float

    # Above this, training costs are plausible but worth asking about
    fortbildung_attention_threshold: float

    # When a return for this year is due. ISO dates, and required rather than
    # defaulted: a year block that forgets them would make the scope statement
    # claim a filing period nobody checked. Rolled forward past a weekend or a
    # public holiday already (§ 108 Abs. 3 AO), so these are the dates as they
    # fall, not the dates in the paragraph.
    filing_due: str  # obligation to file, without an adviser - § 149 Abs. 2 AO
    filing_due_advised: str  # with a Steuerberater - § 149 Abs. 3 AO
    # Antragsveranlagung: no obligation, four years to file voluntarily - § 169 AO
    voluntary_filing_until: str

    form_lines: dict[ExpenseCategory, FormLine] = field(default_factory=dict)
    benefit_form_line: Optional[FormLine] = None

    def line_for(self, category: ExpenseCategory) -> FormLine:
        return self.form_lines[category]


# The years this build holds, one module each. Imported at the bottom rather than the
# top because a year file imports `TaxYear` and `FormLine` from here: the shape is
# shared, the content is not, and the cycle resolves in this direction only.
from domain.tax_year_2025 import YEAR_2025  # noqa: E402

TAX_YEARS: Final[dict[int, TaxYear]] = {2025: YEAR_2025}

DEFAULT_TAX_YEAR: Final = 2025


def for_year(year: int = DEFAULT_TAX_YEAR) -> TaxYear:
    """The rules for a tax year, or a clear failure naming the years we have.

    Failing loudly matters here: silently falling back to another year's rates
    would put a wrong figure in a tax document, which is the one outcome this
    project treats as unacceptable.
    """
    try:
        return TAX_YEARS[year]
    except KeyError:
        known = ", ".join(str(y) for y in sorted(TAX_YEARS))
        raise ValueError(f"No tax rules for {year}; this build covers {known}") from None
