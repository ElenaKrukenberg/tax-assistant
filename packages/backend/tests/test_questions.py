"""The question catalogue and the relevance filter.

Two kinds of test here. The completeness ones guarantee that every field the case
needs is reachable — a field with no question is a figure that can never be
produced, and a question for a field that does not exist is a dead entry. The
relevance ones are the measurement's foundation: "the agent asked an irrelevant
question" only means something if irrelevance is decided by code that can be
tested, so this is where that decision is checked.
"""

import pytest

from domain.calculations import PARAMS_BY_TYPE
from domain.estimate import CALCULATORS
from domain.fields import (
    CATEGORY_FIELDS,
    FACT_NAMESPACES,
    PROFILE_FIELDS,
    PROFILE_NAMESPACE,
    ExpenseCategory,
    key_for,
)
from domain.questions import (
    BY_ID,
    BY_KEY,
    CATALOGUE,
    LOCALES,
    Question,
    When,
    relevant_questions,
)

# A profile that has said no to everything optional: employed all year, in the
# office, no purchases, no move, no applications, no training, no benefit.
PLAIN = {
    "profile.employed_months": 12,
    "profile.employer_count": 1,
    "profile.working_days_total": 220,
    "profile.works_remotely": False,
    "profile.has_minijob": False,
    "profile.benefit_type": "none",
    "profile.bought_work_equipment": False,
    "profile.claims_phone_internet": False,
    "profile.moved_for_work": False,
    "profile.searched_for_job": False,
    "profile.further_education": False,
}

REMOTE_WITH_LAPTOP = {
    **PLAIN,
    "profile.works_remotely": True,
    "profile.bought_work_equipment": True,
}


# --- completeness ---

def test_every_field_is_either_asked_or_filled_from_another_field():
    asked = {q.key for q in CATALOGUE}
    unreachable = []
    for spec in PROFILE_FIELDS:
        key = key_for(None, spec.name)
        if key not in asked and not spec.filled_by:
            unreachable.append(key)
    for category, specs in CATEGORY_FIELDS.items():
        for spec in specs:
            key = key_for(category, spec.name)
            if key not in asked and not spec.filled_by:
                unreachable.append(key)
    assert not unreachable, f"no question can ever fill: {unreachable}"


def test_every_question_points_at_a_field_that_exists():
    for q in CATALOGUE:
        q.spec()  # raises KeyError if the field is not in the category or profile


def test_question_ids_are_unique():
    assert len(BY_ID) == len(CATALOGUE)


def test_no_question_asks_a_field_that_is_filled_from_elsewhere():
    # Homeoffice's commute_days is the same fact as commuting_days. Asking it would
    # be the duplicate question the whole catalogue exists to avoid.
    for q in CATALOGUE:
        assert not q.spec().filled_by, f"{q.id} asks for a field filled from elsewhere"


def test_every_question_has_all_three_locales():
    for q in CATALOGUE:
        for locale in LOCALES:
            assert q.text[locale].strip(), f"{q.id} has no {locale} text"


def test_a_question_missing_a_locale_is_rejected():
    with pytest.raises(ValueError, match="no text for"):
        Question("x.y", "y", {"en": "?", "de": "?"})


# --- relevance ---

def test_an_answer_in_one_category_does_not_silence_another():
    # Three categories have an `amount_eur`. Keyed on the bare field name, paying
    # for a move would answer the training question too.
    known = {**PLAIN, "profile.moved_for_work": True, "profile.further_education": True}
    ids = {q.id for q in relevant_questions(known)}
    assert {"moving.amount_eur", "education.amount_eur"} <= ids

    known["moving.amount_eur"] = 2400.0
    ids = {q.id for q in relevant_questions(known)}
    assert "moving.amount_eur" not in ids
    assert "education.amount_eur" in ids


def test_a_closed_gate_removes_the_whole_category():
    open_ids = {q.id for q in relevant_questions(PLAIN)}
    for prefix in ("homeoffice.", "equipment.", "telecom.", "education.", "moving.",
                   "applications."):
        assert not [i for i in open_ids if i.startswith(prefix)], f"{prefix} stayed open"


