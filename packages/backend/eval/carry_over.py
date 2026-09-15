"""What a second return costs, measured against a first one.

The claim under test is narrow and deliberately so: carrying three facts across the
tax year makes the *next* interview shorter, and it does so without losing anything.
Both halves need a number.

The measurement is deterministic and free. Profile memory is not a model decision —
which fields carry is declared in `domain/fields.py`, and whether a carried field is
still relevant is the catalogue's own condition. So the arm to measure against is the
filter, exactly as ADR 0009 requires of the agent, and no provider is involved at all.
A saving here is not a saving the agent produced; it is one the *product* produces,
and mixing the two would be the same flattery ADR 0009 exists to prevent.

Three columns per profile:

- **first** — the filter on an empty case: what this person answers the first year.
- **second** — the filter on a case pre-seeded with what carries: the year after.
- **on the card** — how many carried values were still relevant and therefore shown
  for confirmation. The saving is not free: those questions are replaced by one card,
  not by nothing, and reporting `second` without this would overstate it.

Run it:
    python -m eval.carry_over
    python -m eval.carry_over p03

Results land in eval/results/carry-over.json.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from domain.fields import CARRY_OVER_FIELDS
from domain.questions import BY_KEY
from eval.baseline import Profile, load_profiles, run_filter

RESULTS = Path(__file__).parent / "results"


@dataclass
class CarryOverRun:
    """One profile, filed twice."""

    profile_id: str
    label: str
    first_year_questions: int
    second_year_questions: int
    carried: list[str] = field(default_factory=list)      # seeded into year two
    on_the_card: list[str] = field(default_factory=list)  # still relevant, so shown
    lost_required: list[str] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return self.first_year_questions - self.second_year_questions


def remembered_from(transcript_known: dict[str, Any]) -> dict[str, Any]:
    """What the first year teaches the profile memory.

    Only fields the person actually answered: a value they could not supply is not
    remembered, exactly as in `agents/profile_memory.py`, where memory is written
    from answers and from nothing else.
    """
    return {key: transcript_known[key] for key in CARRY_OVER_FIELDS
            if key in transcript_known}


def run(profile: Profile) -> CarryOverRun:
    first = run_filter(profile)
    carried = remembered_from(first.known)

    # The second year starts with the carried values already in the case. Everything
    # else is empty: amounts, days and purchases are this year's and are asked again.
    second = run_filter(profile, seeded=dict(carried))

    # A carried value reaches the stop card only if its question still applies —
    # somebody who stopped commuting is not shown last year's distance.
    on_card = [key for key in carried if BY_KEY[key].applies(second.known)]

    return CarryOverRun(
        profile_id=profile.id,
        label=profile.label,
        first_year_questions=first.question_count,
        second_year_questions=second.question_count,
        carried=sorted(carried),
        on_the_card=sorted(on_card),
        # The safety half of the claim: nothing an amount depends on may go missing
        # because it was carried instead of asked.
        lost_required=sorted(set(second.missing_required()) - set(first.missing_required())),
    )


def _table(runs: list[CarryOverRun]) -> str:
    head = ("profile", "first", "second", "saved", "on the card", "lost")
    rows = [(r.profile_id, r.first_year_questions, r.second_year_questions,
             r.saved, len(r.on_the_card), len(r.lost_required) or "-") for r in runs]
    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    out = [" ".join(str(h).ljust(w) for h, w in zip(head, widths)),
           " ".join("-" * w for w in widths)]
    for row in rows:
        out.append(" ".join(str(c).ljust(w) for c, w in zip(row, widths)))
    return "\n".join(out)


def main(argv: list[str]) -> int:
    wanted = argv[0] if argv else ""
    profiles = [p for p in load_profiles() if p.id.startswith(wanted)]
    if not profiles:
        print(f"no profile matching {wanted!r}")
        return 1

    runs = [run(p) for p in profiles]
    print(_table(runs))

    saved = sum(r.saved for r in runs)
    carded = sum(len(r.on_the_card) for r in runs)
    lost = sum(len(r.lost_required) for r in runs)
    helped = sum(1 for r in runs if r.saved > 0)
    print(f"\n{saved} questions not asked the second year across {len(runs)} profiles, "
          f"on {helped} of them.")
    print(f"{carded} of those became one confirmation card per profile, not nothing.")
    print(f"{lost} amount-affecting fields lost. Anything but 0 is a defect, not a trade-off.")
    print("Free and deterministic: which fields carry is declared, not decided by a model.")

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "carry-over.json"
    out.write_text(json.dumps({
        "carry_over_fields": sorted(CARRY_OVER_FIELDS),
        "totals": {"profiles": len(runs), "saved": saved,
                   "on_the_card": carded, "lost_required": lost,
                   "profiles_helped": helped},
        "runs": [asdict(r) for r in runs],
    }, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwritten: {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
