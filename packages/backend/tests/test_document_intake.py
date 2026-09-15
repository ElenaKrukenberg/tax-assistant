"""The plain functions of document intake: file checks, schemas, comparison, mapping.

No model anywhere in this file. That is the boundary `docs/AGENT_ARCHITECTURE.md`
draws around intake - the workflow is stateful, the parts it calls are not - and it
is what makes the parts that decide a figure testable without paying for a provider.
"""

from __future__ import annotations

from datetime import date
from typing import Union, get_args, get_origin

import pytest

from domain.fields import ExpenseCategory
from services.documents import classify, compare, confirm, intake, mapping, schemas
from services.documents.extract import content_blocks, document_type_matches
from services.documents.schemas import Invoice, InvoiceLine, Payslip
from services.documents.sensitivity import DocumentKind, may_be_sent_to_a_model

JPEG = b"\xff\xd8\xff" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# --- the file, before anything is sent anywhere ---------------------------------

def test_the_format_is_decided_by_the_bytes_not_by_the_client():
    """A content type is a claim, and the point of a check is that a claim can be wrong."""
    checked = intake.check(JPEG, file_name="payslip.jpg", declared_format="image/jpeg")
    assert checked.file_format is intake.FileFormat.jpeg

    with pytest.raises(intake.Rejected) as refused:
        intake.check(JPEG, file_name="payslip.pdf", declared_format="application/pdf")
    assert refused.value.code == "format_mismatch"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "empty"),
        (b"GIF89a" + b"\x00" * 64, "unsupported_format"),
        (b"\xff\xd8\xff" + b"\x00" * (intake.MAX_BYTES + 1), "too_large"),
    ],
)
def test_what_is_refused_and_why(data, code):
    with pytest.raises(intake.Rejected) as refused:
        intake.check(data, file_name="x")
    assert refused.value.code == code
    assert refused.value.detail, "a rejection the interface can show as it stands"


def test_a_pdf_is_counted_in_pages_and_a_broken_one_is_refused():
    from pypdf import PdfWriter

    import io

    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=595, height=842)
    buffer = io.BytesIO()
    writer.write(buffer)

    assert intake.check(buffer.getvalue(), file_name="scan.pdf").pages == 2

    with pytest.raises(intake.Rejected) as refused:
        intake.check(b"%PDF-1.4 and then nothing", file_name="scan.pdf")
    assert refused.value.code == "pdf_unreadable"


# --- what the model is asked for ------------------------------------------------

def test_no_schema_can_break_the_two_provider_limits():
    """Both limits are measured, and both are silent failures if crossed (#65).

    Above 16 union-typed parameters Bedrock rejects the whole request; a nullable
    enum it rejects outright. A field added without this test would fail on a live
    upload for one model and work for another.
    """
    def unions(node) -> int:
        if isinstance(node, dict):
            count = 1 if isinstance(node.get("type"), list) else 0
            return count + sum(unions(v) for v in node.values())
        if isinstance(node, list):
            return sum(unions(v) for v in node)
        return 0

    for kind, schema in schemas.SCHEMA_FOR.items():
        assert unions(schema) <= 16, kind
        for name, field in schema["schema"]["properties"].items():
            if "enum" in field:
                assert field["type"] == "string", f"{kind}.{name}: a nullable enum is refused"
                assert None not in field["enum"]


JSON_TYPES = {"string": str, "number": float, "integer": int,
              "boolean": bool, "array": list, "object": dict}


def _schema_shape(field: dict) -> tuple[type, bool]:
    """What one schema property asks for: the type, and whether null is allowed."""
    declared = field["type"]
    names = declared if isinstance(declared, list) else [declared]
    rest = [name for name in names if name != "null"]
    assert len(rest) == 1, f"a property with two non-null types: {declared}"
    return JSON_TYPES[rest[0]], "null" in names


def _model_shape(annotation) -> tuple[type, bool]:
    """The same pair, read off a Pydantic annotation. `Optional[list[X]]` -> (list, True)."""
    nullable = False
    if get_origin(annotation) is Union:
        args = get_args(annotation)
        nullable = type(None) in args
        rest = [arg for arg in args if arg is not type(None)]
        assert len(rest) == 1, f"a union this comparison cannot read: {annotation}"
        annotation = rest[0]
    return get_origin(annotation) or annotation, nullable


