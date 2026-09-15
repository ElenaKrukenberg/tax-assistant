"""Tax calculations for Anlage N.

Pure domain logic: no LLM, no FastAPI, no tool-schema concerns. Every function
takes a validated Pydantic model plus the rules of one tax year, and returns a
CalculationResult with the amount, a human-readable breakdown and warnings
referencing the validation rules (V01-V26, see KB/curated-validation-rules.md).

Rates and thresholds are not defined here. They belong to a tax year and live in
`tax_years.py` (ADR 0008), because both the German rates and the numbering of the
form move between years, and a figure means nothing without the year that
produced it. The year defaults to the only one populated so far; new callers
should pass it from the Tax Case instead of relying on the default.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from domain.tax_years import DEFAULT_TAX_YEAR, TaxYear, for_year


class CalculationType(str, Enum):
    entfernungspauschale = "entfernungspauschale"
    homeoffice_pauschale = "homeoffice_pauschale"
    arbeitsmittel = "arbeitsmittel"
    pauschbetrag_comparison = "pauschbetrag_comparison"
    telefon_internet = "telefon_internet"


class CalculationResult(BaseModel):
    calculation_type: CalculationType
    amount_eur: float
    breakdown: list[str]
    warnings: list[str] = Field(default_factory=list)
    inputs: dict = Field(default_factory=dict)
    # Which branches actually ran, in the order they ran, as ids into
    # `domain/rule_citations.py`. Reported rather than inferred from the category:
    # an item under 800 EUR net and one written off over its useful life are the same
    # category and different provisions, and a trace that cited the category would put
    # a passage about low-value assets beside a depreciation figure.
    applied_rule_ids: list[str] = Field(default_factory=list)


def rule(year: int, category: str, branch: str) -> str:
    """One id, built the same way the catalogue writes it."""
    return f"anlage-n:{year}:{category}:{branch}:v1"


# --- 1. Entfernungspauschale ---

class CommuteParams(BaseModel):
    commuting_days: int = Field(..., ge=1, le=366, description="Days the employee commuted to the first place of work")
    distance_km: int = Field(..., ge=1, le=1000, description="One-way distance home to workplace, full kilometres")
    own_car: bool = Field(default=False, description="True if an own or employer-provided car was used")
    public_transport_cost_eur: Optional[float] = Field(
        default=None, ge=0, description="Actual yearly public-transport ticket costs, if any"
    )


def calc_entfernungspauschale(p: CommuteParams, y: Optional[TaxYear] = None) -> CalculationResult:
    y = y or for_year()
    near = min(p.distance_km, 20)
    far = max(p.distance_km - 20, 0)
    per_day = near * y.rate_km_first_20 + far * y.rate_km_from_21
    raw = round(p.commuting_days * per_day, 2)

    breakdown = [
        f"{p.commuting_days} days x ({near} km x {y.rate_km_first_20:.2f} EUR"
        + (f" + {far} km x {y.rate_km_from_21:.2f} EUR" if far else "")
        + f") = {raw:.2f} EUR",
    ]
    warnings = []
    applied = [rule(y.year, "entfernungspauschale", "per-km")]

    amount = raw
    if not p.own_car and raw > y.commute_cap_no_car:
        amount = y.commute_cap_no_car
        breakdown.append(f"Capped at {y.commute_cap_no_car:.0f} EUR/year (no own car used, § 9 Abs. 1 Nr. 4 EStG)")
        applied.append(rule(y.year, "entfernungspauschale", "cap-without-own-car"))

    if p.public_transport_cost_eur is not None and p.public_transport_cost_eur > amount:
        amount = round(p.public_transport_cost_eur, 2)
        applied.append(rule(y.year, "entfernungspauschale", "actual-public-transport"))
        breakdown.append(
            f"Actual public-transport costs ({p.public_transport_cost_eur:.2f} EUR) exceed the "
            f"allowance and are deducted instead"
        )

    if p.commuting_days > y.typical_max_work_days:
        warnings.append(
            f"V01: {p.commuting_days} commuting days is above the typical maximum of ~{y.typical_max_work_days} "
            "working days per year - double-check the number"
        )
    warnings.append("V21: distance_km must be the one-way distance, not the round trip")

    return CalculationResult(
        calculation_type=CalculationType.entfernungspauschale,
        amount_eur=amount, breakdown=breakdown, warnings=warnings, inputs=p.model_dump(),
        applied_rule_ids=applied,
    )


# --- 2. Homeoffice-Pauschale ---

class HomeofficeParams(BaseModel):
    homeoffice_days: int = Field(..., ge=1, le=366, description="Days worked from home")
    commuting_days: Optional[int] = Field(
        default=None, ge=0, le=366,
        description="Days commuted to the workplace (for the same-day exclusivity check)",
    )


def calc_homeoffice_pauschale(p: HomeofficeParams, y: Optional[TaxYear] = None) -> CalculationResult:
    y = y or for_year()
    effective_days = min(p.homeoffice_days, y.homeoffice_max_days)
    amount = round(effective_days * y.homeoffice_rate, 2)

    breakdown = [f"{effective_days} days x {y.homeoffice_rate:.0f} EUR = {amount:.2f} EUR"]
    warnings = []
    applied = [rule(y.year, "homeoffice", "tagespauschale")]

    if p.homeoffice_days > y.homeoffice_max_days:
        applied.append(rule(y.year, "homeoffice", "yearly-cap"))
        # Worded as the provision words it. § 4 Abs. 5 Satz 1 Nr. 6c EStG caps the
        # *amount* at 1,260 EUR a year, not the number of days; the day limit is
        # arithmetic on our side (1,260 / 6 = 210) and saying "only 210 days count"
        # put a sentence next to the quotation that the quotation does not contain.
        breakdown.append(
            f"Capped at the yearly maximum of {y.homeoffice_cap:.0f} EUR (V03/V10)"
        )
        warnings.append(
            f"V03: {p.homeoffice_days} days entered; the yearly cap of "
            f"{y.homeoffice_cap:.0f} EUR is reached at {y.homeoffice_max_days} days"
        )

    total_days = p.homeoffice_days + (p.commuting_days or 0)
    if p.commuting_days is not None and total_days > y.typical_max_work_days:
        warnings.append(
            f"V02: homeoffice ({p.homeoffice_days}) + commute ({p.commuting_days}) = {total_days} days "
            f"exceeds ~{y.typical_max_work_days} working days/year - a day is either home office or commute"
        )
    warnings.append("V22: the Homeoffice-Pauschale and the Entfernungspauschale cannot be claimed for the same day")

    return CalculationResult(
        calculation_type=CalculationType.homeoffice_pauschale,
        amount_eur=amount, breakdown=breakdown, warnings=warnings, inputs=p.model_dump(),
        applied_rule_ids=applied,
    )


# --- 3. Arbeitsmittel (GWG / AfA) ---

class ArbeitsmittelParams(BaseModel):
    price_eur: float = Field(..., gt=0, description="Purchase price")
    price_is_net: bool = Field(default=False, description="True if price is net (without 19% VAT)")
    purchase_month: int = Field(..., ge=1, le=12, description="Month of purchase in the tax year")
    is_digital: bool = Field(
        default=False,
        description="Computers/peripherals/software: 1-year useful life since 2021",
    )
    useful_life_years: int = Field(
        default=3, ge=1, le=15,
        description="Useful life for AfA if not digital (e.g. office furniture: 13 years, phone: 5)",
    )
    professional_share_pct: int = Field(
        default=100, ge=1, le=100, description="Professional-use share in percent"
    )


def calc_arbeitsmittel(p: ArbeitsmittelParams, y: Optional[TaxYear] = None) -> CalculationResult:
    y = y or for_year()
    net = p.price_eur if p.price_is_net else round(p.price_eur / 1.19, 2)
    share = p.professional_share_pct / 100
    breakdown = []
    warnings = []
    applied: list[str] = []

    if not p.price_is_net:
        breakdown.append(f"Net price: {p.price_eur:.2f} EUR / 1.19 = {net:.2f} EUR")

    deductible_base = round(p.price_eur * share, 2)  # deduction uses the gross price
    if share < 1:
        breakdown.append(f"Professional share {p.professional_share_pct}%: {deductible_base:.2f} EUR")
        applied.append(rule(y.year, "arbeitsmittel", "professional-share"))
    if p.professional_share_pct < 90:
        warnings.append(
            "Private use above 10% - only the professional share is deductible; "
            "be ready to justify the split (Anhang 18a)"
        )

    if net <= y.gwg_limit_net:
        amount = deductible_base
        breakdown.append(
            f"Net price <= {y.gwg_limit_net:.0f} EUR (GWG, V15): fully deductible in {y.year}"
        )
        applied.append(rule(y.year, "arbeitsmittel", "low-value-asset"))
    elif p.is_digital:
        amount = deductible_base
        breakdown.append("Digital equipment: 1-year useful life since 2021 - fully deductible in the purchase year")
        applied.append(rule(y.year, "arbeitsmittel", "digital-one-year"))
    else:
        months_in_first_year = 12 - p.purchase_month + 1
        annual = p.price_eur * share / p.useful_life_years
        amount = round(annual * months_in_first_year / 12, 2)
        breakdown.append(
            f"AfA over {p.useful_life_years} years: {annual:.2f} EUR/year, "
            f"first year pro-rata {months_in_first_year}/12 months = {amount:.2f} EUR (V15)"
        )
        applied.append(rule(y.year, "arbeitsmittel", "depreciation"))
        warnings.append(
            f"Remaining {p.useful_life_years - 1} years continue with {annual:.2f} EUR/year "
            f"(last year: the remainder)"
        )

    return CalculationResult(
        calculation_type=CalculationType.arbeitsmittel,
        amount_eur=amount, breakdown=breakdown, warnings=warnings, inputs=p.model_dump(),
        applied_rule_ids=applied,
    )


# --- 4. Pauschbetrag comparison ---

class PauschbetragParams(BaseModel):
    total_werbungskosten_eur: float = Field(..., ge=0, description="Sum of all itemised Werbungskosten")


def calc_pauschbetrag_comparison(p: PauschbetragParams, y: Optional[TaxYear] = None) -> CalculationResult:
    y = y or for_year()
    diff = round(p.total_werbungskosten_eur - y.pauschbetrag, 2)
    applied = [rule(y.year, "pauschbetrag",
                    "itemised-exceeds" if diff > 0 else "allowance-wins")]
    if diff > 0:
        breakdown = [
            f"Itemised {p.total_werbungskosten_eur:.2f} EUR > Pauschbetrag {y.pauschbetrag:.0f} EUR: "
            f"itemising saves taxes on additional {diff:.2f} EUR (V20)"
        ]
    else:
        breakdown = [
            f"Itemised {p.total_werbungskosten_eur:.2f} EUR <= Pauschbetrag {y.pauschbetrag:.0f} EUR: "
            "the flat allowance is granted automatically, itemising brings no benefit (V20)"
        ]
    return CalculationResult(
        calculation_type=CalculationType.pauschbetrag_comparison,
        amount_eur=max(diff, 0.0), breakdown=breakdown, inputs=p.model_dump(),
        applied_rule_ids=applied,
    )


# --- 5. Telefon / Internet ---

class TelecomParams(BaseModel):
    monthly_bill_eur: float = Field(..., gt=0, description="Average monthly phone/internet bill")
    months: int = Field(default=12, ge=1, le=12)


def calc_telefon_internet(p: TelecomParams, y: Optional[TaxYear] = None) -> CalculationResult:
    y = y or for_year()
    per_month = round(min(p.monthly_bill_eur * y.telecom_share, y.telecom_monthly_cap), 2)
    amount = round(per_month * p.months, 2)
    breakdown = [
        f"Without receipts (H 9.1 LStH, V14): min(20% x {p.monthly_bill_eur:.2f} EUR, "
        f"{y.telecom_monthly_cap:.0f} EUR) = {per_month:.2f} EUR/month x {p.months} months = {amount:.2f} EUR"
    ]
    warnings = ["A higher professional share is deductible with itemised proof (call logs / usage records)"]
    return CalculationResult(
        calculation_type=CalculationType.telefon_internet,
        amount_eur=amount, breakdown=breakdown, warnings=warnings, inputs=p.model_dump(),
        applied_rule_ids=[rule(y.year, "telefon-internet", "flat-share")],
    )


# --- dispatcher ---

PARAMS_BY_TYPE = {
    CalculationType.entfernungspauschale: CommuteParams,
    CalculationType.homeoffice_pauschale: HomeofficeParams,
    CalculationType.arbeitsmittel: ArbeitsmittelParams,
    CalculationType.pauschbetrag_comparison: PauschbetragParams,
    CalculationType.telefon_internet: TelecomParams,
}

_FUNCTIONS = {
    CalculationType.entfernungspauschale: calc_entfernungspauschale,
    CalculationType.homeoffice_pauschale: calc_homeoffice_pauschale,
    CalculationType.arbeitsmittel: calc_arbeitsmittel,
    CalculationType.pauschbetrag_comparison: calc_pauschbetrag_comparison,
    CalculationType.telefon_internet: calc_telefon_internet,
}


def calculate(
    calculation_type: CalculationType,
    params: dict,
    tax_year: int = DEFAULT_TAX_YEAR,
) -> CalculationResult:
    """Validate params for the given type and run the calculation for that year.

    The year is an argument rather than part of `params` on purpose: the tool
    schema handed to the model is built from `PARAMS_BY_TYPE`, and the year must
    come from the Tax Case, not from the model's guess about it.
    """
    model = PARAMS_BY_TYPE[calculation_type]
    return _FUNCTIONS[calculation_type](model(**params), for_year(tax_year))
