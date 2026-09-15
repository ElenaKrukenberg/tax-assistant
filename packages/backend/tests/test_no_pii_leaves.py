"""Nothing that identifies a person leaves for a provider (#79, reduced).

Most of this ticket is satisfied by what the product never collects. `domain/fields.py`
has no name, no address, no email and no Steuer-ID, so there is no identity data in the
interview to separate from the tax reasoning facts - the separation exists because the
other half does not. What is worth a test is that this stays true: a field added for a
person's name would flow into every prompt the Interviewer builds, and nothing else
would complain.

The redaction tests that already exist cover the LangSmith upload path
(`core/tracing.py`, derived from the same catalogue in `9bf8b92`). That is a different
path from the provider call, and this file is about the provider call.

**One exposure is real and is not fixed here.** A document image is sent whole, and a
Lohnsteuerbescheinigung carries the employee's name, the eTIN and the Kirchensteuer
line whether or not this product wants them - `services/documents/sensitivity.py` says
so, and the last test below pins that the statement is still there rather than
pretending the gap is closed.
"""

from __future__ import annotations

import re

from domain.fields import CATEGORY_FIELDS, PROFILE_FIELDS
from domain.questions import BY_ID

# Words that name a person rather than a fact about their tax year. Deliberately not a
# general PII detector: it is the specific list § 79 names, plus the obvious German
# spellings, checked against a catalogue small enough to read.
IDENTITY = re.compile(
    r"\b(name|vorname|nachname|address|adresse|strasse|straße|plz|email|e_mail|mail|"
    r"phone_number|telefonnummer|steuer_?id|steueridentifikationsnummer|idnr|etin|"
    r"iban|bic|kontonummer|geburtsdatum|birth|birthday|ssn)\b",
    re.I,
)


def catalogue_field_names() -> list[str]:
    names = [field.name for field in PROFILE_FIELDS]
    for fields in CATEGORY_FIELDS.values():
        names.extend(field.name for field in fields)
    return names


def test_the_fact_catalogue_holds_nothing_that_identifies_a_person():
    """The separation #79 asks for, as the absence it actually is."""
    offenders = [name for name in catalogue_field_names() if IDENTITY.search(name)]
    assert offenders == [], (
        f"{offenders} identifies a person. Facts travel to the provider in every "
        "Interviewer prompt; identity data has no business in this catalogue."
    )


def test_no_question_asks_for_an_identifier():
    """The other end of the same rule: a question is what puts a value in the case."""
    offenders = [
        qid for qid, question in BY_ID.items()
        if IDENTITY.search(qid) or IDENTITY.search(getattr(question, "field", "") or "")
    ]
    assert offenders == [], f"{offenders} asks the user to identify themselves"


def test_the_document_image_exposure_is_still_written_down():
    """The one thing that does leave, stated where a reader of the privacy story is.

    Local recognition would change this and there is none, so it is a boundary rather
    than a task. What must not happen is the sentence quietly disappearing while the
    behaviour stays.
    """
    from services.documents import sensitivity

    doc = sensitivity.__doc__ or ""
    assert "medical bill" in doc or "declared" in doc
    module = __import__("inspect").getsource(sensitivity)
    assert "Kirchensteuer" in module, (
        "the Art. 9 exposure a payslip image carries is no longer documented beside "
        "the allowlist that permits sending it"
    )
