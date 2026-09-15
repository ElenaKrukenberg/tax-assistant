"""The question catalogue: every question the system is able to ask.

The Interviewer chooses which of these to ask next and when to stop; it never
writes a question of its own (ADR 0001). Each entry names the field it fills, the
condition under which the question is relevant at all, and its wording in the
three interface languages.

Two things are derived from this file, which is why the relevance conditions are
data rather than prose in a prompt:

- `relevant_questions()` is what the Interviewer's `list_open_questions` tool
  returns. Filtering by the state of the case is deterministic and testable, so
  code does it; the agent is left with the ordering and the decision to stop.
- `CATALOGUE` in declaration order is the baseline questionnaire — a form asks
  everything, in a fixed order, whatever the profile says. That indifference is
  the thing being measured against.

A condition that refers to an unanswered field does not hold, so a category's
questions stay closed until its gate is answered. The interview therefore starts
with the cheap yes/no gates on its own, without anything having to order it to.
"""

from dataclasses import dataclass
from typing import Any, Final, Optional

from domain.fields import (
    CATEGORY_FIELDS,
    PROFILE_FIELDS,
    ExpenseCategory,
    FieldSpec,
    key_for,
)

LOCALES: Final = ("en", "de", "ru")

_MISSING: Final = object()


@dataclass(frozen=True)
class When:
    """A condition on what the case already knows.

    Absent knowledge never satisfies a condition: a question whose gate has not
    been answered is not yet relevant, rather than relevant by default.
    """

    field: str
    equals: Any = _MISSING
    not_equals: Any = _MISSING
    at_least: Optional[float] = None

    def holds(self, known: dict[str, Any]) -> bool:
        if self.field not in known or known[self.field] is None:
            return False
        value = known[self.field]
        if self.equals is not _MISSING and value != self.equals:
            return False
        if self.not_equals is not _MISSING and value == self.not_equals:
            return False
        if self.at_least is not None and not (
            isinstance(value, (int, float)) and value >= self.at_least
        ):
            return False
        return True


@dataclass(frozen=True)
class Question:
    """One catalogue entry: which field it fills, when it applies, how it reads."""

    id: str
    field: str
    text: dict[str, str]
    category: Optional[ExpenseCategory] = None
    when: tuple[When, ...] = ()

    def __post_init__(self) -> None:
        missing = [loc for loc in LOCALES if not self.text.get(loc)]
        if missing:
            raise ValueError(f"{self.id}: no text for {missing}")

    @property
    def key(self) -> str:
        """How this question's answer is keyed in the case.

        Always qualified, the profile's own facts included: three categories each
        have an `amount_eur` and two have a `kind`, so on bare names answering what
        the move cost would silence the question about what the training cost - and
        a rule with an exception for one namespace is a rule nobody applies.

        Spelled by `key_for`, which makes this read as "a question's id and the key
        it fills are the same string". The ids in this file were already written that
        way; the tests now hold them to it.
        """
        return key_for(self.category, self.field)

    def applies(self, known: dict[str, Any]) -> bool:
        return all(condition.holds(known) for condition in self.when)

    def spec(self) -> FieldSpec:
        specs = PROFILE_FIELDS if self.category is None else CATEGORY_FIELDS[self.category]
        for spec in specs:
            if spec.name == self.field:
                return spec
        raise KeyError(f"{self.id}: no field {self.field!r} in {self.category or 'the profile'}")


# Gates, so the conditions below read as what they mean rather than as strings.
_WORKED = When("profile.employed_months", at_least=1)
_REMOTE = When("profile.works_remotely", equals=True)
_HAS_BENEFIT = When("profile.benefit_type", not_equals="none")
_BOUGHT_EQUIPMENT = When("profile.bought_work_equipment", equals=True)
_USES_OWN_LINE = When("profile.claims_phone_internet", equals=True)
_MOVED = When("profile.moved_for_work", equals=True)
_APPLIED = When("profile.searched_for_job", equals=True)
_STUDIED = When("profile.further_education", equals=True)


