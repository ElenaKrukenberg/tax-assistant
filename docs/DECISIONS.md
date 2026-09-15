# Decisions log

Format: decision → why → how to apply. Full reasoning lives in
AGENT_ARCHITECTURE; this is the quick-reference version. Formal ADRs are in
`adr/`.

## Two agents, not N

**Decision.** Interviewer/orchestrator + independent Reviewer. Everything else
(case creation, documents, calculations, report, field checks) is plain code,
rule-based workflow or single LLM calls.

**Why.** Of 15 assessed functions only next-question choice needs multi-step,
state-dependent action; the Reviewer is justified by role conflict (the builder
of a case cannot be its only checker), not by autonomy.

**Apply.** No new agent without an answer to "what here cannot be decided by
plain code or one LLM call".

## No extra Anlagen for multi-agent show

**Decision.** The sprint is Anlage N only; another Anlage is an optional
stretch after the core is stable.

**Why.** Another Anlage scales KB and taxonomy, not the number of agents that
are needed.

## Calculations are always code, never an LLM

**Decision.** All arithmetic (Entfernungspauschale, Homeoffice, AfA…) is done
by deterministic, unit-tested functions.

**Why.** Tax-relevant figures must be reproducible; irreproducibility here is a
product/legal problem, not a technical one.

**Apply.** Every new calculator is a pure function with tests before it enters
the graph. The LLM may phrase the explanation, never the number.

## The agent's value is measured, not demonstrated

**Decision.** Success = comparing the Interviewer against a fixed questionnaire
on identical synthetic profiles (question counts, irrelevant questions,
completeness, cost), not the fact of using LangGraph.

**Apply.** The baseline questionnaire is derived mechanically from the
catalogue — one question per field — never hand-written, or its length is the
author's choice and proves nothing. Ten profiles, four deliberately hard;
failure declared upfront: a lost required field, or more questions than the
baseline.

**After the first measurement.** Three arms, not two: form → filter → agent
(ADR 0009). The deterministic filter alone gives 34→13 on a plain profile with
no model; that must never be credited to the agent. Compare against the filter
and accept in advance that the verdict may be "a workflow suffices here".

## Human-in-the-loop is mandatory before finalisation

**Decision.** No report is generated without explicit user approval, whatever
the Reviewer said.

**Apply.** `final_approval` before the report is a required graph node, not an
option. Disclaimer everywhere: this is not tax advice.

## Anlage N boundaries: foreign sums are named, not computed

**Decision.** Einkommensersatzleistungen (ALG I, Elterngeld) are collected and
shown in the report as a separate block; the employment period constrains the
Werbungskosten questions. No Progressionsvorbehalt arithmetic.

**Why.** Per the ESt 1 A form these sums are normally not entered anywhere —
they reach the Finanzamt electronically; Zeile 35 only matters with a paper
Leistungsnachweis. The same (e) marker on Anlage N Zeile 51 means asking users
for employer-transmitted figures is wasted questions — the catalogue skips them.

**Apply.** Any value outside Anlage N is either explicitly addressed in the
report ("Hauptvordruck, line X") or not asked at all — never collected and
silently dropped.

## The Interviewer sees filtered candidates, not the catalogue

**Decision.** The catalogue is not pasted into the prompt. `list_open_questions`
returns only unanswered, profile-relevant questions; round cap 40.

**Why.** With the whole catalogue in view the model re-asks what documents
already answered — generating the very metric ("irrelevant question") we
measure. Filtering is deterministic and testable; the agent keeps ordering and
the stop decision. The cap is derived from the catalogue (busiest profile: 26),
not taste; hitting it escalates to the human.

## The Reviewer runs on a different model than the Interviewer

**Decision.** Interviewer on a fast model; Reviewer on a stronger one from a
**different vendor** (`openai/gpt-5.4`, verified live 3/3 on seeded defects).
Input: final case state only, no interview dialogue; rights: recompute with the
calculators, search the KB.

