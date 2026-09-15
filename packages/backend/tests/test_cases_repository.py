"""The repository against the real database.

Marked `integration` and skipped unless DATABASE_URL and TEST_USER_ID are set, so
the ordinary suite stays fast and offline (ADR 0003). These tests exist because the
things most likely to break here cannot be checked against a fake: the row level
security policies, the trigger that makes a finalized case read-only, the constraint
that an assumption must carry its reason, and the role switch that makes any of it
apply to this backend at all.

Each test cleans up after itself. They use one tax year each so two of them running
in either order cannot collide on the one-case-per-year constraint.
"""

from __future__ import annotations

import uuid

import pytest

from tests import dbguard

from core.config import get_settings
from db import cases
from db.connection import as_user
from domain.fields import FieldValue, Provenance

pytestmark = pytest.mark.integration

settings = get_settings()
USER = dbguard.require_test_database()


@pytest.fixture
def year(request) -> int:
    """A tax year of this test's own, cleaned up whether it passes or fails."""
    # 2090 upwards: inside the schema's range, nowhere near a real tax year.
    taken = 2090 + (hash(request.node.name) % 10)
    case = cases.create_case(USER, taken)
    yield taken
    try:
        cases.reopen(USER, case.id)
        cases.delete_case(USER, case.id)
    except cases.CaseNotFound:
        pass


def test_a_case_can_be_created_read_back_and_listed(year):
    case = cases.create_case(USER, year)
    assert case.tax_year == year
    assert case.status == "gathering"

    again = cases.get_case(USER, case.id)
    assert again.id == case.id

    assert year in [c.tax_year for c in cases.list_cases(USER)]


def test_creating_the_same_year_twice_returns_the_same_case(year):
    first = cases.create_case(USER, year)
    second = cases.create_case(USER, year)
    assert first.id == second.id, "one case per user per year"


def test_values_round_trip_with_their_provenance(year):
    case = cases.create_case(USER, year)
    cases.set_field(USER, case.id, "profile.employed_months",
                    FieldValue(12, Provenance.answer, "profile.employed_months"))
    cases.set_field(USER, case.id, "commute.distance_km",
                    FieldValue(27, Provenance.document, "lohnsteuerbescheinigung"))

    fields = cases.get_fields(USER, case.id)
    assert fields["profile.employed_months"].value == 12
    assert fields["profile.employed_months"].provenance is Provenance.answer
    assert fields["commute.distance_km"].provenance is Provenance.document


def test_writing_a_value_twice_replaces_it(year):
    case = cases.create_case(USER, year)
    key = "commute.commuting_days"
    cases.set_field(USER, case.id, key, FieldValue(200, Provenance.assumed, "typical year"))
    cases.set_field(USER, case.id, key, FieldValue(145, Provenance.answer, "commute.commuting_days"))

    field = cases.get_fields(USER, case.id)[key]
    assert field.value == 145
    assert field.provenance is Provenance.answer


def test_a_repeating_category_keeps_its_items_apart(year):
    case = cases.create_case(USER, year)
    for index, price in enumerate([1400.0, 380.0, 24.0]):
        cases.set_field(USER, case.id, "equipment.price_eur",
                        FieldValue(price, Provenance.answer, "equipment.price_eur"),
                        item_index=index)

    fields = cases.get_fields(USER, case.id)
    assert fields["equipment.price_eur"].value == 1400.0
    assert fields["equipment.price_eur#1"].value == 380.0
    assert fields["equipment.price_eur#2"].value == 24.0


def test_the_database_refuses_an_assumption_without_a_reason(year):
    case = cases.create_case(USER, year)
    with pytest.raises(Exception, match="a_value_the_user_must_confirm_says_why"):
        cases.set_field(USER, case.id, "equipment.useful_life_years",
                        FieldValue(3, Provenance.assumed, source=""))


