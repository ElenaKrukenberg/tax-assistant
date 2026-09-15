"""The interview arms, and the profiles they are run against.

Three arms on the same profile (ADR 0009):

  questionnaire  every catalogue question, in order, whatever the profile says
  filter         the first relevant question, until none are relevant
  agent          the Interviewer, when it exists

The point of the middle one is honesty. A form asks 35 questions; the filter alone
asks far fewer, with no model involved. Comparing the agent against the form would
credit it with work that plain code does, and the first person to ask what the agent
contributed would be right to.

The questionnaire is generated, not written: `CATALOGUE` in declaration order *is*
the baseline. Nobody chooses its length, which is what makes the comparison mean
anything.

Run it:
    python -m eval.baseline            # every profile, both arms that exist
    python -m eval.baseline p03        # one profile, by id prefix
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from domain.fields import (CATEGORY_FIELDS, PROFILE_FIELDS, ExpenseCategory, key_for,
                           namespace_of)
from domain.questions import CATALOGUE, Question, relevant_questions

PROFILES_PATH = Path(__file__).with_name("profiles.jsonl")

DONT_KNOW = object()
"""What the answerer returns for a field the profile deliberately cannot supply."""


@dataclass(frozen=True)
class Profile:
    """One synthetic user: the answer to every question they could be asked."""

    id: str
    label: str
    answers: dict[str, Any]
    cannot_answer: frozenset[str]
    expected: dict[str, Any]

    def answer(self, question: Question) -> Any:
        """What this profile says when asked. DONT_KNOW is an answer too.

        A question outside both `answers` and `cannot_answer` is one the profile has
        no opinion on, which for a synthetic user means the same as not knowing.
        """
        if question.key in self.cannot_answer:
            return DONT_KNOW
        return self.answers.get(question.key, DONT_KNOW)


@dataclass
class Transcript:
    """What one arm did on one profile."""

    arm: str
    profile_id: str
    asked: list[str] = field(default_factory=list)
    unanswered: list[str] = field(default_factory=list)
    known: dict[str, Any] = field(default_factory=dict)

    @property
    def question_count(self) -> int:
        return len(self.asked)

    @property
    def asked_set(self) -> frozenset[str]:
        return frozenset(self.asked)

    @property
    def irrelevant(self) -> list[str]:
        """Questions asked that the profile's own answers make pointless.

        Measured after the fact against the finished state: a question whose
        conditions do not hold there was not worth asking. For the filter arm this is
        empty by construction, which is the baseline the agent has to beat rather
        than merely match.
        """
        out = []
        for question_id in self.asked:
            question = _by_id()[question_id]
            if not question.applies(self.known):
                out.append(question_id)
        return out

    def missing_required(self) -> list[str]:
        """Required fields still empty, counting only categories the profile opened.

        Completeness is the half of the comparison that stops "fewer questions" from
        being achieved by simply asking less.
        """
        missing = [key_for(None, s.name) for s in PROFILE_FIELDS
                   if s.required and self.known.get(key_for(None, s.name)) is None]
        for category in _opened_categories(self.known):
            for spec in CATEGORY_FIELDS[category]:
                key = key_for(category, spec.name)
                if spec.required and not spec.filled_by and self.known.get(key) is None:
                    missing.append(key)
        return missing

    def missing_amount_fields(self) -> list[str]:
        """Unfilled fields that would change a figure, in opened categories only.

        Deliberately narrower than `missing_required`. No profile field is here by
        construction: profile fields open categories, place values on the form or
        feed plausibility checks — none of them enters a calculator. Losing one is
        worth reporting; it is not a wrong figure. The distinction was drawn after
        the first live run punished the agent six times for skipping fields that
        could not have moved a single euro.
        """
        missing = []
        for category in _opened_categories(self.known):
            for spec in CATEGORY_FIELDS[category]:
                key = key_for(category, spec.name)
                if (spec.required and spec.affects_amount and not spec.filled_by
                        and self.known.get(key) is None):
                    missing.append(key)
        return missing


def load_profiles(path: Path = PROFILES_PATH) -> list[Profile]:
    profiles = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        profiles.append(Profile(
            id=raw["id"],
            label=raw["label"],
            answers=raw["answers"],
            cannot_answer=frozenset(raw.get("cannot_answer", ())),
            expected=raw.get("expected", {}),
        ))
    return profiles


# --- the arms -------------------------------------------------------------------

def run_questionnaire(profile: Profile) -> Transcript:
    """Ask everything, in order. What a fixed form does."""
    t = Transcript(arm="questionnaire", profile_id=profile.id)
    for question in CATALOGUE:
        _ask(t, question, profile)
    return t


def run_filter(profile: Profile, limit: int = 200,
               seeded: Optional[dict[str, Any]] = None) -> Transcript:
    """Ask the first relevant, not-yet-asked question until none are left.

    "Not yet asked" is the part that matters. A question the user could not answer
    leaves its field empty, so relevance alone would put it back at the front of the
    queue forever — "I don't know" has to count as having been asked. The first
    version of this looped on three of the ten profiles.

    `seeded` starts the case with values already in it, which is what a second tax
    return looks like: whatever an earlier case carried over is known before the
    first question (ADR 0011). Seeded values are known but not asked, so they do not
    count towards the question total — which is the whole point of measuring them.
    """
    t = Transcript(arm="filter", profile_id=profile.id)
    if seeded:
        t.known.update(seeded)
    for _ in range(limit):
        question = next((q for q in relevant_questions(t.known) if q.id not in t.asked_set),
                        None)
        if question is None:
            break
        _ask(t, question, profile)
    return t


def run_agent(
    profile: Profile,
    decide: Callable[[dict, frozenset], Optional[Question]],
    limit: int = 40,
) -> Transcript:
    """Ask whatever `decide` picks, until it declines to pick anything.

    The Interviewer plugs in here as a pure function of the state: the same function
    a graph node will call between two interrupts, so nothing has to be rewritten to
    move from measuring to running (see docs/SPRINT_AGENTIC_MVP.md on the work order).

    It receives what has been asked as well as what is known, for the same reason the
    filter needs it — otherwise an unanswerable question can be chosen forever. An
    agent that repeats a question anyway is not stopped here: repeating one is a
    result worth measuring, and `limit` is what keeps it finite.
    """
    t = Transcript(arm="agent", profile_id=profile.id)
    for _ in range(limit):
        question = decide(dict(t.known), frozenset(t.asked))
        if question is None:
            break
        _ask(t, question, profile)
    return t


# --- internals ------------------------------------------------------------------

_BY_ID: dict[str, Question] = {}


def _by_id() -> dict[str, Question]:
    if not _BY_ID:
        _BY_ID.update({q.id: q for q in CATALOGUE})
    return _BY_ID


def _ask(t: Transcript, question: Question, profile: Profile) -> None:
    t.asked.append(question.id)
    answer = profile.answer(question)
    if answer is DONT_KNOW:
        t.unanswered.append(question.id)
        # Left absent rather than stored as None: an unanswered field is not a value,
        # and the filter has to keep seeing it as open.
        return
    t.known[question.key] = answer


def _opened_categories(known: dict[str, Any]) -> Iterable[ExpenseCategory]:
    """Categories whose gate the profile actually opened."""
    for category in ExpenseCategory:
        prefix = f"{namespace_of(category)}."
        if any(key.startswith(prefix) for key in known):
            yield category


# --- reporting ------------------------------------------------------------------

def compare(profile: Profile) -> dict[str, Transcript]:
    return {"questionnaire": run_questionnaire(profile), "filter": run_filter(profile)}


def _table(rows: list[tuple]) -> str:
    head = ("profile", "form", "filter", "saved", "dont know", "missing")
    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    out = [" ".join(str(h).ljust(w) for h, w in zip(head, widths))]
    out.append(" ".join("-" * w for w in widths))
    for row in rows:
        out.append(" ".join(str(c).ljust(w) for c, w in zip(row, widths)))
    return "\n".join(out)


def main(argv: list[str]) -> int:
    wanted = argv[0] if argv else ""
    profiles = [p for p in load_profiles() if p.id.startswith(wanted)]
    if not profiles:
        print(f"no profile matching {wanted!r}")
        return 1

    rows = []
    for profile in profiles:
        arms = compare(profile)
        form, filt = arms["questionnaire"], arms["filter"]
        rows.append((
            profile.id,
            form.question_count,
            filt.question_count,
            form.question_count - filt.question_count,
            len(filt.unanswered),
            len(filt.missing_required()) or "-",
        ))

    print(_table(rows))
    print(f"\nThe form always asks {len(CATALOGUE)}: it is the catalogue, in order.")
    print("`saved` is what deterministic filtering does on its own, with no model.")
    print("The agent has to be measured against `filter`, never against `form`.")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
