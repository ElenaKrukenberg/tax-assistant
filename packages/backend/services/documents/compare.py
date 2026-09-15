"""Do two independent reads of the same document agree?

The gate that stands in for a confidence number. Issue #11 measured what models
report about their own certainty and it does not track correctness; two reads that
disagree do, and cheaply - 0.31 cents a pass. Where they disagree, nothing is
proposed as a value: the user is shown both readings and types the figure or uploads
a better photo (issue #5).

Agreement is not string equality. A model may write the same amount as 1302 or
1302.0, and the same description with different spacing. Those are the same reading.
What must never be smoothed over is a different *number*: the cheap Gemini models
were dropped precisely because they move amounts between rows of a skewed form, and
a tolerance wide enough to hide that would make this whole comparison decorative.

Dates are compared as written, and two formats are a disagreement: `2025-09-08`
against `08.09.2025` sends the user to look, rather than being normalised into
agreement here. The prompt asks for one format, so two of them means one pass did
not follow it - and on a German date whose day is 12 or under, `01.02.2025` and
`2025-01-02` are the day/month inversion #11 measured on a real model, not a
formatting difference. Deciding which of the two a pass meant is exactly the guess
the two passes exist to avoid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Money is compared to the cent, and to the cent exactly. Not a percentage: a 1%
# tolerance on a 41,238.76 EUR salary is 412 EUR of silent disagreement.
CENT = 0.005


@dataclass(frozen=True)
class Disagreement:
    field: str
    first: Any
    second: Any

    def __str__(self) -> str:
        return f"{self.field}: {self.first!r} vs {self.second!r}"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _text(value: Any) -> str:
    """Case, punctuation and repeated spaces are not part of a reading."""
    return re.sub(r"[\s.,;:!?\-_/()]+", " ", str(value)).strip().lower()


def same(first: Any, second: Any) -> bool:
    """Whether two readings of one field are the same reading."""
    if first is None or second is None:
        # One pass read a field the other left empty. That is a disagreement, not a
        # missing value to be filled in from the luckier pass: the two reads exist to
        # catch exactly this.
        return first is None and second is None

    a, b = _number(first), _number(second)
    if a is not None and b is not None:
        return abs(a - b) < CENT

    if isinstance(first, list) and isinstance(second, list):
        return len(first) == len(second) and all(
            same(x, y) for x, y in zip(first, second)
        )

    if isinstance(first, dict) and isinstance(second, dict):
        return set(first) == set(second) and all(
            same(first[k], second[k]) for k in first
        )

    return _text(first) == _text(second)


def compare(first: dict[str, Any], second: dict[str, Any]) -> list[Disagreement]:
    """Every field the two passes read differently, in schema order."""
    return [
        Disagreement(field, first.get(field), second.get(field))
        for field in dict.fromkeys([*first, *second])
        if not same(first.get(field), second.get(field))
    ]
