"""LangSmith tracing, with the redaction the privacy decision requires.

Observability does not overrule the privacy decision (ADR 0004, DECISIONS.md):
traces show *why the agent chose what it chose* —
the structure, the candidates, the decisions — and for that nobody needs the
user's salary in cleartext. Before a run leaves for LangSmith, the values of the
sensitive fields are replaced by a marker; the field names stay, so a trace still
reads.

Wiring is explicit, not the LANGSMITH_TRACING env autopilot: the autopilot builds
its own client without the anonymizer, which would upload unredacted runs — the
exact failure this module exists to prevent. `callbacks()` hands back a tracer
built around the anonymizing client, or nothing when no API key is configured,
and `core/llm.py` attaches it to every model call.
"""

from __future__ import annotations

import re
from functools import lru_cache

from core.config import get_settings
from domain.fields import CATEGORY_FIELDS, PROFILE_FIELDS, key_for

# What is redacted, and why it is derived rather than listed.
#
# This used to be four field names written by hand, kept in step with the extraction
# schema by remembering to. It failed exactly as that arrangement fails: of the four,
# only one existed in the live case model, while thirteen fields that did exist -
# distance_km, homeoffice_days, price_eur, move_date and the rest - travelled in
# cleartext because nobody added them.
#
# So the set is now built from `domain/fields.py`, the same way CARRY_OVER_FIELDS is:
# marking a field in the catalogue is the whole of adding one, and a field added
# tomorrow is covered tomorrow rather than when somebody notices. See
# docs/TRACING_POLICY.md for the region, the retention and what can be deleted.

_MARKER = "[redacted]"


def _case_value_keys() -> tuple[str, ...]:
    """Every catalogue key a prompt can print a value for.

    Both spellings, because both appear: a stored fact is always qualified
    (`commute.distance_km`, `profile.employed_months`, plus `#1` for a repeating
    field), while a prompt or a tool argument may still name the bare field. Longest
    first so the qualified form is tried before the bare one - either redacts, but
    this keeps the output predictable.
    """
    keys = {field.name for field in PROFILE_FIELDS}
    keys |= {key_for(None, field.name) for field in PROFILE_FIELDS}
    for category, fields in CATEGORY_FIELDS.items():
        for field in fields:
            keys.add(field.name)
            keys.add(key_for(category, field.name))
    return tuple(sorted(keys, key=len, reverse=True))


# Names the document intake is expected to produce. They have no live source yet -
# nothing in the backend writes `documents.extracted` - so they cannot come from the
# catalogue, and they are listed here rather than left out so that the first traced
# run after intake lands is already covered instead of being the thing that teaches
# us it was not. Both spellings of the salary, because the extraction fixtures use
# the `_eur` suffix and the schema may settle either way.
DOCUMENT_FIELDS: tuple[str, ...] = (
    "gross_salary_eur",
    "gross_salary",
    "employer_name",
    "address",
)

REDACTED_KEYS: tuple[str, ...] = _case_value_keys() + DOCUMENT_FIELDS

# Prompts print case values as `- key = value` and JSON carries them as
# `"key": value`; both shapes are covered, up to the end of the line or value.
# `"?` after the name is the JSON quote; `#\d+` is a repeating field's second item.
#
# One alternation rather than one pattern per key: `redact` runs over every string
# leaf of every run on its way out, and sixty passes over the same text to do what
# one can do is sixty times the work in a thread that is already competing with the
# request that produced it.
_VALUE_RULE = (
    re.compile(
        r"((?:" + "|".join(re.escape(key) for key in REDACTED_KEYS) + r")"
        r"(?:#\d+)?\"?\s*[=:]\s*)[^,\n}]+"
    ),
    rf"\1{_MARKER}",
)

# The two lines that carry a figure without a catalogue key beside it: the running
# per-category total in the Interviewer's prompt and the claimed expense in the
# Reviewer's, both shaped `- category: 252.00 EUR`. Computed from this person's
# answers, so no less theirs than the answers were.
_AMOUNT_RULE = (re.compile(r"^(\s*-\s*[a-z_]+(?:#\d+)?:\s*)[\d.,]+(\s*EUR)",
                           re.MULTILINE),
                rf"\1{_MARKER}\2")

# What this does not reach, recorded rather than left to be discovered: the Reviewer
# prompt also prints each expense's trace, which is the formula with this person's
# numbers already substituted ("220 days x 12 km x 0.30 EUR/km"). A rule broad enough
# to catch those would also redact the Pauschbetrag and the statutory rate beside
# them - public figures that protect nobody and without which a trace cannot be read
# at all. Closing it properly means the trace carrying its inputs as fields rather
# than as prose, which is issue #73 along with the rest of the tracing work.


def redact(text: str) -> str:
    """The values replaced, the structure intact.

    The field names stay: a trace still shows which values the case holds and which
    branch the agent took, which is what a trace is for. What it stops showing is
    what those values say.
    """
    for pattern, replacement in (_VALUE_RULE, _AMOUNT_RULE):
        text = pattern.sub(replacement, text)
    return text


@lru_cache()
def callbacks() -> list:
    """The tracer to attach to model calls, or an empty list without a key.

    Cached: one client, one tracer, shared by every OpenRouterClient — and the
    empty list keeps every local run and every test provider-silent by default.
    """
    settings = get_settings()
    if not settings.langsmith_api_key:
        return []

    from langchain_core.tracers import LangChainTracer
    from langsmith import Client
    from langsmith.anonymizer import create_anonymizer

    client = Client(
        api_key=settings.langsmith_api_key,
        api_url=settings.langsmith_endpoint or None,
        # The same `redact` the tests pin down, applied to every string leaf of a
        # run before upload.
        anonymizer=create_anonymizer(redact),
    )
    return [LangChainTracer(project_name=settings.langsmith_project, client=client)]
