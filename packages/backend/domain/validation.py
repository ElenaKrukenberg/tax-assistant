"""Plausibility validation of user tax data (Anlage N).

Implements the automatable subset of the curated rules V01-V26
(KB/curated-validation-rules.md). Hard legal caps produce severity="error",
plausibility checks produce severity="warning". Only rules whose inputs are
present are evaluated - the tool works with partial data.

Every threshold used here belongs to a tax year and comes from `tax_years.py`
(ADR 0008), so validating a 2026 case is a matter of passing that year rather
than of finding the caps scattered through this file.
"""

from typing import Optional

from pydantic import BaseModel, Field

from domain.tax_years import TaxYear, for_year


class TaxData(BaseModel):
    """Partial snapshot of what the user claims - every field optional."""

    working_days_total: Optional[int] = Field(default=None, ge=0, le=366)
    commuting_days: Optional[int] = Field(default=None, ge=0, le=366)
    homeoffice_days: Optional[int] = Field(default=None, ge=0, le=366)
    homeoffice_amount_eur: Optional[float] = Field(default=None, ge=0)
    dhf_rent_monthly_eur: Optional[float] = Field(default=None, ge=0)
    telecom_monthly_claim_eur: Optional[float] = Field(default=None, ge=0)
    arbeitsmittel_immediate_net_eur: Optional[float] = Field(
        default=None, ge=0, description="Net price of an item deducted in full in the purchase year"
    )
    arbeitszimmer_actual_costs: Optional[bool] = None
    homeoffice_pauschale_claimed: Optional[bool] = None
    total_werbungskosten_eur: Optional[float] = Field(default=None, ge=0)
    fortbildung_costs_eur: Optional[float] = Field(default=None, ge=0)
    expense_year: Optional[int] = None


class Finding(BaseModel):
    rule_id: str
    severity: str  # "error" | "warning" | "info"
    message: str


class ValidationReport(BaseModel):
    valid: bool
    findings: list[Finding]
    checked_rules: list[str]


def validate_tax_data(data: TaxData, y: Optional[TaxYear] = None) -> ValidationReport:
    y = y or for_year()
    findings: list[Finding] = []
    checked: list[str] = []

    def check(rule_id: str):
        checked.append(rule_id)

    # V01: plausible number of working days
    if data.working_days_total is not None:
        check("V01")
        if data.working_days_total > y.typical_max_work_days:
            findings.append(Finding(
                rule_id="V01", severity="warning",
                message=f"{data.working_days_total} working days exceeds the typical maximum of ~{y.typical_max_work_days} "
                        f"(needs justification, e.g. a 6-day week)",
            ))

    # V02: a day is either home office or commute
    if data.homeoffice_days is not None and data.commuting_days is not None:
        check("V02")
        total = data.homeoffice_days + data.commuting_days
        limit = data.working_days_total if data.working_days_total is not None else y.typical_max_work_days
        if total > limit:
            findings.append(Finding(
                rule_id="V02", severity="error",
                message=f"homeoffice ({data.homeoffice_days}) + commute ({data.commuting_days}) = {total} days "
                        f"exceeds {limit} - the same day cannot be counted twice",
            ))

    # V03: home office day cap
    if data.homeoffice_days is not None:
        check("V03")
        if data.homeoffice_days > y.homeoffice_max_days:
            findings.append(Finding(
                rule_id="V03", severity="error",
                message=f"Homeoffice-Pauschale counts at most {y.homeoffice_max_days} days "
                        f"({data.homeoffice_days} entered)",
            ))

    # V10: home office amount cap
    if data.homeoffice_amount_eur is not None:
        check("V10")
        if data.homeoffice_amount_eur > y.homeoffice_cap:
            findings.append(Finding(
                rule_id="V10", severity="error",
                message=f"Homeoffice-Pauschale is capped at {y.homeoffice_cap:.0f} EUR/year "
                        f"({data.homeoffice_amount_eur:.2f} EUR claimed)",
            ))

    # V12: double household rent cap
    if data.dhf_rent_monthly_eur is not None:
        check("V12")
        if data.dhf_rent_monthly_eur > y.dhf_rent_cap_monthly:
            findings.append(Finding(
                rule_id="V12", severity="error",
                message=f"Doppelte Haushaltsfuehrung rent is deductible up to {y.dhf_rent_cap_monthly:.0f} EUR/month "
                        f"in Germany ({data.dhf_rent_monthly_eur:.2f} EUR claimed)",
            ))

    # V14: telecom flat-rate cap
    if data.telecom_monthly_claim_eur is not None:
        check("V14")
        if data.telecom_monthly_claim_eur > y.telecom_monthly_cap:
            findings.append(Finding(
                rule_id="V14", severity="warning",
                message=f"Without receipts, phone/internet is capped at {y.telecom_monthly_cap:.0f} EUR/month; "
                        f"{data.telecom_monthly_claim_eur:.2f} EUR/month needs itemised proof",
            ))

    # V15: GWG immediate deduction threshold
    if data.arbeitsmittel_immediate_net_eur is not None:
        check("V15")
        if data.arbeitsmittel_immediate_net_eur > y.gwg_limit_net:
            findings.append(Finding(
                rule_id="V15", severity="error",
                message=f"Items above {y.gwg_limit_net:.0f} EUR net cannot be deducted at once - "
                        f"use AfA over the useful life (digital equipment: 1 year)",
            ))

    # V20: itemising vs Pauschbetrag
    if data.total_werbungskosten_eur is not None:
        check("V20")
        if data.total_werbungskosten_eur <= y.pauschbetrag:
            findings.append(Finding(
                rule_id="V20", severity="info",
                message=f"Total Werbungskosten ({data.total_werbungskosten_eur:.2f} EUR) does not exceed the "
                        f"automatic Pauschbetrag of {y.pauschbetrag:.0f} EUR - itemising brings no benefit",
            ))

    # V23: Arbeitszimmer actual costs XOR Homeoffice-Pauschale
    if data.arbeitszimmer_actual_costs is not None and data.homeoffice_pauschale_claimed is not None:
        check("V23")
        if data.arbeitszimmer_actual_costs and data.homeoffice_pauschale_claimed:
            findings.append(Finding(
                rule_id="V23", severity="error",
                message="Arbeitszimmer actual costs and the Homeoffice-Pauschale are alternative regimes - "
                        "claim one, not both",
            ))

    # V25: unusually high training costs
    if data.fortbildung_costs_eur is not None:
        check("V25")
        if data.fortbildung_costs_eur > y.fortbildung_attention_threshold:
            findings.append(Finding(
                rule_id="V25", severity="warning",
                message=f"Fortbildung costs of {data.fortbildung_costs_eur:.2f} EUR are unusually high - "
                        f"plausible (MBA, certification), but be ready to provide details",
            ))

    # V26: expense must belong to the tax year
    if data.expense_year is not None:
        check("V26")
        if data.expense_year != y.year:
            findings.append(Finding(
                rule_id="V26", severity="error",
                message=f"This assistant covers tax year {y.year}; the expense is dated {data.expense_year} "
                        f"(Zufluss/Abfluss principle, § 11 EStG)",
            ))

    has_errors = any(f.severity == "error" for f in findings)
    return ValidationReport(valid=not has_errors, findings=findings, checked_rules=checked)
