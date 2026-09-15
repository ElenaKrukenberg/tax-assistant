"""Pass three: RAGAS over the answers already recorded by collect.py.

Runs in its own venv (see requirements-eval.txt) and imports nothing from the backend —
it reads `results/answers-<label>.json` and writes `results/ragas-<label>.{json,md}`.

    eval/venv-eval/bin/python eval/ragas_score.py --judge google/gemini-2.5-flash --limit 3
    eval/venv-eval/bin/python eval/ragas_score.py --judge openai/gpt-4o

The judge is deliberately not the model under test. Haiku 4.5 grading Haiku 4.5 is
self-evaluation: a model is systematically lenient toward its own phrasing. Of the models
this OpenRouter account can actually reach - it is a college account behind a model
allowlist, not a data policy anyone here can enable (issue #15) - that leaves gpt-4o and
gemini-2.5-flash, both outside the family under test. Flash is the cheap one for getting
the integration to work; gpt-4o is the judge of record.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

EVAL_DIR = Path(__file__).resolve().parent
RESULTS = EVAL_DIR / "results"
BACKEND_ROOT = EVAL_DIR.parent

METRICS = [faithfulness, answer_relevancy, context_precision, context_recall]
OPENROUTER = "https://openrouter.ai/api/v1"
EMBEDDING_MODEL = "openai/text-embedding-3-small"


def api_key() -> str:
    """Read the key from the app's .env — the same one collect.py used."""
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    env = BACKEND_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            m = re.match(r"\s*OPENROUTER_API_KEY\s*=\s*(.+)", line)
            if m:
                return m.group(1).strip().strip("\"'")
    sys.exit("OPENROUTER_API_KEY not found in the environment or packages/backend/.env")


def scorable(case: dict) -> bool:
    """Cases RAGAS can say anything about.

    Every metric here needs retrieved context: faithfulness checks the answer against
    it, both context metrics score the context itself. A blocked or out-of-scope case
    has none by design — it never reached retrieval — so including it would average a
    canned refusal into the retrieval scores. Those cases are what the deterministic
    checks are for, and they cover them completely (intent, zero LLM calls, no tools).
    """
    return "error" not in case and bool(case.get("retrieved")) and bool(case.get("answer"))


def build_dataset(cases: list[dict]) -> EvaluationDataset:
    return EvaluationDataset(samples=[
        SingleTurnSample(
            user_input=case["question"],
            response=case["answer"],
            retrieved_contexts=[c["text"] for c in case["retrieved"]],
            reference=case["reference_answer"],
        )
        for case in cases
    ])


def mean_of(rows: list[dict], name: str) -> float | None:
    values = [r[name] for r in rows if isinstance(r.get(name), (int, float)) and r[name] == r[name]]
    return sum(values) / len(values) if values else None