CATALOGUE: Final[tuple[Question, ...]] = (
    # --- profile: asked of everyone, and the gates that close whole categories ---
    Question(
        "profile.employed_months", "employed_months",
        {
            "en": "For how many months of 2025 were you in employment?",
            "de": "In wie vielen Monaten des Jahres 2025 waren Sie beschäftigt?",
            "ru": "Сколько месяцев в 2025 году вы были трудоустроены?",
        },
    ),
    Question(
        "profile.employer_count", "employer_count",
        {
            "en": "How many employers did you have during the year?",
            "de": "Wie viele Arbeitgeber hatten Sie im Laufe des Jahres?",
            "ru": "Сколько у вас было работодателей за год?",
        },
        when=(_WORKED,),
    ),
    Question(
        "profile.working_days_total", "working_days_total",
        {
            "en": "How many days did you work in total during the year?",
            "de": "An wie vielen Tagen haben Sie im Jahr insgesamt gearbeitet?",
            "ru": "Сколько дней вы отработали за год в общей сложности?",
        },
        when=(_WORKED,),
    ),
    Question(
        "profile.works_remotely", "works_remotely",
        {
            "en": "Did you work from home on some days?",
            "de": "Haben Sie an einzelnen Tagen von zu Hause gearbeitet?",
            "ru": "Работали ли вы какие-то дни из дома?",
        },
        when=(_WORKED,),
    ),
    Question(
        "profile.has_minijob", "has_minijob",
        {
            "en": "Did you also have a Minijob alongside your main employment?",
            "de": "Hatten Sie neben Ihrer Hauptbeschäftigung zusätzlich einen Minijob?",
            "ru": "Была ли у вас, помимо основной работы, подработка (Minijob)?",
        },
    ),
    Question(
        "profile.benefit_type", "benefit_type",
        {
            "en": "Did you receive an income-replacement benefit — unemployment benefit, "
                  "parental allowance, sick pay?",
            "de": "Haben Sie Einkommensersatzleistungen erhalten — Arbeitslosengeld, "
                  "Elterngeld, Krankengeld?",
            "ru": "Получали ли вы выплаты, заменяющие доход — Arbeitslosengeld, Elterngeld, "
                  "Krankengeld?",
        },
    ),
    Question(
        "profile.benefit_amount_eur", "benefit_amount_eur",
        {
            "en": "How much did you receive in income-replacement benefit over the year?",
            "de": "Wie hoch war die Lohnersatzleistung im Jahr insgesamt?",
            "ru": "Какую сумму выплат, заменяющих доход, вы получили за год?",
        },
        when=(_HAS_BENEFIT,),
    ),
    Question(
        "profile.has_paper_benefit_certificate", "has_paper_benefit_certificate",
        {
            "en": "Did you receive the benefit statement on paper (a Leistungsnachweis)?",
            "de": "Haben Sie einen Leistungsnachweis in Papierform erhalten?",
            "ru": "Получали ли вы бумажную справку о выплате (Leistungsnachweis)?",
        },
        when=(_HAS_BENEFIT,),
    ),
    Question(
        "profile.bought_work_equipment", "bought_work_equipment",
        {
            "en": "Did you buy anything for work - a computer, a desk, tools, "
                  "professional literature?",
            "de": "Haben Sie etwas für die Arbeit gekauft - Computer, Schreibtisch, "
                  "Werkzeug, Fachliteratur?",
            "ru": "Покупали ли вы что-то для работы - компьютер, стол, инструменты, "
                  "профессиональную литературу?",
        },
        when=(_WORKED,),
    ),
    Question(
        "profile.claims_phone_internet", "claims_phone_internet",
        {
            "en": "Did you use your own phone or internet connection for work?",
            "de": "Haben Sie Ihr privates Telefon oder Ihren Internetanschluss beruflich "
                  "genutzt?",
            "ru": "Использовали ли вы личный телефон или интернет для работы?",
        },
        when=(_WORKED,),
    ),
    Question(
        "profile.moved_for_work", "moved_for_work",
        {
            "en": "Did you move house for professional reasons?",
            "de": "Sind Sie aus beruflichen Gründen umgezogen?",
            "ru": "Переезжали ли вы по служебной необходимости?",
        },
    ),
    Question(
        "profile.searched_for_job", "searched_for_job",
        {
            "en": "Did you apply for jobs during the year?",
            "de": "Haben Sie sich im Laufe des Jahres auf Stellen beworben?",
            "ru": "Искали ли вы работу в течение года — рассылали заявки?",
        },
    ),
    Question(
        "profile.further_education", "further_education",
        {
            "en": "Did you pay for training or further education?",
            "de": "Haben Sie Aufwendungen für Fortbildung oder Weiterbildung getragen?",
            "ru": "Оплачивали ли вы обучение или повышение квалификации?",
        },
    ),

    # --- Entfernungspauschale ---
    Question(
        "commute.commuting_days", "commuting_days",
        {
            "en": "On how many days did you travel to your workplace?",
            "de": "An wie vielen Tagen haben Sie Ihre erste Tätigkeitsstätte aufgesucht?",
            "ru": "Сколько дней вы ездили на рабочее место?",
        },
        category=ExpenseCategory.entfernungspauschale, when=(_WORKED,),
    ),
    Question(
        "commute.distance_km", "distance_km",
        {
            "en": "How far is it from home to your workplace, one way, in full kilometres?",
            "de": "Wie hoch ist die einfache Entfernung von Ihrer Wohnung zur ersten "
                  "Tätigkeitsstätte in vollen Kilometern?",
            "ru": "Каково расстояние от дома до работы в одну сторону, в полных километрах?",
        },
        category=ExpenseCategory.entfernungspauschale, when=(_WORKED,),
    ),
    Question(
        "commute.own_car", "own_car",
        {
            "en": "Did you use your own car, or one your employer provided?",
            "de": "Haben Sie einen eigenen oder einen zur Nutzung überlassenen PKW benutzt?",
            "ru": "Пользовались ли вы своей машиной или машиной, предоставленной работодателем?",
        },
        category=ExpenseCategory.entfernungspauschale, when=(_WORKED,),
    ),
    Question(
        "commute.public_transport_cost_eur", "public_transport_cost_eur",
        {
            "en": "What did public-transport tickets for the commute to work cost you over the year?",
            "de": "Welche Aufwendungen hatten Sie im Jahr für Fahrten mit öffentlichen "
                  "Verkehrsmitteln?",
            "ru": "Сколько вы потратили за год на общественный транспорт для поездок на работу?",
        },
        category=ExpenseCategory.entfernungspauschale,
        when=(_WORKED, When("commute.own_car", equals=False)),
    ),

    # --- Homeoffice-Tagespauschale ---
    Question(
        "homeoffice.homeoffice_days", "homeoffice_days",
        {
            "en": "On how many days did you work from home?",
            "de": "An wie vielen Tagen haben Sie überwiegend von zu Hause gearbeitet?",
            "ru": "Сколько дней вы работали из дома?",
        },
        category=ExpenseCategory.homeoffice_tagespauschale, when=(_REMOTE,),
    ),
    Question(
        "homeoffice.other_workplace_available", "other_workplace_available",
        {
            "en": "On the days you worked from home, was a workplace at the employer available too?",
            "de": "Stand Ihnen an den Homeoffice-Tagen auch ein Arbeitsplatz beim "
                  "Arbeitgeber zur Verfügung?",
            "ru": "В дни работы из дома было ли у вас доступно рабочее место у работодателя?",
        },
        category=ExpenseCategory.homeoffice_tagespauschale, when=(_REMOTE,),
    ),

    # --- Arbeitsmittel ---
    Question(
        "equipment.price_eur", "price_eur",
        {
            "en": "What did the work equipment cost?",
            "de": "Wie hoch war der Kaufpreis des Arbeitsmittels?",
            "ru": "Сколько стоило рабочее оборудование?",
        },
        category=ExpenseCategory.arbeitsmittel, when=(_BOUGHT_EQUIPMENT,),
    ),
    Question(
        "equipment.price_is_net", "price_is_net",
        {
            "en": "Is the price of the work equipment without VAT?",
            "de": "Ist der Kaufpreis des Arbeitsmittels ein Nettopreis, also ohne Umsatzsteuer?",
            "ru": "Цена рабочего оборудования указана без НДС?",
        },
        category=ExpenseCategory.arbeitsmittel, when=(_BOUGHT_EQUIPMENT,),
    ),
    Question(
        "equipment.purchase_month", "purchase_month",
        {
            "en": "In which month did you buy the work equipment?",
            "de": "In welchem Monat haben Sie das Arbeitsmittel gekauft?",
            "ru": "В каком месяце вы купили рабочее оборудование?",
        },
        category=ExpenseCategory.arbeitsmittel, when=(_BOUGHT_EQUIPMENT,),
    ),
    Question(
        "equipment.is_digital", "is_digital",
        {
            "en": "Is the work equipment a computer, a peripheral or software?",
            "de": "Ist das Arbeitsmittel ein Computer, ein Peripheriegerät oder Software?",
            "ru": "Рабочее оборудование — это компьютер, периферия или программа?",
        },
        category=ExpenseCategory.arbeitsmittel, when=(_BOUGHT_EQUIPMENT,),
    ),
    Question(
        "equipment.useful_life_years", "useful_life_years",
        {
            "en": "Over how many years is such work equipment normally written off?",
            "de": "Über wie viele Jahre wird ein solches Arbeitsmittel abgeschrieben?",
            "ru": "За сколько лет обычно списывается такое рабочее оборудование?",
        },
        category=ExpenseCategory.arbeitsmittel,
        when=(_BOUGHT_EQUIPMENT, When("equipment.is_digital", equals=False)),
    ),
    Question(
        "equipment.professional_share_pct", "professional_share_pct",
        {
            "en": "What share of its use is for work, in percent?",
            "de": "Welcher Anteil der Nutzung ist beruflich, in Prozent?",
            "ru": "Какая доля использования — рабочая, в процентах?",
        },
        category=ExpenseCategory.arbeitsmittel, when=(_BOUGHT_EQUIPMENT,),
    ),
    # The question that lets a category hold more than one purchase. Asked after the
    # item above is complete, which `open_items` decides - `when` is about the profile,
    # not about how far through an item the interview is (#35).
    Question(
        "equipment.has_more", "has_more",
        {
            "en": "Did you buy anything else for work?",
            "de": "Haben Sie noch etwas anderes für die Arbeit gekauft?",
            "ru": "Вы покупали для работы что-то ещё?",
        },
        category=ExpenseCategory.arbeitsmittel, when=(_BOUGHT_EQUIPMENT,),
    ),

    # --- Telefon / Internet ---
    Question(
        "telecom.monthly_bill_eur", "monthly_bill_eur",
        {
            "en": "What is your average monthly phone and internet bill?",
            "de": "Wie hoch ist Ihre durchschnittliche monatliche Rechnung für Telefon und "
                  "Internet?",
            "ru": "Каков ваш средний месячный счёт за телефон и интернет?",
        },
        category=ExpenseCategory.telefon_internet, when=(_USES_OWN_LINE,),
    ),
    Question(
        "telecom.months", "months",
        {
            "en": "For how many months of the year did you use the phone or internet line for work?",
            "de": "In wie vielen Monaten des Jahres haben Sie Telefon oder Internet beruflich genutzt?",
            "ru": "Сколько месяцев в году вы использовали телефон или интернет для работы?",
        },
        category=ExpenseCategory.telefon_internet, when=(_USES_OWN_LINE,),
    ),

    # --- Fortbildungskosten ---
    Question(
        "education.amount_eur", "amount_eur",
        {
            "en": "How much did the training cost you?",
            "de": "Welche Aufwendungen hatten Sie für die Fortbildung?",
            "ru": "Сколько вы потратили на обучение?",
        },
        category=ExpenseCategory.fortbildungskosten, when=(_STUDIED,),
    ),
    Question(
        "education.kind", "kind",
        {
            "en": "What was the expense for?",
            "de": "Um welche Art von Aufwendung handelt es sich?",
            "ru": "На что именно был расход?",
        },
        category=ExpenseCategory.fortbildungskosten, when=(_STUDIED,),
    ),
    Question(
        "education.reimbursed_eur", "reimbursed_eur",
        {
            "en": "Did anyone reimburse part of the training costs — an employer, an authority, a grant?",
            "de": "Wurde ein Teil der Fortbildungskosten ersetzt — durch den Arbeitgeber, "
                  "eine Behörde oder einen Zuschuss?",
            "ru": "Возмещал ли кто-то часть расходов на обучение — работодатель, ведомство, грант?",
        },
        category=ExpenseCategory.fortbildungskosten, when=(_STUDIED,),
    ),
    Question(
        "education.has_more", "has_more",
        {
            "en": "Did you pay for any other training or further education?",
            "de": "Hatten Sie weitere Aufwendungen für Fortbildung?",
            "ru": "Были ли другие расходы на обучение?",
        },
        category=ExpenseCategory.fortbildungskosten, when=(_STUDIED,),
    ),

    # --- Umzugskosten ---
    Question(
        "moving.amount_eur", "amount_eur",
        {
            "en": "What did the move cost you in total?",
            "de": "Wie hoch waren Ihre Umzugskosten insgesamt?",
            "ru": "Во сколько вам обошёлся переезд?",
        },
        category=ExpenseCategory.umzugskosten, when=(_MOVED,),
    ),
    Question(
        "moving.move_date", "move_date",
        {
            "en": "When did you move?",
            "de": "Wann sind Sie umgezogen?",
            "ru": "Когда вы переехали?",
        },
        category=ExpenseCategory.umzugskosten, when=(_MOVED,),
    ),
    Question(
        "moving.reason", "reason",
        {
            "en": "What made the move professional - a first job, a change of employer, "
                  "or your employer requiring it?",
            "de": "Was war der berufliche Anlass - erstmalige Stelle, Arbeitgeberwechsel oder "
                  "eine Forderung des Arbeitgebers?",
            "ru": "Что делает переезд служебным - первая работа, смена работодателя или "
                  "требование работодателя?",
        },
        category=ExpenseCategory.umzugskosten, when=(_MOVED,),
    ),

    # --- Bewerbungskosten ---
    Question(
        "applications.amount_eur", "amount_eur",
        {
            "en": "What did applying cost you, not counting anything reimbursed?",
            "de": "Welche nicht erstatteten Kosten sind Ihnen durch die Bewerbungen entstanden?",
            "ru": "Сколько вы потратили на заявки, не считая возмещённого?",
        },
        category=ExpenseCategory.bewerbungskosten, when=(_APPLIED,),
    ),
    Question(
        "applications.kind", "kind",
        {
            "en": "What were the job-application costs spent on?",
            "de": "Wofür sind die Bewerbungskosten angefallen?",
            "ru": "На что ушли расходы на заявки о приёме на работу?",
        },
        category=ExpenseCategory.bewerbungskosten, when=(_APPLIED,),
    ),
    Question(
        "applications.has_more", "has_more",
        {
            "en": "Did you have any other job-application costs?",
            "de": "Hatten Sie weitere Bewerbungskosten?",
            "ru": "Были ли другие расходы на поиск работы?",
        },
        category=ExpenseCategory.bewerbungskosten, when=(_APPLIED,),
    ),
)


