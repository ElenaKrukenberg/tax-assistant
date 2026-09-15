# Agent evaluation

The Sprint 3 half of the evaluation: does the Interviewer agent earn its place, and
does the Reviewer catch what was planted for it. The Sprint 2 half — retrieval and
answer quality of the RAG chat, 26 cases, deterministic checks plus RAGAS — lives in
[SUMMARY.md](SUMMARY.md) and was deliberately left untouched, so its numbers
(`lexical-cap`, 91/91) remain reproducible.

Everything here can be re-run:

```
python -m eval.baseline           # form vs filter, no provider, free
python -m eval.carry_over         # first return vs second, no provider, free
python -m eval.agent_score        # + the live agent           (~$0.47)
python -m eval.review_score       # seeded defects vs Reviewer (~$0.02)
```

Raw artifacts: `results/agent-score-*.json`, `results/review-score-*.json`,
`results/carry-over.json`.

## Method: three arms, not two (ADR 0009)

Every profile runs three ways: the **form** (all 35 catalogue questions, fixed
order), the **filter** (deterministic relevance filter, first open question until
none remain, no model), and the **agent** (the Interviewer, `claude-haiku-4.5`).
Ten synthetic profiles answer from a dictionary; a planted `cannot_answer` list
marks what a profile honestly does not know.

The middle arm is the honesty of the measurement. The filter alone cuts 35
questions to 14–26 with no model involved; crediting that to the agent would be
the first thing a reviewer knocks down. The agent is scored only on what it adds
*over the filter* — and a saving counts only when no amount-affecting field was
lost and no stop was proposed where money remained.


## A second return: what carrying three facts is worth

Measured separately from the agent and on purpose. Which fields carry across the tax
year is declared in `domain/fields.py`, not decided by a model, and whether a carried
value is still relevant is the catalogue's own condition — so this is deterministic,
free, and not a number the Interviewer may claim (ADR 0009 again). The arm is the
filter, filed twice: an empty case, then a case pre-seeded with what the first year
taught the profile memory.

| profile | first year | second year | saved | on the card |
|---|---|---|---|---|
| p01 remote + laptop | 21 | 18 | 3 | 3 |
| p02 commuter, reimbursed | 15 | 13 | 2 | 2 |
| p03 below the allowance | 14 | 12 | 2 | 2 |
| p04 half year, then ALG I | 18 | 16 | 2 | 2 |
| p05 parental leave | 21 | 18 | 3 | 3 |
| p06 job change | 22 | 20 | 2 | 2 |
| p07 Minijob alongside | 15 | 13 | 2 | 2 |
| p08 training + equipment | 26 | 23 | 3 | 3 |
| p09 relocation | 19 | 17 | 2 | 2 |
| p10 first job in September | 24 | 21 | 3 | 3 |

Totals: **24 questions not asked the second year across ten profiles**, every profile
helped, **zero amount-affecting fields lost**.

The last column is the honesty of it. Those 24 questions do not become nothing — they
become one confirmation card per profile, ten cards in place of twenty-four questions.
That is still the better trade (a card answered with one tap against three typed
answers) but reporting the 24 alone would overstate it, in the same way that crediting
the filter's savings to the agent would.

Two things this deliberately does not claim. It is not a saving on a *first* return:
the first column is unchanged, and a new user sees exactly the interview they saw
before. And it does not compound — three fields is what a tax year genuinely leaves
untouched, and the two invariants in ADR 0011 (never a gate, never a repeating field)
are what stop the list from being grown into something that quietly loses a deduction.

## Interviewer: results (2026-08-21, claude-haiku-4.5)

| profile | form | filter | agent | saved | stop proposed | verdict |
|---|---|---|---|---|---|---|
| p01 remote + laptop | 35 | 21 | 21 | 0 | – | no better than the filter |
| p02 commuter, reimbursed | 35 | 15 | 15 | 0 | – | no better than the filter |
| p03 below the allowance | 35 | 14 | **10** | 4 | rightly | earns its place |
| p04 half year, then ALG I | 35 | 18 | **16** | 2 | rightly | earns its place |
| p05 parental leave | 35 | 21 | **20** | 1 | rightly | earns its place |
| p06 job change | 35 | 22 | 22 | 0 | – | no better than the filter |
| p07 Minijob alongside | 35 | 15 | **11** | 4 | rightly | earns its place |
| p08 training + equipment | 35 | 26 | 26 | 0 | – | no better than the filter |
| p09 relocation | 35 | 19 | 19 | 0 | – | no better than the filter |
| p10 first job in September | 35 | 24 | **20** | 4 | rightly | earns its place |

Totals: **15 questions saved over the filter across ten profiles**, zero
amount-affecting fields lost, zero stops proposed where money remained. 185
provider calls, $0.47 for the full run.

The result is narrow and that narrowness is the finding. On the five profiles
whose total cannot reach the Pauschbetrag (1,230 €), the agent proposed stopping
early every time, rightly, with reasons of the form "the remaining categories
cannot plausibly add the missing 978 €". On the five profiles above the
allowance it saved nothing — correctly, because every remaining question there
carries money. **Where judgement has no room, the agent is exactly as good as
the filter and no better; where judgement has room, it uses it.** A fixed
questionnaire cannot do the second thing at any price, and the filter cannot
either: relevance and effect on the outcome are different questions.

### The guard that made the numbers honest

The first live run (kept as `results/agent-score-run1-before-metric-fix.json`,
$0.33) looked better and was worse: 65 questions "saved", but on p08 the agent
stopped at 744 € having never asked the education gate — behind which sat an
1,800 € category. Two changes followed, both structural rather than prompt-level:

1. **Stopping became a proposal** the user confirms, so a wrong stop costs one
   click instead of thousands of euros; the metric now scores whether the
   proposal was right (`stop_early_ok` per profile).
2. **The gate guard**: code, not prompt advice, refuses a conclusion while any
   of the six gate questions is unanswered, substituting the missing gate. In
   the second run it fired **4 times** — the model did try to repeat the p08
   mistake, and could not.

The metric itself was also corrected: only amount-affecting fields count as
losses (fields that place a figure on the form or feed plausibility checks are
reported, not punished). Changing a metric after seeing results is exactly the
move that must never happen silently, which is why run 1 is preserved and the
change is recorded here and in DECISIONS.md.

## Interviewer: the mandatory re-run (2026-09-08, claude-haiku-4.5)

`DECISIONS.md` requires a re-run whenever the calculation tool's contract changes,
and issue #36 changed it: the commute parameter is `commuting_days`, not
`work_days`. Issue #61 renamed every stored fact key in the same diff, so what the
model sees changed too - the candidate ids in its prompt are now
`commute.commuting_days` and `profile.employed_months`.

| profile | filter | agent 08-21 | agent 09-08 | saved then | saved now |
|---|---|---|---|---|---|
| p01 remote + laptop | 21 | 21 | 21 | 0 | 0 |
| p02 commuter, reimbursed | 15 | 15 | 15 | 0 | 0 |
| p03 below the allowance | 14 | 10 | 13 | 4 | **1** |
| p04 half year, then ALG I | 18 | 16 | 11 | 2 | **7** |
| p05 parental leave | 21 | 20 | 16 | 1 | **5** |
| p06 job change | 22 | 22 | 22 | 0 | 0 |
| p07 Minijob alongside | 15 | 11 | 15 | 4 | **0** |
| p08 training + equipment | 26 | 26 | 26 | 0 | 0 |
| p09 relocation | 19 | 19 | 19 | 0 | 0 |
| p10 first job in September | 24 | 20 | 23 | 4 | **1** |

Totals: **14 questions saved** (15 on 08-21), **zero amount-affecting fields lost**,
**zero stops proposed where money remained** - the two invariants hold in both runs.
Of the five profiles that cannot beat the Pauschbetrag, this run shortened four:
p07 was shortened on 08-21 and was not this time. The gate guard fired 3 times
(4 on 08-21). 185 provider calls, $0.4653.
`results/agent-score-anthropic-claude-haiku-4.5-after-key-rename.json`; the 08-21
artifact is kept unchanged beside it.

**Five profiles moved, in both directions** - p03 4 to 1, p04 2 to 7, p05 1 to 5,
p07 4 to 0, p10 4 to 1. The four that were already level with the filter stayed
level.

**What this is and is not evidence of.** The filter arm is identical on all ten
profiles, to the question (21, 15, 14, 18, 21, 22, 15, 26, 19, 24), which is the
arm a broken key would have taken down: the deterministic path did not regress.
It does **not** show that the rename left the agent untouched, because the model
reads those ids. So the honest reading is **run-to-run variability, with no
deterministic regression found** - not provider drift, which would need a run on
the old identifiers to establish, and not a clean bill of health for the rename
either. Further paid re-runs to obtain a rounder number were considered and
rejected: re-running until the result looks better is the one thing a frozen
golden set exists to prevent.

## Reviewer: seeded defects (2026-08-21, claude-haiku-4.5)

Broken cases built from healthy profiles, each defect declaring how a catch is
recognised (`eval/seeded.py`); "caught" is a check, not an impression.

| planted defect | catchable by rules? | caught |
|---|---|---|
| 1,400 € laptop with no document behind it | yes | **yes** (warning) |
| 88 commuting + 180 home-office days vs 220 worked (V02) | yes | **yes** (blocking) |
| commute claimed at 4,100 €; its own inputs give 3,073.04 € | **no** | **yes** (blocking, recomputed) |

The third row is why the Reviewer is an agent and not a rulebook: the values
break no rule individually — only recomputing the expense from the case's own
inputs exposes the claim, and the model had to decide to do that. The
rules-only degraded mode provably misses it
(`tests/test_reviewer.py::test_the_degraded_review_alone_does_not_catch_everything`).
Full run: 5 provider calls, $0.017.

## What this does not measure

- **Documents and the chat as answer sources.** The profiles answer from a
  dictionary; vision extraction and chat-fact capture reduce questions in real
  use but are outside these numbers, and must not be claimed as agent savings
  (DECISIONS.md).
- **Repeating categories.** Three categories accept several items per case; the
  catalogue collects one per run so far, pinned by
  `test_a_repeating_category_is_asked_once_per_run_for_now`.
- ~~The stronger reviewer model~~ — resolved on 2026-08-22: the Reviewer runs on
  `openai/gpt-5.4`, a different *vendor* from the haiku Interviewer, so the
  audit's independence is structural, not just prompted. Rerun of the seeded
  defects: 3 of 3 caught (`results/review-score-openai-gpt-5.4.json`), including
  the day contradiction it phrased in German — which exposed and fixed the
  second language-dependent keyword in the catch detector (numbers now, words
  before).
- ~~RAG quality of the new categories~~ — done on 2026-08-22: five cases added,
  the whole set re-collected and re-judged. 110/111 deterministic, the new
  categories at faithfulness 0.76 / recall 1.00, and one reproducible
  provider-side drift caught on the way — see the addendum in
  [SUMMARY.md](SUMMARY.md).