def _agree(properties: dict, model, where: str) -> None:
    assert set(properties) == set(model.model_fields), where
    for name, field in properties.items():
        annotation = model.model_fields[name].annotation
        assert _schema_shape(field) == _model_shape(annotation), f"{where}.{name}"
        # The one nested shape: an invoice line is a model of its own, and a
        # disagreement inside it is the least visible place for one.
        if "items" in field and "properties" in field["items"]:
            element = get_args(_unwrap(annotation))[0]
            _agree(field["items"]["properties"], element, f"{where}.{name}[]")


def _unwrap(annotation):
    if get_origin(annotation) is Union:
        return next(arg for arg in get_args(annotation) if arg is not type(None))
    return annotation


def test_the_schema_and_the_model_that_reads_the_reply_agree():
    """Two definitions of one shape, held in step here rather than by memory.

    Names *and* types. A field the schema asks for as `["number", "null"]` while the
    model reads it as `Optional[str]` passes a name check and then quietly turns every
    amount on the document into a string - which is the kind of disagreement two
    definitions of one shape exist to produce.
    """
    for kind, schema in schemas.SCHEMA_FOR.items():
        _agree(schema["schema"]["properties"], schemas.MODEL_FOR[kind], kind.value)


def test_the_payslip_schema_asks_for_nothing_it_cannot_store():
    """Data minimisation, as a test rather than as an intention.

    The sweep's schema reads fifteen fields off a Lohnsteuerbescheinigung because it
    is grading a model. The product reads three, because three is what
    `domain/fields.py` has a home for - and one of the twelve it does not ask for is
    the Kirchensteuer, which says whether someone belongs to a church that levies it.
    """
    asked = set(schemas.PAYSLIP_PROPERTIES)
    assert asked == {"document_type", "tax_year",
                     "employment_period_start", "employment_period_end"}
    for never in ("church_tax_eur", "employee_name", "etin", "tax_class",
                  "gross_salary_eur", "income_tax_eur"):
        assert never not in asked


def test_only_the_two_supported_types_may_be_sent_to_a_model():
    assert may_be_sent_to_a_model("rechnung")
    assert may_be_sent_to_a_model("lohnsteuerbescheinigung")
    assert not may_be_sent_to_a_model("arztrechnung")
    assert not may_be_sent_to_a_model("")


def test_a_pdf_travels_as_a_file_block_and_an_image_as_an_image():
    """The parser is named by `extract.PDF_PLUGINS`; the block has to be the file one.

    Measured: on an image-only scan the `pdf-text` engine returns an empty document
    for almost no money, so a PDF sent as anything but a file block with the engine
    named is the failure that looks like success.
    """
    pdf = intake.CheckedUpload("scan.pdf", intake.FileFormat.pdf, 1000, 1)
    blocks = content_blocks(b"%PDF-1.4", pdf, DocumentKind.rechnung)
    assert blocks[1]["type"] == "file"
    assert blocks[1]["file"]["file_data"].startswith("data:application/pdf;base64,")

    photo = intake.CheckedUpload("photo.png", intake.FileFormat.png, 1000, 1)
    assert content_blocks(PNG, photo, DocumentKind.rechnung)[1]["type"] == "image_url"


def test_a_document_of_the_wrong_type_is_a_question_not_an_extraction():
    assert document_type_matches(DocumentKind.rechnung, {"document_type": "rechnung"}) is None
    mismatch = document_type_matches(
        DocumentKind.rechnung, {"document_type": "lohnsteuerbescheinigung"}
    )
    assert mismatch and "lohnsteuerbescheinigung" in mismatch
    assert document_type_matches(DocumentKind.rechnung, {"document_type": "unbekannt"})


# --- when the provider will not answer -------------------------------------------

class _Vision:
    """A vision client that answers, or fails, exactly as a test asks it to."""

    def __init__(self, model: str, payload: dict | None = None,
                 fails: Exception | None = None):
        self.model = model
        self.payload = payload
        self.fails = fails
        self.calls = 0

    async def read_document(self, **_):
        import json

        self.calls += 1
        if self.fails is not None:
            raise self.fails
        return json.dumps(self.payload), {"prompt_tokens": 10, "completion_tokens": 5}