def test_finalizing_waits_for_every_assumption_to_be_confirmed(year):
    case = cases.create_case(USER, year)
    cases.set_field(USER, case.id, "equipment.useful_life_years",
                    FieldValue(3, Provenance.assumed, "three years is usual"))
    assert cases.values_awaiting_confirmation(USER, case.id) == ["equipment.useful_life_years"]

    with pytest.raises(cases.CaseIsFinalized, match="unconfirmed"):
        cases.finalize(USER, case.id)

    cases.set_field(USER, case.id, "equipment.useful_life_years",
                    FieldValue(3, Provenance.assumed, "three years is usual", confirmed=True))
    assert cases.values_awaiting_confirmation(USER, case.id) == []
    assert cases.finalize(USER, case.id).status == "finalized"


def test_a_finalized_case_is_read_only_until_reopened(year):
    case = cases.create_case(USER, year)
    cases.set_field(USER, case.id, "profile.employed_months", FieldValue(12, Provenance.answer, "q"))
    cases.finalize(USER, case.id)

    with pytest.raises(cases.CaseIsFinalized):
        cases.set_field(USER, case.id, "profile.employed_months", FieldValue(6, Provenance.answer, "q"))

    cases.reopen(USER, case.id)
    cases.set_field(USER, case.id, "profile.employed_months", FieldValue(6, Provenance.answer, "q"))
    assert cases.get_fields(USER, case.id)["profile.employed_months"].value == 6


def test_the_trigger_holds_even_when_the_repository_is_bypassed(year):
    """The guard is the database's, not the repository's.

    `set_field` checks the status first and raises a readable error. This goes around
    that check to prove the trigger is what actually stops the write — otherwise the
    rule would only hold as long as every caller remembers to ask.
    """
    case = cases.create_case(USER, year)
    cases.finalize(USER, case.id)

    with pytest.raises(Exception, match="finalized"):
        with as_user(USER) as cur:
            cur.execute(
                """
                insert into field_values (case_id, key, value, provenance)
                values (%s, 'profile.employed_months', '12'::jsonb, 'answer')
                """,
                (case.id,),
            )


def test_another_users_case_is_invisible_rather_than_forbidden(year):
    """Row level security in force: a stranger's case reads as absent.

    Absent, not "denied" — a difference that matters, because an error message
    confirming a case exists is itself a leak.
    """
    case = cases.create_case(USER, year)
    stranger = str(uuid.uuid4())

    with pytest.raises(cases.CaseNotFound):
        cases.get_case(stranger, case.id)

    assert cases.list_cases(stranger) == []


def test_deleting_a_case_takes_its_values_with_it(year):
    case = cases.create_case(USER, year)
    cases.set_field(USER, case.id, "profile.employed_months", FieldValue(12, Provenance.answer, "q"))
    cases.delete_case(USER, case.id)

    with pytest.raises(cases.CaseNotFound):
        cases.get_case(USER, case.id)


# --- values carried over from an earlier year --------------------------------------

def test_a_remembered_value_blocks_the_report_until_it_is_confirmed(year):
    """The same gate as an assumption, for the same reason (ADR 0010).

    Also the one check that the 0003 migration is actually applied: without it the
    insert below fails the provenance constraint rather than reaching finalize.
    """
    case = cases.create_case(USER, year)
    key = "commute.distance_km"
    cases.set_field(USER, case.id, key,
                    FieldValue(42, Provenance.remembered, f"carried over from your {year - 1} case"))

    assert cases.values_awaiting_confirmation(USER, case.id) == [key]
    with pytest.raises(cases.CaseIsFinalized, match="unconfirmed"):
        cases.finalize(USER, case.id)

    cases.confirm_values(USER, case.id, [key])
    assert cases.values_awaiting_confirmation(USER, case.id) == []
    assert cases.get_fields(USER, case.id)[key].confirmed is True
    assert cases.finalize(USER, case.id).status == "finalized"


