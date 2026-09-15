# Sprint 3 — agentic MVP

Rewritten for the actual assignment ([135.md](../135.md)) and the actual budget
(40 working hours plus weekends). The preceding version was written before the
assignment arrived and described roughly 120 hours of scope.

Product context: [[PRODUCT_VISION]]. The boundary between agent and ordinary code:
[[AGENT_ARCHITECTURE]]. Terminology: [CONTEXT.md](../CONTEXT.md). Decisions:
[[DECISIONS]] and `docs/adr/`.

## How the assignment requirements are covered

| Requirement in 135.md | Evidence |
|---|---|
| Agent purpose, value, target user | The Interviewer selects questions for the profile instead of presenting a fixed questionnaire; value is measured rather than claimed |
| Core functionality | End-to-end case → interview → calculations → review → report flow |
| UI for all functionality | Workspace with case list, case dashboard, interview, documents, review, and report, plus the existing chat tab |
| Technical decisions and error handling | The boundary between ordinary code, one LLM call, and an agent is documented; limits, spending cap, redaction, and HITL are included |
| Documentation with examples | README, `docs/adr/`, and the evaluation report |

Bonus credit requires two medium and one hard task. Six are claimed, nearly all as
consequences of the design rather than separate features:

| Task | Evidence |
|---|---|
| medium 1 — token and cost tracking | `core/pricing.py` already exists; results appear in the case UI |
| medium 2 — long-term memory | LangGraph checkpointer on Postgres; the case survives sessions |
| medium 4 — authentication and personalisation | Supabase magic link and a user-owned case ([ADR 0003](adr/0003-supabase-for-auth-and-state.md)) |
| medium 7 — multiple models | Interviewer and Reviewer use different models for independence, not a model switcher |
| medium 8 — security guard and settings | `core/security.py`, `/settings`, limits, and a spending cap |
| hard 1 — Agentic RAG | Retrieval inside gap finding and expense justification |
| hard 3 — AI evaluation report | RAGAS for RAG (26 cases already run) plus agent-versus-questionnaire metrics |
| hard 2 — observability | LangSmith with a redaction hook |

## End-to-end scenario

The user signs in by email link, creates a 2025 Tax Case, uploads documents such as a
Lohnsteuerbescheinigung and laptop receipt, confirms extracted fields, answers a few
targeted Interviewer questions, confirms a discovered Homeoffice-Tagespauschale gap,
receives seven categories of calculations with traces, passes an independent review,
resolves a finding, approves the case, and receives a report in which every amount has
a formula, document, KB citation, and Anlage N line.

## In scope

- Postgres tables are the case source of truth; the checkpointer stores only an
  unfinished graph run ([ADR 0005](adr/0005-tax-case-lives-in-tables-not-in-the-checkpointer.md)).
- Supabase authentication: magic link
  ([ADR 0003](adr/0003-supabase-for-auth-and-state.md)) plus Google OAuth as a second
  button during pre-demo polish. This protects the demo from Supabase's built-in
  limit of two emails per hour for the whole project. Elena must configure the Google
  consent screen and localhost/Vercel redirect URIs; code is one
  `signInWithOAuth` button. Verify that the same email first using a link and later
  Google resolves to one user. During the same polish phase, add custom Gmail SMTP
  and the localised templates in
  [supabase-email-templates.md](supabase-email-templates.md), and return `/settings`
  to navigation.
- A question catalogue of about 35 records (`id`, target field, answer type, en/de/ru
  text) is the only source of question wording
  ([ADR 0001](adr/0001-question-catalogue-instead-of-generated-questions.md)).
- Interviewer: bounded tool-calling loop, 40-round limit, and tools
  `list_open_questions`, `ask_question`, `run_gap_finder`, `run_validation`,
  `request_document`, and `conclude_interview`. The whole catalogue is not put into
  the prompt; the agent sees candidates filtered by case state.
- One typed tax-year keyed structure contains rates, thresholds, Pauschbetrag, and
  form lines ([ADR 0008](adr/0008-everything-year-dependent-lives-in-one-year-keyed-module.md)).
  `calculations.py` reads it using the case `tax_year`. Ingested chunks also get
  `tax_year`; retrieval filtering waits while only one year exists.
- Seven Werbungskosten categories tied to form lines
  ([ADR 0002](adr/0002-expenses-carry-official-form-lines.md)):
  Entfernungspauschale (27–34, with days in 29, total distance in 30, and car distance
  in 31; further workplaces in 35–42 and 43–50), Homeoffice-Tagespauschale (58 or 59,
  depending on whether another workplace was available), Arbeitsmittel and AfA
  (54–56), Fortbildungskosten (60), Telefon/Internet, Umzugskosten, and
  Bewerbungskosten (free-form `Sonstiges` lines 62–63, total in 64). Comparison with
  the Pauschbetrag is a case conclusion, not an expense category or form line. Lines
  were checked against [KB/Anlage_N_2025.pdf](../KB/Anlage_N_2025.pdf), because the
  instruction sometimes names a block where one line is needed.
