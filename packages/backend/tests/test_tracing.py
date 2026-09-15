"""Redaction: the promise that observability keeps (DECISIONS.md).

What must hold: no value the case holds about a person leaves in cleartext, the field
names stay so a trace still reads, and without an API key there is no tracer at all -
the default run is provider-silent.

The test that matters most is the one driven from the catalogue rather than from a
list written here. A hand-written list is what this replaced, and it failed silently:
it named four fields, only one of which existed, while thirteen that did travelled in
the open. A test with its own copy of the list would have passed the whole time.
"""

from core.tracing import (
    DOCUMENT_FIELDS,
    REDACTED_KEYS,
    _VALUE_RULE,
    callbacks,
    redact,
)
from domain.fields import CATEGORY_FIELDS, PROFILE_FIELDS, key_for


def test_every_field_in_the_catalogue_is_covered():
    """The invariant that makes adding a field safe.

    Nothing here enumerates fields: it walks `domain/fields.py`. A field added
    tomorrow is checked tomorrow, which is the whole point of deriving the set
    instead of maintaining it.
    """
    for field in PROFILE_FIELDS:
        assert f"{field.name} = [redacted]" in redact(f"{field.name} = 12345")
    for category, fields in CATEGORY_FIELDS.items():
        for field in fields:
            key = key_for(category, field.name)
            assert f"{key} = [redacted]" in redact(f"{key} = 12345")


def test_the_names_survive_so_a_trace_still_reads():
    out = redact("- commute.distance_km = 12\n- works_remotely = True")
    assert "12" not in out
    assert "True" not in out
    assert "commute.distance_km = [redacted]" in out
    assert "works_remotely = [redacted]" in out


def test_a_boolean_is_redacted_like_everything_else():
    """Deliberate, and the one place the old behaviour is reversed.

    "Covered by default" means nothing if the default is to leave something out, and
    a gate answer is still a fact about the person's employment. The branch the agent
    took stays visible anyway: the Interviewer's prompt prints a per-category state
    line beside the values, and that is what explains the choice.
    """
    assert redact("- has_minijob = True") == "- has_minijob = [redacted]"


def test_a_repeating_field_carries_its_index_and_still_loses_its_value():
    out = redact("- equipment.price_eur#1 = 899.0")
    assert out == "- equipment.price_eur#1 = [redacted]"


def test_both_spellings_of_a_category_field_are_covered():
    """A prompt qualifies the key; other shapes may not."""
    assert "[redacted]" in redact("distance_km = 27")
    assert "[redacted]" in redact("commute.distance_km = 27")


def test_json_payloads_are_covered_too():
    payload = ('{"homeoffice.homeoffice_days": 120,'
               ' "profile.employed_months": 12}')
    out = redact(payload)
    assert "120" not in out and ": 12" not in out


def test_the_document_intake_names_are_covered_before_the_intake_exists():
    """They have no live source yet, which is exactly why they are listed.

    The first traced run after document intake lands must already be safe, rather
    than being the run that teaches us it was not.
    """
    for name in DOCUMENT_FIELDS:
        assert f"{name} = [redacted]" in redact(f"{name} = Nordlicht Systeme GmbH")


def test_a_computed_expense_loses_its_figure():
    """The per-category total and the claimed expense, both `- category: N EUR`.

    No catalogue key sits beside these, but they are this person's answers added up,
    which makes them no less theirs.
    """
    out = redact("- entfernungspauschale: 252.00 EUR\n"
                 "- arbeitsmittel#1: 899.00 EUR, backed by invoice.pdf")
    assert "252" not in out and "899" not in out
    assert "- entfernungspauschale: [redacted] EUR" in out
    assert "backed by invoice.pdf" in out, "which document backs it is structure"


def test_the_figures_of_the_law_itself_stay_readable():
    """The deliberate limit on how broad the money rule is allowed to be.

    A rule that swallowed every number followed by EUR would take the Pauschbetrag
    and the statutory rate with it. Those are public, they protect nobody, and
    without them a trace of a calculation cannot be read at all.
    """
    text = ("Der Pauschbetrag betraegt 1230 EUR und die Entfernungspauschale "
            "0,30 EUR je Entfernungskilometer.")
    assert redact(text) == text


def test_one_pattern_carries_every_key():
    """The alternation has to be complete, because it is the only pass there is.

    `redact` runs over every string leaf of every run on its way out, so the keys
    were collapsed from one pattern each into a single alternation. A key that fell
    out of that join would be silently unprotected while the set still listed it.
    """
    pattern, _ = _VALUE_RULE
    assert len(REDACTED_KEYS) > 40, "the catalogue should be producing these"
    for key in REDACTED_KEYS:
        assert pattern.search(f"{key} = something"), f"{key} is not in the pattern"


def test_without_a_key_there_is_no_tracer():
    callbacks.cache_clear()
    assert callbacks() == []
