# Evaluation

**Results and what they mean: [SUMMARY.md](./SUMMARY.md).**
**What they cannot tell you: [LIMITATIONS.md](./LIMITATIONS.md).**
This file is how to run it.

A golden set of 26 questions and four scripts: one runs them through the pipeline, one
grades what came back with checks that need no judge, one scores the same recorded answers
with RAGAS, and one measures retrieval on its own without paying for generation.

```bash
cd packages/backend

# 1. run the set — real provider calls (~7 min, ~$0.25). --label names the artifacts;
#    the recorded run in results/ is "fixed", the default is "hybrid".
./venv/bin/python eval/collect.py --label fixed

# 2. grade it — free, instant, as often as you like
./venv/bin/python eval/checks.py --label fixed

# 3. ablation: the same set with semantic search only (labels itself "semantic")
./venv/bin/python eval/collect.py --ablation semantic
./venv/bin/python eval/checks.py --compare baseline-line-filter semantic fixed

# 3b. ablation on k: end to end, two more chunks per question
./venv/bin/python eval/collect.py --k 7 --label lexical-cap-k7
./venv/bin/python eval/checks.py --label lexical-cap-k7
#    --out keeps a new comparison from overwriting an older artifact
./venv/bin/python eval/checks.py --compare fixed lexical-cap lexical-cap-k7 \
    --out compare-lexical-cap-and-k.md

# 3c. retrieval only: at which k does each reference document enter the context?
#     ~$0.01 the first time (one analyzer call per case, then cached), then near-free
./venv/bin/python eval/k_sweep.py

# 4. RAGAS — its own venv, see requirements-eval.txt for why
eval/venv-eval/bin/python eval/ragas_score.py --label fixed --judge openai/gpt-4o
eval/venv-eval/bin/python eval/ragas_score.py --report-only   # rewrite the report, free
```

The RAGAS venv is not created by `npm run setup`:

```bash
python3.12 -m venv eval/venv-eval
eval/venv-eval/bin/pip install -r eval/requirements-eval.txt
```

## Why two passes

`collect.py` writes everything a grader could want to `results/answers-<label>.json`:
the answer, the retrieved chunk texts, the intent, the tools called, the tokens. A run
costs real provider calls and minutes; grading the same file costs neither. So the part
you iterate on — the checks, the expectations, later the RAGAS metrics — never pays for
the part you don't.

For the same reason `checks.py` reads expectations from `golden.jsonl` rather than from
the recorded run. Expectations are judgements and judgements get revised: the reference
document turns out to be one sub-part of an annex where three are equally correct, an
intent label turns out to be advisory. Those corrections are free.

The pipeline is driven in-process, not over HTTP — no server to start, and the retrieved
chunks are reachable, which they are not through the API.

## What the checks are

| check | what fails it |
|---|---|
| `intent` | the analyzer's label is outside the accepted set for the case |
| `citation_present` | no inline `[source_id]` naming a document that was actually retrieved |
| `context_hit` | none of the case's reference documents reached the context |
| `expected_tool_called` | the calculation ran as prose instead of through the tool |
| `forbidden_tool_not_called` | a tool ran on a question that lacked the inputs for it |
| `llm_calls` | a blocked question still paid for a provider call |
| `answer_language` | the answer came back in a language the question was not asked in |

A check reports `None` when the case does not declare it, and those are left out of the
totals rather than counted as passes.

## The set

`golden.jsonl`, one case per line, nine categories: knowledge, field_explanation,
calculation, insufficient_data, multi_turn, out_of_scope, injection, ambiguous,
multilingual. Amounts in the reference answers come from `domain/calculations.py` and
`KB/curated-validation-rules.md`, so a reference cannot disagree with what our own tool
computes.

The set is German. The two multilingual cases are graded on answer language and
citation only — scoring a German answer against an English reference would fail
faithfulness for the wrong reason.

Injection cases assert `llm_calls: 0`: the input guard is supposed to refuse before
spending a token, and a guard that refuses after paying is not doing its job.

## What it has caught

The first run scored 13/26. The cause was not the embeddings — queried directly, the
knowledge base returns the right document first at a distance of 0.32. The analyzer was
inventing a line number (10 of 26 cases got the same invented line 31) and `line` was a
hard post-filter over metadata that only 55 of 775 chunks carry. Retrieval collapsed to
one or two tagged survivors, which is how a question about the commute allowance was
answered from a document about doppelte Haushaltsführung.

| | before | after |
|---|---|---|
| cases passing | 13/26 | 24/26 |
| `context_hit` | 11/22 | 20/22 |
| `intent` | 24/26 | 26/26 |

`results/` holds both runs. The two failures that remained after this fix were honest ones
— asked about Verpflegungspauschalen and about the Lohnsteuerbescheinigung the assistant
said its documents did not cover it rather than inventing amounts — and both are now fixed
by the lexical-tier cap, which took the same checks to 26/26. That story is in
[LIMITATIONS.md](./LIMITATIONS.md#known-retrieval-gaps--closed): it was neither a
knowledge-base gap nor a `k` that was too small.

## What is in `results/`

| file | what it is |
|---|---|
| `answers-<label>.json` | a recorded collection run: answers, retrieved chunks, intents, tools, tokens |
| `deterministic-<label>.{json,md}` | the judge-free grading of one run |
| `ablation.md` | `baseline-line-filter`, `semantic` and `fixed` side by side |
| `compare-lexical-cap-and-k.md` | `fixed`, `lexical-cap` and `lexical-cap-k7` side by side |
| `k-sweep.{json,md}` | the rank at which each reference document enters the context |
| `analysis-cache.json` | the analyzer's output per case, so `k_sweep.py` re-runs for free |
| `ragas-fixed.{json,md}` | the RAGAS pass over `answers-fixed.json`, judge recorded in the file |

The labels are `baseline-line-filter` (before the line-filter fix), `semantic` (the
strategy ablation), `fixed` (line-filter fix, 24/26), `lexical-cap` (**what ships**, 26/26)
and `lexical-cap-k7` (the same with k=7, 25/26 — see
[LIMITATIONS.md](./LIMITATIONS.md#known-retrieval-gaps--closed)).

## Why `k_sweep.py` is separate, and cheap

`k` does not change the retrieval ranking: all three strategies overfetch to `FETCH_K` and
the pooled result is sorted before `[:k]` slices it. So the top 5 is a prefix of the top 12,
one retrieval per case answers the question for every candidate `k` at once, and the answer
is exact rather than sampled. What it cannot see is whether extra context changes the
*answers* — for that there is `collect.py --k`, and at k=7 it does, for the worse.

## Still to do

The ablation and the RAGAS pass are done, and `openai/gpt-4o` is the judge of record —
[SUMMARY.md](./SUMMARY.md) has the numbers, [LIMITATIONS.md](./LIMITATIONS.md) the
caveats. What is still open:

- re-run RAGAS. Its numbers are still from `answers-fixed.json`, so they describe the
  pipeline before the lexical-tier cap, and two of the cases they grade now retrieve
  documents they did not have
- a larger set. Twenty-six cases caught a structural defect but cannot separate two
  retrieval configurations that differ by one case
- a second judge. Of twelve models probed, three answer under this account's OpenRouter
  model allowlist (issue #15, not a privacy setting), and one of them is the app's own model