- Gap finder for the same categories.
- Required-field and numeric contradiction validation in ordinary code.
- Reviewer: an independent agent on a stronger model, receiving only final case
  state without interview history, allowed to recalculate and retrieve from the KB.
- HITL for answers, extracted fields, the Interviewer's proposal to stop, Reviewer
  findings, and final approval.
- Report: printable Markdown with amount, substituted formula, document, citation,
  and Anlage N line per expense.
- Lohnersatzleistungen such as ALG I and Elterngeld constrain the employment period;
  the payment is collected and reported separately as belonging to Hauptvordruck,
  not Anlage N. Progressionsvorbehalt is not calculated.
- Vision document extraction; the file is discarded and only confirmed values remain
  ([ADR 0004](adr/0004-documents-are-read-then-discarded.md)).
- LangSmith redaction replaces fields from a fixed list (`gross_salary`,
  `employer_name`, `address`, `benefit_amount`) while leaving trace structure and
  agent decisions visible.
- Limits: at most two cases, 20 documents, and N daily calls per user, plus a global
  monthly spending cap that switches the product to read-only.
- Long-running steps: POST returns `run_id`, progress streams over SSE, polling is the
  fallback.
- Agent-versus-questionnaire measurement over ten profiles.
- Chat can feed a case in two ways without changing the chat prompt
  ([ADR 0007](adr/0007-chat-feeds-the-case-without-owning-it.md)): a “calculate for
  your case” button opens the interview; facts mentioned incidentally in chat are
  extracted in a separate call, confirmed by the user, and remove the corresponding
  interview question. The interview remains the primary path.
- The existing chat dialogue and prompt remain unchanged.

## Out of scope

- Moving the KB from Chroma to pgvector, deliberately scheduled after the sprint
  ([ADR 0006](adr/0006-pgvector-after-the-sprint.md)). `Retriever.search()` remains
  stable, so agent code does not depend on the move.
- A separate OCR stack using Tesseract and image preprocessing.
- Semantic LLM contradiction checking; numeric and logical checks remain.
- A second Anlage, Doppelte Haushaltsführung, or Grenzgänger.
- Progressionsvorbehalt and income-tax calculation in general.
- ELSTER filing; data is only prepared structurally.
- Turkish UI. `tr.json` remains in the repository, and README must explain the
  deliberate removal.
- Retaining uploads, rereading a document, or showing the scan beside the report.
- Improving bad scans; test documents are intentionally readable.
- Multi-year analytics, non-salary income, and non-resident scenarios.

## Measurement profiles

Ten synthetic profiles include both simple cases, where the agent should be modest,
and complex cases that show it is not merely asking fewer questions:

1. Remote employee, one employer, full year, two office days, 18 km, €1,400 laptop.
2. Daily 42 km commute with partial employer reimbursement; tests lines 51/52.
3. Expenses below Pauschbetrag; the correct conclusion is that itemisation is not
   useful and the agent stops.
4. Worked January–June, then ALG I; half as many work days and the benefit belongs in
   Hauptvordruck.
5. Five months of Elternzeit and Elterngeld, employed for the rest.
6. Changed jobs mid-year, two employers and distances; line 38 onward.
7. A flat-taxed minijob beside the main job; it must not enter Anlage N.
8. Training and equipment: a €380 monitor deducted immediately and a €1,400 laptop
   depreciated over three years.
9. Work-required relocation with Umzugskosten.
10. First job from September plus pre-employment Bewerbungskosten.

Profiles 3 and 7 are especially important because they test the ability not to ask
and not to suggest. Two profiles are duplicated with seeded Reviewer defects: an
expense without evidence and contradictory day counts.

## Work order

The budget table below is not the execution order. Risk is attacked first: the
hypothesis that the agent asks fewer questions without losing mandatory fields can
fail, whereas Postgres and screens are known work.

Start with the question catalogue because it defines the field schema and therefore
the database, baseline questionnaire, evaluation, `list_open_questions` filter, UI
control types, and report fields.

The first vertical slice tests the thesis in memory, without database, authentication,
or UI:

1. `domain/fields.py` for profile and category-required fields, and
   `domain/tax_years.py` for year-keyed rates, thresholds, Pauschbetrag, and Anlage N
   lines; migrate `calculations.py` to it.
2. `domain/questions.py`: about 35 records with id, target, type, and en/de/ru text.
3. `eval/baseline.py`: mechanically generate the questionnaire and obtain the first
   project number.
4. `eval/profiles.jsonl`: one or two profiles and a dictionary-driven answer script.
5. `agents/interviewer.py`: tool loop over in-memory state, 20-round limit, reusing
   existing calculations and validation.
6. `eval/agent_score.py`: run one profile and learn whether the thesis holds.
7. Reviewer with an adversarial prompt and one seeded defect, also in memory.

