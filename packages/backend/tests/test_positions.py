from domain.positions import (
    AssessmentStatus,
    Origin,
    TaxPosition,
    UserDecision,
    dependencies_for,
    fact_version,
    includable_positions,
)


def make_position(facts):
    return TaxPosition(
        position_id="fortbildungskosten",
        category="fortbildungskosten",
        assessment_status=AssessmentStatus.identified,
        dependent_facts=dependencies_for(facts, "fortbildungskosten"),
        origin=Origin.deterministic_rule,
    )


def test_acceptance_requires_an_identified_assessment():
    position = TaxPosition("x", "x", AssessmentStatus.unclear)

    try:
        position.decide(UserDecision.accepted)
    except ValueError:
        pass
    else:
        raise AssertionError("unclear positions must not be accepted")


def test_accepted_position_is_includable_only_with_current_dependencies():
    facts = {"education.amount_eur": 1200}
    position = make_position(facts)
    position.decide(UserDecision.accepted)

    assert position.include_in_draft(facts)
    changed = {"education.amount_eur": 1300}
    assert not position.include_in_draft(changed)
    position.mark_dependencies_stale(changed)
    assert position.user_decision is UserDecision.needs_reconfirmation


def test_unrelated_fact_does_not_stale_position():
    facts = {
        "education.amount_eur": 1200,
        "profile.address": "old",
    }
    position = make_position(facts)
    position.decide(UserDecision.accepted)

    changed = {"education.amount_eur": 1200, "profile.address": "new"}
    position.mark_dependencies_stale(changed)
    assert position.user_decision is UserDecision.accepted
    assert position.include_in_draft(changed)


def test_fact_version_is_stable_and_dependency_scope_is_explicit():
    facts = {"education.amount_eur": 1200, "profile.address": "old"}

    assert fact_version(facts, "education.amount_eur") == fact_version(
        {"education.amount_eur": 1200}, "education.amount_eur"
    )
    assert [d.fact_id for d in dependencies_for(facts, "fortbildungskosten")] == [
        "education.amount_eur",
        "education.kind",
        "education.reimbursed_eur",
    ]


def test_rejected_position_cannot_reach_the_draft():
    facts = {"education.amount_eur": 1200}
    position = make_position(facts)
    position.decide(UserDecision.rejected)

    assert includable_positions([position], facts) == []


# --- what a document leaves behind (issues #16, #17) ----------------------------

def test_a_position_names_the_documents_its_facts_came_from():
    """The link the report needs, carried from `field_values` to the Expense row.

    Before this, the API flattened the case to `{key: value}` before assessing, so a
    figure read off a Lohnsteuerbescheinigung arrived at the report
    indistinguishable from one somebody typed - and every row's `document` was
    `None`, unconditionally.

    The documents are asserted on the projection and not on the position: a position
    stores what a recomputation cannot produce, and this is not that.
    """
    from domain.fields import FieldValue, Provenance
    from domain.positions import assess_positions, project_expenses

    fields = {
        "equipment.price_eur": FieldValue(689.0, Provenance.document,
                                          source="doc-1", confirmed=True),
        "equipment.purchase_month": FieldValue(9, Provenance.document,
                                               source="doc-1", confirmed=True),
        "equipment.price_is_net": FieldValue(False, Provenance.answer, source="user"),
        "equipment.is_digital": FieldValue(False, Provenance.answer, source="user"),
        "equipment.useful_life_years": FieldValue(3, Provenance.answer, source="user"),
        "equipment.professional_share_pct": FieldValue(100, Provenance.answer,
                                                       source="user"),
    }
    facts = {key: held.value for key, held in fields.items()}

    positions = assess_positions(facts, None, fields)
    equipment = next(p for p in positions if p.category == "arbeitsmittel")

    # Two entries per document, and they say different things: the model transcribed
    # the value, the person confirmed it (issue #89).
    origins = {(entry.role, entry.origin.value) for entry in equipment.provenance}
    assert ("extraction", "ai_inference") in origins
    assert ("confirmation", "user_input") in origins
    # The position itself stays a deterministic calculation over confirmed facts.
    assert equipment.origin.value == "deterministic_rule"

    row = next(r for r in project_expenses(positions, fields)
               if r["category"] == "arbeitsmittel")
    assert row["documents"] == ["doc-1"]
    assert row["form_line"]
    assert row["trace"]


