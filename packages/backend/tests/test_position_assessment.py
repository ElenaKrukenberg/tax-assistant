from domain.form_fill import entries_for
from domain.positions import (
    AssessmentStatus,
    assess_positions,
    includable_positions,
    project_expenses,
)
from domain.tax_years import for_year


def test_runtime_assessment_produces_non_conclusive_statuses():
    positions = {position.category: position for position in assess_positions({})}
    assert positions["entfernungspauschale"].assessment_status is AssessmentStatus.criteria_not_met

    partial = {"homeoffice.homeoffice_days": 10}
    assert {position.category: position for position in assess_positions(partial)}[
        "homeoffice_tagespauschale"
    ].assessment_status is AssessmentStatus.unclear


def test_runtime_assessment_identifies_a_complete_deterministic_position():
    facts = {
        "education.amount_eur": 1200,
        "education.reimbursed_eur": 0,
        "education.kind": "course",
    }
    positions = {position.category: position for position in assess_positions(facts)}
    position = positions["fortbildungskosten"]
    assert position.assessment_status is AssessmentStatus.identified
    assert position.proposed_amount == 1200
    assert position.rule_version
    assert position.assessment_fingerprint


def test_homeoffice_declares_cross_category_commute_dependency():
    position = next(
        position for position in assess_positions({})
        if position.category == "homeoffice_tagespauschale"
    )
    assert any(
        dependency.fact_id == "commute.commuting_days"
        for dependency in position.dependent_facts
    )


def test_form_mapper_receives_only_included_position_facts():
    facts = {
        "commute.commuting_days": 100,
        "commute.distance_km": 10,
        "commute.own_car": True,
        "commute.public_transport_cost_eur": 50,
    }
    positions = assess_positions(facts, for_year(2025))
    for position in positions:
        if position.category == "entfernungspauschale":
            position.user_decision = "rejected"
    included = includable_positions(positions, facts)
    assert project_expenses(included, facts, for_year(2025)) == []
    scoped_facts = {
        dependency.fact_id: facts[dependency.fact_id]
        for position in included
        for dependency in position.dependent_facts
        if dependency.fact_id in facts
    }
    entries, _ = entries_for(
        scoped_facts, project_expenses(included, facts, for_year(2025)), for_year(2025),
    )
    assert entries == []
