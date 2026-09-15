"""Does the live Reviewer catch what was planted?

Runs the Reviewer against the seeded broken cases (eval/seeded.py) and checks each
planted defect against the findings. This is the acceptance criterion made
executable: "the Reviewer catches the seeded defects" is a table, not an impression.

The interesting defect is broken-2's inflated claim: no rule sees it — only
recomputing the expense from its own inputs does, which the model has to think of.
The rules-only degraded review provably cannot catch it (tests/test_reviewer.py),
so a catch here is the Reviewer earning its place as an agent.

Run it:
    python -m eval.review_score

Results land in eval/results/review-score-<model>.json.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from agents.reviewer import review
from core.config import get_settings
from core.llm import OpenRouterClient
from core.pricing import cost_usd
from eval.agent_score import CountingChat
from eval.seeded import build_seeded_cases

RESULTS = Path(__file__).parent / "results"


async def main(argv: list[str]) -> int:
    settings = get_settings()
    if not settings.openrouter_api_key:
        print("no OPENROUTER_API_KEY")
        return 1
    model = settings.reviewer_model or settings.llm_model
    chat = CountingChat(OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=model,
    ))

    rows = []
    all_caught = True
    for seeded in build_seeded_cases():
        started = time.monotonic()
        result = await review(seeded.case, chat)
        seconds = round(time.monotonic() - started, 2)

        print(f"\n=== {seeded.id} — {result.rounds} round(s), {seconds}s, "
              f"{'model' if result.from_model else 'RULES ONLY: ' + result.note}")
        for finding in result.findings:
            print(f"  [{finding.severity}] {finding.title}")
            print(f"      {finding.reasoning[:150]}")

        defects = []
        for defect in seeded.defects:
            caught = defect.caught_by(result.findings)
            all_caught &= caught
            print(f"  {'CAUGHT' if caught else 'MISSED'}: {defect.description}")
            defects.append({"id": defect.id, "description": defect.description,
                            "caught": caught})

        rows.append({
            "case": seeded.id,
            "from_model": result.from_model,
            "rounds": result.rounds,
            "seconds": seconds,
            "defects": defects,
            "findings": [{"severity": f.severity, "title": f.title,
                          "reasoning": f.reasoning, "category": f.category}
                         for f in result.findings],
        })

    total_cost = cost_usd(model, chat.prompt_tokens, chat.completion_tokens)
    print(f"\n{chat.calls} provider calls, {chat.prompt_tokens} prompt + "
          f"{chat.completion_tokens} completion tokens"
          + (f", ${total_cost:.4f}" if total_cost is not None else ""))
    print("Every planted defect caught." if all_caught
          else "A planted defect was MISSED — the Reviewer does not yet earn its place.")

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"review-score-{model.replace('/', '-')}.json"
    out.write_text(json.dumps({"model": model, "cost_usd": total_cost, "cases": rows},
                              ensure_ascii=False, indent=2) + "\n")
    print(f"written to {out}")
    return 0 if all_caught else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
