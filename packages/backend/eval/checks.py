"""Pass two: the checks that need no judge.

Deliberately first and deliberately separate from RAGAS. These are free, instant and
unambiguous — a tool either ran or it did not — so they catch the regressions that
matter most (a blocked question that spent tokens, a calculation answered by prose,
an answer with no citation) without waiting on a judge model or a heavier dependency
tree. RAGAS grades the prose; this grades the plumbing.

    ./venv/bin/python eval/checks.py                    # scores results/answers-hybrid.json
    ./venv/bin/python eval/checks.py --label semantic   # the ablation run
    ./venv/bin/python eval/checks.py --compare hybrid semantic
    ./venv/bin/python eval/checks.py --compare hybrid semantic --out compare-k.md
"""

import argparse
import json
import re
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
RESULTS = EVAL_DIR / "results"

CITATION_RE = re.compile(r"\[([a-z0-9][a-z0-9\-]+)\]")
CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")
GERMAN_RE = re.compile(r"\b(der|die|das|und|ist|kann|Sie|für|nicht)\b")


def language_of(text: str) -> str:
    """Crude enough for a check that only has to tell four languages apart."""
    if CYRILLIC_RE.search(text):
        return "ru"
    if GERMAN_RE.search(text):
        return "de"
    return "en"


def check_case(case: dict) -> dict:
    """Every check returns True (passed), False (failed) or None (not applicable)."""
    if "error" in case:
        return {"pipeline_error": False}

    expect = case.get("expect", {})
    answer = case.get("answer", "")
    retrieved_ids = {c["source_id"] for c in case.get("retrieved", [])}
    reference_ids = set(case.get("reference_context_ids", []))
    results: dict[str, bool | None] = {}

    # intent: a list means any of them is acceptable — "insufficient data" can
    # legitimately come back as a clarification or as a general answer
    wanted = expect.get("intent")
    if wanted is not None:
        allowed = wanted if isinstance(wanted, list) else [wanted]
        results["intent"] = case.get("intent") in allowed

    # citation_present: an inline tag that names a source actually retrieved. A tag
    # for something that was not retrieved is worse than no tag at all.
    if "citation" in expect:
        cited = {sid for sid in CITATION_RE.findall(answer) if sid in retrieved_ids}
        results["citation_present"] = bool(cited) if expect["citation"] else not cited

    # context_hit: did retrieval surface at least one document the answer could rest on?
    if reference_ids:
        results["context_hit"] = bool(reference_ids & retrieved_ids)

    # primary_context_hit: did it surface *the* authoritative one? context_hit is an OR
    # over acceptable documents, which turned out to be too coarse for the ablation: for
    # "Sind Gewerkschaftsbeiträge absetzbar?" semantic-only retrieved the Anleitung and
    # missed § 9 Werbungskosten entirely, while the hybrid retrieved § 9 — and context_hit
    # scored both as passes because the Anleitung is on the acceptable list. Declared only
    # where one document is unambiguously the authority; None elsewhere.
    primary = case.get("primary_context_id")
    if primary:
        results["primary_context_hit"] = primary in retrieved_ids

    if "tool" in expect:
        results["expected_tool_called"] = expect["tool"] in case.get("tools_called", [])
    if "forbidden_tool" in expect:
        results["forbidden_tool_not_called"] = expect["forbidden_tool"] not in case.get("tools_called", [])

    # a refusal that still paid for an LLM call is a guard that did not guard
    if "llm_calls" in expect:
        results["llm_calls"] = case.get("usage", {}).get("llm_calls") == expect["llm_calls"]

    if "answer_lang" in expect:
        results["answer_language"] = language_of(answer) == expect["answer_lang"]

    return results


def load_expectations() -> dict[str, dict]:
    """Expectations come from golden.jsonl, not from the recorded run.

    A recorded answer costs money; an expectation is a judgement, and judgements get
    revised — a reference document turns out to be one sub-part of an annex when three
    are equally correct, an intent label turns out to be advisory. Reading the golden
    set here means those corrections are free instead of another paid run.
    """
    golden = EVAL_DIR / "golden.jsonl"
    cases = [json.loads(line) for line in golden.read_text().splitlines() if line.strip()]
    return {c["id"]: c for c in cases}


def score(path: Path) -> dict:
    data = json.loads(path.read_text())
    expectations = load_expectations()
    rows = []
    for case in data["cases"]:
        current = expectations.get(case["id"])
        if current:
            case = {**case,
                    "expect": current.get("expect", {}),
                    "reference_context_ids": current.get("reference_context_ids", []),
                    "primary_context_id": current.get("primary_context_id")}
        checks = check_case(case)
        failed = [name for name, ok in checks.items() if ok is False]
        rows.append({"id": case["id"], "category": case["category"],
                     "checks": checks, "failed": failed,
                     "passed": not failed})
    return {**{k: v for k, v in data.items() if k != "cases"}, "rows": rows}


