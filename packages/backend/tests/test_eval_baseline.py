"""The measurement harness, before there is an agent to measure.

The most valuable test here is the dullest: that every key in `profiles.jsonl`
matches a real catalogue key. A typo would not fail anything — it would quietly make
the profile unable to answer that question, and every number computed from it would
be wrong in a direction that looks plausible.
"""

import pytest

from domain.fields import CATEGORY_FIELDS, ExpenseCategory, namespace_of
from domain.questions import CATALOGUE
from eval.baseline import (
    load_profiles,
    run_filter,
    run_questionnaire,
)

PROFILES = load_profiles()
CATALOGUE_KEYS = {q.key for q in CATALOGUE}
IDS = [p.id for p in PROFILES]


def test_the_profile_set_is_the_one_the_plan_describes():
    assert len(PROFILES) == 10
    assert len(set(IDS)) == 10, "duplicate profile id"


@pytest.mark.parametrize("profile", PROFILES, ids=IDS)
def test_every_answer_key_exists_in_the_catalogue(profile):
    unknown = sorted(set(profile.answers) - CATALOGUE_KEYS)
    assert not unknown, f"{profile.id} answers keys nothing asks for: {unknown}"


@pytest.mark.parametrize("profile", PROFILES, ids=IDS)
def test_every_cannot_answer_key_exists_too(profile):
    unknown = sorted(profile.cannot_answer - CATALOGUE_KEYS)
    assert not unknown, f"{profile.id} cannot-answer keys nothing asks for: {unknown}"


@pytest.mark.parametrize("profile", PROFILES, ids=IDS)
def test_the_questionnaire_asks_the_whole_catalogue(profile):
    t = run_questionnaire(profile)
    assert t.question_count == len(CATALOGUE)
    assert t.asked == [q.id for q in CATALOGUE], "the form's order is the catalogue's"


@pytest.mark.parametrize("profile", PROFILES, ids=IDS)
def test_the_filter_never_repeats_a_question(profile):
    # Three profiles used to loop here: an unanswerable question stayed relevant.
    t = run_filter(profile)
    assert len(t.asked) == len(set(t.asked))
    assert t.question_count < len(CATALOGUE)


@pytest.mark.parametrize("profile", PROFILES, ids=IDS)
def test_the_filter_asks_nothing_irrelevant(profile):
    """Zero by construction, and that is the point.

    It is the bar the agent has to clear rather than merely match: beating the form on
    this metric proves nothing, because plain code already does.
    """
    assert run_filter(profile).irrelevant == []


@pytest.mark.parametrize("profile", PROFILES, ids=IDS)
def test_the_filter_leaves_no_required_field_of_an_opened_category_empty(profile):
    missing = run_filter(profile).missing_required()
    assert missing == [], f"{profile.id} would produce a figure it cannot justify: {missing}"


@pytest.mark.parametrize("profile", PROFILES, ids=IDS)
def test_the_filter_opens_exactly_the_categories_the_profile_expects(profile):
    expected = set(profile.expected.get("categories", []))
    if not expected:
        pytest.skip("profile declares no expected categories")

    known = run_filter(profile).known
    opened = {c.value for c in ExpenseCategory
              if any(k.startswith(f"{namespace_of(c)}.") for k in known)}
    assert opened == expected


def test_the_form_asks_more_than_the_filter_on_every_profile():
    for profile in PROFILES:
        form = run_questionnaire(profile).question_count
        filt = run_filter(profile).question_count
        assert filt < form, profile.id


def test_the_form_wastes_questions_and_the_filter_does_not():
    """The form's irrelevant count is what the comparison is about.

    On a profile that bought nothing and moved nowhere, a form still walks through
    every purchase and every moving question. Counting those is the measurement.
    """
    plain = next(p for p in PROFILES if p.id.startswith("p03"))
    assert len(run_questionnaire(plain).irrelevant) > 10
    assert run_filter(plain).irrelevant == []


def test_a_repeating_category_is_asked_once_per_run_for_now():
    """A known limitation, recorded rather than hidden.

    Three categories repeat per item (`repeats=True`), but neither the catalogue nor
    these arms ask for a second item yet: profile p08 buys a monitor and a laptop, and
    only one purchase is collected. Whatever makes repetition work will change this
    test, which is the point of having it.
    """
    repeating = [c.value for c in ExpenseCategory
                 if any(s.repeats for s in CATEGORY_FIELDS[c])]
    assert repeating == ["arbeitsmittel", "fortbildungskosten", "bewerbungskosten"]

    p08 = next(p for p in PROFILES if p.id.startswith("p08"))
    known = run_filter(p08).known
    assert "equipment.price_eur" in known
    assert not any(k.endswith("#1") for k in known), "no second item is collected yet"


def test_golden_references_exist_in_the_kb():
    """Every reference_context_id names a real KB document.

    The Umzugskosten lesson: an expectation authored from memory referenced the
    Anleitung while the KB held a dedicated document the author did not know
    existed. Memory is not an inventory — docs/KB_INDEX.md is, and this test is
    the mechanical half of that guarantee: a golden case cannot point at a ghost.
    """
    import json
    import re
    from pathlib import Path

    kb = Path(__file__).resolve().parents[3] / "KB"
    source_ids = set()
    for f in kb.glob("*.md"):
        m = re.search(r"^source_id:\s*(\S+)", f.read_text(errors="ignore")[:2000], re.M)
        if m:
            source_ids.add(m.group(1))
    assert len(source_ids) >= 40, "the KB inventory looks implausibly small"

    golden = Path(__file__).resolve().parents[1] / "eval" / "golden.jsonl"
    ghosts = []
    for line in golden.read_text().splitlines():
        case = json.loads(line)
        for ref in case.get("reference_context_ids", []):
            if ref not in source_ids:
                ghosts.append((case["id"], ref))
        primary = case.get("primary_context_id")
        if primary and primary not in source_ids:
            ghosts.append((case["id"], primary))
    assert not ghosts, f"golden references documents the KB does not hold: {ghosts}"


# --- the second return --------------------------------------------------------------

def test_a_second_return_is_shorter_and_loses_nothing():
    """The carry-over claim, as a regression guard rather than a report.

    The numbers live in eval/AGENT_EVAL.md; what must never regress is the shape:
    every profile saves something, and no profile loses an amount-affecting field
    because a value was carried instead of asked.
    """
    from eval.carry_over import run

    runs = [run(p) for p in load_profiles()]
    assert all(r.saved > 0 for r in runs), [r.profile_id for r in runs if r.saved <= 0]
    assert all(r.lost_required == [] for r in runs), [
        (r.profile_id, r.lost_required) for r in runs if r.lost_required
    ]


def test_a_carried_value_is_known_without_having_been_asked():
    """Seeding must not sneak into the question count, or the saving is imaginary."""
    from eval.baseline import run_filter

    profile = load_profiles()[0]
    plain = run_filter(profile)
    seeded = run_filter(profile, seeded={"commute.distance_km": 42})

    assert "commute.distance_km" not in seeded.asked
    assert seeded.known["commute.distance_km"] == 42
    assert seeded.question_count < plain.question_count or "commute.distance_km" not in plain.asked
