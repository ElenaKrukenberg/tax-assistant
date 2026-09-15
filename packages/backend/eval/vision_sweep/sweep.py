"""Measure how accurately each reachable vision model reads the three test documents.

Method held fixed from issue #11 so the two tables mean the same thing: one German
instruction, one strict `response_format` JSON schema, 3 runs per document per model,
and `usage.cost` as billed by OpenRouter rather than a computed estimate. Every call
sends `provider={"zdr": True}` — the policy decided in issue #15 — so the sweep
measures under the conditions the product will run in.

Grading, also from #11:

  wrong   a field whose value differs from ground truth
  caught  a wrong field that either disagreed between the 3 runs or came back null,
          i.e. one a two-pass configuration would notice. A wrong field that is
          identical across all 3 runs and non-null is **silent**, which is the
          failure mode that matters.

    ./venv/bin/python eval/vision_sweep/sweep.py --estimate     # priced dry run, no calls
    ./venv/bin/python eval/vision_sweep/sweep.py --max-spend 3  # measure, with a guard
    ./venv/bin/python eval/vision_sweep/sweep.py --models a,b   # a subset
"""

import argparse
import asyncio
import base64
import json
import math
import os
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parents[1]
DOCS = HERE / "documents"
RESULTS = BACKEND_ROOT / "eval" / "results"
BASE_URL = "https://openrouter.ai/api/v1"

RUNS_PER_DOCUMENT = 3

# One instruction for all three documents, in German, ~200 tokens as in #11. It names
# no field values and gives no examples, so it cannot leak ground truth into the answer.
PROMPT = """Du liest ein deutsches Steuerdokument (Lohnsteuerbescheinigung, Rechnung
oder Gehaltsabrechnung) und überträgst seinen Inhalt in das vorgegebene JSON-Schema.

Regeln:
- Übertrage ausschließlich, was im Dokument steht. Rechne nichts um und schätze nichts.
- Beträge als Zahl in Euro, Punkt als Dezimaltrennzeichen: aus "41.238,76" wird 41238.76.
- Datumsangaben im Format JJJJ-MM-TT.
- Felder, die im Dokument nicht vorkommen oder nicht lesbar sind, setze auf null.
- Ordne jeden Betrag der Zeile zu, in der er steht. Verschiebe keinen Betrag in eine
  Nachbarzeile, auch wenn das Dokument schief oder unscharf ist.
- Gib für jedes ausgefüllte Feld in "confidence" an, wie sicher du dir bist.

Antworte nur mit dem JSON-Objekt."""

MONEY = {"type": ["number", "null"]}
DATE = {"type": ["string", "null"]}
TEXT = {"type": ["string", "null"]}

# One schema per document type, not one union over both. Two provider limits force it,
# and both are findings in their own right:
#
#   * `claude-haiku-4.5` served by Amazon Bedrock rejects a **nullable enum** outright —
#     HTTP 400 "Enum value 'lohnsteuerbescheinigung' does not match declared type
#     '['string', 'null']'". Hence `document_type` and `confidence` are plain
#     non-nullable enums with an explicit "unbekannt" member instead of null.
#   * The same provider caps **union-typed parameters at 16** — "Schemas contains too
#     many parameters with union types (24 parameters …). This causes exponential
#     compilation cost." A union schema over payslip and invoice has 24 and is
#     unservable; split, the payslip has 15 and the invoice 12.
#
# The split is also what the product will do: it knows the document type before it asks.
CONFIDENCE = {"type": "string", "enum": ["high", "medium", "low"]}

PAYSLIP_PROPERTIES = {
    "document_type": {
        "type": "string",
        "enum": ["lohnsteuerbescheinigung", "gehaltsabrechnung", "unbekannt"],
    },
    "tax_year": {"type": ["integer", "null"]},
    "employer_name": TEXT,
    "employee_name": TEXT,
    "employment_period_start": DATE,
    "employment_period_end": DATE,
    "tax_class": {"type": ["integer", "null"]},
    "etin": TEXT,
    "gross_salary_eur": MONEY,
    "income_tax_eur": MONEY,
    "solidarity_surcharge_eur": MONEY,
    "church_tax_eur": MONEY,
    "pension_insurance_employee_eur": MONEY,
    "health_insurance_employee_eur": MONEY,
    "care_insurance_employee_eur": MONEY,
    "unemployment_insurance_eur": MONEY,
    "confidence": CONFIDENCE,
}

