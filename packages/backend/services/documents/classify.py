"""Which expense category an invoice belongs to - rules first, model only if asked.

The order is the point. A "Bürostuhl" is Arbeitsmittel by a word, not by a judgement,
and paying a model to decide it would add latency, cost and a way to be wrong to a
question that has an answer. So the rules run first and the model is consulted only
where the descriptions match nothing - and then it is consulted with the knowledge
base behind it, so the answer comes with a passage rather than an opinion (that half
arrives with issue #17).

The second half of this module is the check the ticket asks for by name: a receipt
that says "Restaurant" while the proposed category is Fortbildung is questioned
rather than accepted. It runs *after* the category is decided, whoever decided it,
because the failure it catches is the confident one - rules and models are both
capable of putting a dinner through as a training course.

Every word list here is German and lower-case, matched against the line descriptions
the invoice yielded. Nothing matches against the supplier: it is not extracted
(`schemas.py`), and a shop's name is a poor guide anyway - the same shop sells a
monitor and a birthday present.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from domain.fields import ExpenseCategory

# The four categories a document can land in. The other three the product supports -
# the commute, the home office, the phone line - are not evidenced by an invoice for a
# thing: they are day counts and a monthly bill, and they come from the interview.
CATEGORIES: tuple[ExpenseCategory, ...] = (
    ExpenseCategory.arbeitsmittel,
    ExpenseCategory.fortbildungskosten,
    ExpenseCategory.umzugskosten,
    ExpenseCategory.bewerbungskosten,
)

_WORDS: dict[ExpenseCategory, tuple[str, ...]] = {
    ExpenseCategory.arbeitsmittel: (
        "schreibtisch", "bürostuhl", "drehstuhl", "monitor", "bildschirm", "monitorarm",
        "laptop", "notebook", "rechner", "computer", "pc", "tastatur", "maus",
        "dockingstation", "drucker", "toner", "papier", "regal", "schreibtischlampe",
        "werkzeug", "fachbuch", "fachliteratur", "software", "lizenz", "headset",
        "webcam", "festplatte", "ssd", "usb", "tasche", "aktenschrank",
    ),
    ExpenseCategory.fortbildungskosten: (
        "seminar", "fortbildung", "weiterbildung", "schulung", "kurs", "lehrgang",
        "workshop", "prüfungsgebühr", "prüfung", "zertifizierung", "studiengebühr",
        "teilnahmegebühr", "kursgebühr", "training", "konferenz", "tagung",
    ),
    ExpenseCategory.umzugskosten: (
        "umzug", "spedition", "möbeltransport", "umzugskarton", "transporter",
        "umzugsservice", "einlagerung", "makler", "nachsendeauftrag",
    ),
    ExpenseCategory.bewerbungskosten: (
        "bewerbung", "bewerbungsfoto", "bewerbungsmappe", "beglaubigung", "porto",
        "briefmarke", "kopien", "lebenslauf", "zeugnisbeglaubigung", "passfoto",
    ),
}

# Words that describe something a Werbungskosten claim cannot survive, per category.
# Not a general-purpose "is this private" detector - it is the specific mismatch the
# ticket names, and it is stated per category because the same word is innocent
# elsewhere: a "Restaurant" line is a problem under Fortbildung and merely irrelevant
# under Arbeitsmittel.
_CONTRADICTS: dict[ExpenseCategory, tuple[str, ...]] = {
    ExpenseCategory.fortbildungskosten: (
        "restaurant", "bar", "cocktail", "menü", "getränke", "bier", "wein", "pizza",
        "kaffee und kuchen", "hotelbar", "trinkgeld", "geschenk", "blumen",
    ),
    ExpenseCategory.arbeitsmittel: (
        "spielzeug", "konsole", "playstation", "xbox", "nintendo", "parfum",
        "schmuck", "geschenk", "blumen", "kinderwagen", "fernseher",
    ),
    ExpenseCategory.umzugskosten: ("urlaub", "ferienwohnung", "reise"),
    ExpenseCategory.bewerbungskosten: ("urlaub", "geschenk"),
}


@dataclass(frozen=True)
class Classification:
    category: Optional[ExpenseCategory]
    # Why, in words a report can print. Never empty: an unexplained category is the
    # thing this product exists not to produce.
    reason: str
    by_rule: bool
    # Set when the content argues against the category, whoever proposed it. The
    # workflow turns this into a question rather than a refusal: the user may have a
    # perfectly good answer, and only they can give it.
    contradiction: Optional[str] = None


def _matches(descriptions: Iterable[str], words: tuple[str, ...]) -> list[str]:
    text = " ".join(d.lower() for d in descriptions if d)
    return [word for word in words if word in text]


def by_rules(descriptions: Iterable[str]) -> Classification:
    """The category the descriptions name outright, or none.

    Scored by how many distinct words match, so a three-line invoice for a desk, a
    chair and a monitor arm is Arbeitsmittel three times over rather than a tie.
    A tie between two categories is *not* resolved here - two different kinds of
    purchase on one invoice is a real thing, and guessing which one wins would put
    half the money in the wrong place.
    """
    descriptions = list(descriptions)
    hits = {c: _matches(descriptions, words) for c, words in _WORDS.items()}
    ranked = sorted(hits.items(), key=lambda item: len(item[1]), reverse=True)
    best, best_words = ranked[0]
    if not best_words:
        return Classification(None, "no line on the invoice names a known category", False)
    runner_up = ranked[1][1] if len(ranked) > 1 else []
    if len(runner_up) == len(best_words):
        return Classification(
            None,
            f"the invoice names two categories equally ({', '.join(best_words)} against "
            f"{', '.join(runner_up)})",
            False,
        )
    return Classification(
        best,
        f"the invoice names {', '.join(best_words)}",
        True,
    )


def contradiction(category: ExpenseCategory, descriptions: Iterable[str]) -> Optional[str]:
    """A line that argues against the proposed category, if there is one."""
    found = _matches(descriptions, _CONTRADICTS.get(category, ()))
    if not found:
        return None
    return (
        f"the invoice mentions {', '.join(found)}, which does not belong in "
        f"{category.value}"
    )


def checked(category: Optional[ExpenseCategory], descriptions: Iterable[str],
            reason: str, *, by_rule: bool) -> Classification:
    """One classification, with the content check applied to it."""
    descriptions = list(descriptions)
    if category is None:
        return Classification(None, reason, by_rule)
    return Classification(category, reason, by_rule, contradiction(category, descriptions))