_INVOICE = {
    "document_type": "rechnung", "price_basis": "net", "invoice_date": "2025-09-08",
    "net_total_eur": 240.0, "vat_rate_percent": 19.0, "vat_amount_eur": 45.6,
    "gross_total_eur": 285.6,
    "line_items": [{"description": "Bürostuhl", "quantity": 1, "unit_price_eur": 240.0}],
}

_UPLOAD = intake.CheckedUpload(
    file_name="rechnung.jpg", file_format=intake.FileFormat.jpeg,
    size_bytes=1024, pages=1,
)


def _read_twice(primary, fallback=None):
    import asyncio

    from services.documents import extract

    return asyncio.run(extract.read_twice(
        primary, b"\xff\xd8\xff", _UPLOAD, DocumentKind.rechnung, fallback=fallback,
    ))


def test_an_unreachable_provider_moves_both_passes_to_the_fallback():
    """Both, not one: two models disagree where one model is consistent."""
    from core.llm import LLMError

    primary = _Vision("google/gemini-3.7-flash", fails=LLMError("502 from the provider"))
    fallback = _Vision("x-ai/grok-4.5", payload=_INVOICE)

    first, second = _read_twice(primary, fallback)

    assert fallback.calls == 2
    assert first.model == second.model == "x-ai/grok-4.5"
    assert first.values["net_total_eur"] == 240.0


def test_a_document_says_which_model_read_it():
    primary = _Vision("google/gemini-3.7-flash", payload=_INVOICE)
    fallback = _Vision("x-ai/grok-4.5", payload=_INVOICE)

    first, _ = _read_twice(primary, fallback)

    assert first.model == "google/gemini-3.7-flash"
    assert fallback.calls == 0, "the fallback costs nothing while the primary answers"


def test_a_reply_in_the_wrong_shape_is_not_a_reason_to_pay_twice():
    """The configured model ignoring the schema is a configuration fault, not a bad day.

    Measured on `claude-opus-4.7`, which returns HTTP 200 and valid JSON under keys of
    its own invention. Falling back would hide that behind a doubled bill on every
    upload; `scripts/check_vision.py` is where it is meant to surface.
    """
    from services.documents.extract import ExtractionFailed

    primary = _Vision("anthropic/claude-opus-4.7",
                      payload={"dokumenttyp": "rechnung", "arbeitgeber": "Hoffmann"})
    fallback = _Vision("x-ai/grok-4.5", payload=_INVOICE)

    with pytest.raises(ExtractionFailed) as failed:
        _read_twice(primary, fallback)

    assert failed.value.code == "unexpected_shape"
    assert fallback.calls == 0


def test_both_providers_down_is_one_failure_the_user_can_act_on():
    from core.llm import LLMError

    from services.documents.extract import ExtractionFailed

    primary = _Vision("google/gemini-3.7-flash", fails=LLMError("502"))
    fallback = _Vision("x-ai/grok-4.5", fails=LLMError("503"))

    with pytest.raises(ExtractionFailed) as failed:
        _read_twice(primary, fallback)

    assert failed.value.code == "provider_unavailable"
    assert "type the values in" in failed.value.detail


def test_a_fallback_that_is_the_same_model_is_not_a_fallback():
    """Nothing is retried when the two settings name one model: the bill would double
    and the answer would be the same failure."""
    from core.llm import LLMError

    from services.documents.extract import ExtractionFailed

    primary = _Vision("google/gemini-3.7-flash", fails=LLMError("502"))
    fallback = _Vision("google/gemini-3.7-flash", payload=_INVOICE)

    with pytest.raises(ExtractionFailed):
        _read_twice(primary, fallback)
    assert fallback.calls == 0


# --- two passes -----------------------------------------------------------------

def test_the_same_reading_written_differently_is_the_same_reading():
    assert compare.same(1302, 1302.0)
    assert compare.same("Bürostuhl, schwarz", "bürostuhl schwarz")
    assert compare.same(None, None)
    assert compare.same([{"x": 1}], [{"x": 1.0}])


