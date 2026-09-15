# Evaluation Limitations

This page documents the constraints, known gaps, and methodological limitations of the evaluation described in [`SUMMARY.md`](./SUMMARY.md). How to reproduce any of it: [`README.md`](./README.md).

## Dataset Limitations

### Size and statistical power
- **26 test cases total** — enough to catch a structural defect (which it did) but insufficient for confident ranking between two retrieval configurations. A 24/26 vs 23/26 difference could easily be noise.
- **Single-language bias** — all questions in German except 2 multilingual cases, which are graded only on answer language and citation presence (deterministically, not with the judge). Real traffic patterns may differ.
- **Nine categories, arbitrary distribution** — the split reflects the project's priority rather than what users actually ask. Underrepresented categories (calculation, multi-turn) may have hidden weak spots.
- **Curated examples** — the set was manually assembled to cover important tax scenarios rather than sampled from real traffic logs. Coverage gaps may exist for edge cases or unusual question patterns.

## Known Retrieval Gaps — closed

This section used to record two documents that were indexed but never reached the top 5:

| Document | Chunks | Was | Now |
|---|---|---|---|
| `reisekosten-bmf-2024-12-02` (Verpflegungspauschalen) | 11 | not in the top 12 at all | rank 5, answered with a citation |
| `lsth-2025-anhang-23-i-lohnsteuerbescheinigung` | 26 | absent | rank 5, answered with a citation |

Both were attributed to `k` being too small, with "raise `k` from 5 to 8" as the obvious
next experiment. The experiment was run (`eval/k_sweep.py`, `results/k-sweep.md`) and the
attribution was wrong in both directions:

- **`k` was not the constraint.** The BMF Reisekosten letter was not in the top 12, so no
  `k` in the proposed range could have reached it. The lexical tier was taking every slot:
  the needle `Dienstreis` matches 16 of 775 chunks, those 16 ranked 1–16, and the letter —
  second-nearest chunk in the collection — sat at rank 18. Capping the tier at three chunks
  (`LEXICAL_TIER_MAX` in `services/retrieval.py`) put it back at rank 5 and took the
  deterministic checks from 24/26 to 26/26, 86/91 to 91/91, at unchanged `k` and cost.
- **The Lohnsteuerbescheinigung annex was already reachable** before that change, at rank 5.
  This page had gone stale: the line-filter fix recorded in `SUMMARY.md` had moved it, and
  the claim here was never re-measured.
- **Raising `k` anyway makes things worse.** At k=7 the run scores 25/26 for 15% more money
  with identical retrieval — `field-zeile-31` refuses a question whose answer is in four of
  its seven chunks, distracted by two chunks k=5 did not include.

**What is left:** `know-pauschbetrag` and `know-verpflegungsmehraufwand` both enter at
exactly rank 5, so they have no margin. Re-run `k_sweep.py` after any change to the
knowledge base or the embedding model — it costs fractions of a cent once the analyzer
calls are cached, and it is the check that would catch either of them slipping out again.

### The gap underneath it: the checks are document-level, the answer is chunk-level

`know-verpflegungsmehraufwand` now passes every check, and the user still does not get the
number. Chased to the bottom:

- The reference answer is "28 € for a full 24-hour day, 14 € for arrival and departure
  days". Three chunks in the knowledge base carry those rates: one in
  `055-anleitung-anlage-n-2025`, and the curated tables `curated-validation-rules` (V13) and
  `curated-expense-classification`.
- For this query the Anleitung chunk that carries them ranks **27th**. The other two do not
  appear in the top 30 at all — both are English-language tables and the search query is
  German, so the vectors put them far away.
- What does arrive is `reisekosten-bmf-2024-12-02`, the case's declared primary document —
  which is the BMF letter on **foreign** per-diems and does not state the domestic rates.
  The answer says so, correctly and with a citation, and both `citation_present` and
  `primary_context_hit` pass.

So `primary_context_hit` at 11/11 means every case retrieved the document it was told to
expect, not that every answer is grounded in the sentence that answers it. `context_hit` and
`primary_context_hit` are computed over `source_id`, and a document is up to 80 chunks — the
same coarseness that once made `context_hit` unable to see the difference between semantic
and hybrid retrieval, one level further down.