BY_ID: Final[dict[str, Question]] = {q.id: q for q in CATALOGUE}

# The same catalogue keyed by the case key rather than the question id. Profile
# memory needs it: a carried-over value arrives as a key ("commute.distance_km") and
# has to find the question behind it to ask whether that question still applies this
# year. Keys are unique across the catalogue - one question per field - which
# `tests/test_questions.py` holds to.
#
# Since the rename this is the same mapping as BY_ID, and the tests assert that it
# is. Both names stay: one says "the question the user asked about", the other "the
# question behind this stored value", and they are different questions to ask even
# while the dictionary is the same.
BY_KEY: Final[dict[str, Question]] = {q.key: q for q in CATALOGUE}


@dataclass(frozen=True)
class OpenQuestion:
    """One question, and which purchase of its category it is about.

    `item_index` is 0 for everything except a repeating category's second and further
    purchases. Carried beside the question rather than baked into its id, because
    `equipment.price_eur#2` reads as a different question and it is not: which item it
    is belongs beside the label, not inside it.
    """

    question: Question
    item_index: int = 0

    @property
    def key(self) -> str:
        return key_for(self.question.category, self.question.field, self.item_index)


def _item_is_complete(category, known: dict[str, Any], item_index: int) -> bool:
    """Whether every required field of one purchase has been answered."""
    from domain.fields import CATEGORY_FIELDS

    return all(
        known.get(key_for(category, spec.name, item_index)) is not None
        for spec in CATEGORY_FIELDS[category]
        if spec.required and not spec.filled_by and not spec.interview_only
    )