INVOICE_PROPERTIES = {
    "document_type": {"type": "string", "enum": ["rechnung", "unbekannt"]},
    "invoice_number": TEXT,
    "invoice_date": DATE,
    "supplier_name": TEXT,
    "customer_name": TEXT,
    "net_total_eur": MONEY,
    "vat_rate_percent": MONEY,
    "vat_amount_eur": MONEY,
    "gross_total_eur": MONEY,
    "line_items": {
        "type": ["array", "null"],
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["description", "quantity", "unit_price_eur"],
            "properties": {
                "description": TEXT,
                "quantity": {"type": ["number", "null"]},
                "unit_price_eur": MONEY,
            },
        },
    },
    "confidence": CONFIDENCE,
}


def schema(name: str, properties: dict) -> dict:
    return {
        "name": name,
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": properties,
        },
    }


PAYSLIP_SCHEMA = schema("lohnsteuerbescheinigung", PAYSLIP_PROPERTIES)
INVOICE_SCHEMA = schema("rechnung", INVOICE_PROPERTIES)

SCHEMAS = {
    "lohnsteuerbescheinigung.jpg": PAYSLIP_SCHEMA,
    "payslip-degraded.jpg": PAYSLIP_SCHEMA,
    # The part-year payslip, whose only reason to exist is a date a day/month swap
    # would visibly ruin: 01.02.2025 - 30.09.2025 (make_documents.py says why).
    "payslip-part-year.jpg": PAYSLIP_SCHEMA,
    "rechnung-foto.jpg": INVOICE_SCHEMA,
}

# Graded fields, per document. `confidence` is not graded — #11 established it does not
# track correctness — and `line_items` is graded as a whole below.
PAYSLIP_FIELDS = [f for f in PAYSLIP_PROPERTIES if f != "confidence"]
INVOICE_FIELDS = [f for f in INVOICE_PROPERTIES if f != "confidence"]
GRADED = {
    "lohnsteuerbescheinigung.jpg": PAYSLIP_FIELDS,
    "payslip-degraded.jpg": PAYSLIP_FIELDS,
    "payslip-part-year.jpg": PAYSLIP_FIELDS,
    "rechnung-foto.jpg": INVOICE_FIELDS,
}


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    for line in (BACKEND_ROOT / ".env").read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("no OPENROUTER_API_KEY in the environment or packages/backend/.env")


def data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def normalise(field: str, value):
    """Compare like with like: money to 2 dp, text case- and whitespace-insensitive."""
    if value is None:
        return None
    if field == "line_items":
        if not isinstance(value, list):
            return None
        return sorted(
            (
                (str(i.get("description", "")).strip().lower(),
                 round(float(i["quantity"]), 2) if i.get("quantity") is not None else None,
                 round(float(i["unit_price_eur"]), 2) if i.get("unit_price_eur") is not None else None)
                for i in value if isinstance(i, dict)
            )
        )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 2)
    return str(value).strip().lower()


def truth_for(field: str, truth: dict):
    return normalise(field, truth.get(field))


async def one_call(client, key, model, doc_path, sem, effort: str | None = None):
    body = {
        "model": model,
        "provider": {"zdr": True},
        "max_tokens": 4000,
        "temperature": 0,
        **({"reasoning": {"effort": effort}} if effort else {}),
        "response_format": {"type": "json_schema", "json_schema": SCHEMAS[doc_path.name]},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url(doc_path)}},
                ],
            }
        ],
    }
    async with sem:
        for attempt in range(3):
            try:
                r = await client.post(
                    f"{BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                    timeout=180.0,
                )
            except Exception as exc:
                if attempt == 2:
                    return {"error": repr(exc), "cost": 0.0}
                await asyncio.sleep(3 * (attempt + 1))
                continue
            # 429 and a bare provider 500 are transient; a 400 or 404 is a verdict.
            if r.status_code in (429, 500, 502, 503) and attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
                continue
            # An upstream fault can arrive as HTTP 200 with an `error` object and no
            # choices. That is infrastructure, not a verdict on the model, so retry it
            # — otherwise the model is recorded as answering nothing.
            if attempt < 2:
                try:
                    body_json = r.json()
                except Exception:
                    body_json = {}
                if r.status_code == 200 and body_json.get("error") and not body_json.get("choices"):
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
            break
    try:
        payload = r.json()
    except Exception:
        return {"error": r.text[:300], "cost": 0.0}
    usage = payload.get("usage") or {}
    out = {
        "status": r.status_code,
        "cost": usage.get("cost") or 0.0,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    }
    if r.status_code == 200 and payload.get("error") and not payload.get("choices"):
        err = payload["error"]
        return {"status": 200, "cost": 0.0,
                "error": f"upstream {err.get('code')}: {str(err.get('message'))[:300]}"}
    if r.status_code != 200:
        err = payload.get("error") or {}
        raw = ((err.get("metadata") or {}).get("raw") or "")
        out["error"] = ((err.get("message") or r.text) + (f" | {raw}" if raw else ""))[:500]
        return out
    content = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    out["raw"] = content[:4000]
    try:
        out["parsed"] = json.loads(content)
    except Exception:
        # The failure mode #11 warned about: HTTP 200, prose where a typed object
        # was requested. Try to rescue a fenced object before calling it unparsed.
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            try:
                out["parsed"] = json.loads(content[start:end + 1])
                out["repaired"] = True
            except Exception:
                out["parse_error"] = True
        else:
            out["parse_error"] = True
    return out


