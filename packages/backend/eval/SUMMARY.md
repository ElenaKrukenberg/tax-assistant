# Evaluation summary

One page over the artifacts in `results/`. Every number here comes from a file in that
directory and can be regenerated with the commands in `README.md`; the interpretation is
the part worth reading.

The set is 26 questions across nine categories (`golden.jsonl`). Two independent layers
grade it: deterministic checks that need no judge, and RAGAS with `openai/gpt-4o` as
judge. They measure different things and they disagree in an informative way.

## Deterministic checks — five configurations

| run | k | cases | primary document | reference document | citation | expected tool | cost |
|---|---|---|---|---|---|---|---|
| `baseline-line-filter` | 5 | 15/26 | **5/11** | 13/22 | 17/19 | 5/5 | $0.216 |
| `semantic` (ablation) | 5 | 23/26 | **9/11** | 21/22 | 18/19 | 4/5 | $0.240 |
| `fixed` | 5 | 24/26 | **10/11** | 20/22 | 17/19 | 5/5 | $0.246 |
| `lexical-cap` (current) | 5 | **26/26** | **11/11** | 22/22 | 19/19 | 5/5 | $0.250 |
| `lexical-cap-k7` | 7 | 25/26 | **11/11** | 22/22 | 18/19 | 5/5 | $0.287 |

`intent` 26/26, `forbidden_tool_not_called` 4/4, `answer_language` 2/2 and `llm_calls`
2/2 hold across every run after the first. `llm_calls` is the injection guard: a blocked
question must cost zero provider calls, and it does.

The `lexical-cap` run is the only one with every check passing: 91/91.

**What moved the numbers.** Not the hybrid retrieval — the line filter. The analyzer was
returning an Anlage N line number for 12 of the 26 questions and in 10 of those it was
the same invented line 31, while only 55 of 775 chunks carry line metadata at all. As a
post-filter that discarded every document that answered the question and kept whichever
tagged chunk survived, which is how a question about the commute allowance came back
answered from a document about doppelte Haushaltsführung. Making the line promote instead
of filter took primary-document retrieval from 5/11 to 10/11.

### Retrieval fix: the lexical tier cap

The two documents this evaluation had written off as unreachable were a tier-ordering bug,
not a knowledge-base gap and not a `k` that was too small.

`eval/k_sweep.py` measures the rank at which each reference document enters the context.
It is cheap because `k` does not change the ranking — the strategies overfetch to
`FETCH_K` and the pooled result is sorted before `[:k]` slices it — so one retrieval per
case answers the question for every `k` at once. It reported
`reisekosten-bmf-2024-12-02` absent from the top **12**, which already refutes k=7 or k=8
as the fix. The cause: the needle `Dienstreis` matches 16 of 775 chunks — rare enough to
qualify, and three times `k` — and those 16 filled ranks 1–16. The BMF letter was the
second-nearest chunk in the whole collection (distance 0.34) and second in its own
metadata tier, and it sat at rank 18.

Capping the lexical tier at three chunks (`LEXICAL_TIER_MAX`) fixed it: the letter returns
at rank 5, no other case's ranking moves, and end to end the checks go from 24/26 to
**26/26** and 86/91 to **91/91** at the same `k` and the same cost. The tier still does its
job — `know-berufsverbaende`, the case it exists for, needs only its top two hits.