Two things follow, neither of them attempted here:

1. **The case may be mislabelled.** If the expected answer is the domestic rates, the
   authoritative document is the Anleitung or `curated-validation-rules`, not the foreign
   per-diem letter. Worth deciding before the number is chased.
2. **Chunk-level retrieval, not `k`, is the next real experiment.** Rank 27 is out of reach
   for any `k` worth paying for. A reranker over the top ~30, or query-side handling of the
   German/English split in the curated tables, is where this leads. `k` is exhausted as a
   lever — that is the one thing this round settled for good.

## Metric Limitations

### Faithfulness inapplicable to calculations
RAGAS measures faithfulness by checking whether each claim in the answer appears in the retrieved context. For a calculation task:

```
150 × (20 km × 0,30 € + 54 km × 0,38 €) = 3.978 €
```

This number appears in no document because it comes from the tool, not the KB. A correct answer scores 0.30 faithfulness (calculation category) while the same retrieval-only answer scores 0.81 (knowledge category).

**Fix:** Arithmetic is verified by the backend unit tests and the `expected_tool_called` deterministic check, not by RAGAS.

### Answer relevancy penalizes intended behavior
RAGAS zeroes `answer_relevancy` when it judges an answer noncommittal. The system is built to produce two such cases:
- "Please tell me the number of working days" (clarification in a multi-turn conversation)
- "My documents do not cover this question" (honest refusal rather than hallucination)

These are wanted behaviors, not failures.

### Context recall broken for tool-generated claims
Same issue as faithfulness: a reference answer containing a calculated number will score 0 context_recall because the number is not in the documents.