def grade(doc: str, truth: dict, runs: list[dict]) -> dict:
    """Per-document verdict over the 3 runs: wrong fields, and how many were caught."""
    # A run that produced no object at all is a failure of the whole document, not of
    # individual fields — reported separately so it cannot read as accuracy.
    parsed = [r["parsed"] for r in runs if isinstance(r.get("parsed"), dict)]
    if not parsed:
        return {"unusable": True, "schema_ignored": False, "runs_parsed": 0,
                "wrong": None, "caught": None, "silent": None}

    # A model that answered with keys of its own invention has not got the fields
    # wrong — it never filled them in. Grading it field by field would score it as
    # "every field wrong but every one caught", which reads as a cautious model
    # rather than an unusable one. It is its own verdict.
    required = set(SCHEMAS[doc]["schema"]["required"])
    if all(len(required & set(p)) < len(required) / 2 for p in parsed):
        return {"unusable": False, "schema_ignored": True, "runs_parsed": len(parsed),
                "wrong": None, "caught": None, "silent": None,
                "keys_returned": sorted(parsed[0])[:12]}

    wrong, caught, detail = 0, 0, {}
    for field in GRADED[doc]:
        expected = truth_for(field, truth)
        seen = [normalise(field, p.get(field)) for p in parsed]
        if all(s == expected for s in seen):
            continue
        wrong += 1
        disagreed = len({json.dumps(s, sort_keys=True, default=str) for s in seen}) > 1
        any_null = any(s is None for s in seen)
        if disagreed or any_null:
            caught += 1
        detail[field] = {
            "expected": expected,
            "seen": seen,
            "caught": bool(disagreed or any_null),
        }
    return {
        "unusable": False,
        "schema_ignored": False,
        "runs_parsed": len(parsed),
        "wrong": wrong,
        "caught": caught,
        "silent": wrong - caught,
        "fields": len(GRADED[doc]),
        "detail": detail,
    }


def estimate(models_meta: dict, models: list[str], docs: list[Path]) -> float:
    """Priced dry run from the published per-token prices, image tokens included.

    Deliberately crude — #11 could not reproduce OpenAI's image-token multiplier from
    measured bills, so this is a spend guard, not a result. `usage.cost` is what the
    table reports.
    """
    total = 0.0
    for m in models:
        p = (models_meta.get(m) or {}).get("pricing") or {}
        pin = float(p.get("prompt") or 0)
        pout = float(p.get("completion") or 0)
        for d in docs:
            from PIL import Image
            with Image.open(d) as im:
                w, h = im.size
            # The most expensive of the three vendor formulas, so the guard errs high.
            img_tokens = max(
                math.ceil(w / 28) * math.ceil(h / 28),        # Anthropic patches
                math.ceil(w / 32) * math.ceil(h / 32) * 1.62,  # OpenAI patches, worst multiplier
            )
            total += RUNS_PER_DOCUMENT * ((img_tokens + 400) * pin + 900 * pout)
    return total


