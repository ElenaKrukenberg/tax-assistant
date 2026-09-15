"""Tax-position assessment and confirmation, separate from field provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable

from domain.estimate import CALCULATORS, SUMMED, estimate, item_indexes, to_params
from domain.fields import CATEGORY_FIELDS, ExpenseCategory, key_for, namespace_of
from domain.rule_citations import RuleCitation, for_rules
from domain.tax_years import TaxYear, for_year


class AssessmentStatus(str, Enum):
    identified = "identified"
    criteria_not_met = "criteria_not_met"
    unclear = "unclear"


class UserDecision(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    needs_reconfirmation = "needs_reconfirmation"


class Origin(str, Enum):
    user_input = "user_input"
    deterministic_rule = "deterministic_rule"
    retrieved_source = "retrieved_source"
    ai_suggestion = "ai_suggestion"
    # A value a model read out of a document. Distinct from `ai_suggestion`, which is
    # a model proposing something; this is a model *transcribing* something that was
    # already written down, and the two carry different weight beside a figure. It is
    # also why a document-backed position is not itself AI-generated: the extraction
    # was, the user's confirmation was not, and the position is a deterministic
    # calculation over what they confirmed.
    ai_inference = "ai_inference"


@dataclass(frozen=True)
class ProvenanceEntry:
    role: str
    origin: Origin
    reference: str
    version: str | None = None


@dataclass(frozen=True)
class FactDependency:
    fact_id: str
    version: str


@dataclass
class TaxPosition:
    """A proposed tax position; assessment and user authority are separate."""

    position_id: str
    category: str
    assessment_status: AssessmentStatus
    user_decision: UserDecision = UserDecision.pending
    dependent_facts: list[FactDependency] = field(default_factory=list)
    # The official passages behind this position, resolved and kept. Stored rather
    # than looked up when the report is drawn: a finished Tax Case has to keep saying
    # what it said, and an excerpt fetched at display time changes when the corpus is
    # reindexed or a source replaced. Empty for a category that sums receipts without
    # a rate rule - there is no branch to cite.
    source_refs: list[RuleCitation] = field(default_factory=list)
    calculator_version: str | None = None
    rule_version: str | None = None
    proposed_amount: float | None = None
    origin: Origin = Origin.deterministic_rule
    missing_facts: list[str] = field(default_factory=list)
    assessment_fingerprint: str = ""
    provenance: list[ProvenanceEntry] = field(default_factory=list)

    # `form_line`, `trace` and `documents` are deliberately *not* here. They were,
    # and they were never persisted: `save_positions` wrote thirteen columns and none
    # of the three, so a Tax Case read back from the table produced expense rows with
    # no form line, no formula and no documents. The fix is not a wider insert. All
    # three are functions of the facts, their provenance and the tax year - none is a
    # decision anybody made - so they belong to the Expense projection that is
    # recomputed on the way out (`project_expenses`), and the position stores only
    # what cannot be derived again: the assessment, the user's decision, and what the
    # assessment was made against.

    def dependencies_are_current(self, facts: dict[str, Any]) -> bool:
        if not self.assessment_fingerprint:
            return all(dependency.version == fact_version(facts, dependency.fact_id)
                       for dependency in self.dependent_facts)
        return self.assessment_fingerprint == assessment_fingerprint(
            facts, self.dependent_facts, self.rule_version, self.calculator_version,
        )

    def include_in_draft(self, facts: dict[str, Any]) -> bool:
        return (
            self.assessment_status is AssessmentStatus.identified
            and self.user_decision is UserDecision.accepted
            and self.dependencies_are_current(facts)
        )

    def mark_dependencies_stale(self, facts: dict[str, Any]) -> None:
        if (self.user_decision is UserDecision.accepted
                and not self.dependencies_are_current(facts)):
            self.user_decision = UserDecision.needs_reconfirmation

    def decide(self, decision: UserDecision) -> None:
        if decision is UserDecision.accepted and self.assessment_status is not AssessmentStatus.identified:
            raise ValueError("only an identified position can be accepted")
        if decision is UserDecision.needs_reconfirmation:
            raise ValueError("stale is produced by dependency changes, not user input")
        self.user_decision = decision

    def as_dict(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "category": self.category,
            "assessment_status": self.assessment_status.value,
            "user_decision": self.user_decision.value,
            "dependent_facts": [dependency.__dict__ for dependency in self.dependent_facts],
            "source_refs": [asdict(citation) for citation in self.source_refs],
            "calculator_version": self.calculator_version,
            "rule_version": self.rule_version,
            "proposed_amount": self.proposed_amount,
            "origin": self.origin.value,
            "missing_facts": self.missing_facts,
            "assessment_fingerprint": self.assessment_fingerprint,
            "provenance": [entry.__dict__ | {"origin": entry.origin.value}
                           for entry in self.provenance],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaxPosition":
        return cls(
            position_id=str(value["position_id"]),
            category=str(value["category"]),
            assessment_status=AssessmentStatus(value["assessment_status"]),
            user_decision=UserDecision(value.get("user_decision", UserDecision.pending)),
            dependent_facts=[FactDependency(str(item["fact_id"]), str(item["version"]))
                             for item in value.get("dependent_facts", [])],
            # Rows written before the catalogue hold plain strings like
            # "tax-year:2025:anlage-n:arbeitsmittel", which named nothing anybody could
            # read. They are dropped rather than half-converted: a position reassessed
            # from the same facts gets real citations, and inventing a RuleCitation
            # around an old identifier would claim a source that was never checked.
            source_refs=[RuleCitation(**item) for item in value.get("source_refs", [])
                         if isinstance(item, dict)],
            calculator_version=value.get("calculator_version"),
            rule_version=value.get("rule_version"),
            proposed_amount=value.get("proposed_amount"),
            origin=Origin(value.get("origin", Origin.deterministic_rule)),
            missing_facts=[str(item) for item in value.get("missing_facts", [])],
            assessment_fingerprint=str(value.get("assessment_fingerprint", "")),
            # `form_line`, `trace` and `documents` are ignored rather than rejected if
            # they appear: a checkpoint written before this change still carries them,
            # and refusing to read it would strand a paused interview.
            provenance=[ProvenanceEntry(
                role=str(item["role"]), origin=Origin(item["origin"]),
                reference=str(item["reference"]), version=item.get("version"),
            ) for item in value.get("provenance", [])],
        )


def fact_version(facts: dict[str, Any], fact_id: str) -> str:
    """Stable version for one fact, without storing the fact in the position."""
    encoded = json.dumps(facts.get(fact_id), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def dependency_ids(
    category: ExpenseCategory, facts: dict[str, Any] | None = None,
) -> list[str]:
    """Facts declared by the rule, including inputs from another namespace.

    With `facts`, a repeating field is expanded across every item the case holds:
    three purchases in one category are `equipment.price_eur`, `…#1` and `…#2`, and
    the position depends on all three. Without that expansion the dependency list
    named only item zero, so `dependencies_are_current` could not see a change to the
    second or third item at all - a corrected price on invoice two would leave an
    accepted position looking current while the figure behind it had moved.
    """
    ids: set[str] = set()
    for spec in CATEGORY_FIELDS[category]:
        if spec.interview_only:
            # Not a dependency: answering "no, nothing else" changes no figure, and
            # counting it would turn a decision the user already approved into
            # `needs_reconfirmation` for a question about the conversation (#35).
            continue
        base = spec.filled_by or key_for(category, spec.name)
        ids.add(base)
        if facts and spec.repeats and not spec.filled_by:
            ids.update(key for key in facts if key.startswith(f"{base}#"))
    return sorted(ids)


def dependencies_for(facts: dict[str, Any], category: str | ExpenseCategory) -> list[FactDependency]:
    category = ExpenseCategory(category)
    keys = dependency_ids(category, facts)
    return [FactDependency(key, fact_version(facts, key)) for key in keys]


def assessment_fingerprint(
    facts: dict[str, Any], dependencies: list[FactDependency],
    rule_version: str | None, calculator_version: str | None,
) -> str:
    payload = {
        "facts": [(item.fact_id, fact_version(facts, item.fact_id)) for item in dependencies],
        "rule_version": rule_version,
        "calculator_version": calculator_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _category_started(facts: dict[str, Any], category: ExpenseCategory) -> bool:
    return any(key.startswith(f"{namespace_of(category)}.") for key in facts)


def documents_behind(
    fields: dict[str, Any] | None, dependencies: list[FactDependency],
) -> list[str]:
    """The documents this position's facts came from, if any.

    `fields` is the case's values *with* their provenance - `db.cases.get_fields`,
    not the flattened `{key: value}` the calculators take. Flattening is where this
    used to be lost: the API built `known = {k: v.value ...}` and the provenance went
    no further, so a figure read off a Lohnsteuerbescheinigung reached the report
    indistinguishable from one somebody typed.
    """
    if not fields:
        return []
    documents: list[str] = []
    for dependency in dependencies:
        held = fields.get(dependency.fact_id)
        if held is None:
            continue
        # Either a `FieldValue` (from the repository) or the plain dict the graph
        # state carries across a pause. Both, because the assessment runs in both
        # places and JSON is what survives a checkpoint.
        if isinstance(held, dict):
            provenance, source = held.get("provenance"), held.get("source") or ""
        else:
            provenance = getattr(held, "provenance", None)
            source = getattr(held, "source", "") or ""
        if getattr(provenance, "value", provenance) != "document":
            continue
        if source and source not in documents:
            documents.append(source)
    return documents


def assess_positions(
    facts: dict[str, Any],
    year: TaxYear | None = None,
    fields: dict[str, Any] | None = None,
) -> list[TaxPosition]:
    """Assess every known category before any Expense/draft row is created.

    `fields` is optional and carries the provenance of each value. Without it the
    assessment is exactly what it was; with it, a position knows which documents its
    facts came from - which is what the report needs to say "145 days, from
    Lohnsteuerbescheinigung 2025.pdf" rather than "interview answer".
    """
    year = year or for_year()
    estimate_result = estimate(facts, year)
    positions: list[TaxPosition] = []
    for category in ExpenseCategory:
        rule_version = f"anlage-n:{year.year}:{category.value}:v1"
        calculator_version = (f"calculator:{CALCULATORS[category].value}:v1"
                              if category in CALCULATORS else None)
        dependencies = dependencies_for(facts, category)
        documents = documents_behind(fields, dependencies)
        fingerprint = assessment_fingerprint(
            facts, dependencies, rule_version, calculator_version,
        )
        citations: list[RuleCitation] = []
        if not _category_started(facts, category):
            status = AssessmentStatus.criteria_not_met
            missing: list[str] = []
            amount = None
        else:
            entry = estimate_result.per_category.get(category)
            missing = list(entry.missing) if entry else [f"{category.value}: assessment unavailable"]
            status = AssessmentStatus.unclear if missing else AssessmentStatus.identified
            amount = entry.amount_eur if entry and not missing else None
            if entry and not missing:
                citations = for_rules(entry.applied_rule_ids, year.year)
        positions.append(TaxPosition(
            position_id=category.value,
            category=category.value,
            assessment_status=status,
            dependent_facts=dependencies,
            source_refs=citations,
            calculator_version=calculator_version,
            rule_version=rule_version,
            proposed_amount=amount,
            origin=Origin.deterministic_rule,
            missing_facts=missing,
            assessment_fingerprint=fingerprint,
            provenance=[
                ProvenanceEntry("assessment", Origin.deterministic_rule,
                                category.value, rule_version),
                *([ProvenanceEntry("calculation", Origin.deterministic_rule,
                                   category.value, calculator_version)]
                  if calculator_version else []),
                # Two entries per document, never one. The model transcribed the
                # value and the user confirmed it, and collapsing those into a single
                # "AI" row would either overstate the machine's part or hide it -
                # both of which issue #89 (AI-03) exists to prevent.
                *[ProvenanceEntry("extraction", Origin.ai_inference,
                                  f"document:{document}", None)
                  for document in documents],
                *[ProvenanceEntry("confirmation", Origin.user_input,
                                  f"document:{document}", None)
                  for document in documents],
            ],
        ))
    return positions


def positions_from_expenses(
    facts: dict[str, Any], expenses: Iterable[dict[str, Any]],
    *, rule_version: str = "2025.1", calculator_version: str = "calculations.v1",
) -> list[TaxPosition]:
    """Compatibility wrapper; runtime assessment does not consume expense rows."""
    del expenses, rule_version, calculator_version
    return assess_positions(facts)


def includable_positions(positions: Iterable[TaxPosition], facts: dict[str, Any]) -> list[TaxPosition]:
    return [position for position in positions if position.include_in_draft(facts)]


def project_expenses(
    positions: Iterable[TaxPosition],
    fields: dict[str, Any] | None,
    year: TaxYear | None = None,
) -> list[dict[str, Any]]:
    """The Expense rows for a set of positions, recomputed rather than read back.

    Three inputs and not one, because the three derived parts each need a different
    one and taking only `facts` would have to be widened again the first time any of
    them grew:

    * **the form line** comes from the `TaxYear` - the same category sits on
      different lines in different years, which is the whole point of the year files;
    * **the documents** come from `fields`, the values *with* their provenance, not
      the flattened `{key: value}` the calculators take. Flattening is where a
      document used to be lost (`documents_behind`);
    * **the formula** comes from the facts inside `fields` plus the year's rates.

    A position whose stored amount no longer matches what its facts produce is an
    error and not a silently updated figure: the two disagreeing means the position
    was assessed against something else, and `dependencies_are_current` is what
    decides whether it may still be used, not this function.
    """
    year = year or for_year()
    facts = {key: _value_of(held) for key, held in (fields or {}).items()}
    rows: list[dict[str, Any]] = []
    for position in positions:
        if position.assessment_status is not AssessmentStatus.identified:
            continue
        if position.proposed_amount is None:
            continue
        category = ExpenseCategory(position.category)
        line = year.line_for(category)
        trace: list[str] = []
        # One entry per purchase, with its own amount. The report shows a category
        # total, but the Reviewer has to be able to recompute each item on its own -
        # with a single row it could only ever check the first, so a wrong price on
        # the second invoice was invisible to it (#35).
        items: list[dict[str, Any]] = []
        if category in CALCULATORS:
            calculate = __import__("domain.calculations", fromlist=["calculate"]).calculate
            indexes = item_indexes(category, facts)
            for item_index in indexes:
                params, missing = to_params(category, facts, item_index)
                if missing:
                    # A half-entered second purchase contributes nothing to the amount
                    # (`estimate._calculated` skips it), so it contributes nothing to
                    # the explanation either - an item in the formula that is not in
                    # the total is worse than an item in neither.
                    continue
                computed = calculate(CALCULATORS[category], params, year.year)
                items.append({"item_index": item_index, "amount_eur": computed.amount_eur})
                lines = computed.breakdown
                if len(indexes) > 1:
                    # Numbered, because three purchases in one category produce three
                    # formulas and an unlabelled list of them reads as one long sum.
                    # The explanation used to be built from item zero alone while the
                    # amount added up all of them (#35), which is the same figure with
                    # a formula that does not produce it.
                    lines = [f"{item_index + 1}. {first}" if i == 0 else f"   {first}"
                             for i, first in enumerate(lines)]
                trace.extend(lines)
        rows.append({
            "category": position.category,
            "amount_eur": position.proposed_amount,
            # Both, and deliberately. `form_line` stays the exact identifier a
            # machine reads out of an export; `form` and `form_lines` are what the
            # interface turns into "Anlage N, Zeilen 54-56" in the reader's language.
            # Building the readable string here would put German - or English - into
            # data that four locales render (#56).
            "form_line": f"{line.form} {line.lines}",
            "form": line.form,
            "form_lines": line.lines,
            "trace": trace,
            # A list because three invoices in one category are three documents, and
            # picking one of them to show would be a smaller lie than `None` but a
            # lie all the same.
            "documents": documents_behind(fields, position.dependent_facts),
            "items": items,
            # Read off the position rather than recomputed with the formula beside
            # them. The formula follows from the facts and may be rebuilt; the
            # citation was checked against the corpus as it stood when the position
            # was assessed, and re-resolving it would let a reindexed source quietly
            # change the words under a figure the user already approved.
            "citations": [asdict(citation) for citation in position.source_refs],
        })
    return rows


def _value_of(held: Any) -> Any:
    """The plain value out of a `FieldValue`, a graph-state dict, or a bare value."""
    if isinstance(held, dict) and "value" in held:
        return held["value"]
    return getattr(held, "value", held)


def fields_from_state(
    known: dict[str, Any], provenance: dict[str, Any] | None,
) -> dict[str, Any]:
    """One `fields`-shaped mapping out of the two the graph state keeps apart.

    The repository hands out `FieldValue` objects carrying value and provenance
    together; a checkpoint has to be JSON, so the graph keeps `known` and
    `provenance` as separate dicts. `project_expenses` takes one mapping, and this is
    the seam - rather than a second parameter that only the graph would ever pass.
    """
    held = provenance or {}
    return {
        key: {"value": value, **(held.get(key) or {})}
        for key, value in known.items()
    }


def reconcile_positions(
    current: list[TaxPosition], persisted: Iterable[TaxPosition],
) -> list[TaxPosition]:
    """Carry the user's decisions onto a freshly assessed set, and only those.

    The assessment is a function of the facts and is rebuilt from them; the decision
    is the one thing in a position that no recomputation can produce, so it is the
    one thing carried across. It is carried only where the fingerprint matches: a
    decision is a decision *about something*, and if what was assessed has moved - a
    fact, a rule version, a calculator version - then it was made about something
    that no longer exists.

    Both answers are asked again, not only yes. A no is an answer to a figure under
    particular rules too, and the reason for it can be exactly the thing that moved:
    somebody who declined 180 EUR of training costs because the amount was not worth
    the paperwork has not thereby declined 1,800. Treating a rejection as permanent
    would decide the new question on their behalf and never show it to them, which is
    the failure this whole mechanism exists to prevent.
    """
    by_id = {position.position_id: position for position in persisted}
    for position in current:
        old = by_id.get(position.position_id)
        if old is None:
            continue
        if old.assessment_fingerprint == position.assessment_fingerprint:
            position.user_decision = old.user_decision
        elif old.user_decision in (UserDecision.accepted, UserDecision.rejected):
            position.user_decision = UserDecision.needs_reconfirmation
    return current