def test_a_position_built_from_answers_alone_names_no_documents():
    from domain.fields import FieldValue, Provenance
    from domain.positions import assess_positions, project_expenses

    facts = {"telecom.monthly_bill_eur": 45.0, "telecom.months": 12}
    fields = {key: FieldValue(value, Provenance.answer, source="q")
              for key, value in facts.items()}

    positions = assess_positions(facts, None, fields)
    telecom = next(p for p in positions if p.category == "telefon_internet")
    assert not any(entry.origin.value.startswith("ai_") for entry in telecom.provenance)

    row = next(r for r in project_expenses(positions, fields)
               if r["category"] == "telefon_internet")
    assert row["documents"] == []


def test_a_change_to_the_second_item_makes_the_position_stale():
    """What the item-aware dependency list buys, stated as the failure it prevents.

    An accepted position depends on the facts behind it, and a repeating category has
    one set of facts per purchase. With only item zero in the list, correcting the
    price on the second invoice left the position looking current while its figure
    had moved - the user would never be asked to confirm the changed number.
    """
    from domain.positions import AssessmentStatus, UserDecision, assess_positions

    facts = {
        "equipment.price_eur": 689.0, "equipment.price_is_net": False,
        "equipment.purchase_month": 9, "equipment.is_digital": False,
        "equipment.useful_life_years": 3, "equipment.professional_share_pct": 100,
        "equipment.price_eur#1": 46.25, "equipment.price_is_net#1": False,
        "equipment.purchase_month#1": 9, "equipment.is_digital#1": False,
        "equipment.useful_life_years#1": 3, "equipment.professional_share_pct#1": 100,
    }
    equipment = next(p for p in assess_positions(facts)
                     if p.category == "arbeitsmittel")
    assert equipment.assessment_status is AssessmentStatus.identified
    assert "equipment.price_eur#1" in {d.fact_id for d in equipment.dependent_facts}

    equipment.decide(UserDecision.accepted)
    assert equipment.include_in_draft(facts)

    corrected = dict(facts, **{"equipment.price_eur#1": 52.00})
    assert not equipment.dependencies_are_current(corrected)
    equipment.mark_dependencies_stale(corrected)
    assert equipment.user_decision is UserDecision.needs_reconfirmation


def test_every_part_of_a_position_is_either_stored_or_declared_derived():
    """The guard that would have caught the bug this test file was extended for.

    `assessment_fingerprint` was a field of `TaxPosition` from the day the dataclass
    was written and was never in the insert, so it was written away and read back
    empty - and nothing failed, because a fallback in `dependencies_are_current`
    quietly covered for it. A field added to the dataclass and not to the statement
    fails here now, rather than in somebody's reloaded Tax Case.
    """
    from dataclasses import fields as dataclass_fields

    from db.cases import DERIVED_POSITION_FIELDS, PERSISTED_POSITION_COLUMNS
    from domain.positions import TaxPosition

    stored = set(PERSISTED_POSITION_COLUMNS) | set(DERIVED_POSITION_FIELDS)
    unaccounted = [f.name for f in dataclass_fields(TaxPosition) if f.name not in stored]
    assert unaccounted == [], (
        f"{unaccounted} is on TaxPosition but neither persisted nor declared derived "
        "in db/cases.py"
    )
    # And the other way: a column named here that no longer has a field behind it.
    names = {f.name for f in dataclass_fields(TaxPosition)}
    renamed = set(DERIVED_POSITION_FIELDS)
    orphans = [c for c in PERSISTED_POSITION_COLUMNS
               if c not in names and c not in {"position_key", "proposed_amount_eur"}]
    assert orphans == [], f"{orphans} is inserted but no longer exists on TaxPosition"
    assert renamed <= names


def test_the_projection_is_rebuilt_rather_than_stored():
    """Form line, formula and documents are not position state and are not kept.

    They were, and `save_positions` never wrote them, which is how a reloaded case
    came back with an empty form line and no formula on every row.
    """
    from dataclasses import fields as dataclass_fields

    from domain.positions import TaxPosition, assess_positions, project_expenses

    names = {f.name for f in dataclass_fields(TaxPosition)}
    assert {"form_line", "trace", "documents"} & names == set()

    facts = {"telecom.monthly_bill_eur": 45.0, "telecom.months": 12}
    row = next(r for r in project_expenses(assess_positions(facts), facts)
               if r["category"] == "telefon_internet")
    assert row["form_line"]
    assert row["trace"]


