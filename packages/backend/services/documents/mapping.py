"""From what the model read to the Fact keys a Tax Case stores.

Two documents, two shapes, and neither maps one-to-one:

**A Lohnsteuerbescheinigung yields one fact.** The employment period becomes
`profile.employed_months`, and that is the whole of it - the tax year is checked
against the case rather than stored, and nothing else on the form has a home in
`domain/fields.py` yet. Several payslips are the ordinary case (two employers, or a
job change mid-year), so the months are the **union of the periods**, never the last
document's own: overwriting would turn two half-year jobs into half a year of work.

**An invoice yields one item per thing bought.** An integer quantity is expanded
into separate items at the unit price, because the low-value threshold that decides
whether an Arbeitsmittel is deducted at once or written off over its useful life
applies per item - two monitor arms at 46.25 EUR are two items, not one at 92.50.

Nothing here decides a category (`classify.py`) and nothing here writes (the
workflow does, after the user has confirmed). What it does do is refuse to guess:
every value it cannot derive honestly comes back as a question for the human.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from domain.fields import ExpenseCategory, key_for
from services.documents.schemas import Invoice, Payslip


@dataclass(frozen=True)
class ProposedValue:
    """One value the document offers, keyed as the case keys it."""

    key: str
    value: Any


@dataclass
class Proposal:
    """What a document offers, and what it cannot answer on its own."""

    values: list[ProposedValue] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


def parse_date(value: Optional[str]) -> Optional[date]:
    """A date the model wrote, in the format asked for or the German one.

    Both, because the prompt asks for `YYYY-MM-DD` and a model that is reading
    `08.09.2025` off a page sometimes hands it back as it stands. Refusing that would
    turn a correct read into a failure; guessing between `08.09` and `09.08` would be
    worse than either, so an ambiguous German-looking date is not parsed here at all -
    `08.09.2025` is unambiguous only because 2025 cannot be a day.
    """
    if not value:
        return None
    text = value.strip()
    for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def months_in_year(periods: list[tuple[date, date]], tax_year: int) -> int:
    """How many months of the tax year the periods cover, counted once each.

    A month is counted if any day of it falls inside a period, which is how the
    question is meant ("in how many months of 2025 were you in employment?") and what
    makes two overlapping payslips add up to twelve rather than to twenty-four.
    """
    covered: set[int] = set()
    for start, end in periods:
        if end < start:
            continue
        for month in range(1, 13):
            first = date(tax_year, month, 1)
            last = date(tax_year + 1, 1, 1) if month == 12 else date(tax_year, month + 1, 1)
            if start < last and end >= first:
                covered.add(month)
    return len(covered)


def payslip_proposal(
    payslip: Payslip, *, tax_year: int, periods_from_other_documents: list[tuple[date, date]],
) -> Proposal:
    """What one payslip offers, together with what the case already holds."""
    out = Proposal()

    if payslip.tax_year is not None and payslip.tax_year != tax_year:
        out.questions.append(
            f"The document is for {payslip.tax_year}, this case is for {tax_year}. "
            "Upload the document for the right year, or open the other case."
        )
        return out

    start = parse_date(payslip.employment_period_start)
    end = parse_date(payslip.employment_period_end)
    if start is None or end is None:
        out.questions.append(
            "The employment period could not be read. Enter the number of months in "
            "employment yourself."
        )
        return out
    if end < start:
        out.questions.append(
            f"The period reads {start} to {end}, which ends before it begins. Check "
            "the dates on the document."
        )
        return out

    months = months_in_year([*periods_from_other_documents, (start, end)], tax_year)
    if months == 0:
        out.questions.append(
            f"The period {start} to {end} lies outside {tax_year} entirely."
        )
        return out

    out.values.append(ProposedValue(key_for(None, "employed_months"), months))
    return out


def invoice_proposal(
    invoice: Invoice, *, category: ExpenseCategory, first_index: int = 0,
) -> Proposal:
    """What one invoice offers for the category it was classified into.

    `first_index` is where this document's items start, so a second invoice in the
    same category adds items rather than replacing the first one's.
    """
    out = Proposal()
    repeating = category is ExpenseCategory.arbeitsmittel

    net = {"net": True, "gross": False}.get(invoice.price_basis)
    if net is None:
        out.questions.append(
            "Whether the prices on this invoice are net or gross could not be read. "
            "Say which, so VAT is not counted twice or dropped."
        )

    invoice_date = parse_date(invoice.invoice_date)
    if invoice_date is None and repeating:
        out.questions.append(
            "The invoice date could not be read, and the purchase month decides how a "
            "write-off is split across years. Enter the month."
        )

    prices = _item_prices(invoice, out)
    if not prices:
        return out

    if not repeating:
        # The other three categories are a sum of receipts with one amount each, so
        # the invoice total is the figure - and it has to be the total, not the first
        # line, or a three-line seminar invoice would claim a third of itself.
        total = invoice.gross_total_eur if net is False else invoice.net_total_eur
        if total is None:
            total = round(sum(prices), 2)
        out.values.append(ProposedValue(key_for(category, "amount_eur", first_index), total))
        return out

    for offset, price in enumerate(prices):
        index = first_index + offset
        out.values.append(ProposedValue(key_for(category, "price_eur", index), price))
        if net is not None:
            out.values.append(ProposedValue(key_for(category, "price_is_net", index), net))
        if invoice_date is not None:
            out.values.append(
                ProposedValue(key_for(category, "purchase_month", index), invoice_date.month)
            )
    return out


def _item_prices(invoice: Invoice, out: Proposal) -> list[float]:
    """One price per thing bought, integer quantities expanded.

    A fractional or unreadable quantity is not divided or rounded: 1.5 of something is
    either a typo or a unit this product does not understand, and both are questions.
    """
    lines = invoice.line_items or []
    if not lines:
        # An invoice with no readable lines but a readable total is still usable - one
        # item at the total. It is the receipt for a single purchase, which is most of
        # them.
        total = invoice.gross_total_eur or invoice.net_total_eur
        if total is None:
            out.questions.append(
                "Neither the individual items nor a total could be read from this "
                "document. Enter the amount yourself, or upload a clearer photo."
            )
            return []
        return [total]

    prices: list[float] = []
    for line in lines:
        if line.unit_price_eur is None:
            out.questions.append(
                f"No price could be read for \"{line.description or 'one item'}\". "
                "Enter it yourself."
            )
            continue
        quantity = 1.0 if line.quantity is None else float(line.quantity)
        if quantity <= 0 or quantity != int(quantity):
            out.questions.append(
                f"The quantity for \"{line.description or 'one item'}\" reads "
                f"{line.quantity!r}. Enter how many were bought."
            )
            continue
        prices.extend([line.unit_price_eur] * int(quantity))
    return prices
