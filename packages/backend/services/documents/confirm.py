"""What the user sent back, checked before any of it becomes a tax value.

Two jobs, and both of them are about not trusting the request.

**The keys and the values are validated against the catalogue.** A confirmation
arrives as `{"equipment.price_eur#1": 46.25}` - a Fact key and a number chosen by the
client. Neither is taken on trust: the key has to be a question the catalogue can
fill, and the value has to satisfy that field's own type and bounds
(`domain/fields.py`). Without this, the confirm route is an arbitrary write into
somebody's tax data by whoever can shape a JSON body.

**The category and the keys have to be the same claim.** `equipment.price_eur` is an
Arbeitsmittel price and `education.amount_eur` is what a course cost: each Fact key
belongs to exactly one category, so a confirmation that writes the first while
recording the second is a document whose stored category contradicts its own values.
Both halves pass their own validation - the category is one of the four, the key is
in the catalogue - which is why the disagreement between them needs a check of its
own (`category_problem`).

**The provenance is decided here, not sent by the client.** A value the model read
and the user confirmed unchanged is a `document` value; a value the user typed or
corrected is an `answer`, because that is what the report has to be able to say
(issue #12, and `Provenance` in `domain/fields.py`). The client does not get a vote
on which - it would be free to claim a hand-typed figure came off a document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from domain.fields import AnswerType, ExpenseCategory, FieldSpec, FieldValue, Provenance
from domain.questions import BY_KEY


@dataclass(frozen=True)
class Checked:
    """One value the user confirmed, ready for `db.cases.set_field`."""

    key: str
    item_index: int
    value: FieldValue


def split_index(key: str) -> tuple[str, int]:
    """`equipment.price_eur#2` into its key and its item index."""
    base, _, suffix = key.partition("#")
    if not suffix:
        return base, 0
    try:
        index = int(suffix)
    except ValueError:
        return base, -1
    return base, index if index >= 0 else -1


def _coerce(spec: FieldSpec, value: Any) -> Any:
    """The value as its field's type, or a TypeError naming what was wrong.

    Deliberately narrow: JSON has one number type, so an integer field accepts 12.0
    and refuses 12.4 rather than rounding it. A figure that reaches a tax return is
    not the place to be helpful.
    """
    if spec.answer_type is AnswerType.boolean:
        if not isinstance(value, bool):
            raise TypeError("expects yes or no")
        return value

    if isinstance(value, bool):
        # True is 1 in Python, and a day count of `true` is nobody's intention.
        raise TypeError("expects a number, not yes or no")

    if spec.answer_type in (AnswerType.integer, AnswerType.month):
        if not isinstance(value, (int, float)) or float(value) != int(value):
            raise TypeError("expects a whole number")
        return int(value)

    if spec.answer_type in (AnswerType.money, AnswerType.percent):
        if not isinstance(value, (int, float)):
            raise TypeError("expects an amount")
        return round(float(value), 2)

    if spec.answer_type is AnswerType.choice:
        if value not in spec.options:
            raise TypeError(f"expects one of {', '.join(spec.options)}")
        return value

    if not isinstance(value, str) or not value.strip():
        raise TypeError("expects text")
    return value.strip()


def _within_bounds(spec: FieldSpec, value: Any) -> Optional[str]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if spec.minimum is not None and value < spec.minimum:
        return f"is below the minimum of {spec.minimum:g}"
    if spec.maximum is not None and value > spec.maximum:
        return f"is above the maximum of {spec.maximum:g}"
    return None


def check(
    values: dict[str, Any], *, proposed: dict[str, Any], document_id: str,
) -> tuple[list[Checked], list[str]]:
    """Validate a confirmation, and decide each value's provenance.

    `proposed` is what the extraction offered, taken from the paused run rather than
    from the request - it is the only way to tell a confirmed reading from a typed
    correction, and the client must not be the one to say which is which.
    """
    checked: list[Checked] = []
    problems: list[str] = []

    for raw_key, value in values.items():
        key, index = split_index(str(raw_key))
        if index < 0:
            problems.append(f"{raw_key}: not a value this case can hold")
            continue

        question = BY_KEY.get(key)
        if question is None:
            problems.append(f"{raw_key}: not a value this case can hold")
            continue

        spec = question.spec()
        if index and not spec.repeats:
            problems.append(f"{raw_key}: {key} holds one value, not several")
            continue

        try:
            coerced = _coerce(spec, value)
        except TypeError as wrong:
            problems.append(f"{raw_key}: {wrong}")
            continue

        out_of_range = _within_bounds(spec, coerced)
        if out_of_range:
            problems.append(f"{raw_key}: {coerced:g} {out_of_range}")
            continue

        offered = raw_key in proposed
        unchanged = offered and _same_value(proposed[raw_key], coerced)
        checked.append(Checked(
            key=key,
            item_index=index,
            value=FieldValue(
                coerced,
                Provenance.document if unchanged else Provenance.answer,
                # What the report shows beside the figure. The document for a
                # reading the user let stand, and the fact of a correction for one
                # they did not - "the user corrected what the document said" is a
                # different claim from "the document said this", and the trace has
                # to be able to make it (issue #12).
                source=_source(document_id, offered=offered, unchanged=unchanged),
                confirmed=True,
            ),
        ))

    return checked, problems


def category_problem(
    checked: list[Checked], *, recorded: Optional[str], proposed: Optional[str],
) -> Optional[str]:
    """Whether the category being recorded is the one these values belong to.

    Three ways for it to be wrong, and all three are reachable from a request rather
    than from the interface: values from two categories at once, a category that is
    not the one the keys belong to, and a category other than the one the paused run
    proposed - which the user can only change through the category route, never by
    saying so while confirming.
    """
    categories = {BY_KEY[value.key].category for value in checked}
    categories.discard(None)

    if len(categories) > 1:
        named = ", ".join(sorted(c.value for c in categories))
        return f"these values belong to two categories at once ({named})"

    belongs: Optional[ExpenseCategory] = next(iter(categories), None)

    if recorded is not None and belongs is not None and recorded != belongs.value:
        return (f"the category says {recorded} but the values are "
                f"{belongs.value} ones")
    if recorded is not None and belongs is None:
        # A Lohnsteuerbescheinigung yields `profile.employed_months` and no expense.
        return f"a document with no expense values cannot be recorded as {recorded}"
    if proposed is not None and recorded is not None and recorded != proposed:
        return (f"this document was proposed as {proposed}; change the category "
                "before confirming it as something else")
    return None


def _source(document_id: str, *, offered: bool, unchanged: bool) -> str:
    """What the report prints beside the figure, in three honest variants.

    "The document said this", "the user corrected what the document said" and "the
    user typed this while looking at the document" are three different claims, and
    the middle one must not be printed for the third.
    """
    if unchanged:
        return document_id
    if offered:
        return f"corrected by the user, from document {document_id}"
    return f"entered by the user while confirming document {document_id}"


def _same_value(proposed: Any, confirmed: Any) -> bool:
    if isinstance(proposed, bool) or isinstance(confirmed, bool):
        return proposed is confirmed
    if isinstance(proposed, (int, float)) and isinstance(confirmed, (int, float)):
        return abs(float(proposed) - float(confirmed)) < 0.005
    return proposed == confirmed