def test_both_answers_are_asked_again_when_what_was_decided_moves():
    """Yes and no alike: a decision is a decision about a particular figure.

    A refusal is not permanent. Somebody who declined 180 EUR of training costs
    because the amount was not worth the paperwork has not declined 1,800, and
    carrying the no across would decide the new question for them without ever
    showing it to them.
    """
    from domain.positions import (
        AssessmentStatus,
        TaxPosition,
        UserDecision,
        reconcile_positions,
    )

    def position(decision: UserDecision, fingerprint: str) -> TaxPosition:
        return TaxPosition(
            position_id="arbeitsmittel", category="arbeitsmittel",
            assessment_status=AssessmentStatus.identified, user_decision=decision,
            assessment_fingerprint=fingerprint,
        )

    accepted_elsewhere = reconcile_positions(
        [position(UserDecision.pending, "new")],
        [position(UserDecision.accepted, "old")],
    )
    assert accepted_elsewhere[0].user_decision is UserDecision.needs_reconfirmation

    unchanged = reconcile_positions(
        [position(UserDecision.pending, "same")],
        [position(UserDecision.accepted, "same")],
    )
    assert unchanged[0].user_decision is UserDecision.accepted

    refused_then_moved = reconcile_positions(
        [position(UserDecision.pending, "new")],
        [position(UserDecision.rejected, "old")],
    )
    assert refused_then_moved[0].user_decision is UserDecision.needs_reconfirmation

    refused_unchanged = reconcile_positions(
        [position(UserDecision.pending, "same")],
        [position(UserDecision.rejected, "same")],
    )
    assert refused_unchanged[0].user_decision is UserDecision.rejected


def test_the_explanation_accounts_for_every_purchase_not_just_the_first():
    """The figure and the formula that produces it have to be the same figure.

    The amount already summed every item; the explanation was built from item zero
    alone (#35). So a case with a desk and a chair showed 1,001.61 EUR above a formula
    that produced 689 - the kind of trace that is worse than none, because it looks
    checked.
    """
    from domain.positions import assess_positions, project_expenses

    facts = {
        "equipment.price_eur": 689.0, "equipment.price_is_net": False,
        "equipment.purchase_month": 9, "equipment.is_digital": False,
        "equipment.useful_life_years": 13, "equipment.professional_share_pct": 100,
        "equipment.price_eur#1": 312.61, "equipment.price_is_net#1": False,
        "equipment.purchase_month#1": 9, "equipment.is_digital#1": False,
        "equipment.useful_life_years#1": 13, "equipment.professional_share_pct#1": 100,
    }
    row = next(r for r in project_expenses(assess_positions(facts), facts)
               if r["category"] == "arbeitsmittel")

    assert row["amount_eur"] == 1001.61
    assert any("689" in line for line in row["trace"])
    assert any("312.61" in line for line in row["trace"]), (
        "the second purchase is in the total and not in the explanation"
    )
    # Numbered, or three formulas read as one long sum.
    assert row["trace"][0].startswith("1.")

    # And one entry per purchase for the Reviewer, which matches on the item index.
    assert [item["item_index"] for item in row["items"]] == [0, 1]
    assert sum(item["amount_eur"] for item in row["items"]) == row["amount_eur"]


def test_a_half_entered_second_purchase_is_in_neither_the_total_nor_the_formula():
    """An item the calculator skips must not appear in the explanation either."""
    from domain.positions import assess_positions, project_expenses

    facts = {
        "equipment.price_eur": 689.0, "equipment.price_is_net": False,
        "equipment.purchase_month": 9, "equipment.is_digital": False,
        "equipment.useful_life_years": 13, "equipment.professional_share_pct": 100,
        # a second purchase with only its price answered so far
        "equipment.price_eur#1": 312.61,
    }
    rows = project_expenses(assess_positions(facts), facts)
    row = next((r for r in rows if r["category"] == "arbeitsmittel"), None)
    if row is None:
        return  # the category is unclear while an item is incomplete, which is fine
    assert all("312.61" not in line for line in row["trace"])