def open_items(known: dict[str, Any]) -> tuple[OpenQuestion, ...]:
    """Every question worth asking, with the purchase it belongs to.

    A repeating category opens its next purchase only when the user has said there is
    one: the `has_more` answer on item N is what opens item N+1, and the question
    itself is only offered once item N is complete. So the interview never asks "did
    you buy anything else?" in the middle of describing the first thing, and never
    opens a second item nobody asked for.

    Item zero is exactly `relevant_questions`, which is why that stays the narrow
    function it was - the agent's tool, the measurement and the tests all read it.
    """
    out: list[OpenQuestion] = []
    for question in CATALOGUE:
        if not question.applies(known):
            continue
        category = question.category
        spec = question.spec()
        if category is None or not spec.repeats:
            if known.get(question.key) is None:
                out.append(OpenQuestion(question))
            continue

        index = 0
        while True:
            key = key_for(category, question.field, index)
            if spec.interview_only:
                # "Anything else?" is worth asking only once the purchase it follows
                # is actually described.
                if (known.get(key) is None
                        and _item_is_complete(category, known, index)):
                    out.append(OpenQuestion(question, index))
            elif known.get(key) is None:
                out.append(OpenQuestion(question, index))
            # The next purchase exists only if the user said so on this one.
            if known.get(key_for(category, "has_more", index)) is not True:
                break
            index += 1
    return tuple(out)