def test_a_different_number_is_never_smoothed_over():
    """The failure two passes exist to catch, and the reason for no percentage tolerance."""
    assert not compare.same(312.61, 46.25)
    assert not compare.same(1302.00, 1302.01)
    # One pass reading a field the other left empty is a disagreement, not a value to
    # be taken from the luckier pass.
    assert not compare.same(None, 5)

    disagreements = compare.compare(
        {"gross_total_eur": 312.61, "invoice_date": "2025-09-08"},
        {"gross_total_eur": 46.25, "invoice_date": "2025-09-08"},
    )
    assert [d.field for d in disagreements] == ["gross_total_eur"]
    assert "312.61" in str(disagreements[0])


def test_a_german_date_whose_day_is_twelve_or_under_is_read_as_a_german_date():
    """The inversion #11 measured, and the case #16 asks for by name.

    A period of `01.01. - 31.12.` cannot express it: the swap is invisible on the
    first and impossible on the second, because there is no thirteenth month. So the
    document that settles it has a day of 12 or under on both ends - `01.02.2025` is
    the first of February, and reading it as the second of January would turn eight
    months of employment into one.
    """
    assert mapping.parse_date("01.02.2025") == date(2025, 2, 1)
    assert mapping.parse_date("2025-02-01") == date(2025, 2, 1)
    assert mapping.parse_date("01.02.2025") != mapping.parse_date("2025-01-02")

    payslip = Payslip(
        document_type="lohnsteuerbescheinigung", tax_year=2025,
        employment_period_start="01.02.2025", employment_period_end="30.09.2025",
    )
    proposal = mapping.payslip_proposal(payslip, tax_year=2025,
                                        periods_from_other_documents=[])
    assert [(v.key, v.value) for v in proposal.values] == [("profile.employed_months", 8)]


def test_two_passes_that_invert_a_date_disagree_rather_than_agreeing():
    """And the gate that catches it when a model does invert one.

    The two readings below are the same page read twice, one of them with the day and
    the month swapped. Nothing downstream can tell which is right - only that they
    differ - so this has to come back as a disagreement, which proposes no value at
    all (`workflows/document_intake.py`).
    """
    assert not compare.same("2025-02-01", "2025-01-02")
    # Two formats are a disagreement too: the prompt asks for one, and on a day of 12
    # or under, deciding which format a pass meant is the guess two passes avoid.
    assert not compare.same("2025-02-01", "01.02.2025")

    disagreements = compare.compare(
        {"employment_period_start": "2025-02-01", "employment_period_end": "2025-09-30"},
        {"employment_period_start": "2025-01-02", "employment_period_end": "2025-09-30"},
    )
    assert [d.field for d in disagreements] == ["employment_period_start"]


def test_a_category_that_is_not_the_one_the_keys_belong_to_is_refused():
    """Both halves are valid on their own, which is why this check exists.

    `fortbildungskosten` is one of the four, `equipment.price_eur` is in the
    catalogue, and each passes its own validation. Together they are a document whose
    recorded category contradicts the values stored under it.
    """
    checked, problems = confirm.check(
        {"equipment.price_eur": 689.0}, proposed={}, document_id="d",
    )
    assert not problems

    assert confirm.category_problem(
        checked, recorded="fortbildungskosten", proposed=None,
    ) == "the category says fortbildungskosten but the values are arbeitsmittel ones"
    assert confirm.category_problem(
        checked, recorded="arbeitsmittel", proposed="arbeitsmittel",
    ) is None


def test_values_from_two_categories_cannot_be_confirmed_as_one_document():
    checked, _ = confirm.check(
        {"equipment.price_eur": 689.0, "education.amount_eur": 240.0},
        proposed={}, document_id="d",
    )
    problem = confirm.category_problem(checked, recorded="arbeitsmittel", proposed=None)
    assert problem is not None and "two categories" in problem


def test_a_payslip_confirms_without_a_category_and_never_with_one():
    """It yields the employment period and no expense, so it has none to record."""
    checked, _ = confirm.check(
        {"profile.employed_months": 8}, proposed={}, document_id="d",
    )
    assert confirm.category_problem(checked, recorded=None, proposed=None) is None
    assert confirm.category_problem(checked, recorded="arbeitsmittel", proposed=None)


