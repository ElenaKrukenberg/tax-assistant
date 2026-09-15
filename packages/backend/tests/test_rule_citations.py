"""Every citation in the rule catalogue, checked against the files in `KB/`.

What a person decides and what a machine decides are split here on purpose. That an
excerpt about low-value assets *supports* the branch that deducts an item at once is a
reading of the law: it is made in `domain/rule_citations.py`, reviewed like any other
code, and no test can confirm it. Everything mechanical around that reading is checked
here - that the source is official, that its year and form match the figure it backs,
that the words are in the file exactly as quoted, that they fall inside one chunk and
that the chunk id written down is that chunk.

The alternative was a model asked at runtime whether a quotation supports a claim.
That is weaker on three counts: it costs money on every request, it can answer
differently on two identical requests, and it can approve a bad citation - so the
guarantee would be "a model thought so once", which is not what a quotation beside a
figure on a tax return should mean.

No network and no model: this reads files and runs the same chunker ingestion runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.chunking import chunk_document, parse_frontmatter
from domain.calculations import CalculationType
from domain.rule_citations import BY_YEAR, RuleCitation

KB = Path(__file__).resolve().parents[3] / "KB"

CITED = [c for year in BY_YEAR for c in BY_YEAR[year] if c.is_cited]
UNCITED = [c for year in BY_YEAR for c in BY_YEAR[year] if not c.is_cited]


def normalise(text: str) -> str:
    """Compare words, not typesetting.

    The PDFs these files came from carry non-breaking and soft hyphens and wrap lines
    mid-sentence, so a quotation that is correct to the eye differs byte for byte. The
    normalisation is deliberately narrow - whitespace and those two characters - so it
    cannot paper over a changed word or a changed number.
    """
    return re.sub(r"\s+", " ", text.replace("‑", "-").replace("­", "")).strip()


def source_path(citation: RuleCitation) -> Path:
    return KB / f"{citation.source_id}.md"


@pytest.mark.parametrize("citation", CITED, ids=lambda c: c.rule_id)
def test_the_source_is_official_and_for_the_right_year_and_form(citation: RuleCitation):
    """A citation is only worth printing if it comes from the Finanzamt's own text."""
    path = source_path(citation)
    assert path.exists(), f"{citation.rule_id}: {path.name} is not in KB/"
    front, _ = parse_frontmatter(path.read_text(encoding="utf-8"))

    assert front.get("source_type") == "official", citation.rule_id
    assert front.get("source_id") == citation.source_id, citation.rule_id
    assert front.get("form_id") == "anlage_n", citation.rule_id
    # The year on the rule and the year on the source have to be the same year. A 2025
    # figure backed by a 2024 passage is the failure the year files exist to prevent.
    year = int(citation.rule_id.split(":")[1])
    assert int(front.get("tax_year")) == year, citation.rule_id


@pytest.mark.parametrize("citation", CITED, ids=lambda c: c.rule_id)
def test_the_excerpt_is_in_the_source_word_for_word(citation: RuleCitation):
    body = source_path(citation).read_text(encoding="utf-8")
    assert normalise(citation.excerpt) in normalise(body), (
        f"{citation.rule_id}: the quotation is not in {citation.source_id} as written"
    )


@pytest.mark.parametrize("citation", CITED, ids=lambda c: c.rule_id)
def test_the_excerpt_falls_in_exactly_one_chunk_and_it_is_the_recorded_one(
    citation: RuleCitation,
):
    """Two hits is a real failure mode, not a hypothetical.

    The first excerpt written for the commuting rate matched two chunks, because § 9
    EStG states the same rate again for journeys home under a second household. Either
    chunk id would have passed a "the words are in the file" check, and the trace would
    have pointed at a rule about a different deduction.
    """
    text = source_path(citation).read_text(encoding="utf-8")
    chunks = chunk_document(text, citation.source_id)
    holding = [c.chunk_id for c in chunks if normalise(citation.excerpt) in normalise(c.text)]

    assert len(holding) == 1, (
        f"{citation.rule_id}: the quotation is in {len(holding)} chunks ({holding}); "
        "make it long enough to be unambiguous"
    )
    assert holding[0] == citation.chunk_id, (
        f"{citation.rule_id}: recorded {citation.chunk_id}, found in {holding[0]}"
    )


def test_a_branch_with_no_source_yet_says_so_rather_than_being_absent():
    """The gap is carried, not hidden.

    An entry with an empty excerpt is how a branch that `KB/` cannot back yet stays
    visible: it names the provision it is waiting for, and issue #93 is where it gets
    a source. An absent entry would look like a branch nobody thought about.
    """
    for citation in UNCITED:
        assert citation.reference, f"{citation.rule_id}: an uncited rule must still name the provision"
        assert not citation.source_id and not citation.chunk_id, (
            f"{citation.rule_id}: half a citation is worse than none"
        )
    assert [c.rule_id for c in UNCITED] == [
        "anlage-n:2025:arbeitsmittel:professional-share:v1"
    ], "a new uncited rule appeared - add it to issue #93 before widening this list"


# --- coverage: every branch that can change a figure has an entry ----------------

