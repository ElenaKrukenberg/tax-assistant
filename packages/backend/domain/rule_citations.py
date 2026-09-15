"""The official passage behind each branch of each calculator, written down once.

**Why a catalogue and not a search.** For seven known categories the source does not
have to be found again for every user: the same branch of the same 2025 calculator is
backed by the same provision every time, and looking it up semantically per request
would make a deterministic figure depend on a retrieval that can return something
different tomorrow. The semantic retriever stays where it belongs - open questions in
the chat, and the model-backed classification of an ambiguous invoice (#91).

**Why per branch and not per category.** "Arbeitsmittel" is not one rule. An item
under 800 EUR net is deducted at once because of the low-value-asset provision; a
laptop is written off in one year because of a 2022 BMF letter; everything else is
depreciated over its useful life. One citation per category would attach a passage
about low-value assets to a figure produced by depreciation - a quotation that does
not support the claim beside it, which is worse than no quotation, because it looks
checked.

**Why the excerpt is stored and not fetched.** A finished Tax Case has to keep saying
what it said. An excerpt read out of the knowledge base at display time changes when
the corpus is reindexed or a source is replaced, so the trace beside a figure would
quietly drift away from the rules the figure was computed under.

**What makes this trustworthy.** Not this file on its own - a citation is only as good
as the claim that it supports the formula, and that link is made by a person and a code
review, not by a model at runtime. What is mechanical is everything around it, and
`tests/test_rule_citations.py` enforces it against `KB/`: the source is official, its
year and form match, the excerpt is present verbatim, it falls inside exactly one
chunk, the recorded chunk id is that chunk, and every reachable branch has an entry.

That test has already earned its place. The first excerpt written for the commuting
rate appeared in two chunks, because § 9 EStG repeats the same sentence for journeys
home under a second household - so the trace would have cited a rule about a different
deduction entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

Purpose = Literal["eligibility", "calculation", "placement"]


@dataclass(frozen=True)
class RuleCitation:
    """One branch of one calculator, and the passage that authorises it."""

    rule_id: str
    purpose: Purpose
    # The KB file, by its `source_id` frontmatter.
    source_id: str
    # The chunk the excerpt falls in, in the chunker's own `source_id::NNN` form.
    # Recorded rather than computed at read time so a reindex that moves a boundary
    # fails the test instead of silently re-pointing a citation.
    chunk_id: str
    title: str
    # How a German reader would name the provision - what goes beside the quotation.
    reference: str
    excerpt: str

    @property
    def is_cited(self) -> bool:
        return bool(self.excerpt)


def _uncited(rule_id: str, purpose: Purpose, reference: str, why: str) -> RuleCitation:
    """A branch that exists in the calculator and has no passage in `KB/` yet.

    Present rather than absent on purpose. A missing entry would fail the coverage
    check and invite somebody to delete the branch; an entry with an empty excerpt
    says the gap is known, names the provision it is waiting for, and is listed in
    issue #93 so it is revisited when the corpus grows rather than forgotten.
    """
    return RuleCitation(rule_id, purpose, source_id="", chunk_id="",
                        title=why, reference=reference, excerpt="")


# Tax year 2025. A second year gets its own dict rather than edits here: the rates
# move, the provisions can move with them, and a figure means nothing without the
# year that produced it (ADR 0008).
CITATIONS_2025: Final[tuple[RuleCitation, ...]] = (
    # --- the commute ---------------------------------------------------------
    RuleCitation(
        rule_id="anlage-n:2025:entfernungspauschale:per-km:v1",
        purpose="calculation",
        source_id="lsth-2025-par-9-werbungskosten",
        chunk_id="lsth-2025-par-9-werbungskosten::002",
        title="LStH 2025 - § 9 EStG Werbungskosten",
        reference="§ 9 Abs. 1 Satz 3 Nr. 4 EStG",
        excerpt=(
            "für jeden Arbeitstag, an dem der Arbeitnehmer die erste Tätigkeitsstätte "
            "aufsucht, eine Entfernungspauschale für jeden vollen Kilometer der ersten "
            "20 Kilometer der Entfernung zwischen Wohnung und erster Tätigkeitsstätte "
            "von 0,30 Euro und für jeden weiteren vollen Kilometer"
        ),
    ),
    RuleCitation(
        rule_id="anlage-n:2025:entfernungspauschale:cap-without-own-car:v1",
        purpose="calculation",
        source_id="lsth-2025-par-9-werbungskosten",
        chunk_id="lsth-2025-par-9-werbungskosten::002",
        title="LStH 2025 - § 9 EStG Werbungskosten",
        reference="§ 9 Abs. 1 Satz 3 Nr. 4 EStG",
        excerpt=(
            "höchstens 4.500 Euro im Kalenderjahr; ein höherer Betrag als 4.500 Euro "
            "ist anzusetzen, soweit der Arbeitnehmer einen eigenen oder ihm zur "
            "Nutzung überlassenen Kraftwagen benutzt."
        ),
    ),
    RuleCitation(
        rule_id="anlage-n:2025:entfernungspauschale:actual-public-transport:v1",
        purpose="calculation",
        source_id="lsth-2025-par-9-werbungskosten",
        chunk_id="lsth-2025-par-9-werbungskosten::005",
        title="LStH 2025 - § 9 EStG Werbungskosten",
        reference="§ 9 Abs. 2 Satz 2 EStG",
        excerpt=(
            "Aufwendungen für die Benutzung öffentlicher Verkehrsmittel können "
            "angesetzt werden, soweit sie den im Kalenderjahr insgesamt als "
            "Entfernungspauschale abziehbaren Betrag übersteigen."
        ),
    ),
    # --- the home office -----------------------------------------------------
    # One sentence carries both branches, because the provision states the daily
    # amount and its yearly ceiling in the same breath. Two entries rather than one
    # so the trace can say which of the two actually bit on this case.
    RuleCitation(
        rule_id="anlage-n:2025:homeoffice:tagespauschale:v1",
        purpose="calculation",
        source_id="lsth-2025-anhang-19-i-ha-usliches-arbeitszimmer",
        chunk_id="lsth-2025-anhang-19-i-ha-usliches-arbeitszimmer::026",
        title="LStH 2025 - Anhang 19 I, häusliches Arbeitszimmer und Tagespauschale",
        reference="§ 4 Abs. 5 Satz 1 Nr. 6c EStG",
        excerpt=(
            "Die Tagespauschale beträgt 6 € pro Kalendertag, höchstens 1.260 € im "
            "Wirtschafts- oder Kalenderjahr."
        ),
    ),
    RuleCitation(
        rule_id="anlage-n:2025:homeoffice:yearly-cap:v1",
        purpose="calculation",
        source_id="lsth-2025-anhang-19-i-ha-usliches-arbeitszimmer",
        chunk_id="lsth-2025-anhang-19-i-ha-usliches-arbeitszimmer::026",
        title="LStH 2025 - Anhang 19 I, häusliches Arbeitszimmer und Tagespauschale",
        reference="§ 4 Abs. 5 Satz 1 Nr. 6c EStG",
        excerpt=(
            "Die Tagespauschale beträgt 6 € pro Kalendertag, höchstens 1.260 € im "
            "Wirtschafts- oder Kalenderjahr."
        ),
    ),
    # --- equipment -----------------------------------------------------------
    RuleCitation(
        rule_id="anlage-n:2025:arbeitsmittel:low-value-asset:v1",
        purpose="calculation",
        source_id="055-anleitung-anlage-n-2025",
        chunk_id="055-anleitung-anlage-n-2025::012",
        title="Anleitung zur Anlage N 2025",
        reference="§ 6 Abs. 2 EStG, Anleitung zur Anlage N 2025",
        excerpt=(
            "Arbeitsmittel, die höchstens 800 € (ohne Umsatzsteuer) gekostet haben, "
            "können Sie in dem Jahr voll als Werbungskosten absetzen, in dem Sie diese "
            "angeschafft haben (sog. geringwertige Wirtschaftsgüter)."
        ),
    ),
    RuleCitation(
        rule_id="anlage-n:2025:arbeitsmittel:digital-one-year:v1",
        purpose="calculation",
        source_id="lsth-2025-par-9-werbungskosten",
        chunk_id="lsth-2025-par-9-werbungskosten::075",
        title="LStH 2025 - § 9 EStG Werbungskosten",
        reference="BMF vom 22.02.2022, BStBl I S. 187",
        excerpt=(
            "Bei Computerhardware und Software zur Dateneingabe und -verarbeitung kann "
            "eine betriebsgewöhnliche Nutzungsdauer von einem Jahr zugrunde gelegt "
            "werden"
        ),
    ),
    RuleCitation(
        rule_id="anlage-n:2025:arbeitsmittel:depreciation:v1",
        purpose="calculation",
        source_id="055-anleitung-anlage-n-2025",
        chunk_id="055-anleitung-anlage-n-2025::012",
        title="Anleitung zur Anlage N 2025",
        reference="§ 7 Abs. 1 EStG, Anleitung zur Anlage N 2025",
        excerpt=(
            "Sind die Anschaffungskosten höher als 800 €, müssen Sie diese auf die "
            "Jahre der üblichen Nutzungsdauer verteilen."
        ),
    ),
    _uncited(
        rule_id="anlage-n:2025:arbeitsmittel:professional-share:v1",
        purpose="calculation",
        reference="§ 12 Nr. 1 EStG, LStH Anhang 18a",
        why="No passage in KB/ yet - see issue #93, to be cited when the corpus grows.",
    ),
    # --- the flat allowance --------------------------------------------------
    RuleCitation(
        rule_id="anlage-n:2025:pauschbetrag:itemised-exceeds:v1",
        purpose="eligibility",
        source_id="estg-09a-pauschbetraege",
        chunk_id="estg-09a-pauschbetraege::000",
        title="§ 9a EStG - Pauschbeträge für Werbungskosten",
        reference="§ 9a Satz 1 Nr. 1a EStG",
        excerpt="ein Arbeitnehmer-Pauschbetrag von 1 230 Euro",
    ),
    RuleCitation(
        rule_id="anlage-n:2025:pauschbetrag:allowance-wins:v1",
        purpose="eligibility",
        source_id="estg-09a-pauschbetraege",
        chunk_id="estg-09a-pauschbetraege::000",
        title="§ 9a EStG - Pauschbeträge für Werbungskosten",
        reference="§ 9a Satz 1 Nr. 1a EStG",
        excerpt="ein Arbeitnehmer-Pauschbetrag von 1 230 Euro",
    ),
    # --- phone and internet --------------------------------------------------
    RuleCitation(
        rule_id="anlage-n:2025:telefon-internet:flat-share:v1",
        purpose="calculation",
        source_id="lsth-2025-par-9-werbungskosten",
        chunk_id="lsth-2025-par-9-werbungskosten::012",
        title="LStH 2025 - § 9 EStG Werbungskosten",
        reference="H 9.1 LStH, Telekommunikationsaufwendungen",
        excerpt=(
            "Fallen erfahrungsgemäß beruflich veranlasste Telekommunikationsaufwendungen "
            "an, können aus Vereinfachungsgründen ohne Einzelnachweis bis zu 20 % des "
            "Rechnungsbetrags, jedoch höchstens 20 € monatlich als Werbungskosten "
            "anerkannt werden."
        ),
    ),
)


BY_YEAR: Final[dict[int, tuple[RuleCitation, ...]]] = {
    2025: CITATIONS_2025,
}


def for_rule(rule_id: str, year: int = 2025) -> RuleCitation:
    """The citation for one rule, or a clear failure naming the year.

    Loud rather than lenient, for the reason `for_year` is: a figure shown without
    the source it claims to have is the one outcome this product treats as
    unacceptable, and a silent `None` here becomes an empty block on the report.
    """
    try:
        catalogue = BY_YEAR[year]
    except KeyError:
        known = ", ".join(str(y) for y in sorted(BY_YEAR))
        raise ValueError(f"No rule catalogue for {year}; this build covers {known}") from None
    for citation in catalogue:
        if citation.rule_id == rule_id:
            return citation
    raise KeyError(f"{rule_id} is not in the {year} rule catalogue")


def for_rules(rule_ids: list[str], year: int = 2025) -> list[RuleCitation]:
    """The citations for the branches a calculation actually took, in order."""
    return [for_rule(rule_id, year) for rule_id in rule_ids]
