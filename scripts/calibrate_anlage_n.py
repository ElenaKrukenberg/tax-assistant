"""Measure the value boxes of the official Anlage N once, into a JSON map.

The blank is not a fillable form — zero AcroForm fields — so a figure is placed by
drawing it at a coordinate. Guessing those coordinates by hand would be unreviewable
and would rot the first time the Finanzamt reflows a page, so they are measured from
the blank itself and written down.

Measured, not hardcoded, and measured *offline*: the backend then needs neither a PDF
parser nor the pdfminer stack behind it, and the map is a small file a person can read
and a diff can show. Re-run it when a new tax year's blank arrives:

    python scripts/calibrate_anlage_n.py KB/Anlage_N_2025.pdf 2025

How a row is found. Every line of the form prints its Zeile number in the left
margin, and every value on it sits inside a drawn rectangle. So the row is located by
its Zeile number and the box by the rectangle whose vertical span contains that row —
both of them things the document actually draws. Nothing is a pixel offset somebody
measured on screen.

The unit marker beside the box (`km`, `EUR`, the `,–` of a whole-euro field) is read
too, but only to record what kind of value belongs there. A whole-euro box already
prints its own decimal part, so writing "1.234" into it is right and "1.234,00" is
not — the renderer has to know which.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# The lines this product can fill. Everything else on the form is somebody else's
# figure — the employer's, the Hauptvordruck's — and is deliberately left blank.
WANTED = {
    1: ["29", "30", "31", "33", "34"],
    2: ["56", "58", "59", "60"],
    3: ["64"],
}

UNITS = {"km": "km", "EUR": "eur", ",–": "eur", ",": "eur"}


def measure(pdf_path: Path) -> dict:
    import pdfplumber  # dev-only dependency, deliberately not in requirements.txt

    boxes: dict[str, dict] = {}
    missing: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, lines in WANTED.items():
            page = pdf.pages[page_index]
            words = page.extract_words()
            for line in lines:
                marker = next((w for w in words
                               if w["text"] == line and w["x0"] < 60), None)
                if marker is None:
                    missing.append(f"Zeile {line}: no margin number on page {page_index}")
                    continue
                middle = (marker["top"] + marker["bottom"]) / 2
                # The value box: a drawn rectangle on the right half of the page whose
                # vertical span covers this row. Height filters out the hairlines the
                # form uses for rules and the comb separators inside a box.
                candidates = [r for r in page.rects
                              if r["x0"] >= 400 and (r["bottom"] - r["top"]) >= 8
                              and r["top"] - 6 <= middle <= r["bottom"] + 6]
                if not candidates:
                    missing.append(f"Zeile {line}: no value box on page {page_index}")
                    continue
                # Nearest by centre, so Zeile 29 does not adopt the box belonging to 30.
                box = min(candidates,
                          key=lambda r: abs((r["top"] + r["bottom"]) / 2 - middle))

                lo, hi = marker["top"] - 14, marker["bottom"] + 8
                row = [w for w in words if lo <= w["top"] <= hi]
                unit = next((w for w in row if w["text"] in UNITS
                             and w["x0"] >= box["x1"] - 2), None)

                boxes[line] = {
                    "page": page_index,
                    "kind": UNITS[unit["text"]] if unit else "integer",
                    # Reportlab draws from the bottom-left; pdfplumber measures from
                    # the top. Convert once, here, so the renderer never has to.
                    "baseline_y": round(page.height - box["bottom"] + 4.5, 1),
                    "right_x": round(box["x1"] - 4, 1),
                    "left_x": round(box["x0"] + 3, 1),
                }
    return {"boxes": boxes, "missing": missing}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    pdf_path, year = Path(argv[0]), argv[1]
    if not pdf_path.exists():
        print(f"no such file: {pdf_path}")
        return 1

    result = measure(pdf_path)
    for problem in result["missing"]:
        print(f"  ! {problem}")

    out = (Path(__file__).resolve().parents[1] / "packages" / "backend" / "forms"
           / f"anlage-n-{year}-boxes.json")
    out.write_text(json.dumps({
        "tax_year": int(year),
        "source_pdf": pdf_path.name,
        "boxes": result["boxes"],
    }, indent=2) + "\n")
    print(f"{len(result['boxes'])} boxes measured -> {out}")
    return 1 if result["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