def test_the_category_cannot_be_changed_by_saying_so_while_confirming():
    """Changing it is the category route's job, where the values are mapped again."""
    checked, _ = confirm.check(
        {"education.amount_eur": 240.0}, proposed={}, document_id="d",
    )
    problem = confirm.category_problem(
        checked, recorded="fortbildungskosten", proposed="umzugskosten",
    )
    assert problem is not None and "change the category" in problem


# --- onto Fact keys -------------------------------------------------------------

def test_several_payslips_add_up_to_the_months_they_cover():
    """Two half-year jobs are a year of employment, not half of one.

    The reason `documents.extracted` keeps the confirmed period per document: with
    only the latest document's period, a job change in July would overwrite January
    to June and claim six months of employment for a year that had twelve.
    """
    first = Payslip(document_type="lohnsteuerbescheinigung", tax_year=2025,
                    employment_period_start="2025-01-01", employment_period_end="2025-06-30")
    second = Payslip(document_type="lohnsteuerbescheinigung", tax_year=2025,
                     employment_period_start="2025-07-01", employment_period_end="2025-12-31")

    alone = mapping.payslip_proposal(first, tax_year=2025, periods_from_other_documents=[])
    assert alone.values[0].key == "profile.employed_months"
    assert alone.values[0].value == 6

    together = mapping.payslip_proposal(
        second, tax_year=2025,
        periods_from_other_documents=[(date(2025, 1, 1), date(2025, 6, 30))],
    )
    assert together.values[0].value == 12

    # And the same document twice is still six months, not twelve.
    twice = mapping.payslip_proposal(
        first, tax_year=2025,
        periods_from_other_documents=[(date(2025, 1, 1), date(2025, 6, 30))],
    )
    assert twice.values[0].value == 6


def test_a_payslip_for_another_year_is_refused_with_the_year_named():
    other = Payslip(document_type="lohnsteuerbescheinigung", tax_year=2024,
                    employment_period_start="2024-01-01", employment_period_end="2024-12-31")
    proposal = mapping.payslip_proposal(other, tax_year=2025, periods_from_other_documents=[])
    assert proposal.values == []
    assert "2024" in proposal.questions[0] and "2025" in proposal.questions[0]


def test_an_integer_quantity_becomes_separate_items():
    """Two monitor arms are two items, because the low-value threshold is per item."""
    invoice = Invoice(
        document_type="rechnung", price_basis="net", invoice_date="2025-09-08",
        net_total_eur=781.5,
        line_items=[
            InvoiceLine(description="Schreibtisch", quantity=1, unit_price_eur=689.0),
            InvoiceLine(description="Monitorarm", quantity=2, unit_price_eur=46.25),
        ],
    )
    proposal = mapping.invoice_proposal(invoice, category=ExpenseCategory.arbeitsmittel)
    values = {v.key: v.value for v in proposal.values}

    assert values["equipment.price_eur"] == 689.0
    assert values["equipment.price_eur#1"] == 46.25
    assert values["equipment.price_eur#2"] == 46.25
    assert values["equipment.purchase_month#2"] == 9
    assert proposal.questions == []


def test_a_second_invoice_adds_items_rather_than_replacing_them():
    invoice = Invoice(document_type="rechnung", price_basis="gross", invoice_date="2025-03-02",
                      gross_total_eur=99.0,
                      line_items=[InvoiceLine(description="Tastatur", quantity=1,
                                              unit_price_eur=99.0)])
    proposal = mapping.invoice_proposal(
        invoice, category=ExpenseCategory.arbeitsmittel, first_index=3,
    )
    assert {v.key for v in proposal.values} == {
        "equipment.price_eur#3", "equipment.price_is_net#3", "equipment.purchase_month#3",
    }
    assert next(v.value for v in proposal.values if v.key == "equipment.price_is_net#3") is False


def test_an_unreadable_price_basis_is_a_question_not_a_default():
    """The test invoice prices its lines net and adds 19% at the bottom.

    So "a receipt shows the gross price" - the assumption the interview may make when
    a human answers - is exactly wrong here, and a document may not make it.
    """
    invoice = Invoice(document_type="rechnung", price_basis="unknown",
                      invoice_date="2025-09-08", gross_total_eur=1302.0)
    proposal = mapping.invoice_proposal(invoice, category=ExpenseCategory.arbeitsmittel)
    assert any("net or gross" in q for q in proposal.questions)
    assert not any(v.key.startswith("equipment.price_is_net") for v in proposal.values)


