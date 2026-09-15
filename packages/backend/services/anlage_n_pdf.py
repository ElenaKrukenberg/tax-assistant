"""Draw a case's figures onto the official Anlage N blank.

The blank the Finanzamt publishes has no form fields at all — it is a printed page,
not an AcroForm — so a figure is placed by drawing it at a coordinate. The
coordinates are not written here: they were measured from the blank itself by
`scripts/calibrate_anlage_n.py`, which reads the rectangle the form draws around each
value, and they live in `forms/anlage-n-<year>-boxes.json`. Measuring offline is what
keeps a PDF parser out of the backend; all this module needs is a canvas and a merge.

What it will not do:

- **Invent a figure.** Only what `domain/form_fill.py` produced is drawn. A line the
  case has no value for stays empty, which on a tax form means something.
- **Silently drop one.** A value whose box is not in the map comes back in
  `unplaced`, and the caller has to show it. A form that quietly lost an amount is
  worse than no form.
- **Claim to be filed.** The result is a draft the user checks and files themselves;
  the report says so, and so does the stamp in the margin of page one.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from domain.form_fill import FormEntry

BLANKS = Path(__file__).resolve().parents[3] / "KB"
BOXES = Path(__file__).resolve().parents[1] / "forms"

# Small enough to sit inside the form's own boxes, large enough to read on paper.
FONT = "Helvetica"
FONT_SIZE = 9.5


class BlankNotAvailable(FileNotFoundError):
    """The official blank or its measured box map is missing for this tax year."""


@dataclass(frozen=True)
class FilledForm:
    pdf: bytes
    placed: list[str]      # "Zeile 29 = 120"
    unplaced: list[str]    # a value the box map has no box for


def _boxes(tax_year: int) -> dict:
    path = BOXES / f"anlage-n-{tax_year}-boxes.json"
    if not path.exists():
        raise BlankNotAvailable(
            f"no measured box map for {tax_year}; run scripts/calibrate_anlage_n.py")
    return json.loads(path.read_text())["boxes"]


def _blank(tax_year: int) -> Path:
    path = BLANKS / f"Anlage_N_{tax_year}.pdf"
    if not path.exists():
        raise BlankNotAvailable(f"no official blank for {tax_year} at {path}")
    return path


def render(value: float, kind: str) -> str:
    """The value as the box wants it written.

    A whole-euro box prints its own `,–`, so the cents must not be written again; a
    German form separates thousands with a dot. Days and kilometres are whole numbers
    on this form and are rounded rather than truncated — truncating a distance would
    quietly shrink the deduction.
    """
    if kind == "eur":
        return f"{round(value):,}".replace(",", ".")
    return str(int(round(value)))


def fill(entries: list[FormEntry], tax_year: int,
         note: Optional[str] = None) -> FilledForm:
    """Stamp the entries onto the blank and return the finished PDF."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    boxes = _boxes(tax_year)
    # Cloned into the writer before anything is merged onto it: pypdf deprecated
    # merging into a page that no writer owns, and the replacement is to own it first.
    writer = PdfWriter(clone_from=str(_blank(tax_year)))

    by_page: dict[int, list[tuple[dict, FormEntry]]] = {}
    placed, unplaced = [], []
    for entry in entries:
        box = boxes.get(entry.line)
        if box is None:
            unplaced.append(f"{entry.label}: Zeile {entry.line} is not in the box map")
            continue
        by_page.setdefault(int(box["page"]), []).append((box, entry))
        placed.append(f"Zeile {entry.line} = {render(entry.value, box['kind'])}"
                      f" ({entry.label})")

    for index, page in enumerate(writer.pages):
        drawn = by_page.get(index)
        if drawn or (index == 0 and note):
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            buffer = io.BytesIO()
            pen = canvas.Canvas(buffer, pagesize=(width, height))
            pen.setFont(FONT, FONT_SIZE)
            for box, entry in drawn or ():
                # Right-aligned: German value boxes fill from the right, and a
                # left-aligned number in a comb box reads as a different number.
                pen.drawRightString(float(box["right_x"]), float(box["baseline_y"]),
                                    render(entry.value, box["kind"]))
            if index == 0 and note:
                pen.setFont(FONT, 7)
                pen.drawString(28, 20, note)
            pen.save()
            buffer.seek(0)
            page.merge_page(PdfReader(buffer).pages[0])

    out = io.BytesIO()
    writer.write(out)
    return FilledForm(pdf=out.getvalue(), placed=placed, unplaced=unplaced)