### Judge model constrained
The OpenRouter account is a college account and cannot enable the data policy most model endpoints require. Of 12 models tested, exactly 3 are available:
- **Haiku 4.5** (the app's own model) — excluded because grading its own answers introduces self-evaluation bias
- **GPT-4o** — the judge of record
- **Gemini-2.5-flash** — measurably more lenient (0.96 vs 0.65 on answer_relevancy), so recorded in every artifact

**Impact:** The evaluation was not run against the broader market of LLM judges. Different judges might score differently.

## System Scope Limitations

### Tax domain
- **Anlage N only** — the annex for income from employment (Einkünfte aus nichtselbständiger Arbeit), the most common one for German individual income tax but far from all of it
- **Tax year 2025 only** — rates, thresholds, and rules change annually; evaluation does not account for 2026+ changes
- **Employees only** — self-employment (Anlage S / EÜR), capital gains, corporate tax, VAT and every other domain are out of scope, and the assistant refuses them rather than guessing
- **German law interpretation** — follows German tax authority (BMF/Finanzamt) documents in the knowledge base

### Knowledge base
- **47 documents, 775 chunks** — the current snapshot is frozen. Adding or removing documents is out of scope for this evaluation.
- **No real-time updates** — the KB is a manual snapshot of the tax-year-2025 sources; anything published after it was assembled is not in there, and nothing re-fetches
- **Official sources only** — the KB contains official PDFs (BMF-Merkblätter, ELSTER-Anleitung, EStG); unofficial interpretations are not included

### Retrieval constants are tuned to a 775-chunk collection
Every number the retrieval measured itself into holds at the current collection size and only there. `LEXICAL_MAX_MATCHES = 40` is documented as "roughly 5% of the collection is the line between a useful needle and a useless one", but it is written as an absolute count: at 77,500 chunks a needle matching 3,000 chunks is still ~4% and still useless, yet it passes the filter and floods the top tier — the exact failure `LEXICAL_TIER_MAX` was introduced to stop. `FETCH_K = 20` has the same property.

The two distance cutoffs (`MAX_DISTANCE`, `LEXICAL_MAX_DISTANCE`) do not: cosine distance is scale-free, so they carry over unchanged.

This is a defect of the retrieval code, not of the store, and it is not fixed here deliberately — turning 40 into a fraction of the collection changes it to 38 at today's size, which would require re-running all five configurations to prove nothing moved, for no benefit at 775 chunks. It is scheduled with the pgvector migration ([ADR 0006](../../../docs/adr/0006-pgvector-after-the-sprint.md)), where the collection stops being frozen and the constants have to become relative anyway.

## Model Selection Limitations

### Haiku 4.5 chosen for cost, not evaluated against alternatives
The app uses Haiku 4.5 because of:
- Lower per-token cost ($1/$5 per 1M vs GPT-4o at $2.50/$10 per 1M)
- Sufficient capability for the task as designed

**Not evaluated:** Haiku vs GPT-4o, Sonnet 5, or Opus 5 on the same 26-case set. Better models might close the known gaps; worse models might fail more cases. This is out of scope.

### Retrieval architecture barely compared
The evaluation covers four configurations of the *same* pipeline: exact-term lexical matching (Chroma `where_document $contains` over rare capitalised prefixes — not BM25, there is no lexical index), metadata filtering on topic flags and `form_id`, and dense vector search, differing in how the line filter is applied. Dense-only is the `semantic` ablation. Not tested:
- Reranking models
- Query expansion or decomposition
- Chunk size and overlap variations
- A real sparse index (BM25/SPLADE) in place of the substring match
- Tier weights other than the current fixed order with a cap of three on the lexical tier — three is measured as sufficient for the case the tier exists for, not tuned

## Ablation Study Limitations

### 26 cases too few to confidently rank configurations
The ablation showed:
- **Semantic-only:** 23/26 cases, 9/11 primary documents
- **All three strategies:** 24/26 cases, 10/11 primary documents
- **All three, lexical tier capped:** 26/26 cases, 11/11 primary documents

The 1-case difference between the first two is real but small. Larger test sets would be needed to claim the hybrid approach is *statistically* superior (not just better on this particular set). The cap is a different kind of result: it moved two specific documents from unreachable to rank 5, and the retrieval ranks behind it are exact rather than sampled (`results/k-sweep.md`), so it does not rest on the 26 cases the way a configuration ranking would.

### Cost/quality tradeoff not evaluated
- Semantic-only retrieval costs $0.240 per run
- Hybrid (all three strategies) costs $0.246 per run
- The $0.006 difference is 2.5% extra cost for 1 extra case passing

Whether this is worth it depends on the application; no user research was done.

## Metrics Summary

The table below shows which metrics apply to each evaluation category:

| Category | RAGAS applicable | Deterministic checks cover |
|---|---|---|
| knowledge (8 cases) | ✅ Yes, both metrics work | intent, citations, document retrieval |
| calculation (4) | ❌ faithfulness/recall broken by tools | tool calls, intent, citations |
| field_explanation (3) | ⚠️ Partial — one overclaim; the retrieval gap is fixed | intent, citations, document retrieval |
| insufficient_data (2) | ❌ answer_relevancy zeros on intended behavior | multi-turn handling, intent |
| multi_turn (2) | ⚠️ Partial — context_recall broken by memory | history handling, intent |
| out_of_scope (2) | ❌ No context retrieved | injection guard, intent |
| injection (2) | ❌ No context retrieved | injection guard, zero token cost |
| ambiguous (1) | ❌ Incomplete context by design | intent, citations |
| multilingual (2) | ⚠️ Deterministic only (language + citations) | language detection, citations |

**Summary:** The RAG signal is strongest in the knowledge category (0.81 faithfulness). The apparent weakness in calculations (0.30) and insufficient_data (0.42) reflects metric limitations, not system failure.

## What Would Improve the Evaluation

1. **Larger test set** (100+ cases) — enough for statistical confidence and better category representation
2. **Real-traffic sampling** — understand what users actually ask before designing the test set
3. **Multiple judges** — run with Sonnet, Opus, or open-source judges to see if gpt-4o is an outlier
4. ~~**Ablation on k**~~ — done: `eval/k_sweep.py` and the `lexical-cap-k7` run. k=5 to 12 changes neither `context_hit` nor `primary_context_hit`, and k=7 end to end costs 15% more and loses a case. See "Known Retrieval Gaps — closed" above
5. **Cost-quality curves** — trade-off analysis: latency, embedding cost, and retrieval strategy variants
6. **Multilingual depth** — more than 2 non-German cases, measured on fluency and correctness
7. **2026 data** — once January comes, evaluate the knowledge base against tax year 2026 forms