def test_the_database_refuses_a_remembered_value_that_cannot_say_where_it_came_from(year):
    case = cases.create_case(USER, year)
    with pytest.raises(Exception, match="a_value_the_user_must_confirm_says_why"):
        cases.set_field(USER, case.id, "commute.distance_km",
                        FieldValue(42, Provenance.remembered, source=""))


def test_a_rejected_carried_value_leaves_the_case_entirely(year):
    case = cases.create_case(USER, year)
    key = "commute.distance_km"
    cases.set_field(USER, case.id, key,
                    FieldValue(42, Provenance.remembered, "carried over"))

    cases.clear_field(USER, case.id, key)
    assert key not in cases.get_fields(USER, case.id)


def test_confirming_touches_only_the_keys_it_was_given(year):
    case = cases.create_case(USER, year)
    cases.set_field(USER, case.id, "commute.distance_km",
                    FieldValue(42, Provenance.remembered, "carried over"))
    cases.set_field(USER, case.id, "equipment.useful_life_years",
                    FieldValue(3, Provenance.assumed, "three years is usual"))

    cases.confirm_values(USER, case.id, ["commute.distance_km"])
    assert cases.values_awaiting_confirmation(USER, case.id) == ["equipment.useful_life_years"]


def test_findings_are_stored_worst_first_and_replaced_wholesale(year):
    case = cases.create_case(USER, year)

    cases.save_findings(USER, case.id, [
        {"severity": "suggestion", "title": "third", "reasoning": "r3",
         "category": "arbeitsmittel"},
        {"severity": "blocking", "title": "first", "reasoning": "r1",
         "category": "entfernungspauschale"},
        {"severity": "warning", "title": "second", "reasoning": "r2", "category": ""},
    ])

    stored = cases.get_findings(USER, case.id)
    # Worst first, because that is the order the Review screen reads in.
    assert [f.title for f in stored] == ["first", "second", "third"]
    assert [f.severity for f in stored] == ["blocking", "warning", "suggestion"]
    assert stored[0].category == "entfernungspauschale"
    assert stored[1].category == ""
    assert all(f.resolution == "open" for f in stored)

    # A second review replaces the first rather than adding to it: a revision round
    # that clears a finding has to clear the row, or the screen shows it forever.
    cases.save_findings(USER, case.id, [
        {"severity": "warning", "title": "only this one", "reasoning": "r",
         "category": "homeoffice_tagespauschale"},
    ])
    assert [f.title for f in cases.get_findings(USER, case.id)] == ["only this one"]

    # And an empty review is a meaningful answer, not a no-op.
    cases.save_findings(USER, case.id, [])
    assert cases.get_findings(USER, case.id) == []


def test_a_severity_the_reviewer_invented_keeps_the_finding(year):
    """The check constraint would reject it; losing the judgement is the worse loss."""
    case = cases.create_case(USER, year)
    cases.save_findings(USER, case.id, [
        {"severity": "catastrophic", "title": "kept", "reasoning": "r", "category": ""},
    ])
    stored = cases.get_findings(USER, case.id)
    assert [(f.severity, f.title) for f in stored] == [("suggestion", "kept")]


def test_findings_cannot_be_written_to_a_finalized_case(year):
    case = cases.create_case(USER, year)
    cases.save_findings(USER, case.id, [
        {"severity": "warning", "title": "before", "reasoning": "r", "category": ""},
    ])
    cases.finalize(USER, case.id)

    with pytest.raises(cases.CaseIsFinalized):
        cases.save_findings(USER, case.id, [])
    # Reading is untouched: the Review screen has to work on a finished case.
    assert [f.title for f in cases.get_findings(USER, case.id)] == ["before"]


def test_another_user_cannot_read_this_case_findings(year):
    case = cases.create_case(USER, year)
    cases.save_findings(USER, case.id, [
        {"severity": "blocking", "title": "private", "reasoning": "r", "category": ""},
    ])
    assert cases.get_findings(str(uuid.uuid4()), case.id) == []


