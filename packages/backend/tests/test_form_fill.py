"""The case as Anlage N: which figure goes where, and what the form cannot take.

Two halves, deliberately apart. `domain/form_fill.py` decides placement and is pure,
so it is tested against values; `services/anlage_n_pdf.py` draws, and is tested by
checking that a real PDF comes out with the figures actually in it. Neither test
knows a coordinate — those were measured into forms/anlage-n-2025-boxes.json and are
verified by looking at the rendered page, which no assertion can do for you.
"""

import json
from pathlib import Path

import pytest

from domain.estimate import expense_rows
from domain.form_fill import entries_for
from services.anlage_n_pdf import BLANKS, BOXES, BlankNotAvailable, fill, render

COMMUTER = {
    "profile.employed_months": 12, "profile.works_remotely": False,
    "commute.commuting_days": 210,
    "commute.distance_km": 42,
    "commute.own_car": True,
}

REMOTE = {
    "profile.employed_months": 12, "profile.works_remotely": True,
    "homeoffice.homeoffice_days": 120,
    "homeoffice.other_workplace_available": True,
}


def lines(entries) -> dict:
    return {e.line: e.value for e in entries}


# --- placement ---------------------------------------------------------------------

def test_the_commute_fills_the_days_the_total_and_the_means_of_transport():
    entries, _ = entries_for(COMMUTER, expense_rows(COMMUTER))
    placed = lines(entries)

    assert placed["29"] == 210        # days attended
    assert placed["30"] == 42         # total one-way distance
    assert placed["31"] == 42         # of which by own car
    assert "33" not in placed         # the other-means line stays empty


def test_without_a_car_the_distance_goes_in_the_other_means_line_instead():
    known = dict(COMMUTER, **{"commute.own_car": False})
    placed = lines(entries_for(known, expense_rows(known))[0])

    assert placed["33"] == 42
    assert "31" not in placed


def test_home_office_days_go_in_the_line_the_other_workplace_answer_decides():
    with_desk = lines(entries_for(REMOTE, expense_rows(REMOTE))[0])
    assert with_desk["58"] == 120 and "59" not in with_desk

    without = dict(REMOTE, **{"homeoffice.other_workplace_available": False})
    placed = lines(entries_for(without, expense_rows(without))[0])
    assert placed["59"] == 120 and "58" not in placed


def test_home_office_days_are_placed_in_neither_line_when_nobody_asked():
    """The two lines are exclusive and the answer decides which. Guessing is not an option.

    Today `estimate` will not compute the category without that answer, so no amount
    reaches this function either — the row below is handed in directly to exercise the
    guard rather than the arithmetic. It is kept because the failure it prevents is a
    figure landing in the wrong line of a tax return, and "the caller currently cannot
    do that" is a weaker guarantee than "and if it did, it would be reported".
    """
    known = {k: v for k, v in REMOTE.items()
             if k != "homeoffice.other_workplace_available"}
    row = [{"category": "homeoffice_tagespauschale", "amount_eur": 720.0,
            "form_line": "anlage_n 58-59", "trace": [], "document": None}]
    entries, unplaced = entries_for(known, row)

    assert "58" not in lines(entries) and "59" not in lines(entries)
    assert any("58 or 59" in u.where for u in unplaced)


def test_the_estimate_will_not_produce_a_home_office_amount_without_that_answer():
    """The first line of the same defence, upstream: no answer, no figure at all."""
    known = {k: v for k, v in REMOTE.items()
             if k != "homeoffice.other_workplace_available"}
    assert expense_rows(known) == []


def test_the_shared_sonstiges_rows_place_the_total_and_report_each_part():
    known = dict(COMMUTER, **{"applications.amount_eur": 60,
                              "applications.kind": "postage",
                              "profile.searched_for_job": True})
    entries, unplaced = entries_for(known, expense_rows(known))

    assert lines(entries)["64"] == 60
    assert [u.label for u in unplaced] == ["bewerbungskosten"]
    assert "description" in unplaced[0].where


