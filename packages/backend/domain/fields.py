"""What a Tax Case can know: profile facts and the fields each category needs.

This is the schema three other things are derived from, which is why it is plain
data and imports nothing but the standard library:

- the question catalogue asks for exactly these fields, and its answer controls
  come from `AnswerType` plus the bounds recorded here (ADR 0001);
- the baseline questionnaire is one question per field, generated rather than
  written, so its length is a consequence of this file and not a choice made by
  whoever reports the measurement;
- the database columns for a Tax Case follow the same shape.

The per-category fields are lifted from the Pydantic parameter models in
`calculations.py`, which already encoded them with their ranges and defaults.
Where a field exists there, its name is identical - not merely similar - so a
category's answers can be handed to its calculator with no translation step at
all. That is an invariant, checked by the tests: the day the two drift apart, one
number acquires two names, which is how `work_days` came to mean the yearly total
in one module and the commute count in another (issue #36).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Optional

_NO_ASSUMPTION: Final = object()


class Provenance(str, Enum):
    """Where a value in the case came from.

    Recorded per field, not per expense: the report has to be able to say that the
    distance came from an answer, the price from a receipt, the useful life from an
    assumption the system offered, and the commute from what the same person said
    about the previous year.
    """

    answer = "answer"       # the user said so, in the interview or in the chat
    document = "document"   # extracted from an uploaded document and confirmed
    assumed = "assumed"     # the system proposed it because the user could not say
    remembered = "remembered"  # carried over from this user's own earlier case


@dataclass(frozen=True)
class FieldValue:
    """One value in a case, together with where it came from.

    An assumption is a value like any other except in one respect: it must be
    visible as an assumption everywhere it appears, and it must be confirmed
    before the report is generated. A remembered value is held to the same
    standard: last year's commute is a good guess about this year's, never a
    fact about it, and a tax return may not rest on a guess nobody looked at.
    """

    value: Any
    provenance: Provenance
    source: str = ""  # question id, document id, or the reason for the assumption
    confirmed: bool = False
    # What this value replaced, when the user corrected it in place (#28, shape in
    # #12), and where that superseded value had come from. Both None for a value
    # nobody has changed - which is most of them. Kept beside the value rather than
    # folded into it: a corrected figure is still the figure, and what it replaced is
    # a second sentence the trace prints.
    superseded_value: Any = None
    superseded_provenance: Optional[str] = None

    @property
    def needs_confirmation(self) -> bool:
        return (self.provenance in (Provenance.assumed, Provenance.remembered)
                and not self.confirmed)


class AnswerType(str, Enum):
    """How the interview asks for a value, and how the UI renders the control."""

    integer = "integer"       # whole number, e.g. days, kilometres
    money = "money"           # EUR amount
    percent = "percent"       # 1-100
    boolean = "boolean"       # yes / no
    month = "month"           # month of the tax year, 1-12
    date = "date"
    choice = "choice"         # one of `options`
    text = "text"             # short free text, never used for a computed value


class ExpenseCategory(str, Enum):
    """The Werbungskosten categories the product covers.

    Not the same set as `CalculationType`: three of these are simply the sum of
    receipts and have no formula, and `pauschbetrag_comparison` is a conclusion
    about a case rather than a category of expense.
    """

    entfernungspauschale = "entfernungspauschale"
    homeoffice_tagespauschale = "homeoffice_tagespauschale"
    arbeitsmittel = "arbeitsmittel"
    telefon_internet = "telefon_internet"
    fortbildungskosten = "fortbildungskosten"
    umzugskosten = "umzugskosten"
    bewerbungskosten = "bewerbungskosten"


# --- How a fact is keyed ---------------------------------------------------------
#
# A value is keyed by what it means, never by the category that happens to consume
# it: `commute.distance_km`, not `entfernungspauschale.commuting_days`. The same
# commute kilometres also feed the Mobilitaetspraemie, so a key named after one
# category is already wrong for the other (issue #14).
#
# Which is why `ExpenseCategory` above is untouched by this: it names a *tax
# category*, correctly and in German, and the form lines and the `expenses.category`
# constraint are built on those names. A fact and the category that consumes it are
# two different things, and this map is the seam between them - one namespace per
# category today, and nothing here assumes it stays one.
#
# The namespaces are the ones the question catalogue's ids already carried, so a
# stored key is now exactly the id of the question that fills it.
PROFILE_NAMESPACE: Final = "profile"

FACT_NAMESPACES: Final[dict[ExpenseCategory, str]] = {
    ExpenseCategory.entfernungspauschale: "commute",
    ExpenseCategory.homeoffice_tagespauschale: "homeoffice",
    ExpenseCategory.arbeitsmittel: "equipment",
    ExpenseCategory.telefon_internet: "telecom",
    ExpenseCategory.fortbildungskosten: "education",
    ExpenseCategory.umzugskosten: "moving",
    ExpenseCategory.bewerbungskosten: "applications",
}


def namespace_of(category: Optional[ExpenseCategory]) -> str:
    """The fact namespace a field belongs to. The profile has one too: no fact is
    stored under a bare name, so nothing has to remember which kind it was."""
    return PROFILE_NAMESPACE if category is None else FACT_NAMESPACES[category]


def key_for(category: Optional[ExpenseCategory], field_name: str,
            item_index: int = 0) -> str:
    """How one fact is keyed in a case - the only place this is spelled out.

    The suffix is what a repeating category's second item gets: three purchases are
    `equipment.price_eur`, `equipment.price_eur#1`, `equipment.price_eur#2`.
    """
    key = f"{namespace_of(category)}.{field_name}"
    return f"{key}#{item_index}" if item_index else key


@dataclass(frozen=True)
class FieldSpec:
    """One value the case needs, and everything the interview needs to ask for it."""

    name: str
    answer_type: AnswerType
    required: bool = True
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    options: tuple[str, ...] = ()
    repeats: bool = False
    # A fully qualified key: the source of a field filled from elsewhere may live in
    # another category, and "commuting_days" alone would be looked for in this one.
    filled_by: Optional[str] = None
    # False for a value that never changes a figure: it places one on the form, feeds
    # a plausibility check, or classifies an expense. The measurement counts a missing
    # amount field as a wrong figure; missing anything else is reported, not punished.
    affects_amount: bool = True
    # True for a fact about the person that does not change when the tax year does:
    # where they live relative to work, how they get there, whether the employer
    # gives them a desk. Such a value is offered to the next year's case as a
    # remembered value the user confirms, which is the only reason a second return
    # is shorter than the first. Never a gate (a "no" carried over would silently
    # close a category the user opened this year) and never a repeating field (that
    # belongs to one purchase, not to the person) — both are enforced below.
    carries_over: bool = False
    # True for a value the interview asks for and stores but never hands to a
    # calculator. "Did you buy anything else?" is a fact about the conversation rather
    # than about the purchase: it decides whether a second item is opened, and a
    # calculator handed it would refuse a parameter it never declared.
    interview_only: bool = False
    assumption: Any = _NO_ASSUMPTION
    assumption_reason: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.answer_type is AnswerType.choice and not self.options:
            raise ValueError(f"{self.name}: a choice field needs options")
        if self.options and self.answer_type is not AnswerType.choice:
            raise ValueError(f"{self.name}: options only apply to a choice field")
        if self.has_assumption and not self.assumption_reason:
            raise ValueError(f"{self.name}: an assumption has to say why it is defensible")
        if self.carries_over and self.repeats:
            raise ValueError(f"{self.name}: a repeating field belongs to an item, "
                             "not to the person, so it cannot carry over")

    @property
    def has_assumption(self) -> bool:
        return self.assumption is not _NO_ASSUMPTION

    def assume(self) -> FieldValue:
        """The value to use when the user cannot answer, marked as an assumption."""
        if not self.has_assumption:
            raise ValueError(f"{self.name}: nothing may be assumed here, it has to be answered")
        return FieldValue(self.assumption, Provenance.assumed, source=self.assumption_reason)


# --- Profile: what the case knows about the person, independent of any expense ---
#
# The employment period is here rather than in a category because it constrains
# almost every category at once: half a year unemployed halves the commuting days
# and caps the home-office days, which is exactly where a fixed questionnaire
# overstates the figures.

PROFILE_FIELDS: Final[tuple[FieldSpec, ...]] = (
    FieldSpec("employed_months", AnswerType.integer, minimum=0, maximum=12,
              note="Months in employment during the tax year"),
    FieldSpec("employer_count", AnswerType.integer, minimum=0, maximum=5,
              assumption=1, assumption_reason="one employer is the ordinary case",
              note="A second employer fills a second commute block on the form (Zeilen 35-42)"),
    FieldSpec("working_days_total", AnswerType.integer, minimum=1, maximum=366,
              note="All days worked in the year, however and wherever. Only plausibility "
                   "uses it (V01, V02): home-office days plus commuting days cannot exceed "
                   "it. Not the same number as commuting_days, and the seeded contradiction "
                   "the Reviewer has to catch lives in the gap between the two"),
    FieldSpec("works_remotely", AnswerType.boolean),
    FieldSpec("has_minijob", AnswerType.boolean, required=False,
              note="A Minijob taxed at a flat rate produces no Anlage N entries at all"),
    FieldSpec("benefit_type", AnswerType.choice, required=False,
              options=("none", "alg_1", "elterngeld", "kurzarbeitergeld"),
              note="Lohnersatzleistungen: declared in the Hauptvordruck, not here"),
    FieldSpec("benefit_amount_eur", AnswerType.money, required=False, minimum=0,
              note="Collected so the report can say where it belongs; never computed with"),
    FieldSpec("has_paper_benefit_certificate", AnswerType.boolean, required=False,
              note="Einkommensersatzleistungen reach the Finanzamt electronically and are "
                   "normally not entered anywhere; only a paper Leistungsnachweis makes "
                   "Hauptvordruck Zeile 35 something the user has to fill in"),
    FieldSpec("bought_work_equipment", AnswerType.boolean, required=False),
    FieldSpec("claims_phone_internet", AnswerType.boolean, required=False),
    FieldSpec("moved_for_work", AnswerType.boolean, required=False),
    FieldSpec("searched_for_job", AnswerType.boolean, required=False),
    FieldSpec("further_education", AnswerType.boolean, required=False),
)

# The last five are gates: one cheap yes/no that opens or closes a whole category.
# They are where the interview's saving actually comes from — a "no" removes every
# question of that category, while a fixed questionnaire walks through all of them
# regardless.

# The gates by name, works_remotely included: it opens the home-office category the
# same way. The Interviewer may not propose ending the interview while any of these
# is unanswered — until they are, "nothing more will be found" is a guess, and
# skipping the education gate is exactly how the first live run lost an 1,800 EUR
# category on profile p08.
GATE_FIELDS: Final[tuple[str, ...]] = (
    "profile.works_remotely",
    "profile.bought_work_equipment",
    "profile.claims_phone_internet",
    "profile.moved_for_work",
    "profile.searched_for_job",
    "profile.further_education",
)


# --- Per category: the fields its figure cannot be computed without ---

CATEGORY_FIELDS: Final[dict[ExpenseCategory, tuple[FieldSpec, ...]]] = {
    ExpenseCategory.entfernungspauschale: (
        FieldSpec("commuting_days", AnswerType.integer, minimum=1, maximum=366,
                  note="Days the workplace was actually attended - Zeile 29, "
                       '"aufgesucht an Tagen". Not the yearly total, which is '
                       "profile.working_days_total: home-office days and commuting days "
                       "are both drawn from it and cannot together exceed it"),
        FieldSpec("distance_km", AnswerType.integer, minimum=1, maximum=1000,
                  carries_over=True,
                  note="One-way distance, not the round trip (V21). Carries over: it "
                       "changes when the person moves or changes employer, not when "
                       "the year does"),
        FieldSpec("own_car", AnswerType.boolean, carries_over=True,
                  note="Carries over: how someone gets to work is a habit, not a "
                       "yearly decision"),
        FieldSpec("public_transport_cost_eur", AnswerType.money, required=False, minimum=0),
    ),
    ExpenseCategory.homeoffice_tagespauschale: (
        FieldSpec("homeoffice_days", AnswerType.integer, minimum=1, maximum=366),
        FieldSpec("other_workplace_available", AnswerType.boolean,
                  affects_amount=False, carries_over=True,
                  # Carries over: whether the employer provides a desk is a property
                  # of the job, and it decides Zeile 58 against Zeile 59 every year.
                  note="Decides Zeile 58 against Zeile 59. It changes no amount, which is why "
                       "no calculator takes it, but without it the figure cannot be placed"),
        FieldSpec("commuting_days", AnswerType.integer, required=False, minimum=0, maximum=366,
                  filled_by="commute.commuting_days", affects_amount=False,
                  note="Needed for the same-day exclusivity check (V02/V22). The very same "
                       "fact as the commute's, under the very same name now, so it is never "
                       "asked twice: a form has no way of knowing the two are one question"),
    ),
    ExpenseCategory.arbeitsmittel: (
        FieldSpec("price_eur", AnswerType.money, minimum=0.01, repeats=True),
        FieldSpec("price_is_net", AnswerType.boolean, repeats=True,
                  assumption=False,
                  assumption_reason="a receipt shows the gross price, VAT included"),
        FieldSpec("purchase_month", AnswerType.month, minimum=1, maximum=12, repeats=True),
        FieldSpec("is_digital", AnswerType.boolean, repeats=True,
                  assumption=False,
                  assumption_reason="writing an item off over its useful life is the more "
                                    "cautious treatment of the two",
                  note="Computers and peripherals: one-year useful life since 2021"),
        FieldSpec("useful_life_years", AnswerType.integer, required=False, minimum=1, maximum=15,
                  repeats=True, assumption=3,
                  assumption_reason="three years is the usual life of work equipment that is "
                                    "not a computer"),
        FieldSpec("professional_share_pct", AnswerType.percent, required=False,
                  minimum=1, maximum=100, repeats=True),
        # Asked once the purchase above is answered, and only for a category that can
        # hold several. Three invoices in one category is the ordinary case, and until
        # this existed the interview could collect exactly one (#35).
        FieldSpec("has_more", AnswerType.boolean, required=False, repeats=True,
                  affects_amount=False, interview_only=True),
    ),
    ExpenseCategory.telefon_internet: (
        FieldSpec("monthly_bill_eur", AnswerType.money, minimum=0.01),
        FieldSpec("months", AnswerType.integer, required=False, minimum=1, maximum=12),
    ),
    ExpenseCategory.fortbildungskosten: (
        FieldSpec("amount_eur", AnswerType.money, minimum=0.01, repeats=True),
        FieldSpec("kind", AnswerType.choice, repeats=True, affects_amount=False,
                  options=("course_fee", "exam_fee", "literature", "travel", "material")),
        FieldSpec("reimbursed_eur", AnswerType.money, required=False, minimum=0,
                  note="Third-party reimbursements must be subtracted (Zeile 60)"),
        FieldSpec("has_more", AnswerType.boolean, required=False, repeats=True,
                  affects_amount=False, interview_only=True),
    ),
    ExpenseCategory.umzugskosten: (
        FieldSpec("amount_eur", AnswerType.money, minimum=0.01),
        FieldSpec("move_date", AnswerType.date, affects_amount=False,
                  note="Feeds the expense-year check (V26), never the amount"),
        FieldSpec("reason", AnswerType.choice, affects_amount=False,
                  options=("first_job", "employer_change", "employer_required"),
                  note="A professional reason is what makes the move deductible at all"),
    ),
    ExpenseCategory.bewerbungskosten: (
        FieldSpec("amount_eur", AnswerType.money, minimum=0.01, repeats=True),
        FieldSpec("kind", AnswerType.choice, repeats=True, affects_amount=False,
                  options=("postage", "copies", "advertisement", "phone", "travel")),
        FieldSpec("has_more", AnswerType.boolean, required=False, repeats=True,
                  affects_amount=False, interview_only=True),
    ),
}


# Deliberately without an assumption, though `calculations.py` has a Pydantic default
# for both: `professional_share_pct` (100) and the telecom `months` (12). Assuming
# either one enlarges the claim rather than making it cautious — a full year of
# professional use, or a laptop used for nothing else — and a figure in a tax return
# should not grow because nobody asked. Those defaults are a safety net against a
# missing key, and the case layer must never let them fire: it fills every field
# explicitly, with an assumption where one is defensible and a question where it is not.


def required_fields(category: ExpenseCategory) -> tuple[FieldSpec, ...]:
    """Fields without which the category's figure cannot be produced."""
    return tuple(f for f in CATEGORY_FIELDS[category] if f.required)