# --- tax positions (issue #17) ---------------------------------------------------

def _position(fingerprint: str = "fp-1", decision: str = "pending"):
    from domain.rule_citations import for_rule
    from domain.positions import (
        AssessmentStatus,
        FactDependency,
        Origin,
        ProvenanceEntry,
        TaxPosition,
        UserDecision,
    )
    return TaxPosition(
        position_id="fortbildungskosten",
        category="fortbildungskosten",
        assessment_status=AssessmentStatus.identified,
        user_decision=UserDecision(decision),
        dependent_facts=[FactDependency("education.amount_eur", "v1")],
        # A real catalogue entry, not a made-up one: the round trip has to carry the
        # shape the product actually stores, and `source_refs` became structured
        # citations rather than identifier strings when #17 built the catalogue.
        source_refs=[for_rule("anlage-n:2025:telefon-internet:flat-share:v1")],
        calculator_version="calculator:education:v1",
        rule_version="anlage-n:2025:fortbildungskosten:v1",
        proposed_amount=1200.0,
        origin=Origin.deterministic_rule,
        missing_facts=[],
        assessment_fingerprint=fingerprint,
        provenance=[ProvenanceEntry("assessment", Origin.deterministic_rule,
                                    "fortbildungskosten", "anlage-n:2025:v1")],
    )


def test_a_tax_position_survives_the_round_trip_whole(year):
    """Every part of it, not most of it.

    `assessment_fingerprint` is why this test exists: it was on the dataclass, was
    never in the insert, and came back empty on every read - and no test looked,
    because there was no round-trip test for positions at all. Comparing field by
    field rather than spot-checking is the point, so the next dropped column fails
    here.
    """
    from dataclasses import fields as dataclass_fields

    case = cases.create_case(USER, year)
    written = _position()
    cases.save_positions(USER, case.id, [written])

    read_back = cases.get_positions(USER, case.id)
    assert len(read_back) == 1
    for f in dataclass_fields(type(written)):
        assert getattr(read_back[0], f.name) == getattr(written, f.name), f.name


def test_a_changed_fingerprint_takes_an_acceptance_back_to_the_user(year):
    """A new rule or calculator version invalidates a decision made under the old one.

    The upsert used to compare `dependent_facts`, which is a strict subset of what
    the fingerprint covers: the rule version and the calculator version are not facts,
    so shipping new rules for a year left every accepted position looking current
    while the figure behind it was recomputed under rules the user never saw.
    """
    from domain.positions import UserDecision

    case = cases.create_case(USER, year)
    cases.save_positions(USER, case.id, [_position(fingerprint="fp-1")])
    cases.decide_position(USER, case.id, "fortbildungskosten", "accepted")
    assert cases.get_positions(USER, case.id)[0].user_decision is UserDecision.accepted

    # Same facts, same amount - only the rules moved.
    moved = _position(fingerprint="fp-2")
    moved.rule_version = "anlage-n:2025:fortbildungskosten:v2"
    cases.save_positions(USER, case.id, [moved])

    assert cases.get_positions(USER, case.id)[0].user_decision is (
        UserDecision.needs_reconfirmation
    )


def test_an_unchanged_fingerprint_leaves_the_acceptance_alone(year):
    """The other half: a save that changes nothing must not re-ask."""
    from domain.positions import UserDecision

    case = cases.create_case(USER, year)
    cases.save_positions(USER, case.id, [_position(fingerprint="fp-1")])
    cases.decide_position(USER, case.id, "fortbildungskosten", "accepted")
    cases.save_positions(USER, case.id, [_position(fingerprint="fp-1")])

    assert cases.get_positions(USER, case.id)[0].user_decision is UserDecision.accepted


