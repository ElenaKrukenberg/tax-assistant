"""Document checklists per Werbungskosten category (Anlage N, 2025).

Curated content for topic 19 (belege): which proofs the Finanzamt may ask
for per expense category. Since 2017 receipts are kept, not submitted
(Belegvorhaltepflicht) - the checklist tells the user what to keep ready.
"""

from enum import Enum

from pydantic import BaseModel, Field


class ChecklistCategory(str, Enum):
    entfernungspauschale = "entfernungspauschale"
    homeoffice_pauschale = "homeoffice_pauschale"
    arbeitszimmer = "arbeitszimmer"
    arbeitsmittel = "arbeitsmittel"
    fortbildung = "fortbildung"
    reisekosten = "reisekosten"
    doppelte_haushaltsfuehrung = "doppelte_haushaltsfuehrung"
    umzugskosten = "umzugskosten"
    bewerbungskosten = "bewerbungskosten"
    arbeitskleidung = "arbeitskleidung"
    telefon_internet = "telefon_internet"
    berufsverbaende = "berufsverbaende"


class ChecklistItem(BaseModel):
    document: str
    required: bool = Field(description="True = expect the Finanzamt to ask; False = helpful to have")
    note: str = ""


class Checklist(BaseModel):
    category: ChecklistCategory
    items: list[ChecklistItem]
    general_note: str


GENERAL_NOTE = (
    "Since 2017 receipts are not submitted with the return but must be kept "
    "(Belegvorhaltepflicht) and provided if the Finanzamt asks."
)

_CHECKLISTS: dict[ChecklistCategory, list[ChecklistItem]] = {
    ChecklistCategory.entfernungspauschale: [
        ChecklistItem(document="Number of working days (employer confirmation or own record)", required=True),
        ChecklistItem(document="One-way distance (route planner printout)", required=False,
                      note="Shortest road connection; a longer route only if clearly more convenient"),
        ChecklistItem(document="Public-transport tickets / invoices", required=False,
                      note="Only if actual costs exceed the allowance"),
    ],
    ChecklistCategory.homeoffice_pauschale: [
        ChecklistItem(document="Record of home-office days (calendar, employer confirmation)", required=True),
        ChecklistItem(document="Employer statement that work was performed from home", required=False),
    ],
    ChecklistCategory.arbeitszimmer: [
        ChecklistItem(document="Floor plan showing the separate room", required=True),
        ChecklistItem(document="Rent contract / ancillary cost statements", required=True),
        ChecklistItem(document="Proof the room is the centre of professional activity", required=True,
                      note="e.g. employer confirmation that no other workplace is available"),
    ],
    ChecklistCategory.arbeitsmittel: [
        ChecklistItem(document="Invoices / receipts for each item", required=True),
        ChecklistItem(document="Note on professional-use share for mixed-use items", required=False,
                      note="Private use above 10% means only the share is deductible"),
    ],
    ChecklistCategory.fortbildung: [
        ChecklistItem(document="Course invoice and payment proof", required=True),
        ChecklistItem(document="Participation certificate", required=False),
        ChecklistItem(document="Travel costs to the venue (tickets, km record)", required=False),
        ChecklistItem(document="Connection to the current or targeted job", required=False,
                      note="e.g. job description - decisive for deductibility"),
    ],
    ChecklistCategory.reisekosten: [
        ChecklistItem(document="Travel dates, destinations and business purpose per trip", required=True),
        ChecklistItem(document="Transport tickets / km record for own car", required=True),
        ChecklistItem(document="Hotel invoices", required=True,
                      note="Meals in the hotel bill must be split out"),
        ChecklistItem(document="Employer statement on reimbursements", required=True,
                      note="Reimbursed amounts reduce the deduction"),
    ],
    ChecklistCategory.doppelte_haushaltsfuehrung: [
        ChecklistItem(document="Rent contract of the second home", required=True),
        ChecklistItem(document="Proof of own household at the main residence", required=True,
                      note="Financial participation in the household costs"),
        ChecklistItem(document="Record of trips home (Familienheimfahrten)", required=True),
    ],
    ChecklistCategory.umzugskosten: [
        ChecklistItem(document="Proof the move was job-related", required=True,
                      note="New contract, transfer letter, or >= 1h daily commute saved"),
        ChecklistItem(document="Moving company invoice / transport receipts", required=True),
        ChecklistItem(document="Old and new rental contracts", required=False),
    ],
    ChecklistCategory.bewerbungskosten: [
        ChecklistItem(document="List of applications (company, date, position)", required=True),
        ChecklistItem(document="Receipts for printing, postage, photos", required=False,
                      note="Plausible flat amounts are usually accepted without receipts"),
        ChecklistItem(document="Invitations to interviews + travel receipts", required=False),
    ],
    ChecklistCategory.arbeitskleidung: [
        ChecklistItem(document="Receipts for typical work clothing", required=True,
                      note="Only typische Berufskleidung (safety shoes, uniform, lab coat)"),
        ChecklistItem(document="Cleaning cost estimate", required=False),
    ],
    ChecklistCategory.telefon_internet: [
        ChecklistItem(document="Monthly bills", required=True),
        ChecklistItem(document="Usage records for a share above the 20%/20 EUR flat rate", required=False),
    ],
    ChecklistCategory.berufsverbaende: [
        ChecklistItem(document="Membership fee statement (union / professional association)", required=True),
    ],
}


def build_document_checklist(categories: list[ChecklistCategory]) -> list[Checklist]:
    """Return checklists for the requested categories (unknown ones are skipped upstream)."""
    return [
        Checklist(category=c, items=_CHECKLISTS[c], general_note=GENERAL_NOTE)
        for c in categories
        if c in _CHECKLISTS
    ]
