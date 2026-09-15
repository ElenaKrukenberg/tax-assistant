"""Seeded defects: broken cases the Reviewer is required to catch.

The only honest way to show a reviewer does something is to hand it a case that is
known to be wrong and see whether it objects (CONTEXT.md, Seeded defect). Each case
here starts from a healthy evaluation profile and plants exactly the defects the
sprint plan names, plus one that exercises the recompute tool.

Every defect declares how a catch is recognised — by the category a finding points
at, or by words its title or reasoning must contain — so that "the Reviewer caught
it" is a check, not an impression.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.reviewer import ClaimedExpense, Finding, ReviewCase
from domain.estimate import estimate
from eval.baseline import load_profiles, run_filter


@dataclass(frozen=True)
class PlantedDefect:
    id: str
    description: str
    category: str | None = None
    must_mention: tuple[str, ...] = ()

    def caught_by(self, findings: list[Finding]) -> bool:
        for finding in findings:
            if finding.severity == "suggestion":
                continue  # a defect noticed only as a suggestion was not caught
            text = f"{finding.title} {finding.reasoning}".lower()
            # The category field is optional in the verdict, and a live run showed a
            # correct catch scored as a miss because the model named the category in
            # the title instead of the field. Naming it anywhere counts.
            if self.category and (finding.category == self.category
                                  or self.category in text):
                return True
            if self.must_mention and all(w in text for w in self.must_mention):
                return True
        return False


@dataclass(frozen=True)
class SeededCase:
    id: str
    case: ReviewCase
    defects: tuple[PlantedDefect, ...]


def _healthy_case(profile_prefix: str) -> tuple[dict, list[ClaimedExpense]]:
    """A correct case built from a profile: fields via the filter, amounts recomputed."""
    profile = next(p for p in load_profiles() if p.id.startswith(profile_prefix))
    fields = dict(run_filter(profile).known)
    expenses = []
    for category, entry in estimate(fields).per_category.items():
        if entry.computable:
            expenses.append(ClaimedExpense(
                category=category.value,
                amount_eur=entry.amount_eur,
                document=f"{category.value}-beleg.pdf",
            ))
    return fields, expenses


def build_seeded_cases() -> list[SeededCase]:
    cases: list[SeededCase] = []

    # --- broken-1: from p01, an unbacked expense and contradictory day counts ------
    fields, expenses = _healthy_case("p01")
    # Defect A: the 1,400 EUR laptop loses its document.
    expenses = [
        e if e.category != "arbeitsmittel"
        else ClaimedExpense(e.category, e.amount_eur, e.item_index, e.trace, None)
        for e in expenses
    ]
    # Defect B: home-office days grow until the day counts cannot all be true:
    # 88 commuting + 180 home office = 268 against 220 days worked in total (V02).
    fields["homeoffice.homeoffice_days"] = 180
    # The claimed home-office amount is left as computed from 180 days, so only the
    # contradiction is planted here, not a recomputation mismatch as well.
    updated = estimate(fields)
    expenses = [
        e if e.category != "homeoffice_tagespauschale"
        else ClaimedExpense(e.category, updated.per_category[
            next(c for c in updated.per_category if c.value == e.category)
        ].amount_eur, e.item_index, e.trace, e.document)
        for e in expenses
    ]
    cases.append(SeededCase(
        id="broken-1-unbacked-and-contradictory",
        case=ReviewCase(
            tax_year=2025, fields=fields, expenses=tuple(expenses),
            documents=tuple(e.document for e in expenses if e.document),
        ),
        defects=(
            PlantedDefect(
                "unbacked-expense",
                "The 1,400 EUR laptop has no document behind it",
                category="arbeitsmittel",
                must_mention=("document",),
            ),
            PlantedDefect(
                "contradictory-days",
                "88 commuting + 180 home-office days exceed 220 days worked (V02)",
                # The planted numbers, not a word: a reviewer model is free to answer
                # in German ("Tage"), and an English keyword scored a real catch as a
                # miss — the second language artifact this detector has produced.
                must_mention=("180", "220"),
            ),
        ),
    ))

    # --- broken-2: from p02, a claimed amount its own inputs do not produce --------
    fields, expenses = _healthy_case("p02")
    # Defect C: the commute is claimed at 4,100 EUR; recomputing from the case's own
    # values gives 3,073.04. Only recomputation can see this — the values themselves
    # break no rule.
    expenses = [
        e if e.category != "entfernungspauschale"
        else ClaimedExpense(e.category, 4100.00, e.item_index, e.trace, e.document)
        for e in expenses
    ]
    cases.append(SeededCase(
        id="broken-2-inflated-claim",
        case=ReviewCase(
            tax_year=2025, fields=fields, expenses=tuple(expenses),
            documents=tuple(e.document for e in expenses if e.document),
        ),
        defects=(
            PlantedDefect(
                "inflated-claim",
                "Entfernungspauschale claimed at 4,100 EUR; the values give 3,073.04",
                category="entfernungspauschale",
            ),
        ),
    ))

    return cases