**Why.** Independence must be more than a prompt, or "it will just agree with
itself" has no answer. Without recompute/retrieval rights the reviewer can only
quibble with wording.

**Apply.** Never pass the Reviewer the interview dialogue, not even a summary.
If it starts agreeing with everything, fix the adversarial prompt and the
seeded defects first — do not add a third agent.

## Observability does not override the privacy decision

**Decision.** LangSmith is on (including production), in the EU region, but the
value of every field in the case is replaced by a marker before upload
(`core/tracing.py`). The set is derived from `domain/fields.py`, not listed.

**Why.** ADR 0004 forbids storing the file; sending its contents to LangSmith
in cleartext would be the same decision bypassed through another door. Traces
exist to show *why the agent chose*, which needs no cleartext salary.

Derived rather than listed because the listed version failed. It named four
fields, of which one existed in the live model, while thirteen that did existed
travelled in the open - and nothing said so, because the only thing checking the
list was somebody remembering it.

**Apply.** Nothing to remember: a field added to the catalogue is redacted the
same day. What still needs a decision is a value that reaches a prompt without a
catalogue key beside it - a computed total, a substituted formula - and those are
covered case by case in `core/tracing.py`. Wiring is explicit - never the
`LANGSMITH_TRACING` autopilot, whose own client uploads unredacted. Region,
retention and deletion: `docs/TRACING_POLICY.md`.

## The public demo is limited from two sides

**Decision.** Per-user limits (2 cases, daily interview quota) plus a global
monthly ceiling with read-only degradation. Counters live in Postgres
(`db/usage.py`): a deploy must not reset the month.

**Why.** An agent run is dozens of calls on a personal key at a public URL. One
enthusiast and twenty simultaneous strangers are different failures; invite-only
was rejected because the reviewer must be able to walk in.

**Apply.** Any new endpoint that spends provider money gets both limits in the
same revision it appears.

## The end of the interview is a proposal, gated by the gate questions

**Decision.** `conclude_interview` is a proposal the user confirms (an HITL
point). Code forbids proposing while any of the six gates is unanswered — a
premature conclude is replaced by the missing gate question. The metric counts
only amount-affecting fields as losses and scores stop-proposal correctness.

**Why.** First live run: the agent stopped at €744 without asking the education
gate hiding €1,800. While gates are open, "nothing more to find" is a guess; a
stop-as-decision prices that guess in thousands, a stop-as-proposal in one
click. Typical-amount ranges in the prompt were rejected (two €250 courses
defeat any range). The old metric punished fields that move no euro — six false
losses out of six.

**Apply.** Run 1 is preserved (`agent-score-run1-before-metric-fix.json`) so the
metric change is auditable. Result after the fixes: right stop proposals on all
five below-allowance profiles, −15 questions vs the filter, zero lost figures;
the gate guard fired 4 times — it is not decorative.

## Extracted fields show no confidence number

**Decision.** No `confidence` on document-extracted fields; every field gets
one label: "read from the document — please check".

**Why.** A vision model can name a number but it is not calibrated; a reader
takes 0.97 as a measurement and stops checking. Invented precision in a tax
tool is worse than none.

**Apply.** If reliability tiers are ever needed, derive them from checkable
facts (field missing, format unparsed, sum mismatch), not model self-reports.

## Done: `work_days` is split, and every fact is keyed by meaning

