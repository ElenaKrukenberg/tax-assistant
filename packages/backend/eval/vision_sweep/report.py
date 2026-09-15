"""Render the sweep's JSON as the Markdown table that goes into the research note.

Kept separate from `sweep.py` so the table can be regenerated, or its ordering
argued with, without paying for the calls again.

    ./venv/bin/python eval/vision_sweep/report.py
"""

import argparse
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "results"
DOCS = ["lohnsteuerbescheinigung.jpg", "rechnung-foto.jpg", "payslip-degraded.jpg"]
HEADS = ["Clean A4", "Phone photo", "Degraded scan"]


def cell(grade: dict) -> str:
    if grade["unusable"]:
        return "**no answer**"
    if grade.get("schema_ignored"):
        return "**schema ignored**"
    if grade["wrong"] == 0:
        return "**0**"
    silent = grade["silent"]
    return f"{grade['wrong']} / {silent} silent" if silent else f"{grade['wrong']} / 0"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="vision-sweep.json")
    args = ap.parse_args()

    d = json.loads((RESULTS / args.file).read_text())
    rows = []
    for m, e in d["models"].items():
        grades = [e["documents"][dn]["grade"] for dn in DOCS]
        unusable = any(g["unusable"] for g in grades)
        ignored = any(g.get("schema_ignored") for g in grades)
        gradeable = [g for g in grades if not g["unusable"] and not g.get("schema_ignored")]
        wrong = sum(g["wrong"] or 0 for g in gradeable)
        silent = sum(g["silent"] or 0 for g in gradeable)
        per_doc = e["cost"] / (len(DOCS) * d["runs_per_document"]) * 100
        rows.append((m, grades, unusable or ignored, wrong, silent, per_doc))

    # Silent errors first, then total wrong, then price: the order the recommendation
    # is argued in. A model that cannot answer at all sorts last.
    rows.sort(key=lambda r: (r[2], r[4], r[3], r[5]))

    print(f"| Model string | {' | '.join(HEADS)} | Total silent | Cost per pass |")
    print("|---|" + "---|" * (len(HEADS) + 2))
    for m, grades, unusable, wrong, silent, per_doc in rows:
        cells = " | ".join(cell(g) for g in grades)
        s = "–" if unusable else ("**0**" if silent == 0 else f"**{silent}**")
        cost = "–" if unusable else f"{per_doc:.3f} c"
        print(f"| `{m}` | {cells} | {s} | {cost} |")
    print(f"\nBilled in total: ${d['total_cost']:.4f}"
          + (f", reasoning effort `{d['reasoning_effort']}`" if d.get("reasoning_effort") else ""))


if __name__ == "__main__":
    main()