def all_field_specs() -> tuple[FieldSpec, ...]:
    """Every field the interview could ever ask for, profile first.

    This is what the baseline questionnaire is generated from: one question per
    field, in a fixed order, with no regard for whether the profile makes the
    field relevant. That indifference is the point of the comparison.
    """
    fields = list(PROFILE_FIELDS)
    for category in ExpenseCategory:
        fields.extend(CATEGORY_FIELDS[category])
    return tuple(fields)


# --- What survives the tax year --------------------------------------------------

def _carry_over_keys() -> dict[str, FieldSpec]:
    """The catalogue keys that carry over, qualified exactly as a case keys them.

    Built rather than written out, so marking a field in the tables above is the
    whole of adding one and the two lists cannot drift apart.
    """
    keys: dict[str, FieldSpec] = {}
    for field in PROFILE_FIELDS:
        if field.carries_over:
            keys[key_for(None, field.name)] = field
    for category, fields in CATEGORY_FIELDS.items():
        for field in fields:
            if field.carries_over:
                keys[key_for(category, field.name)] = field
    return keys


CARRY_OVER_FIELDS: Final[dict[str, FieldSpec]] = _carry_over_keys()

# The invariant that makes carrying over safe. A gate is one cheap yes/no that opens
# or closes a whole category, and the interview's entire measured saving comes from
# asking them; carrying last year's "no" over would close a category in silence and
# lose the deduction without anybody deciding to. Checked at import, because a future
# `carries_over=True` on a gate has to fail the test suite, not a user's return.
_CARRIED_GATES = sorted(set(GATE_FIELDS) & set(CARRY_OVER_FIELDS))
if _CARRIED_GATES:  # pragma: no cover — the assertion is the documentation
    raise ValueError(
        f"gate fields may never carry over: {', '.join(_CARRIED_GATES)}. "
        "A gate carried over closes a category without the user being asked."
    )