def every_branch_that_can_run() -> set[str]:
    """The rule ids the calculators actually emit, by running every branch.

    Driven rather than declared. A list of expected ids written by hand would be the
    same list twice and would agree with itself while both drifted from the code; this
    runs the calculators over inputs chosen to take each path, so a branch that stops
    reporting its rule shows up as a missing id.
    """
    from domain import calculations as c

    results = [
        # commute: plain, then the cap without an own car, then real tickets on top
        c.calc_entfernungspauschale(c.CommuteParams(commuting_days=200, distance_km=30, own_car=True)),
        c.calc_entfernungspauschale(c.CommuteParams(commuting_days=220, distance_km=90, own_car=False)),
        c.calc_entfernungspauschale(c.CommuteParams(
            commuting_days=200, distance_km=30, own_car=True, public_transport_cost_eur=9000)),
        # home office: under the cap, then over it
        c.calc_homeoffice_pauschale(c.HomeofficeParams(homeoffice_days=100)),
        c.calc_homeoffice_pauschale(c.HomeofficeParams(homeoffice_days=300)),
        # equipment: low-value, digital, depreciated, and a part-private item
        c.calc_arbeitsmittel(c.ArbeitsmittelParams(price_eur=300, purchase_month=3)),
        c.calc_arbeitsmittel(c.ArbeitsmittelParams(price_eur=2000, purchase_month=3, is_digital=True)),
        c.calc_arbeitsmittel(c.ArbeitsmittelParams(price_eur=2000, purchase_month=3, useful_life_years=13)),
        c.calc_arbeitsmittel(c.ArbeitsmittelParams(price_eur=300, purchase_month=3,
                                                   professional_share_pct=60)),
        # the flat allowance, both ways round
        c.calc_pauschbetrag_comparison(c.PauschbetragParams(total_werbungskosten_eur=3000)),
        c.calc_pauschbetrag_comparison(c.PauschbetragParams(total_werbungskosten_eur=200)),
        # phone and internet
        c.calc_telefon_internet(c.TelecomParams(monthly_bill_eur=60)),
    ]
    return {rule_id for r in results for rule_id in r.applied_rule_ids}


def test_every_branch_a_calculator_can_take_has_a_catalogue_entry():
    """A figure with no entry would reach the report with nothing beside it."""
    catalogue = {c.rule_id for year in BY_YEAR for c in BY_YEAR[year]}
    missing = sorted(every_branch_that_can_run() - catalogue)
    assert missing == [], f"branches with no citation: {missing}"


def test_the_catalogue_has_no_entry_no_calculator_can_reach():
    """The other direction: a rule nobody applies is a rule nobody reviewed.

    It would sit in the catalogue looking checked, and the first time a branch was
    written to match it the wording could have moved on years earlier.
    """
    reachable = every_branch_that_can_run()
    orphans = sorted(c.rule_id for year in BY_YEAR for c in BY_YEAR[year]
                     if c.rule_id not in reachable)
    assert orphans == [], f"catalogue entries no branch emits: {orphans}"


def test_each_branch_reports_only_the_rules_it_actually_took():
    """The point of per-branch ids: one purchase, one provision.

    An item under the low-value limit is deducted at once; a desk is written off over
    its useful life. If both reported both, the trace would show a passage about
    low-value assets beside a depreciation figure - which is the failure this whole
    file exists to prevent.
    """
    from domain import calculations as c

    cheap = c.calc_arbeitsmittel(c.ArbeitsmittelParams(price_eur=300, purchase_month=3))
    desk = c.calc_arbeitsmittel(
        c.ArbeitsmittelParams(price_eur=2000, purchase_month=3, useful_life_years=13))

    assert "anlage-n:2025:arbeitsmittel:low-value-asset:v1" in cheap.applied_rule_ids
    assert "anlage-n:2025:arbeitsmittel:depreciation:v1" not in cheap.applied_rule_ids
    assert "anlage-n:2025:arbeitsmittel:depreciation:v1" in desk.applied_rule_ids
    assert "anlage-n:2025:arbeitsmittel:low-value-asset:v1" not in desk.applied_rule_ids


def test_the_citation_reaches_the_expense_row_beside_the_figure():
    """End to end through the domain: calculator branch -> position -> Expense row.

    Asserted on the row and not only on the position because the row is what the
    report draws, and the two were joined by hand.
    """
    from domain.positions import assess_positions, project_expenses

    facts = {
        "equipment.price_eur": 2000.0, "equipment.price_is_net": False,
        "equipment.purchase_month": 3, "equipment.is_digital": False,
        "equipment.useful_life_years": 13, "equipment.professional_share_pct": 100,
    }
    row = next(r for r in project_expenses(assess_positions(facts), facts)
               if r["category"] == "arbeitsmittel")

    assert [c["rule_id"] for c in row["citations"]] == [
        "anlage-n:2025:arbeitsmittel:depreciation:v1"
    ], "a desk is depreciated; the low-value rule must not be cited beside it"
    assert row["citations"][0]["excerpt"]
    assert row["citations"][0]["reference"]


def test_a_category_with_no_rate_rule_cites_nothing_rather_than_something_vague():
    """Training costs are a sum of receipts, not a rate. No branch, so no citation.

    Silence is the honest answer here. Attaching the general Werbungskosten clause to
    a figure that is just an addition would put a quotation beside it that supports
    nothing in particular - the appearance of a source without one.
    """
    from domain.positions import assess_positions, project_expenses

    facts = {"education.amount_eur": 1200, "education.kind": "fortbildung",
             "education.reimbursed_eur": 0}
    row = next(r for r in project_expenses(assess_positions(facts), facts)
               if r["category"] == "fortbildungskosten")
    assert row["citations"] == []