def markdown(label: str, judge: str, rows: list[dict], means: dict, skipped: list[str]) -> str:
    metric_names = [m.name for m in METRICS]
    lines = [
        f"# RAGAS — `{label}`",
        "",
        f"- judge: `{judge}`",
        f"- embeddings: `{EMBEDDING_MODEL}`",
        f"- scored: **{len(rows)}** cases"
        + (f", skipped {len(skipped)} without retrieval context "
           f"({', '.join(f'`{s}`' for s in skipped)})" if skipped else ""),
        "",
        "| metric | mean over all scored cases |",
        "|---|---|",
    ]
    for name in metric_names:
        value = means.get(name)
        lines.append(f"| `{name}` | {value:.3f} |" if value is not None else f"| `{name}` | — |")

    # The flat means above are the number a reviewer will quote and the number that
    # misleads, so the breakdown that explains them comes immediately after.
    by_category: dict[str, list[dict]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    lines += [
        "",
        "## By category",
        "",
        "| category | n | " + " | ".join(f"`{n}`" for n in metric_names) + " |",
        "|---|---" + "|---" * len(metric_names) + "|",
    ]
    for category, group in sorted(by_category.items()):
        cells = []
        for name in metric_names:
            value = mean_of(group, name)
            cells.append(f"{value:.2f}" if value is not None else "—")
        lines.append(f"| {category} | {len(group)} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "### Reading these numbers",
        "",
        "Two of the four metrics are structurally inapplicable to half of this set, and",
        "the split in the table above is where that happens rather than a quality",
        "difference.",
        "",
        "**faithfulness** checks every claim in the answer against the retrieved context.",
        "A calculation answer states a number the tool computed — `150 × (20 km × 0,30 € +",
        "54 km × 0,38 €) = 3.978 €` appears in no document — so the claim is scored",
        "unsupported however correct it is. Hence knowledge cases at 0.81 and calculation",
        "cases at 0.30. The tool's arithmetic is verified by unit tests and by the",
        "`expected_tool_called` check instead.",
        "",
        "**answer_relevancy** zeroes out on answers RAGAS judges noncommittal. Asking the",
        "user for the missing number of working days *is* the wanted behaviour for the",
        "insufficient_data category, and saying \"my documents do not cover this\" is the",
        "wanted behaviour when retrieval genuinely misses. Both read as evasion to the",
        "metric.",
        "",
        "**context_recall** attributes each sentence of the reference answer to the",
        "context, so a reference that is an arithmetic result scores 0 for the same reason",
        "as faithfulness.",
        "",
        "So the RAG signal in this run is the knowledge and multilingual rows — the ten",
        "cases whose answers should come entirely out of the documents. `field_explanation`",
        "is genuinely weak and worth a look: one of its three cases is a real retrieval",
        "gap (the Lohnsteuerbescheinigung annex never reaches the context) and another",
        "answers beyond what its context supports.",
        "",
        "## Per case",
        "",
    ]
    lines += ["| case | " + " | ".join(f"`{n}`" for n in metric_names) + " |",
              "|---" * (len(metric_names) + 1) + "|"]
    for row in rows:
        cells = []
        for name in metric_names:
            v = row.get(name)
            cells.append(f"{v:.2f}" if isinstance(v, (int, float)) and v == v else "—")
        lines.append(f"| `{row['id']}` | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="fixed", help="which answers-<label>.json to score")
    parser.add_argument("--judge", default="openai/gpt-4o")
    parser.add_argument("--limit", type=int, default=None, help="score only the first N cases")
    parser.add_argument("--report-only", action="store_true",
                        help="rewrite the markdown from the saved scores, calling no judge")
    args = parser.parse_args()

    # Rewriting the report must never cost a judge run: the prose around the numbers
    # gets revised far more often than the numbers themselves.
    if args.report_only:
        saved = json.loads((RESULTS / f"ragas-{args.label}.json").read_text())
        text = markdown(args.label, saved["judge"], saved["rows"],
                        saved["means"], saved.get("skipped", []))
        (RESULTS / f"ragas-{args.label}.md").write_text(text)
        print(text)
        return

    path = RESULTS / f"answers-{args.label}.json"
    if not path.exists():
        sys.exit(f"{path} not found — run collect.py first")
    data = json.loads(path.read_text())

    cases = [c for c in data["cases"] if scorable(c)]
    skipped = [c["id"] for c in data["cases"] if not scorable(c)]
    if args.limit:
        cases = cases[:args.limit]
    print(f"scoring {len(cases)} cases · judge={args.judge} · skipping {len(skipped)}")

    key = api_key()
    judge = LangchainLLMWrapper(ChatOpenAI(
        model=args.judge, base_url=OPENROUTER, api_key=key, temperature=0.0, timeout=120))
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(
        model=EMBEDDING_MODEL, base_url=OPENROUTER, api_key=key,
        # OpenRouter is not the OpenAI endpoint langchain assumes: without this it
        # pre-tokenizes with tiktoken and sends token-id arrays, which OpenRouter rejects.
        check_embedding_ctx_length=False))

    result = evaluate(dataset=build_dataset(cases), metrics=METRICS,
                      llm=judge, embeddings=embeddings)

    scored = result.to_pandas().to_dict("records")
    rows = [{"id": case["id"], "category": case["category"],
             **{m.name: record.get(m.name) for m in METRICS}}
            for case, record in zip(cases, scored)]
    means = {m.name: (sum(r[m.name] for r in rows if r[m.name] == r[m.name])
                      / max(1, sum(1 for r in rows if r[m.name] == r[m.name])))
             for m in METRICS}

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"ragas-{args.label}.json").write_text(json.dumps(
        {"label": args.label, "judge": args.judge, "embeddings": EMBEDDING_MODEL,
         "skipped": skipped, "means": means, "rows": rows},
        ensure_ascii=False, indent=2, default=float))
    text = markdown(args.label, args.judge, rows, means, skipped)
    (RESULTS / f"ragas-{args.label}.md").write_text(text)
    print("\n" + text)


if __name__ == "__main__":
    main()