def test_an_empty_case_places_nothing_rather_than_zeroes():
    """A blank line on a tax form means something. It must not be filled with 0."""
    entries, unplaced = entries_for({"profile.employed_months": 12}, [])
    assert entries == [] and unplaced == []


# --- how a value is written ----------------------------------------------------------

def test_a_whole_euro_box_is_written_without_its_cents():
    """The box prints its own `,–`; writing the cents again would read as ten times more."""
    assert render(1800.0, "eur") == "1.800"
    assert render(1234567.0, "eur") == "1.234.567"


def test_distances_and_days_are_rounded_not_truncated():
    assert render(41.6, "km") == "42"
    assert render(209.5, "integer") == "210"


# --- the drawn form -------------------------------------------------------------------

def test_the_measured_box_map_covers_every_line_the_mapping_can_produce():
    """The two files are maintained apart; this is what keeps them in step."""
    boxes = json.loads((BOXES / "anlage-n-2025-boxes.json").read_text())["boxes"]
    produced = set()
    for known in (COMMUTER, REMOTE,
                  dict(COMMUTER, **{"commute.own_car": False,
                                    "commute.public_transport_cost_eur": 310}),
                  dict(COMMUTER, **{"profile.further_education": True,
                                    "education.amount_eur": 1800,
                                    "education.kind": "course_fee"}),
                  dict(COMMUTER, **{"profile.searched_for_job": True,
                                    "applications.amount_eur": 60,
                                    "applications.kind": "postage"})):
        produced |= {e.line for e in entries_for(known, expense_rows(known))[0]}
    assert produced - set(boxes) == set(), f"no measured box for {produced - set(boxes)}"


@pytest.mark.skipif(not (BLANKS / "Anlage_N_2025.pdf").exists(),
                    reason="the official blank is not in KB/")
def test_the_figures_end_up_in_the_finished_pdf():
    known = dict(COMMUTER, **{"profile.further_education": True,
                              "education.amount_eur": 1800,
                              "education.kind": "course_fee"})
    entries, _ = entries_for(known, expense_rows(known))
    form = fill(entries, 2025, note="ENTWURF")

    assert form.pdf.startswith(b"%PDF")
    assert form.unplaced == []
    assert any("Zeile 29 = 210" in p for p in form.placed)
    assert any("Zeile 60 = 1.800" in p for p in form.placed)

    from pypdf import PdfReader
    import io as _io
    text = "".join(page.extract_text() for page in PdfReader(_io.BytesIO(form.pdf)).pages)
    assert "210" in text and "1.800" in text and "ENTWURF" in text


def test_a_tax_year_with_no_measured_blank_fails_loudly():
    with pytest.raises(BlankNotAvailable):
        fill([], 1999)


def test_the_export_contract_is_one_rule_and_not_three():
    """Draft, final, incomplete: which note the form carries, decided in one place.

    The architecture said no report exists before approval while the endpoint handed
    out watermarked drafts, and the warning about figures the blank could not take
    travelled in a response header a caller could ignore (#30).
    """
    import inspect

    from api.routes import cases as route

    source = inspect.getsource(route.get_anlage_n) if hasattr(route, "get_anlage_n") else \
        inspect.getsource(route)

    assert "INCOMPLETE_NOTE" in source, (
        "an export with unplaced figures no longer says so on the page"
    )
    # The banner is the default and approval is what removes it, never the other way.
    assert 'note=None if final else DRAFT_NOTE' in source
    assert 'kind = "final" if final and not left_out else "draft"' in source


def test_an_incomplete_sheet_is_never_named_final():
    """The filename is a claim too - it is what the file is called on a desktop."""
    import inspect

    from api.routes import cases as route

    source = inspect.getsource(route)
    assert '"final" if final and not left_out' in source
