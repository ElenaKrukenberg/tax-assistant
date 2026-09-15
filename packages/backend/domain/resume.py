"""What a browser is allowed to send back to a paused interview.

The graph pauses with a typed payload and waits for a reply. Every node that
reads such a reply reads it leniently on purpose - `ask_user` takes a bare value
or `{"value": ...}`, `read_stop_answer` takes a bare boolean or a dict - because
a pause contract that breaks on shape is a pause contract that loses an
interview. Leniency at the node is not leniency at the boundary: this module is
the one place that decides whether a reply answers the question that is actually
pending, and the routes call it before anything is persisted.

Three things the nodes cannot check for themselves:

  - The value's type, range and choice set come from the catalogue question, not
    from the pause payload. The payload is a copy made when the question was
    asked; the catalogue is what the calculators will read the answer back
    through, and a figure of the wrong type there is dropped in silence.
  - An approval has to be a real boolean. `bool("no")` is True, and so is
    `bool([])`'s opposite for every non-empty string a tester might type; a
    final approval decided by Python truthiness is a return filed because
    somebody sent the string "false".
  - A carried-over value may only be rejected if that pause offered it. The
    rejection clears the field, so an unshown key is a write to a value the user
    never saw.

`None` stays a legal answer to every question, required ones included: the
interview's own screen offers "I don't know" on every card, and `ask_user`
records the question as asked without landing a value. Whether the case may
finish without it is decided by the gate guard on the way to the stop card, not
here.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from domain.fields import AnswerType
from domain.questions import BY_ID

# The two decisions a person may make about a Tax Position on the final card.
# `pending` and `needs_reconfirmation` are states the assessment puts a position
# into, never a reply: accepting the payload's word for either would let a client
# reset a decision it is supposed to be making.
_DECISIONS: tuple[str, ...] = ("accepted", "rejected")

_ACTIONS: tuple[str, ...] = ("revise", "dismiss")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ResumeInvalid(ValueError):
    """A reply that does not answer the pause it was sent for.

    Carries a sentence meant for the person who sent it: the routes put it
    straight into a 422 body.
    """


def validate_resume(pause: dict[str, Any], resume: Any) -> None:
    """Raise `ResumeInvalid` unless `resume` answers `pause`.

    Returns nothing. The reply is passed on to the graph exactly as it arrived -
    this checks the reply, it does not rewrite it, because a value quietly
    coerced here would be persisted under `Provenance.answer` as though the user
    had typed it.
    """
    kind = pause.get("type", "")
    if kind == "question":
        _check_question(pause, resume)
    elif kind == "confirm_stop":
        _check_confirm_stop(pause, resume)
    elif kind == "findings":
        _check_findings(resume)
    elif kind == "final_approval":
        _check_final_approval(pause, resume)
    else:
        # An unrecognised pause type is a server-side mistake, not a client one,
        # but passing the reply through unchecked is the one option that is worse
        # than either.
        raise ResumeInvalid(f"the interview is paused on something unanswerable: {kind!r}")


def _check_question(pause: dict[str, Any], resume: Any) -> None:
    question = BY_ID.get(str(pause.get("question_id") or ""))
    if question is None:
        raise ResumeInvalid("this question is no longer in the catalogue; start the interview again")
    spec = question.spec()

    value = _unwrap(resume, "value")
    if value is None:  # "I don't know", the one answer every question takes
        return

    what = f"{question.id} expects"
    if spec.answer_type is AnswerType.boolean:
        _require_bool(value, f"{what} yes or no")
        return
    if spec.answer_type is AnswerType.choice:
        if not isinstance(value, str) or value not in spec.options:
            allowed = ", ".join(spec.options)
            raise ResumeInvalid(f"{what} one of: {allowed}")
        return
    if spec.answer_type is AnswerType.text:
        if not isinstance(value, str):
            raise ResumeInvalid(f"{what} text")
        return
    if spec.answer_type is AnswerType.date:
        if not isinstance(value, str) or not _ISO_DATE.match(value):
            raise ResumeInvalid(f"{what} a date as YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ResumeInvalid(f"{what} a real calendar date; {value} is not one") from None
        return

    # integer, month, money, percent
    whole = spec.answer_type in (AnswerType.integer, AnswerType.month)
    number = _require_number(value, whole, what)
    _require_range(number, spec.minimum, spec.maximum, question.id)


def _check_confirm_stop(pause: dict[str, Any], resume: Any) -> None:
    if isinstance(resume, bool):  # the original contract: a card with nothing carried
        return
    if not isinstance(resume, dict):
        raise ResumeInvalid("the stop card expects yes or no")
    _reject_unknown_keys(resume, ("confirm", "reject"), "the stop card")

    if "confirm" in resume:
        # Absent is not the same as malformed: `read_stop_answer` defaults a
        # missing flag to True, and a card that only rejects a carried value
        # relies on it.
        _require_bool(resume["confirm"], "the stop card expects yes or no")

    rejected = resume.get("reject")
    if rejected is None:
        return
    if not isinstance(rejected, list):
        raise ResumeInvalid("the values you no longer agree with have to arrive as a list")
    shown = {str(c.get("key")) for c in pause.get("carried_over") or []}
    for key in rejected:
        if not isinstance(key, str):
            raise ResumeInvalid("a rejected value is named by its key")
        if key not in shown:
            raise ResumeInvalid(f"{key} was not among the values this card offered")


def _check_findings(resume: Any) -> None:
    action = _unwrap(resume, "action")
    if action not in _ACTIONS:
        # `resolve_findings` reads anything that is not "revise" as a dismissal,
        # so an unrecognised action does not fail there - it waves the review
        # through. Which is the reason this is checked here.
        raise ResumeInvalid("the review card expects either revise or dismiss")


def _check_final_approval(pause: dict[str, Any], resume: Any) -> None:
    if not isinstance(resume, dict):
        raise ResumeInvalid("the approval card expects an approval and a decision per position")
    _reject_unknown_keys(resume, ("approve", "decisions"), "the approval card")
    if "approve" not in resume:
        raise ResumeInvalid("the approval card expects you to approve or decline")
    _require_bool(resume["approve"], "an approval has to be yes or no")

    decisions = resume.get("decisions")
    if decisions is None:
        return
    if not isinstance(decisions, dict):
        raise ResumeInvalid("the decisions have to arrive keyed by position")
    known = {str(p.get("position_id")) for p in pause.get("tax_positions") or []}
    for position_id, decision in decisions.items():
        if position_id not in known:
            raise ResumeInvalid(f"{position_id} is not a position on this card")
        if decision not in _DECISIONS:
            raise ResumeInvalid(f"{position_id}: a position is either accepted or rejected")


# --- the small shared checks ---


def _unwrap(resume: Any, field: str) -> Any:
    """The payload's one value, whether it arrived bare or wrapped.

    A dict has to be the wrapper and nothing else: a stray second key is a client
    sending a shape this pause does not read, and half of it would be dropped in
    silence.
    """
    if not isinstance(resume, dict):
        return resume
    if field not in resume:
        raise ResumeInvalid(f"the answer has to carry a {field}")
    _reject_unknown_keys(resume, (field,), "the answer")
    return resume[field]


def _reject_unknown_keys(payload: dict[str, Any], allowed: tuple[str, ...], what: str) -> None:
    extra = sorted(set(payload) - set(allowed))
    if extra:
        raise ResumeInvalid(f"{what} does not read {', '.join(extra)}")


def _require_bool(value: Any, message: str) -> None:
    if not isinstance(value, bool):
        raise ResumeInvalid(message)


def _require_number(value: Any, whole: bool, what: str) -> float:
    # bool is an int in Python, and True would otherwise pass as the number 1.
    if isinstance(value, bool):
        raise ResumeInvalid(f"{what} a number")
    if whole:
        if not isinstance(value, int):
            raise ResumeInvalid(f"{what} a whole number")
        return float(value)
    if not isinstance(value, (int, float)):
        raise ResumeInvalid(f"{what} a number")
    if not math.isfinite(value):
        raise ResumeInvalid(f"{what} a number")
    return float(value)


def _require_range(value: float, minimum: Any, maximum: Any, question_id: str) -> None:
    if minimum is not None and value < minimum:
        raise ResumeInvalid(f"{question_id}: {_plain(value)} is below {_plain(minimum)}")
    if maximum is not None and value > maximum:
        raise ResumeInvalid(f"{question_id}: {_plain(value)} is above {_plain(maximum)}")


def _plain(number: float) -> str:
    return str(int(number)) if float(number).is_integer() else str(number)