def test_an_open_gate_admits_exactly_its_category():
    ids = {q.id for q in relevant_questions(REMOTE_WITH_LAPTOP)}
    assert "homeoffice.homeoffice_days" in ids
    assert "equipment.price_eur" in ids
    assert "moving.amount_eur" not in ids


def test_a_question_stays_closed_until_its_gate_is_answered():
    # Nothing known at all: only the questions that depend on nothing may be asked.
    ids = {q.id for q in relevant_questions({})}
    assert ids == {
        "profile.employed_months",
        "profile.has_minijob",
        "profile.benefit_type",
        "profile.moved_for_work",
        "profile.searched_for_job",
        "profile.further_education",
    }


def test_conditions_inside_a_category_use_the_qualified_key():
    # The public-transport question only applies to somebody without a car.
    with_car = {**PLAIN, "commute.own_car": True}
    without = {**PLAIN, "commute.own_car": False}
    assert "commute.public_transport_cost_eur" not in {q.id for q in relevant_questions(with_car)}
    assert "commute.public_transport_cost_eur" in {q.id for q in relevant_questions(without)}


def test_useful_life_is_only_asked_for_non_digital_equipment():
    digital = {**REMOTE_WITH_LAPTOP, "equipment.is_digital": True}
    furniture = {**REMOTE_WITH_LAPTOP, "equipment.is_digital": False}
    assert "equipment.useful_life_years" not in {q.id for q in relevant_questions(digital)}
    assert "equipment.useful_life_years" in {q.id for q in relevant_questions(furniture)}


def test_benefit_follow_ups_wait_for_a_benefit():
    none = {q.id for q in relevant_questions(PLAIN)}
    assert "profile.benefit_amount_eur" not in none
    some = {q.id for q in relevant_questions({**PLAIN, "profile.benefit_type": "alg_1"})}
    assert {"profile.benefit_amount_eur", "profile.has_paper_benefit_certificate"} <= some


def test_an_unanswered_condition_field_never_satisfies_the_condition():
    assert not When("profile.works_remotely", equals=True).holds({})
    assert not When("profile.works_remotely", equals=True).holds({"profile.works_remotely": None})
    assert When("profile.works_remotely", equals=True).holds({"profile.works_remotely": True})


def test_at_least_needs_a_number_not_a_truthy_value():
    assert not When("profile.employed_months", at_least=1).holds({"profile.employed_months": 0})
    assert not When("profile.employed_months", at_least=1).holds({"profile.employed_months": "yes"})
    assert When("profile.employed_months", at_least=1).holds({"profile.employed_months": 6})


def test_only_cautious_fields_may_be_assumed():
    from domain.fields import CATEGORY_FIELDS as CF
    from domain.fields import ExpenseCategory as EC
    from domain.fields import Provenance

    assumable = {s.name for s in PROFILE_FIELDS if s.has_assumption}
    for specs in CF.values():
        assumable |= {s.name for s in specs if s.has_assumption}
    # Assuming either of these enlarges the claim rather than making it cautious,
    # so both stay questions however inconvenient that is (ADR 0010).
    assert "professional_share_pct" not in assumable
    assert "months" not in assumable

    spec = next(s for s in CF[EC.arbeitsmittel] if s.name == "useful_life_years")
    assumed = spec.assume()
    assert assumed.value == 3
    assert assumed.provenance is Provenance.assumed
    assert assumed.needs_confirmation
    assert assumed.source, "an assumption has to carry the reason it is defensible"


def test_a_field_without_an_assumption_refuses_to_invent_one():
    spec = next(s for s in CATEGORY_FIELDS[ExpenseCategory.arbeitsmittel]
                if s.name == "professional_share_pct")
    with pytest.raises(ValueError, match="has to be answered"):
        spec.assume()


def test_an_assumption_without_a_reason_is_rejected():
    from domain.fields import AnswerType, FieldSpec

    with pytest.raises(ValueError, match="why it is defensible"):
        FieldSpec("employer_count", AnswerType.integer, assumption=1)


def test_an_answered_question_drops_out():
    known = {**PLAIN, "commute.commuting_days": 220}
    assert "commute.commuting_days" not in {q.id for q in relevant_questions(known)}