One caveat, because 26/26 invites over-reading: on
`know-verpflegungsmehraufwand` the checks now pass and the answer still does not state the
28 €/14 € rates. The document that arrives is the BMF letter on *foreign* per-diems, the
chunk that carries the domestic rates is at rank 27, and the checks are document-level so
they cannot see the difference. Written up under
[LIMITATIONS.md](./LIMITATIONS.md#the-gap-underneath-it-the-checks-are-document-level-the-answer-is-chunk-level);
it is the next real experiment, and it is not `k`.

**And `k` itself?** Measured, both ways, and the answer is no. `k` from 5 to 12 changes
neither `context_hit` (22/22) nor `primary_context_hit` (11/11) once the flood is fixed:
every reference document the set names is already inside the top five. Run end to end at
k=7 it is actively worse — 25/26 for 15% more money. Retrieval was identical, so the loss
is in generation: `field-zeile-31` retrieved the Anleitung in four of its seven chunks and
still answered "I cannot find line 31 in the context documents", talked out of it by two
distractor chunks about doppelte Haushaltsführung and Arbeitszimmer that k=5 did not
include. More context is not free even when the extra chunks are cheap.

The one number that argues for raising `k` is margin: `know-pauschbetrag` and
`know-verpflegungsmehraufwand` both land at exactly rank 5, so a KB edit that shifts a rank
loses them. That is an argument for watching `k-sweep.md` when the KB changes, not for
paying 15% and a case now.

**What the ablation is worth.** Lexical and metadata add one case over plain semantic
search (10/11 against 9/11) at two extra Chroma queries and no extra provider call. Real
and worth keeping, but one case out of 26 — not the transformation the architecture might
suggest. Twenty-six questions are also too few to separate two configurations
confidently, and that limit belongs next to the result rather than under it.

**A metric that could not see its own subject.** The first ablation run scored 24/26
against 24/26 — a tie, from which "lexical and metadata are useless" would have followed.
The check was at fault: `context_hit` passes on *any* acceptable reference document, and
for "Sind Gewerkschaftsbeiträge absetzbar?" the acceptable list included the Anleitung,
which comes back under every configuration. Semantic-only had actually missed § 9
Werbungskosten entirely. `primary_context_hit` — did *the* authoritative document arrive —
is declared on 11 cases where one document is unambiguously the authority, and it is the
column to read in the table above.

## RAGAS — and why the means need the breakdown

**These scores are from the `fixed` run and have not been re-judged since the lexical-tier
cap.** Two of the cases below now retrieve documents they did not have, so the
`field_explanation` and `knowledge` rows understate the current pipeline. The deterministic
table above is the one that describes it.

Judge `openai/gpt-4o`, embeddings `openai/text-embedding-3-small`, 22 of 26 cases scored.
The four injection and out-of-scope cases are excluded on purpose: they never reach
retrieval, so every metric here is undefined for them, and the deterministic checks cover
them completely.

| | faithfulness | answer relevancy | context precision | context recall |
|---|---|---|---|---|
| **all 22 cases** | 0.545 | 0.466 | 0.566 | 0.636 |
| knowledge (8) | **0.81** | 0.62 | 0.64 | 0.69 |
| multilingual (2) | 0.64 | 0.66 | 0.71 | 1.00 |
| calculation (4) | **0.30** | 0.50 | 0.63 | 1.00 |
| field_explanation (3) | 0.31 | 0.24 | 0.42 | 0.33 |
| insufficient_data (2) | 0.42 | 0.23 | 0.35 | 0.75 |
| multi_turn (2) | 0.38 | 0.39 | 0.22 | 0.00 |
| ambiguous (1) | 0.44 | 0.00 | 1.00 | 0.00 |

Two of the four metrics are inapplicable to half this set, and the knowledge/calculation
gap is where that shows rather than a quality difference.

**faithfulness** checks every claim against the retrieved context. A calculation answer
states a number the tool computed: `150 × (20 km × 0,30 € + 54 km × 0,38 €) = 3.978 €`
appears in no document, so a correct claim is scored unsupported. Hence 0.81 for knowledge
and 0.30 for calculation. The arithmetic is verified by the backend unit tests and by
`expected_tool_called` instead.

**answer_relevancy** zeroes out on answers RAGAS judges noncommittal, which catches two
behaviours the system is built to produce: asking for the missing number of working days,
and saying plainly that the documents do not cover the question.

**context_recall** attributes each sentence of the reference to the context, so an
arithmetic reference scores zero for the same reason as faithfulness.

So the RAG signal is the knowledge and multilingual rows — ten cases whose answers must
come entirely out of the documents.

## Where it is genuinely weak

**~~Two documents that exist but never arrive.~~ Retrieval fixed, one answer still short.**
Both `reisekosten-bmf-2024-12-02` and `lsth-2025-anhang-23-i-lohnsteuerbescheinigung` now
reach the context and both cases pass every check. The Lohnsteuerbescheinigung question is
genuinely answered; the Verpflegungspauschalen one is not — the rates it asks for sit in a
chunk at rank 27, so the assistant correctly reports that its context does not contain them.
Kept here rather than deleted because the diagnosis is the point: it was written up as a
knowledge-base gap with `k` as the suspect, and it was neither — first a tier-ordering bug,
and underneath that a chunk-level ranking problem that document-level metrics cannot see.
The honest refusal that made it look like a knowledge-base limit is also what made it
survivable: the answer layer has never invented the 14 €/28 € rates it cannot retrieve.

**`field_explanation` remains the weakest category** on the RAGAS run above, though one of
its three cases was the Lohnsteuerbescheinigung gap and is now retrieving. What is left is
a case that answers past what its context supports; that has not been re-judged.

**Judge selection was constrained.** The OpenRouter account is a college one and cannot
enable the data policy most model endpoints require. Of twelve candidates probed, three
answer: the app's own Haiku 4.5, gpt-4o and gemini-2.5-flash. Haiku is excluded because it
would grade its own answers; gpt-4o is the judge of record. Gemini is measurably more
lenient on the same cases (0.96 against 0.65 on relevancy), so the judge is recorded in
every artifact.

**The set is small and single-language.** Twenty-six German questions, two of them
multilingual and graded only on answer language and citation presence. Enough to catch a
structural defect — it caught one — and not enough for a confident ranking.

## What this cost

| | |
|---|---|
| one collection run (26 questions, live pipeline) | ~$0.25, ~7 minutes |
| the same run at k=7 (two more chunks per question) | ~$0.29, +15% |
| `k_sweep.py`, first time (26 analyzer calls, then cached) | ~$0.01, ~40 seconds |
| `k_sweep.py`, thereafter (embeddings + Chroma only) | fractions of a cent |
| RAGAS scoring, 22 cases, 88 judge evaluations | ~$0.30–0.50, ~40 seconds |
| deterministic checks, any number of times | free, instant |

The k sweep is the row worth noticing: the question "does a larger `k` fix the retrieval
gaps" was answered for a cent, and answered exactly, because `k` only slices a ranking it
does not influence. The two full runs that followed were spent confirming it end to end.

Collection is separated from scoring precisely because of that first row: expectations,
checks and report prose all get revised, and none of them should cost another run.


---

## Addendum, 2026-08-22: the 31-case rerun

The golden set grew by five cases for the categories Sprint 3 added (Umzugskosten,
Bewerbungskosten) — `answers-lexical-cap-31.json`. Nothing in the pipeline changed;
the original 26-case artifacts above stand as recorded.

Deterministic checks: **110 of 111**. All five new cases pass in full, and two of
them corrected their own expectations rather than the pipeline: retrieval surfaced
`lsth-2025-anhang-29-iv-2-umzugskosten` — a KB document dedicated to Umzugskosten
that the hand-written expectation did not know existed — and the DHF question's
authority is the 056 Anleitung, which retrieval also ranked first.

The one failure is a finding, not a defect in the harness: `ml-en-commute`, which
passed on 2026-08-03, now fails `citation_present` reproducibly — the model answers
the general English commuting question with a clarifying question instead of the
cited rates, twice in a row on an unchanged pipeline. That is **provider-side model
drift caught by re-running the evaluation**, which is precisely what a frozen,
re-runnable golden set is for. Recorded here rather than papered over with a prompt
tweak; the RAGAS row (`faithfulness 0.00` for that case) agrees.

RAGAS over all 31 (judge `openai/gpt-4o`): faithfulness 0.66, answer relevancy 0.58,
context precision 0.79, context recall 0.72 — the same metric caveats as above apply
(calculation and clarification categories depress the means by construction). The
five new cases alone: faithfulness 0.76, precision 0.98, recall 1.00.

## Addendum, 2026-09-08: the re-run the key rename required

Issues #61 and #36 renamed every stored fact key and split `work_days` into
`commuting_days` / `homeoffice_days` / `working_days_total`. The second of those is
in the calculation tool's schema, so `DECISIONS.md` required this re-run -
`answers-after-key-rename.json`, `deterministic-after-key-rename.md`.

The check tables are **identical to `lexical-cap-31`**, row for row; the two lines
that differ in the file are the run label and the cost ($0.2987 against $0.2964).
111 of 112 checks, and the single failure is `ml-en-commute` on `citation_present` -
the same case, the same check, already recorded above as model drift on an unchanged
pipeline. **No new failures, and it was not re-run in the hope of a pass**: a golden
set whose failures are retried until they clear measures nothing. What this re-run
establishes is the narrow thing it can: the rename introduced no regression the
deterministic checks can see.

RAGAS was not re-run - it grades the recorded answers, and those are byte-comparable
on every check the harness makes.