def markdown(report: dict) -> str:
    rows = report["rows"]
    passed = sum(1 for r in rows if r["passed"])
    total_checks = sum(len(r["checks"]) for r in rows)
    failed_checks = sum(len(r["failed"]) for r in rows)

    lines = [
        f"# Deterministic checks — `{report['label']}`",
        "",
        f"- retrieval: `{'+'.join(report['strategies'])}`",
        f"- model: `{report['model']}`",
        f"- cases: **{passed}/{len(rows)}** fully passing",
        f"- checks: **{total_checks - failed_checks}/{total_checks}** passing",
        f"- cost of the run: ${report['cost_usd']}",
        "",
        "| case | category | result | failed checks |",
        "|---|---|---|---|",
    ]
    for r in rows:
        mark = "pass" if r["passed"] else "**fail**"
        lines.append(f"| `{r['id']}` | {r['category']} | {mark} | {', '.join(r['failed']) or '—'} |")

    # Per-check totals say *what* is weak, which the per-case table does not.
    per_check: dict[str, list[int]] = {}
    for r in rows:
        for name, ok in r["checks"].items():
            if ok is None:
                continue
            hit, seen = per_check.setdefault(name, [0, 0])
            per_check[name] = [hit + (1 if ok else 0), seen + 1]
    lines += ["", "| check | passing |", "|---|---|"]
    for name, (hit, seen) in sorted(per_check.items()):
        lines.append(f"| `{name}` | {hit}/{seen} |")
    return "\n".join(lines) + "\n"


def compare(labels: list[str]) -> str:
    def ratio(rows: list[dict], check: str) -> str:
        values = [r["checks"].get(check) for r in rows]
        seen = [v for v in values if v is not None]
        return f"{sum(1 for v in seen if v)}/{len(seen)}" if seen else "—"

    reports = {label: score(RESULTS / f"answers-{label}.json") for label in labels}
    ids = [r["id"] for r in next(iter(reports.values()))["rows"]]

    lines = ["# Ablation — what the retrieval strategies add", "",
             "| case | " + " | ".join(f"`{lbl}`" for lbl in labels) + " |",
             "|---" * (len(labels) + 1) + "|"]
    for case_id in ids:
        cells = []
        for label in labels:
            row = next((r for r in reports[label]["rows"] if r["id"] == case_id), None)
            cells.append("pass" if row and row["passed"] else "fail")
        lines.append(f"| `{case_id}` | " + " | ".join(cells) + " |")

    lines += [
        "",
        "| run | k | cases passing | context_hit | primary_context_hit | cost |",
        "|---|---|---|---|---|---|",
    ]
    for label, report in reports.items():
        rows = report["rows"]
        lines.append(f"| `{label}` | {report.get('k', 5)} "
                     f"| {sum(1 for r in rows if r['passed'])}/{len(rows)} "
                     f"| {ratio(rows, 'context_hit')} "
                     f"| {ratio(rows, 'primary_context_hit')} "
                     f"| ${report['cost_usd']} |")

    lines += [
        "",
        "`primary_context_hit` is the number to read for a retrieval change. `context_hit`",
        "accepts any of a case's acceptable documents, which is often too coarse to show a",
        "difference — for \"Sind Gewerkschaftsbeiträge absetzbar?\" semantic-only returned the",
        "Anleitung and missed § 9 Werbungskosten, the hybrid returned § 9, and `context_hit`",
        "scored both as passes. When both columns are equal across runs, whatever moved in",
        "the case table moved in generation, not in retrieval.",
        "",
    ]
    return "\n".join(lines) + "\n"



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="hybrid")
    parser.add_argument("--compare", nargs="+", metavar="LABEL",
                        help="two or more runs to put side by side")
    parser.add_argument("--out", default="ablation.md",
                        help="filename for --compare, under results/ — pass one per "
                             "comparison so a new one does not overwrite an old artifact")
    args = parser.parse_args()

    if args.compare:
        out = RESULTS / args.out
        text = compare(list(args.compare))
    else:
        path = RESULTS / f"answers-{args.label}.json"
        if not path.exists():
            sys.exit(f"{path} not found — run collect.py first")
        report = score(path)
        text = markdown(report)
        (RESULTS / f"deterministic-{args.label}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2))
        out = RESULTS / f"deterministic-{args.label}.md"

    out.write_text(text)
    print(text)
    print(f"written: {out.relative_to(EVAL_DIR.parent)}")


if __name__ == "__main__":
    main()