def test_nothing_is_relevant_once_a_plain_profile_is_fully_answered():
    known = {
        **PLAIN,
        "commute.commuting_days": 220,
        "commute.distance_km": 18,
        "commute.own_car": True,
    }
    assert relevant_questions(known) == ()


def test_the_two_day_counts_are_different_facts_and_both_collected():
    """Total working days and days the workplace was attended are not the same.

    Both were called `work_days` once - the yearly total in `validation.py`, the
    commute count in `calculations.py` - and the contradiction the Reviewer has to
    catch lives exactly in the gap between them: 145 commuting days plus 96
    home-office days against 220 worked in total. Since issue #36 each number has
    its own name, in the catalogue and in the calculators alike, so nothing has to
    remember which module meant which.
    """
    total = next(s for s in PROFILE_FIELDS if s.name == "working_days_total")
    commuting = next(s for s in CATEGORY_FIELDS[ExpenseCategory.entfernungspauschale]
                     if s.name == "commuting_days")
    assert total.name != commuting.name
    assert "work_days" not in (total.name, commuting.name)

    ids = {q.id for q in relevant_questions({"profile.employed_months": 12})}
    assert "profile.working_days_total" in ids
    assert "commute.commuting_days" in ids


# --- a question has to make sense on its own ------------------------------------------

# The agent chooses the order, so a question cannot lean on the one before it. Reported
# from a real interview: "Did you receive an income-replacement benefit?" was answered
# yes, an unrelated category question came next, and then "How much did you receive in
# total?" arrived with nothing on screen saying what it was about. The catalogue had
# been written as if it were read top to bottom, which is exactly what this product
# does not do — and ADR 0001 puts the wording in code so that it can be held to a
# standard, which is what this holds it to.
DANGLING = {
    "en": (r"\bdid it cost\b", r"\bbuy it\b", r"\bis it a\b", r"\buse it for\b",
           r"\bpart of it\b", r"\bthat price\b", r"\bthat spent\b", r"\bthose days\b",
           r"\bis it normally written off\b", r"^how much did you receive in total"),
    "de": (r"\bdavon ersetzt\b", r"\bhaben Sie es\b", r"\bwird es üblicherweise\b",
           r"\bdiesen Tagen\b", r"\bdiese Kosten\b", r"\bdieser Preis\b",
           r"^Wie hoch war die Leistung"),
    "ru": (r"\bэто стоило\b", r"\bэто купили\b", r"\bиспользовали это\b",
           r"\bэти деньги\b", r"\bэта цена\b", r"\bэти дни\b",
           r"\bчасть\s*—", r"^Какую сумму вы получили в общей сложности"),
}

# Two questions keep a pronoun and are right to. `distance_km` uses the expletive "it"
# of "how far is it from A to B", which refers to nothing at all; `moving.reason` names
# the move in the same sentence before referring back to it.
SELF_CONTAINED_PRONOUNS = {"commute.distance_km", "moving.reason"}


def test_no_question_depends_on_the_one_asked_before_it():
    import re

    offenders = []
    for question in CATALOGUE:
        if question.id in SELF_CONTAINED_PRONOUNS:
            continue
        for locale, patterns in DANGLING.items():
            text = question.text[locale]
            for pattern in patterns:
                if re.search(pattern, text, re.I):
                    offenders.append(f"{question.id} [{locale}]: {text}")
    assert not offenders, "questions that only make sense in catalogue order:\n" + \
        "\n".join(offenders)


# --- how a fact is keyed (issues #61, #36) --------------------------------------

def test_a_questions_id_is_the_key_it_fills():
    """One string, not two that have to be kept in step.

    The catalogue's ids were already written as `commute.distance_km` while the keys
    were built from the category name (`entfernungspauschale.commuting_days`), so the
    two spellings drifted in the same file. Now `Question.key` derives from the same
    namespace the id uses, and this is what stops them parting again.
    """
    mismatched = [(q.id, q.key) for q in CATALOGUE if q.id != q.key]
    assert mismatched == [], f"id and key disagree: {mismatched}"
    assert BY_ID == BY_KEY