def test_a_refusal_is_asked_again_when_the_rules_move(year):
    """The SQL side of the same rule: a no is an answer about a particular figure.

    Kept here as well as in `test_positions.py` because there are two paths that
    change a decision - the graph reconciles in Python, the repository reconciles in
    the upsert - and the two agreeing is the thing worth pinning.
    """
    from domain.positions import UserDecision

    case = cases.create_case(USER, year)
    cases.save_positions(USER, case.id, [_position(fingerprint="fp-1")])
    cases.decide_position(USER, case.id, "fortbildungskosten", "rejected")
    assert cases.get_positions(USER, case.id)[0].user_decision is UserDecision.rejected

    # Unchanged save: the refusal stands, nobody is asked twice for nothing.
    cases.save_positions(USER, case.id, [_position(fingerprint="fp-1")])
    assert cases.get_positions(USER, case.id)[0].user_decision is UserDecision.rejected

    # The rules move: the refusal was about the old figure, so it is asked again.
    cases.save_positions(USER, case.id, [_position(fingerprint="fp-2")])
    assert cases.get_positions(USER, case.id)[0].user_decision is (
        UserDecision.needs_reconfirmation
    )


def test_a_corrected_value_remembers_what_it_replaced(year):
    """The correction path #28 opened: edit the fact, not the total.

    Three things have to happen together, which is why they are one function: the
    value becomes an answer, what it replaced is kept so the trace can say the figure
    was changed by hand, and the Reviewer's findings go - every one of them was raised
    against the old number.
    """
    case = cases.create_case(USER, year)
    cases.set_field(USER, case.id, "commute.commuting_days",
                    FieldValue(154, Provenance.document, source="payslip.jpg", confirmed=True))
    cases.save_findings(USER, case.id, [
        {"severity": "warning", "title": "154 days looks high",
         "reasoning": "against 11 employed months", "category": "entfernungspauschale"},
    ])

    cases.correct_field(USER, case.id, "commute.commuting_days", 145)

    held = cases.get_fields(USER, case.id)["commute.commuting_days"]
    assert held.value == 145
    # A value a model read off a document does not stay a document value once a
    # person has overridden it.
    assert held.provenance is Provenance.answer
    assert held.superseded_value == 154
    assert held.superseded_provenance == "document"
    assert cases.get_findings(USER, case.id) == []


def test_correcting_a_value_that_is_not_there_is_refused(year):
    case = cases.create_case(USER, year)
    try:
        cases.correct_field(USER, case.id, "commute.commuting_days", 145)
    except KeyError:
        pass
    else:
        raise AssertionError("a correction must not invent a value that was never set")


def test_removing_one_purchase_leaves_the_others(year):
    """A wrong thing, not a wrong number: an invoice uploaded by mistake (#35).

    Keyed by meaning rather than by category, so this has to match `equipment.` and
    not `arbeitsmittel.` - the category name matches no stored key at all.
    """
    case = cases.create_case(USER, year)
    for index in (0, 1):
        cases.set_field(USER, case.id, "equipment.price_eur",
                        FieldValue(100.0 + index, Provenance.document,
                                   source=f"invoice-{index}", confirmed=True),
                        item_index=index)

    removed = cases.remove_item(USER, case.id, "arbeitsmittel", 1)
    assert removed == 1

    held = cases.get_fields(USER, case.id)
    assert "equipment.price_eur" in held
    assert "equipment.price_eur#1" not in held


def test_item_zero_cannot_be_removed(year):
    """Removing it would leave a category whose first purchase is #1, which every
    caller that starts at zero reads as empty. Correcting its values is the operation."""
    case = cases.create_case(USER, year)
    cases.set_field(USER, case.id, "equipment.price_eur",
                    FieldValue(100.0, Provenance.answer, source="q", confirmed=True))
    try:
        cases.remove_item(USER, case.id, "arbeitsmittel", 0)
    except ValueError:
        pass
    else:
        raise AssertionError("item 0 must not be removable")