def relevant_questions(known: dict[str, Any]) -> tuple[Question, ...]:
    """The questions worth asking given what the case already knows.

    This is the body of the Interviewer's `list_open_questions` tool. A question
    drops out for one of two reasons: its field is already answered, or the
    profile makes it irrelevant. Both are decided here rather than by the model,
    so that "the agent asked an irrelevant question" stays a measurable event
    instead of a matter of opinion.
    """
    return tuple(
        q for q in CATALOGUE
        if known.get(q.key) is None
        if q.applies(known)
    )


def text_for(key: str, locale: str) -> Optional[str]:
    """How one Fact key reads to a person, in the locale asked for.

    The catalogue is where a value's wording lives, so the screens that show a
    stored value read it from here rather than keeping a second list of names that
    drifts from the questions. `equipment.price_eur#2` reads as the same question as
    `equipment.price_eur` - which item it is belongs beside the label, not inside it.

    `None` for a key the catalogue does not hold, so a caller has to decide what to
    show instead rather than being handed an invented label. English for a locale
    the catalogue has no text in - Turkish today (issue #54), and the fallback is
    visible to the reader rather than an empty line.
    """
    question = BY_KEY.get(key.partition("#")[0])
    if question is None:
        return None
    return question.text.get(locale) or question.text["en"]