After that checkpoint: Supabase and tables, graph/checkpointer wiring, Lovable
screens, report, LangSmith and limits, then vision extraction, chat entry, and SSE.

Before the first code line, add `langgraph` and configure LangSmith so the first
Interviewer run is traceable. The explicit cost of this order is that visible UI may
not appear until halfway through the schedule; progress is measured in terminal
numbers first.

## Work budget

| Block | Hours |
|---|---:|
| Supabase, authentication, tables, checkpointer | 6 |
| Question catalogue: 35 records, fields, form lines, en/de/ru | 5 |
| Annual rates, thresholds, and form-line structure | 2 |
| Google OAuth button during polish | 1.5 |
| Gmail SMTP and localised templates | 1 |
| Return `/settings` to navigation | 0.5 |
| Interviewer tools, filtering, round limit | 6 |
| Seven calculation categories, including two new ones | 2 |
| Gap finder | 2 |
| Validation and numeric contradictions | 2 |
| Reviewer, stronger model, seeded defects | 4 |
| Markdown report and form lines | 2 |
| Frontend: seven Lovable screens, wiring, Russian | 10 |
| Evaluation: ten profiles, baseline, scorer, run, report | 5 |
| LangSmith and redaction | 1 |
| Limits and spending cap | 1 |
| Vision extraction | 3 |
| Chat entry button | 2 |
| Chat fact extraction and confirmation | 3 |
| SSE over `run_id` | 2 |
| Documentation, README, demo preparation | 3 |
| **Total** | **64** |

Against 40 planned hours; weekends consciously absorb the difference.

### Cut order

Defined before the final night:

1. Vision extraction (−3).
2. Fact extraction from chat (−3).
3. Umzugskosten and Bewerbungskosten plus profiles 9 and 10 (−3).
4. SSE (−2); polling already works.
5. Report print styles (−1).
6. “Calculate for your case” button (−2), cut last because it is cheap and visible.

Items 1 and 2 both import facts from outside the interview, so at most one should be
cut. If both appear necessary, retain chat extraction: it is cheaper, avoids file
handling, and does not inherit ADR 0004's constraints. Screens and the first eight
profiles are not cut because they are what the reviewer sees and what proves the
central hypothesis.

### Checkpoint

If Interviewer, Reviewer, and `agent_score.py` do not work together on at least one
profile by the end of week two, cutting begins immediately.

## Acceptance criteria

- A case survives a new session without data loss.
- On the same profiles, Interviewer asks fewer questions than the deterministic
  filter, not merely fewer than the questionnaire
  ([ADR 0009](adr/0009-the-measurement-has-three-arms.md)), without losing any
  amount-relevant field. Stop proposals are correct for below-Pauschbetrag profiles
  and absent when stopping loses money. Report measured numbers; if the agent adds
  nothing beyond the filter, record that a workflow is enough.
- On profile 3 it concludes that itemisation is not worthwhile; on profile 7 it
  creates no minijob record.
- Gap finder proposes Homeoffice-Tagespauschale and Entfernungspauschale only where
  appropriate.
- Calculations match exact golden values in unit tests with no LLM arithmetic.
- Reviewer finds both seeded defects.
- Every reported expense has amount, substituted formula, document, KB citation,
  and Anlage N line.
- The user can edit or reject anything before finalisation.
- Run cost and latency are logged and visible in the UI.
- Document-extracted values never appear unredacted in LangSmith traces.

## Evaluation

Two independent measurements share one entry point.

`golden.jsonl` and `checks.py` remain unchanged so Sprint 2's `lexical-cap` 91/91
result stays reproducible. Only four to six Umzugskosten/Bewerbungskosten questions
are added to cover the new RAG topics.

The agent arm uses `profiles.jsonl` and `eval/agent_score.py`. Each profile runs in
three branches ([ADR 0009](adr/0009-the-measurement-has-three-arms.md)):

1. **Questionnaire:** all 34 catalogue questions in fixed order.
2. **Filter:** model-free `relevant_questions()`, taking the first open question until
   none remain. Already measured: 13 questions on a simple profile, 20 for the remote
   laptop worker, 15 for profile 4, and 34 worst case.
3. **Agent:** Interviewer over the same filter.

Per-branch metrics are question count, irrelevant share, required-field completeness,
missed topics, discovered and missed seeded defects, cost, and latency. The difference
between filter and agent matters; the questionnaire is only an upper bound. It is
generated mechanically from the catalogue so its length cannot be chosen by the
evaluation author.

Failure is declared in advance if the agent misses a required field or asks more
questions than baseline.

## What is and is not measured

The profile-based agent-versus-questionnaire evaluation does not use chat: a script
answers interview questions from a dictionary. Facts arriving through chat therefore
cannot be counted as agent savings in the evaluation report. Vision extraction is the
same: it reduces real-world questions, but evaluation profiles upload no documents.

There are no unresolved sprint decisions.