**Decision.** `work_days` meant the yearly total in `validation.py` and the
commute count in `calculations.py`. It is now three names, one per number:
`working_days_total`, `commuting_days`, `homeoffice_days` - in the catalogue and
in the calculator parameters alike. `maps_to` is gone with it, and a test asserts
what replaced it: a field that affects an amount must have a calculator parameter
of the same name, because the parameter models ignore a key they do not declare
and would drop the figure without a word (issue #36).

Done together with the key rename it was waiting for: a stored fact is keyed by
what it means, `commute.commuting_days` and `profile.employed_months`, never by
the category that consumes it (issue #61, shape decided in #14). The data
migration is `db/schema/0007_keys_by_meaning.sql`.

**Why now rather than later.** The deferral below was right at the time and had a
price attached: `work_days` is in the tool schema the model sees, so renaming
changes the tool contract and demands an eval rerun. What made it due is storage -
the old keys were already in `field_values`, and the same rename after twenty
testers arrive is a data migration on other people's tax data.

**Apply.** The eval rerun that the tool-contract change demands is not optional
and is not "next sprint": the live agent evaluation and `eval/collect.py` are
re-run once on the finished diff.

**Result of that rerun, 2026-09-08.** Both were run once, and the numbers above -
the 2026-08-21 run - are left standing rather than rewritten.

- *Interviewer*: 14 questions saved (15 on 08-21), zero amount-affecting fields
  lost, zero stops proposed where money remained, gate guard 3 times. Five of the
  ten profiles moved, in both directions. The filter arm is identical on all ten,
  so the deterministic path did not regress; that is not the same as showing the
  rename left the agent untouched, because the model reads the renamed ids in its
  prompt. Recorded as **run-to-run variability with no deterministic regression
  found**, and no further paid re-runs: re-running until the number looks better
  is what a frozen golden set exists to prevent. Both artifacts are kept
  (`results/agent-score-anthropic-claude-haiku-4.5[-after-key-rename].json`), and
  `eval/agent_score.py` now refuses to overwrite one - the rerun had silently
  replaced the recorded run, and only a diff noticed.
- *RAG*: `deterministic-after-key-rename.md` is identical to the recorded
  `lexical-cap-31` run except for the label and the cost - 111 of 112 checks, with
  the one failure being the `ml-en-commute` citation drift already recorded in
  `eval/SUMMARY.md`. No new failures.

**Not decided here.** Issue #14 asked for an ADR on separating a fact from the tax
category that consumes it, and this is only the half of that shape which had to
land before any tax data was written. The ADR is deliberately deferred to #62,
where it can be written against the whole thing - deduction class, allocations and
form placements - rather than against a namespace map on its own. Until then the
vocabulary lives in `CONTEXT.md` under **Fact key**.

## Chat feeds the case but never carries it in its prompt

**Decision.** Two entrances from chat to the case — a "compute for my case"
button under an answer, and extraction of facts mentioned in passing (confirmed
by the user) — both leaving the chat prompt untouched (ADR 0007). The interview
itself is never conducted in chat.

**Apply.** Answers may arrive from anywhere (interview, document, chat), but
every source confirms with the user before a value lands, and none puts the
case into the chat prompt. Chat-sourced facts are not credited to the agent in
the evaluation.

## KB moves to pgvector, but not in this sprint

**Decision.** Chroma → pgvector in the same Supabase Postgres, after the
sprint, together with making retrieval size-independent (ADR 0006). Target
scale: ×100 (~77k chunks), see PRODUCT_VISION.

**Why.** The lexical tier's substring search is unindexable in Chroma and
indexable in Postgres (`pg_trgm`); but `Retriever.search()` is a stable
interface, so nothing written in the sprint is written twice by waiting.

**Apply.** Acceptance: `lexical-cap` scores 91/91 again, else revert — never
retune the thresholds, they are what the Sprint 2 numbers mean.

## Everything year-dependent lives in one year-keyed module

**Decision.** Rates, caps, Pauschbetrag and form lines in one typed structure
per tax year (`domain/tax_years.py`, ADR 0008); chunk metadata carries
`tax_year` at ingest.

**Apply.** No new year-dependent value outside that structure — not in a
calculator, a prompt or the UI. Annual update: new Anlage N + Anleitung → KB →
check whether Zeilen shifted → rates → new year block. If anything else needs
touching, that is the defect.
