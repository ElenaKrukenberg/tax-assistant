"""Ablation on k: at which cut-off does each reference document reach the context?

The open question from LIMITATIONS.md was whether raising `k` from 5 rescues the two
documents that exist in the knowledge base and never reach the top 5. This measures it
directly, and it is much cheaper than a full run, because of one property of
`Retriever.search`: `k` does not change the ranking. All three strategies overfetch to
FETCH_K and are pooled and sorted before `ranked[:k]` slices the result, so the top-5 is
a prefix of the top-12. One retrieval per case therefore answers the question for every
k at once — exactly, not by approximation.

What still costs money is the analysis stage, one call per case, because retrieval runs
on the rewritten German query with the topic and form filters the analyzer chose;
sweeping over the raw question would measure a pipeline nobody runs. Those analyses are
cached in `results/analysis-cache.json`, so only the first sweep pays for them.

    ./venv/bin/python eval/k_sweep.py              # cached analyses where available
    ./venv/bin/python eval/k_sweep.py --refresh    # re-analyse every case
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Run as a script from packages/backend, so the backend root has to be importable.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from api.schemas.tax import TaxQuestionRequest                     # noqa: E402
from core.config import get_settings                              # noqa: E402
from core.dependencies import get_llm_client                       # noqa: E402
from core.embeddings import OpenRouterEmbeddings                   # noqa: E402
from db.kb_store import PostgresChunks                             # noqa: E402
from services.query_analysis import analyze_query                  # noqa: E402
from services.retrieval import ALL_STRATEGIES, Retriever           # noqa: E402
from services.tax_service import TaxService                        # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
GOLDEN = EVAL_DIR / "golden.jsonl"
RESULTS = EVAL_DIR / "results"
CACHE = RESULTS / "analysis-cache.json"

# The candidate cut-offs. 5 is what ships; 12 is past anything worth paying for and is
# there to show where the curve flattens.
K_VALUES = (5, 6, 7, 8, 10, 12)
# Deep enough to rank every candidate any k in K_VALUES could reach.
K_MAX = max(K_VALUES)


def load_cases() -> list[dict]:
    """Only the cases that name a reference document — the rest cannot move with k.

    An out-of-scope or injection case never retrieves, and a case with no reference
    document has nothing for this to measure.
    """
    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    return [c for c in cases if c.get("reference_context_ids")]


async def analysis_for(case: dict, cache: dict, llm, refresh: bool) -> dict:
    """The analyzer's output for a case: the German query and the retrieval filters."""
    if not refresh and case["id"] in cache:
        return cache[case["id"]]

    request = TaxQuestionRequest(
        text=case["question"],
        language=case.get("language", "de"),
        history=case.get("history", []),
    )
    # Same preparation the pipeline does, so a multi-turn case is analysed with the
    # turns that make its "74 km" answerable.
    history, _ = TaxService._prepare_history(request.history)
    analysis = await analyze_query(llm, request.text, history)
    cache[case["id"]] = {
        "search_query": analysis.search_query,
        "topics": analysis.topics,
        "line": analysis.line,
        "form_id": analysis.form_id,
        "intent": analysis.intent,
        "cost_tokens": analysis.usage.get("total_tokens", 0),
    }
    return cache[case["id"]]


def rank_of(source_ids: list[str], wanted: set[str]) -> int | None:
    """1-based position of the first chunk from any wanted document, or None."""
    for position, source_id in enumerate(source_ids, 1):
        if source_id in wanted:
            return position
    return None


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true",
                        help="re-run the analysis stage instead of using the cache")
    args = parser.parse_args()

    settings = get_settings()
    embedder = OpenRouterEmbeddings(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.embedding_model,
    )
    retriever = Retriever(PostgresChunks(), embedder, ALL_STRATEGIES)
    llm = get_llm_client()

    RESULTS.mkdir(exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() and not args.refresh else {}
    cases = load_cases()
    print(f"{len(cases)} retrieval cases · k up to {K_MAX} · model={llm.model}")

    rows = []
    for i, case in enumerate(cases, 1):
        analysis = await analysis_for(case, cache, llm, args.refresh)
        result = retriever.search(
            analysis["search_query"],
            analysis["topics"] or None,
            analysis["line"],
            analysis["form_id"],
            k=K_MAX,
        )
        source_ids = [c.metadata.get("source_id", "") for c in result.chunks]
        reference = set(case["reference_context_ids"])
        primary = case.get("primary_context_id")

        rows.append({
            "id": case["id"],
            "category": case["category"],
            "search_query": analysis["search_query"],
            "filters": {"topics": analysis["topics"], "line": analysis["line"],
                        "form_id": analysis["form_id"]},
            "strategies": result.strategies,
            "ranked_source_ids": source_ids,
            "reference_context_ids": sorted(reference),
            "primary_context_id": primary,
            # the k at which each first becomes reachable; None = not in the top K_MAX
            "reference_rank": rank_of(source_ids, reference),
            "primary_rank": rank_of(source_ids, {primary}) if primary else None,
            "candidates": len(source_ids),
        })
        print(f"  {i:2}/{len(cases)} · {case['id']}: "
              f"reference@{rows[-1]['reference_rank']} primary@{rows[-1]['primary_rank']}")

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")

    report = {
        "k_values": list(K_VALUES),
        "k_max": K_MAX,
        "model": llm.model,
        "strategies": list(ALL_STRATEGIES),
        "cases": rows,
        "totals": totals(rows),
    }
    (RESULTS / "k-sweep.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    text = markdown(report)
    (RESULTS / "k-sweep.md").write_text(text)
    print("\n" + text)
    print(f"written: {(RESULTS / 'k-sweep.md').relative_to(BACKEND_ROOT)}")


def totals(rows: list[dict]) -> dict:
    """context_hit and primary_context_hit at each candidate k."""
    with_primary = [r for r in rows if r["primary_context_id"]]
    return {
        str(k): {
            "context_hit": sum(1 for r in rows
                               if r["reference_rank"] and r["reference_rank"] <= k),
            "context_hit_of": len(rows),
            "primary_context_hit": sum(1 for r in with_primary
                                       if r["primary_rank"] and r["primary_rank"] <= k),
            "primary_context_hit_of": len(with_primary),
        }
        for k in K_VALUES
    }


def markdown(report: dict) -> str:
    rows = report["cases"]
    lines = [
        "# Ablation on k — when does each reference document become reachable?",
        "",
        f"- retrieval: `{'+'.join(report['strategies'])}`, ranked to k={report['k_max']}",
        f"- analyzer: `{report['model']}` (one call per case, cached)",
        "",
        "`k` does not change the ranking — the strategies overfetch to `FETCH_K` and the",
        "pooled result is sorted before `[:k]` slices it — so the rank below is the",
        "smallest k at which that document enters the context.",
        "",
        "| case | reference doc at k= | primary doc at k= | candidates ranked |",
        "|---|---|---|---|",
    ]
    for r in rows:
        reference = r["reference_rank"] or "—"
        primary = r["primary_rank"] or ("—" if r["primary_context_id"] else "n/a")
        lines.append(f"| `{r['id']}` | {reference} | {primary} | {r['candidates']} |")

    lines += ["", "| k | context_hit | primary_context_hit |", "|---|---|---|"]
    for k, total in report["totals"].items():
        lines.append(
            f"| {k} | {total['context_hit']}/{total['context_hit_of']} "
            f"| {total['primary_context_hit']}/{total['primary_context_hit_of']} |"
        )
    lines += ["", "A dash means the document is not in the top "
              f"{report['k_max']} at all, so no k in this range reaches it.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    asyncio.run(main())
