"""What the model is asked for, per document type - and nothing beyond it.

Two things shape this file, and neither is a preference.

**The provider's limits, measured (issue #65).** `claude-haiku-4.5` served by Amazon
Bedrock refuses a nullable enum outright and caps union-typed parameters at 16, so
every enum here is a plain string with an explicit "unbekannt" member, and there is
one schema per document type rather than one union over both. Intake knows the type
before it asks - the user picks it - so the split costs nothing.

**Data minimisation.** These schemas are deliberately much smaller than the ones in
`eval/vision_sweep`, which is a measuring rig and grades everything a document
carries. Here a field exists only if it maps onto something the product uses: the
Lohnsteuerbescheinigung yields the employment period and the tax year and nothing
else, because nothing else has a home in `domain/fields.py`. Not extracted, on
purpose: the employee's name, the eTIN, the tax class, the gross salary, the
withheld taxes - and the Kirchensteuer, which says whether someone belongs to a
church that levies it (Art. 9 GDPR, see `sensitivity.py`). A field that is not
extracted is a field that cannot be stored, logged or traced by accident.

There is no `confidence` field. Issue #11 measured it and it does not track
correctness; two independent reads that disagree do (`compare.py`).
"""

from __future__ import annotations

from typing import Any, Final, Optional

from pydantic import BaseModel, ConfigDict

from services.documents.sensitivity import DocumentKind

# The measured shapes. `["number", "null"]` and not Pydantic's `anyOf` form, because
# `["number", "null"]` is what the sweep actually sent to 24 models; the anyOf variant
# is untested here and this is not the place to find out.
_MONEY: Final = {"type": ["number", "null"]}
_DATE: Final = {"type": ["string", "null"]}
_TEXT: Final = {"type": ["string", "null"]}
_INT: Final = {"type": ["integer", "null"]}

# Every schema can name every supported type plus "unbekannt". That is what makes the
# type the user picked checkable: asked for a Rechnung and handed a payslip, the model
# says so in this field instead of inventing invoice rows (extract.py refuses it).
_DOCUMENT_TYPE: Final = {
    "type": "string",
    "enum": [*(k.value for k in DocumentKind), "unbekannt"],
}

PAYSLIP_PROPERTIES: Final[dict[str, Any]] = {
    "document_type": _DOCUMENT_TYPE,
    "tax_year": _INT,
    "employment_period_start": _DATE,
    "employment_period_end": _DATE,
}

INVOICE_PROPERTIES: Final[dict[str, Any]] = {
    "document_type": _DOCUMENT_TYPE,
    "invoice_date": _DATE,
    # Whether the line prices and the totals are net or gross has to be *read*, not
    # assumed: the test invoice prices its lines net and adds 19% USt at the bottom,
    # so defaulting to "a receipt shows the gross price" would deduct the wrong base.
    # "unknown" is a real answer and goes to the user rather than to a calculator.
    "price_basis": {"type": "string", "enum": ["net", "gross", "unknown"]},
    "net_total_eur": _MONEY,
    "vat_rate_percent": _MONEY,
    "vat_amount_eur": _MONEY,
    "gross_total_eur": _MONEY,
    "line_items": {
        "type": ["array", "null"],
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["description", "quantity", "unit_price_eur"],
            "properties": {
                # The description is the one piece of free text worth having: it is
                # what the category rules read ("Bürostuhl" against "Restaurant"),
                # and it is about the purchase rather than about a person. The
                # supplier's name is not extracted - "Bürotechnik Hoffmann e.K." is
                # a person's name in company clothing, and no rule needs it.
                "description": _TEXT,
                "quantity": _MONEY,
                "unit_price_eur": _MONEY,
            },
        },
    },
}


def json_schema(name: str, properties: dict[str, Any]) -> dict[str, Any]:
    """The `response_format.json_schema` payload for one document type."""
    return {
        "name": name,
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": properties,
        },
    }


PAYSLIP_SCHEMA: Final = json_schema("lohnsteuerbescheinigung", PAYSLIP_PROPERTIES)
INVOICE_SCHEMA: Final = json_schema("rechnung", INVOICE_PROPERTIES)

SCHEMA_FOR: Final[dict[DocumentKind, dict[str, Any]]] = {
    DocumentKind.lohnsteuerbescheinigung: PAYSLIP_SCHEMA,
    DocumentKind.rechnung: INVOICE_SCHEMA,
}


# --- what comes back ------------------------------------------------------------
#
# The schema above is what the provider is given; these models are what the reply is
# read into, so a malformed answer is a validation error here rather than a KeyError
# three modules later. `tests/test_document_intake.py` holds the two in step field for
# field, name and type - one source would be better, but Pydantic emits the `anyOf`
# form of a nullable field and that form is not the one that was measured.


class InvoiceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price_eur: Optional[float] = None


class Payslip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str
    tax_year: Optional[int] = None
    employment_period_start: Optional[str] = None
    employment_period_end: Optional[str] = None


class Invoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: str
    price_basis: str = "unknown"
    invoice_date: Optional[str] = None
    net_total_eur: Optional[float] = None
    vat_rate_percent: Optional[float] = None
    vat_amount_eur: Optional[float] = None
    gross_total_eur: Optional[float] = None
    line_items: Optional[list[InvoiceLine]] = None


MODEL_FOR: Final[dict[DocumentKind, type[BaseModel]]] = {
    DocumentKind.lohnsteuerbescheinigung: Payslip,
    DocumentKind.rechnung: Invoice,
}