def test_every_stored_fact_is_qualified_by_a_namespace():
    """No fact is keyed by a bare name, the profile's own included.

    A bare `amount_eur` would be three different figures - the move, the training,
    the applications - and a rule with an exception for the profile is a rule nobody
    remembers to apply.
    """
    for question in CATALOGUE:
        namespace, _, field = question.key.partition(".")
        assert field, f"{question.id}: not qualified"
        assert namespace in ({PROFILE_NAMESPACE} | set(FACT_NAMESPACES.values()))
        assert field == question.field


def test_no_namespace_is_named_after_a_tax_category():
    """The point of the rename (issue #14).

    The same commute kilometres feed the Entfernungspauschale and, below the
    Grundfreibetrag, the Mobilitaetspraemie. A namespace named after one consumer is
    already wrong for the other, so a fact is named after what it means.
    """
    categories = {c.value for c in ExpenseCategory}
    assert set(FACT_NAMESPACES.values()) & categories == set()


def test_a_field_and_its_calculator_parameter_share_one_name():
    """The invariant that replaces `maps_to` (issue #36).

    `work_days` meant the yearly total in `validation.py` and the commute count in
    `calculations.py`, and a `maps_to` on the field papered over it. One name per
    number instead, checked here: the day these drift, `to_params` starts handing a
    calculator a parameter it does not have and the figure quietly disappears.
    """
    for category, calculation in CALCULATORS.items():
        model = PARAMS_BY_TYPE[calculation]
        parameters = set(model.model_fields)
        for spec in CATEGORY_FIELDS[category]:
            if spec.name in parameters:
                continue
            # The exemption is one-way and worth stating: the parameter models ignore
            # a key they do not declare, so a field that moves a figure and misses
            # its parameter loses the figure in silence. A field that changes no
            # amount - `other_workplace_available` decides Zeile 58 against Zeile 59
            # and nothing else - may legitimately have no parameter at all.
            assert not spec.affects_amount, (
                f"{key_for(category, spec.name)} affects the amount but "
                f"{model.__name__} has no parameter of that name, and the model "
                "would drop it without a word"
            )


# --- more than one purchase in a category (#35) ---------------------------------

def test_a_second_purchase_opens_only_when_the_user_says_there_is_one():
    """The interview could collect exactly one item per category before this.

    The gate is the user's own answer, not a guess: `has_more` on item N is what opens
    item N+1, so nobody is asked about a second invoice they never mentioned.
    """
    from domain.questions import open_items

    started = {
        "profile.bought_work_equipment": True,
        "equipment.price_eur": 689.0, "equipment.price_is_net": False,
        "equipment.purchase_month": 9, "equipment.is_digital": False,
    }
    opened = {(o.question.id, o.item_index) for o in open_items(started)}
    assert ("equipment.has_more", 0) in opened, "nothing asks whether there is another"
    assert not any(index > 0 for _, index in opened), "a second item opened unasked"

    said_yes = dict(started, **{"equipment.has_more": True})
    second = {o.question.id for o in open_items(said_yes) if o.item_index == 1}
    assert "equipment.price_eur" in second

    said_no = dict(started, **{"equipment.has_more": False})
    assert not any(o.item_index > 0 for o in open_items(said_no))


def test_the_anything_else_question_waits_until_the_purchase_is_described():
    """Asked mid-item it would read as an interruption, and it is not one."""
    from domain.questions import open_items

    half = {"profile.bought_work_equipment": True, "equipment.price_eur": 689.0}
    assert not any(o.question.id == "equipment.has_more" for o in open_items(half))


def test_an_interview_only_field_never_reaches_a_calculator():
    """`has_more` is a fact about the conversation, and the calculators declare no
    such parameter - handed one they would refuse the whole call."""
    from domain.estimate import to_params
    from domain.fields import ExpenseCategory

    params, _ = to_params(ExpenseCategory.arbeitsmittel, {
        "equipment.price_eur": 689.0, "equipment.price_is_net": False,
        "equipment.purchase_month": 9, "equipment.is_digital": False,
        "equipment.has_more": True,
    })
    assert "has_more" not in params


def test_saying_there_are_no_more_purchases_does_not_unsettle_a_decision():
    """It changes no figure, so it must not turn an approved position stale (#35)."""
    from domain.positions import dependency_ids
    from domain.fields import ExpenseCategory

    assert not any(key.endswith("has_more")
                   for key in dependency_ids(ExpenseCategory.arbeitsmittel))