def test_a_fractional_quantity_is_asked_about_never_rounded():
    invoice = Invoice(document_type="rechnung", price_basis="net", invoice_date="2025-09-08",
                      line_items=[InvoiceLine(description="Kabel", quantity=1.5,
                                              unit_price_eur=10.0)])
    proposal = mapping.invoice_proposal(invoice, category=ExpenseCategory.arbeitsmittel)
    assert proposal.values == []
    assert "1.5" in proposal.questions[0]


def test_a_non_repeating_category_takes_the_total_not_the_first_line():
    """A three-line seminar invoice claims itself, not a third of itself."""
    invoice = Invoice(
        document_type="rechnung", price_basis="gross", invoice_date="2025-05-04",
        gross_total_eur=1800.0,
        line_items=[
            InvoiceLine(description="Seminargebühr", quantity=1, unit_price_eur=1500.0),
            InvoiceLine(description="Prüfungsgebühr", quantity=1, unit_price_eur=300.0),
        ],
    )
    proposal = mapping.invoice_proposal(invoice, category=ExpenseCategory.fortbildungskosten)
    assert {v.key: v.value for v in proposal.values} == {"education.amount_eur": 1800.0}


# --- which category -------------------------------------------------------------

def test_the_rules_decide_what_a_word_decides():
    assert classify.by_rules(["Schreibtisch Ergoline", "Bürostuhl Aristo"]).category is (
        ExpenseCategory.arbeitsmittel
    )
    assert classify.by_rules(["Seminar Projektmanagement"]).category is (
        ExpenseCategory.fortbildungskosten
    )
    assert classify.by_rules(["Speditionsrechnung Umzug"]).category is (
        ExpenseCategory.umzugskosten
    )
    assert classify.by_rules(["Bewerbungsfotos"]).category is ExpenseCategory.bewerbungskosten
    assert classify.by_rules(["Schreibtisch", "Seminar"]).category is None, "a real tie"
    assert classify.by_rules(["Abendessen"]).category is None


def test_every_classification_says_why():
    for descriptions in (["Bürostuhl"], ["Abendessen"], ["Schreibtisch", "Seminar"]):
        assert classify.by_rules(descriptions).reason


def test_a_restaurant_line_under_fortbildung_is_questioned():
    """The check the ticket asks for by name."""
    descriptions = ["Seminar Rhetorik", "Abendessen Restaurant Adler"]
    decided = classify.by_rules(descriptions)
    checked = classify.checked(decided.category, descriptions, decided.reason,
                              by_rule=decided.by_rule)
    assert checked.category is ExpenseCategory.fortbildungskosten
    assert checked.contradiction and "restaurant" in checked.contradiction
    # And the same word under Arbeitsmittel is merely irrelevant, not a contradiction.
    assert classify.contradiction(ExpenseCategory.arbeitsmittel, descriptions) is None


def test_the_reading_record_names_the_model_that_answered_not_the_configured_one():
    """What a document read cost, in the shape the row stores (#39).

    The distinction matters the moment the primary vision model is unreachable: the
    fallback is a different model at a different price, and naming the configured one
    would put the cheaper number next to a call that did not make it.
    """
    from services.documents.extract import Read, reading_record

    first = Read(values={}, usage={"prompt_tokens": 1200, "completion_tokens": 80},
                 model="x-ai/grok-4.5")
    second = Read(values={}, usage={"prompt_tokens": 1180, "completion_tokens": 75},
                  model="x-ai/grok-4.5")

    record = reading_record(first, second, configured="google/gemini-3.7-flash")
    assert record["model"] == "x-ai/grok-4.5"
    # Both passes, because both were paid for.
    assert record["prompt_tokens"] == 2380
    assert record["completion_tokens"] == 155


def test_a_model_with_no_price_on_file_records_no_cost_rather_than_zero():
    """Zero would be a claim; None is the gap it actually is."""
    from services.documents.extract import Read, reading_record

    pass_one = Read(values={}, usage={"prompt_tokens": 10, "completion_tokens": 5},
                    model="some/unlisted-model")
    record = reading_record(pass_one, pass_one, configured="some/unlisted-model")
    assert record["cost_usd"] is None
