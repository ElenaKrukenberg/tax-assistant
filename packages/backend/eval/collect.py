"""Pass one of the evaluation: run the golden set through the pipeline and record it.

Collection is separated from scoring because scoring is the part you iterate on. A
run costs real provider calls and minutes; re-reading a JSON file costs neither. So
this writes everything a scorer could want — the answer, the retrieved chunk texts,
the intent, the tools, the tokens — and `checks.py` (and later RAGAS) work offline
from that file.

The pipeline is driven in-process rather than over HTTP: no server to start, and the
retrieved chunks are reachable, which they are not through the API.

    ./venv/bin/python eval/collect.py                      # hybrid retrieval
    ./venv/bin/python eval/collect.py --ablation semantic   # baseline for comparison
    ./venv/bin/python eval/collect.py --k 7 --label k7      # sweep the context size
    ./venv/bin/python eval/collect.py --only calc-,inj-     # iterate on a subset
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
from core.dependencies import get_llm_client                       # noqa: E402
from core.embeddings import OpenRouterEmbeddings                   # noqa: E402
from core.config import get_settings                               # noqa: E402
from db.kb_store import PostgresChunks                             # noqa: E402
from services.retrieval import ALL_STRATEGIES, DEFAULT_K, Retriever  # noqa: E402
from services.tax_service import TaxService                        # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
GOLDEN = EVAL_DIR / "golden.jsonl"
RESULTS = EVAL_DIR / "results"


class RecordingRetriever:
    """Wraps the retriever to keep what it returned for the case being run.

    The API deliberately exposes only cited sources, but a scorer needs the whole
    retrieved set — its texts for faithfulness, its ids for context recall. Recording
    here keeps that out of the response contract.

    `k` overrides the retriever's default for the whole run, so a sweep over k needs no
    edit to `services/retrieval.py`: the pipeline never passes k, which is exactly why
    it can be injected here.
    """

    def __init__(self, inner: Retriever, k: int | None = None):
        self.inner = inner
        self.k = k
        self.chunks: list = []

    def search(self, *args, **kwargs):
        if self.k is not None:
            kwargs.setdefault("k", self.k)
        result = self.inner.search(*args, **kwargs)
        self.chunks = [
            {"source_id": c.metadata.get("source_id", ""),
             "section": c.metadata.get("section", ""),
             "distance": round(c.distance, 4),
             "text": c.text}
            for c in result.chunks
        ]
        return result


def load_golden(only: list[str]) -> list[dict]:
    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    if only:
        cases = [c for c in cases if any(c["id"].startswith(p) for p in only)]
    return cases


async def run_case(service: TaxService, recorder: RecordingRetriever, case: dict) -> dict:
    request = TaxQuestionRequest(
        text=case["question"],
        language=case.get("language", "de"),
        history=case.get("history", []),
    )
    recorder.chunks = []
    answer = await service.answer_question(request, request_id=f"eval-{case['id']}")
    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "reference_answer": case["reference_answer"],
        "reference_context_ids": case.get("reference_context_ids", []),
        "expect": case.get("expect", {}),
        "answer": answer.summary,
        "intent": answer.intent,
        "cited_source_ids": [s.source_id for s in answer.sources],
        "tools_called": [t.tool for t in answer.tool_results],
        "trace": [f"{s.label}: {s.detail}" for s in answer.trace],
        "warnings": answer.warnings,
        "usage": answer.usage.model_dump(),
        # what RAGAS calls `contexts`
        "retrieved": recorder.chunks,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ablation", choices=["semantic"], default=None,
                        help="run with a reduced retriever to measure what the rest adds")
    parser.add_argument("--only", default="", help="comma-separated case-id prefixes")
    parser.add_argument("--k", type=int, default=None,
                        help="chunks per question; defaults to DEFAULT_K in services/retrieval.py")
    parser.add_argument("--label", default=None, help="output file suffix (defaults to the mode)")
    args = parser.parse_args()

    strategies = ("semantic",) if args.ablation == "semantic" else ALL_STRATEGIES
    label = args.label or (args.ablation or "hybrid")

    settings = get_settings()
    embedder = OpenRouterEmbeddings(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.embedding_model,
    )
    recorder = RecordingRetriever(
        Retriever(PostgresChunks(), embedder, strategies), k=args.k)
    service = TaxService(get_llm_client(), recorder)

    cases = load_golden([p for p in args.only.split(",") if p])
    print(f"{len(cases)} cases · retrieval={'+'.join(strategies)} · k={args.k or DEFAULT_K}"
          f" · model={service.llm.model}")

    records = []
    for i, case in enumerate(cases, 1):
        try:
            record = await run_case(service, recorder, case)
        except Exception as e:                                  # noqa: BLE001
            # One bad case must not throw away a paid run of the others.
            record = {"id": case["id"], "category": case["category"],
                      "question": case["question"], "error": f"{type(e).__name__}: {e}"}
        records.append(record)
        mark = "!" if "error" in record else "·"
        print(f"  {i:2}/{len(cases)} {mark} {record['id']}")

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"answers-{label}.json"
    spent = sum(r.get("usage", {}).get("cost_usd") or 0 for r in records)
    out.write_text(json.dumps(
        {"label": label, "strategies": list(strategies), "model": service.llm.model,
         "k": args.k or DEFAULT_K, "cost_usd": round(spent, 6), "cases": records},
        ensure_ascii=False, indent=2) + "\n")
    print(f"\n{out.relative_to(BACKEND_ROOT)} · {len(records)} cases · ${spent:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