def regrade(path: Path) -> None:
    """Re-apply grading to a finished run, from the raw answers it kept. No calls.

    Grading has been wrong before — the first pass scored a model that ignored the
    schema as "every field wrong" — so the raw answers are stored precisely to make
    a rescore free.
    """
    d = json.loads(path.read_text())
    truth = json.loads((DOCS / "ground-truth.json").read_text(encoding="utf-8"))
    for entry in d["models"].values():
        for dn, cell in entry["documents"].items():
            runs = []
            for raw in cell.get("raw") or []:
                run = {"raw": raw}
                if raw:
                    try:
                        run["parsed"] = json.loads(raw)
                    except Exception:
                        start, end = raw.find("{"), raw.rfind("}")
                        if start >= 0 and end > start:
                            try:
                                run["parsed"] = json.loads(raw[start:end + 1])
                            except Exception:
                                pass
                runs.append(run)
            cell["grade"] = grade(dn, truth[dn], runs)
    path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"regraded {path.name}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--estimate", action="store_true", help="price the sweep, call nothing")
    ap.add_argument("--models", help="comma-separated subset")
    ap.add_argument("--max-spend", type=float, default=4.0, help="abort above this, in USD")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default="vision-sweep.json")
    ap.add_argument("--regrade", action="store_true",
                    help="rescore an existing result file from its stored answers")
    ap.add_argument(
        "--reasoning-effort",
        help="send reasoning.effort — #11 found 'low' halves the Gemini 3.7 bill",
    )
    args = ap.parse_args()

    if args.regrade:
        regrade(RESULTS / args.out)
        return

    reachable_file = HERE / "reachable-zdr.json"
    if not reachable_file.exists():
        raise SystemExit("run probe.py first — reachable-zdr.json is missing")
    models = json.loads(reachable_file.read_text())["reachable"]
    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]

    docs = sorted(DOCS.glob("*.jpg"))
    truth = json.loads((DOCS / "ground-truth.json").read_text(encoding="utf-8"))
    key = api_key()

    async with httpx.AsyncClient() as client:
        meta = {m["id"]: m for m in (await client.get(f"{BASE_URL}/models")).json()["data"]}
        priced = estimate(meta, models, docs)
        calls = len(models) * len(docs) * RUNS_PER_DOCUMENT
        print(f"{len(models)} models x {len(docs)} documents x {RUNS_PER_DOCUMENT} runs "
              f"= {calls} calls, priced high at ${priced:.2f}")
        if args.estimate:
            for m in sorted(models, key=lambda m: -estimate(meta, [m], docs)):
                print(f"  ${estimate(meta, [m], docs):7.4f}  {m}")
            return
        if priced > args.max_spend:
            raise SystemExit(
                f"priced at ${priced:.2f}, above --max-spend ${args.max_spend:.2f}; "
                "raise the guard deliberately or cut the model list"
            )

        sem = asyncio.Semaphore(args.concurrency)
        jobs = [
            (m, d.name, i)
            for m in models for d in docs for i in range(RUNS_PER_DOCUMENT)
        ]
        raw = await asyncio.gather(
            *(one_call(client, key, m, DOCS / dn, sem, args.reasoning_effort)
              for m, dn, _ in jobs)
        )

    calls_by_cell: dict[tuple[str, str], list[dict]] = {}
    for (m, dn, _), res in zip(jobs, raw):
        calls_by_cell.setdefault((m, dn), []).append(res)

    report = {"prompt": PROMPT, "schemas": SCHEMAS,
              "reasoning_effort": args.reasoning_effort, "runs_per_document": RUNS_PER_DOCUMENT,
              "models": {}}
    spent = 0.0
    for m in models:
        entry = {"documents": {}, "cost": 0.0}
        for d in docs:
            runs = calls_by_cell.get((m, d.name), [])
            cell_cost = sum(r.get("cost") or 0.0 for r in runs)
            spent += cell_cost
            entry["cost"] += cell_cost
            errors = [r["error"] for r in runs if r.get("error")]
            entry["documents"][d.name] = {
                "cost_total": cell_cost,
                "cost_per_call": cell_cost / len(runs) if runs else None,
                "prompt_tokens": [r.get("prompt_tokens") for r in runs],
                "completion_tokens": [r.get("completion_tokens") for r in runs],
                "errors": errors,
                "repaired": sum(1 for r in runs if r.get("repaired")),
                "parse_errors": sum(1 for r in runs if r.get("parse_error")),
                "grade": grade(d.name, truth[d.name], runs),
                "raw": [r.get("raw") for r in runs],
            }
        report["models"][m] = entry

    report["total_cost"] = spent
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / args.out
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nbilled ${spent:.4f}  ->  {out}")

    print(f"\n{'model':32s} {'clean w/c':>10s} {'photo w/c':>10s} {'degraded w/c':>13s} {'c/doc':>8s}")
    for m in sorted(report["models"], key=lambda m: report["models"][m]["cost"]):
        e = report["models"][m]
        cells = []
        for dn in ("lohnsteuerbescheinigung.jpg", "rechnung-foto.jpg", "payslip-degraded.jpg"):
            g = e["documents"][dn]["grade"]
            if g["unusable"]:
                cells.append("unusable")
            elif g["schema_ignored"]:
                cells.append("no schema")
            else:
                cells.append(f"{g['wrong']}/{g['caught']}")
        per_doc = e["cost"] / (len(docs) * RUNS_PER_DOCUMENT) * 100
        print(f"{m:32s} {cells[0]:>10s} {cells[1]:>10s} {cells[2]:>13s} {per_doc:7.3f}c")


if __name__ == "__main__":
    asyncio.run(main())
