# Known limitations and Capstone backlog

Sprint 3 has been submitted. This document is now the planning baseline for the
Capstone project (status on 2026-08-29): it combines the external review's
recommendations with a fresh comparison of `PRODUCT_VISION.md`,
`AGENT_ARCHITECTURE.md`, `DECISIONS.md`, every ADR, the deployment/evaluation
documents and the live implementation. The passing Sprint 3 suites and evaluation
artifacts remain the baseline; they are not evidence that the unimplemented
product paths below work.

The Tax Case workspace is not enabled in production yet, so the first group is
the gate for that future rollout. Not every long-term vision item belongs in the
Capstone: the explicit non-goals near the end keep the scope bounded.

The labels are deliberate:

- **Before production** — a correctness, privacy or misleading-UX risk that
  must be resolved before real users enter tax data.
- **Technical debt / architecture** — the current implementation works for the
  Sprint 3 path, but its storage, execution or maintenance boundary is weaker
  than the architecture intends.
- **Capstone scope** — product, quality or scale work proposed for the Capstone;
  the recommended order distinguishes the core vertical slice from extensions.
- **Explicit non-goal** — intentionally not part of the current Capstone unless
  its brief changes.

## Before production

- [x] **Implement the real Documents workflow** (#16, model and failure behaviour
  decided in #11 and #65). The whole path is live: the file is checked by its bytes
  rather than by what the client claims, read twice by
  `google/gemini-3.7-flash` in memory, compared pass against pass, validated into a
  typed schema, corrected and confirmed by the user, and only then written to
  `documents` and `field_values`. The original file is never stored
  ([ADR 0004](adr/0004-documents-are-read-then-discarded.md)). The semantic check is
  there and reaches the screen: a receipt naming a Restaurant under Fortbildung is
  raised as a question rather than accepted. A signed-in user no longer sees fixture
  documents - the live screen and the demo screen are different components.
  **One line of the original wording is deferred, not implemented**: classification
  is rules first, and the RAG-backed model where the rules are ambiguous is
  [#91](https://github.com/TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1/issues/91).
  Until that lands, an invoice the word rules cannot place is categorised by the
  user, choosing from the four categories a document can land in.
  `packages/backend/scripts/check_vision.py` is the deploy gate for the one thing a
  model catalogue cannot answer: whether the configured model honours the strict
  schema, which `anthropic/claude-opus-4.7` claims and does not do (#65).
- [ ] **Complete the live Trace contract before calling the output a report.**
  `LiveReport` currently shows the amount, calculator breakdown and form line,
  while the richer document, provenance, official-source title and KB quotation
  exist only in the frontend fixture. Carry evidence plus the exact KB snapshot
  and chunk identifier from classification or justification into each Expense,
  verify that the quotation supports the claim, and render all of it in the live
  report and Markdown export. A formula without its document and source does not
  satisfy the central promise in `PRODUCT_VISION.md`.
- [x] **Implement or hide the non-functional Settings controls** (#18, decided in
  #70). Seven controls became real: theme puts the palette on the document and
  remembers it, response depth is a field on the ask request and a line of the
  generation prompt, trace visibility and conversation history are read by the chat
  page - history off also deletes what is already stored - and delete acts on a Tax
  Case the user picks, through the same operation and the same warning as the case
  list. Two left the screen: Export, until the operation behind it exists, and
  “improve the model with my chats” for good, since every call already carries a
  zero-data-retention policy and a switch that cannot change the outcome is not a
  privacy control. The account card names the real sign-in, and the three sections
  that were hard-coded English are in all four catalogues.
- [x] **Make the two product modes and their availability unmistakable** (#19).
  `/scope`, linked from the navigation beside the two modes and from the landing
  page, names both modes, whether each is open on this instance and why not,
  where each one leaves something behind, every tax year with its filing
  deadlines and the forms its figures land on, the demo's enforced limits, and
  what the build refuses to do. The storage answer is four separate claims, not a
  boolean: what the server keeps, what this browser keeps, what the profile memory
  remembers after the case is deleted, and where traces go. A single
  `stores_data: false` read on screen as "keeps nothing about you" while the chat's
  history sat in `localStorage` and travelled back with the next question.
  Nothing on the page is written twice: it renders
  `/api/v1/meta/scope`, which reads `domain/tax_years.py` and `Settings`, so a
  year added to the rules appears there without anyone editing the page and a
  claim cannot outlive the build that made it true. The synchronisation the
  rollout note asks for is `tests/test_scope_statement.py`, which fails when the
  statement and the rules disagree. When the endpoint cannot be reached the page
  shows nothing rather than a remembered copy.
- [ ] **Make interview advances idempotent.** A broken SSE connection can fall
  back to the plain endpoint after the server has already accepted the answer,
  sending the same value into the next pause. Add a pause/version identifier,
  reject stale resumes on the server and reconnect without resending an
  ambiguous answer.
- [ ] **Move long-running model work out of the request process.** The SSE POST
  currently executes the Interviewer, gap justification and the full Reviewer
  pass inside the HTTP request; the plain fallback executes the same work again.
  Use a durable job/run boundary with an idempotency key, persisted status and
  events, then let SSE subscribe and polling read the same run. A process restart,
  proxy timeout or reconnect must not lose work or repeat a paid side effect.
- [x] **Remove the duplicate `RATE_LIMIT_PER_IP` entry from `render.yaml`** (#22).
  The second entry said 10 a minute and won, because a Render blueprint is a YAML
  list and the last key of a name is the one that takes effect - so the deployed
  limit was the one the comment three lines above it argued against, and an
  interview of roughly sixteen requests was being cut off. 60 stands alone now.
  `tests/test_render_blueprint.py` reads the file as text and groups each key by
  the service block it sits in - not because a loader would miss the repeat
  (`envVars` is a list, so `yaml.safe_load` keeps both entries), but because a
  name is only duplicated when it appears twice inside one service.
- [ ] **Bring LangGraph persistence under the data-lifecycle contract.** Put
  checkpoint/store tables in a private schema or explicitly restrict them, and
  delete a case's checkpoint when the case is deleted. Tax answers must not
  remain as orphaned graph state after the UI says the case is gone.
  **Half done:** deleting a case now clears `checkpoints`, `checkpoint_blobs` and
  `checkpoint_writes` along with the tables (`services/case_erasure.py`), and the
  `store` table has a delete of its own (`services/profile_erasure.py`) so what the
  system remembers about a person can be reached at all. The access restriction is
  still open, and it covers all four tables - none of them carry row level security.
- [ ] **Implement an honest user-data lifecycle across every store.** Define and
  expose export, delete-case, delete-profile-memory and delete-account operations
  across relational tables, LangGraph checkpoints, the user-level LangGraph Store,
  local chat history and any LangSmith traces. Profile memory intentionally
  outlives a Tax Case, so deleting a case and deleting remembered person-level
  facts must be separate choices. Replace the four-name telemetry redaction list
  with schema-driven data classification, and document the tracing region,
  retention and deletion policy before sending real tax data to a third party.
  **Partially done - reduced September scope.** A successful case deletion now
  removes the relational case cascade and its LangGraph checkpoint together, and
  delete-all-my-cases exists beside it; the tracing region, retention and deletion
  policy are written down in `docs/TRACING_POLICY.md`, and traces go to the EU
  region, pinned by `LANGSMITH_ENDPOINT` in `render.yaml`. The four-name redaction
  list is gone: what leaves in cleartext is now derived from `domain/fields.py`, so
  a field added to the catalogue is covered the same day rather than when somebody
  remembers. Forgetting a person is a separate operation now too
  (`services/profile_erasure.py`, `DELETE /api/v1/profile/memory`), beside deleting
  their cases and not implied by it. Browser chat history, LangSmith trace deletion,
  and export and delete-account remain open, the last two in the account-wide issue.
- [x] **Keep the tests off the production database, and off the real provider**
  (#90). Two Supabase projects and one `DATABASE_URL` meant the integration suite
  ran against whichever project the string named - creating and deleting Tax Cases,
  clearing checkpoints, borrowing a row out of the `schema_versions` ledger. The same
  was true of the provider: `Settings` reads `.env`, so the real `OPENROUTER_API_KEY`
  was loaded on every run with nothing but a per-file override in the way. Both are
  closed by construction now: `TEST_DATABASE_URL` is the only DSN a test process has
  and the development project carries a marker row the suite checks for
  (`tests/dbguard.py`), and `tests/conftest.py` blocks the two constructors every
  paid provider call passes through.
- [ ] **Take the synchronous database calls off the event loop** (#74). The async
  routes in `api/routes/cases.py` call the synchronous psycopg repository directly
  - `_advance_events` and `step_back` both do - so every one of those queries
  blocks the loop for the whole round trip to Supabase, and with it every other
  request the single worker is serving. `services/case_erasure.py` goes through
  `anyio.to_thread.run_sync` and is the shape the rest should take; it was left as
  the only one because rewriting the interview's hot path days before a hand-in is
  its own risk.
- [ ] **Apply every schema change during rollout.** The production checklist
  must include `0003_remembered_values.sql` — otherwise cross-year memory fails
  soft and appears to work while carrying nothing over — and
  `0004_finding_category.sql`, without which no finding can be stored at all.
  **Checklist rewritten** (`db/README.md`, now four steps including the 0005
  ledger), and a forgotten file no longer fails soft: the schema check refuses the
  Tax Case routes and names it. Applying them is still by hand.
- [x] **Validate every resume payload on the server** (#26). `domain/resume.py`
  checks each reply against the pause that is waiting for it - the catalogue
  question's type, range and option list, real booleans rather than the string
  "false", decisions only for positions that pause offered, and rejected
  carry-over keys only from the keys it showed. It runs before the quota is spent
  and before anything is written, so a refusal spends no interview quota and
  leaves no half-answered case - the request itself is still counted by the
  per-IP and global rate limiters, which sit ahead of the handler. A reply that
  arrives with no pause waiting for it is refused too (422): that branch used to
  fall through to starting a fresh run, which is the one path validation could
  never see, and it spent a call on the way. The graph's own readers stay lenient
  on purpose: they are reached from the tests and the evaluations as well as from
  the browser.
- [ ] **Do not let unresolved data disappear at stop or final approval.** “I don't
  know” currently marks a Question as asked but stores no value; a started but
  uncomputable category can then be omitted by `expense_rows`, leaving the
  Reviewer nothing to audit. The cautious Assumption declarations from
  [ADR 0010](adr/0010-the-system-may-assume-but-never-silently.md) are not wired
  into the live interview either. List every missing required field, incomplete
  category, unresolved Gap and unconfirmed Assumption at the stop/final gates;
  require a correction, document, explicit exclusion or visible cautious
  Assumption before finalisation.
- [ ] **Give the user a complete correction path.** The live workspace can undo
  only the last answer; it cannot edit an arbitrary earlier answer, a document-
  sourced value or one item among repeated expenses. Add an auditable case editor
  that reopens downstream calculation and review when a value changes. “Human in
  the loop” is not complete if the human can see a wrong value but cannot correct
  it where it is shown.
- [ ] **Make Reviewer coverage and human resolutions explicit.** The live Reviewer
  has calculator and deterministic-validation tools, but no KB retrieval tool and
  no document/citation input despite the architecture promising both. When its
  provider fails, `from_model`/the degraded-review note is not persisted or shown,
  so a rules-only pass can look like a full independent review. Finding
  `resolution` and `note` columns are also never updated: “dismiss” is only a graph
  routing action. Give the Reviewer snapshot-scoped retrieval and evidence, store
  the review run/model/mode, and persist each user's fixed/dismissed resolution and
  rationale without exposing the interview dialogue.
- [ ] **Enforce one draft/final export contract.** The architecture says no report
  is generated before approval, while the current report page and official Anlage
  N endpoint deliberately allow a watermarked draft before finalisation. Decide
  and document the intended contract; if drafts remain, make the watermark and
  unplaced-field warning unavoidable, and allow an unmarked final export only from
  a finalized, fully reviewed Tax Case.
- [ ] **Fail safely across the documented error scenarios.** Empty or irrelevant
  retrieval must not produce an unsupported tax claim or citation; contradictory
  inputs and implausible amounts must be surfaced for correction; out-of-scope
  questions must stay out of scope; and LLM failures or timeouts must preserve
  the Tax Case and offer a safe retry. Turn this list into explicit acceptance
  tests rather than relying on the happy-path smoke test.

## Technical debt and architecture

- [ ] **High priority: separate KB ingestion from application deployment and
  runtime.** Today `KB/` lives in the application repository and `render.yaml`
  rebuilds the Chroma store and regenerates all embeddings during every backend
  build. Move the source documents and indexing pipeline out of the application
  repository and deployment artifact into an independently versioned KB/ingestion
  boundary: a dedicated service, release job or container that validates
  documents, chunks them, creates embeddings and writes to persistent
  pgvector/Postgres storage. Give the application backend read-only retrieval
  access so a KB release can be indexed, verified, activated or rolled back
  without rebuilding the backend, and so an indexing failure cannot take an
  otherwise healthy application deployment down. This extends the store migration
  already accepted in [ADR 0006](adr/0006-pgvector-after-the-sprint.md): the
  boundary between ingestion and retrieval is as important as the choice of store.
  The migration is complete only when it also replaces collection-size constants
  such as `LEXICAL_MAX_MATCHES` and `FETCH_K`, adds the `pg_trgm` lexical index,
  JSONB topic metadata and a partial index per `form_id`, and has a measured HNSW/
  embedding-dimension plan for the 10–20k and 77k-chunk targets. Re-run the
  deterministic suite and `k_sweep.py`; the current `lexical-cap` behaviour must
  remain 91/91 rather than being retuned until it passes.
- [ ] **High priority: version the KB and enforce temporal retrieval.** `tax_year`
  and `source_type` already reach chunk metadata, but retrieval does not yet filter
  by tax year and there is no immutable KB snapshot. Add `kb_version` or
  `snapshot_id`, `validity_period`, a controlled `source_type` and
  `ingestion_version` to every document and chunk. Filter retrieval by the Tax
  Case year, record the selected snapshot in response provenance and evaluation
  artifacts, and support activating, comparing and rolling back snapshots. A
  2024 rule must never enter a 2025 answer merely because it is semantically
  similar.
- [ ] Persist the interview audit and computed expenses in the relational
  `answers` and `expenses` tables. They are declared as the Tax Case source of
  truth, but today that history lives only in graph state while `field_values`
  holds the latest answers. Findings are done: they are written at each review
  and read back by the Review screen. Expenses are deliberately still computed
  on read, so a stored figure can never disagree with the rules.
- [ ] **Complete repeated Expense items end to end.** The field-value shape and
  calculators can sum multiple item indexes, but the catalogue/UI cannot add,
  edit or remove another item, the Reviewer does not preserve each `item_index`,
  and the report trace is built only from item zero. Capture, persist, recompute,
  review and report each item separately before aggregating the category total.
- [x] **Remove the ambiguous calculator field `work_days`** (#36, done with #61).
  It meant total yearly working days in validation and commute days in the
  Entfernungspauschale calculator, and `maps_to` hid the mismatch. Now three names,
  one per number - `working_days_total`, `commuting_days`, `homeoffice_days` - in the
  catalogue and in the calculator parameters alike; `maps_to` is deleted and a test
  holds the invariant that replaced it. Both evaluations were re-run once as
  `DECISIONS.md` requires, and both results are recorded there rather than the older
  numbers being rewritten.
- [ ] **Get every year-dependent figure back into the year files before adding a
  second year.** Rates and form lines are supposed to live only in
  `domain/tax_years.py` (ADR 0008), but 2025 and the 1,230 EUR Pauschbetrag are still
  written directly into the Interviewer prompt, the Question wording, frontend
  messages, the case-creation constant, the Chroma collection name and the form
  assets. Pass the tax year in to the prompts, question catalogue and UI instead, and
  add an automated repository check that fails if a year or a year-dependent amount
  appears in any file other than that year's own file. Read together with "Add a tax
  year by adding files" below: this is what makes that possible, and the check is what
  keeps it true.
- [ ] **Automate schema rollout and test migration drift.** The deployment guide
  still tells an operator to run only migrations 0001 and 0002 by hand even though
  0003 and 0004 are required. Add a versioned migration runner, a production
  preflight that compares expected/applied versions, and a reproducible local or
  ephemeral Postgres/Supabase integration environment instead of discovering
  schema drift in the hosted project.
  **Mostly done.** The comparison exists and is enforced rather than reported:
  `db/schema_version.py` checks the `schema_versions` ledger (0005) against a probe
  per version, the Tax Case routes answer 503 naming the file that is missing, and
  `tests/test_schema_version.py` owns the invariant. The runner is
  `db/migrate.py` (`python -m db.migrate`, `--dry-run`, `--db-url`): it applies what
  is missing one transaction per file, records each version, baselines a file the
  probes find already present, and refuses a database that contradicts its own
  ledger. Verified against the development project: the probes, the plan, and the
  write path (`tests/test_migrate.py` borrows the 0005 ledger row and puts it back).
  Still owed: no local or ephemeral Postgres, so migrations are rehearsed only
  against hosted projects. One branch of the runner has therefore never executed -
  `apply`, which runs a file's SQL against a database that does not have it yet.
  Both projects already hold every file, so there is nothing behind to apply to, and
  the branch will make its debut on whatever the next real migration is, against
  live data. The Supabase CLI is not the way out of that: it is closed for
  migrations in ADR 0003. Carried as issue #72, after 15 September.
- [ ] **Instrument the agent workflow, not only the stateless chat.** Interviewer,
  gap-justifier and Reviewer usage values are discarded in the live path. Persist
  run-level model/version, calls, tokens, latency, cost, fallbacks and tool outcomes
  with redacted inputs, and expose a safe operational view. LangSmith traces alone
  do not satisfy the product's own visible cost/latency acceptance criterion.
- [ ] **Move chat rate limits to shared storage before horizontal scaling.** `/ask`
  limits are process-local, so N workers or instances multiply the effective
  global budget. Keep the current simple limiter for one Render worker, but use
  Redis/Postgres or an API-gateway limit before scaling beyond it; reuse one budget
  policy for every new provider-spending endpoint.
- [x] **Consolidate backend dependency management** (#41). The pinned
  `requirements.txt` is now the only place a version is written; `pyproject.toml`
  keeps the pytest configuration and nothing else. Test-only packages moved to
  `requirements-dev.txt` so Render stops installing pytest into production. The
  ignored `CHROMA_PERSISTENCE` setting is gone, and `browse_chroma.py`'s semantic
  search embeds the query through `core/embeddings.py` instead of leaving it to
  Chroma's bundled MiniLM.
- [ ] Add integration coverage for stream interruption after an accepted
  answer, checkpoint cleanup on case deletion, live Documents routing, empty or
  irrelevant retrieval, contradictory inputs, unsupported topics, LLM
  failure/timeouts, invalid amounts, and the production deployment manifest.

## Capstone product, quality and evaluation scope

- [ ] **Cover the forms an employed filer actually files, not Anlage N alone.**
  Decided on 2026-08-29: a real return is never one sheet, so the product's unit is
  the *return of an employed person*, not a single form. The set stays bounded by the
  filer — only what an Arbeitnehmer files — and the specific list is still to be
  supplied. It is deliberately not guessed here; no question text or form line should
  be written against a form nobody has named yet.

  Part of the material is already indexed. `KB/` holds the Hauptvordruck (ESt 1 A)
  and its Anleitung, Anlage N-DHF, Anlage N-AUS, Anlage N-Gre and Anlage
  Mobilitätsprämie, all as 2025 documents. The Python code is already prepared for
  more than one form as well: every form line carries a `FormLine.form` field saying
  which form it belongs to, and one figure — Einkommensersatzleistungen — is already
  recorded against the Hauptvordruck rather than Anlage N. So the code was never
  written for Anlage N alone; only the filled-in content stops there.

  The storage layer is where the gap is real. `db/schema/0001_tax_case.sql` has **no
  form dimension at all**: `expenses.form_line` is free text and the form's identity
  survives only in Python. And `expenses.category` carries a hard-coded
  `check (category in (...))` repeating the seven members of `ExpenseCategory`, so
  every new category — let alone a new form — needs a migration. That is precisely
  the coupling the file's own header claims to have avoided ("A column per field would
  have to be migrated every time a category is added, and the catalogue is expected to
  grow"): `field_values` escaped it, `expenses` reintroduced it. Move the category
  vocabulary out of the constraint and give expenses and form lines an explicit form
  key *before* the set starts growing, not after.

  Open, and to be settled before the first added form:

  - Does one Tax Case span every form of the year, or does each form get its own
    case? `unique (user_id, tax_year)` currently assumes the former; nothing else in
    the schema commits either way.
  - How does the interview decide *which* forms apply to this filer? Relevance is
    per person, and asking every question of every form is the failure mode to avoid.
  - Which forms need capturing rather than computing. The Hauptvordruck's
    Einkommensersatzleistungen mostly arrive electronically and are entered only to
    deviate from the transmitted figure — capture, no calculation.
  - Whether the deliverable is one filled PDF per form, and how a multi-form export
    is assembled, marked draft/final and reviewed as a whole.
  - Where the ordering sits against the core work below. This decision moves forms
    out of the non-goals; it does not by itself decide that they precede the
    truthfulness, traceability and KB-release work.

- [ ] **Add a tax year by adding files, never by editing the years already there.**
  Decided on 2026-08-29 as a standing constraint on everything else in this file.
  Adding 2026 must mean: write a new file holding 2026's rates and form lines, add
  2026's documents to the knowledge base, add 2026's form PDF and its measured field
  positions. Nothing else. No database migration, and no edit to any file that
  describes a year already supported.

  **2025 must stay frozen.** Once a year's rules are written down they are the record
  of what that year's law was, and they stop changing. This is not tidiness: filing a
  voluntary German return is allowed for four years back, so somebody sitting down in
  2026 may well be filing 2025 for the very first time, and 2027 will still have 2025
  users. A file that mixes several years is a file that gets edited every year, and
  every edit is a chance to move a figure out from under a return that already used
  it.

  That means `domain/tax_years.py` has to be split before 2026 arrives. Today it holds
  three different things in one file: the shape of a tax year (the `TaxYear` and
  `FormLine` dataclasses), the content of 2025 (`YEAR_2025`), and the lookup
  (`TAX_YEARS`, `for_year()`). Only the first and third are shared. Give each year its
  own file — 2025's content moves out unchanged — and let the lookup find the year
  files rather than listing them, so that adding 2026 adds a file and touches no
  existing one. Keep `for_year()`'s current behaviour exactly: asked for a year it does
  not have, it fails loudly and names the years it does, because quietly answering with
  another year's rates would put a wrong number on a tax return.

  Some of what this needs already holds and is to be preserved rather than
  rediscovered: `tax_cases.tax_year` is a plain integer checked only against
  2020–2100, so a new year needs no migration; `field_values` is key/value JSONB, so
  new fields need none either; and `services/anlage_n_pdf.py` already looks up its
  field positions per year, as `forms/anlage-n-<year>-boxes.json`.

  What blocks it is listed elsewhere in this document and is hereby reclassified from
  cleanup to year-groundwork: the hard-coded 2025 and 1,230 EUR in the Interviewer
  prompt, Question wording, frontend messages and case-creation constant; the single
  Chroma collection with no snapshot and no year filter, which lets a 2025 rule be
  retrieved into a 2026 answer; and the year-named assets themselves.

  One honest limit. The year cannot be finished early: the 2026 Anlage N, its
  Anleitung and the confirmed rates do not exist until the Bundesfinanzministerium
  publishes them, and the box map has to be measured against the real PDF. What can
  be done now is removing every reason the year would need anything beyond those
  documents — which is also the cheapest way to keep the multi-form work above from
  hard-coding a year a second time.

- [ ] **Widen the Werbungskosten catalogue.** Seven categories are covered today
  (`domain/fields.py`), and the interview can only ask what the catalogue holds
  ([ADR 0001](adr/0001-question-catalogue-instead-of-generated-questions.md)) —
  so an expense outside it is silently lost, however well the knowledge base
  knows the rule. The gap is sharper than it looks: § 9 EStG and the BMF letters
  are already in `KB/`, so the chat can answer about these while the interview
  cannot ask about them.

  Candidates, each to be confirmed against `KB/` and given its Anlage N line
  before any question text is written — the line numbers below are not yet
  verified:

  - **Job-related insurance**, the item that prompted this entry. Only the
    work-related share is deductible and the split is the whole difficulty: a
    Rechtsschutzversicherung deducts only its *Arbeitsrechtsschutz* portion, and
    the insurer's statement is what states it; an Unfallversicherung splits
    between the occupational share (Werbungskosten) and the private one
    (Sonderausgaben); a Berufshaftpflicht is job-related throughout. This is
    also the only candidate here with **no KB document behind it yet** — the
    knowledge base would have to grow first, or the interview would ask a
    question the Reviewer cannot check.
  - **Berufsverbände and Gewerkschaftsbeiträge** — fully deductible, common,
    carries across years unchanged, and has its own line on Anlage N. Probably
    the cheapest of these to add and the most often applicable.
  - **Reisekosten** for work travel not covered by the employer, including
    Verpflegungsmehraufwand. `reisekosten-bmf-2024-12-02` is already indexed.
  - **Doppelte Haushaltsführung** — a second household kept for work.
    `056-anleitung-anlage-n-doppelte-haushaltsfuehrung-2025` is indexed and the
    form's own guidance is in it.
  - **Häusliches Arbeitszimmer** as the alternative to the Tagespauschale
    already covered, which makes it a choice between two treatments rather than
    a new sum — the interview would have to ask which applies, not add both.
  - **Typische Berufskleidung** and its cleaning, narrow on purpose: ordinary
    clothing does not qualify however exclusively it is worn for work.
  - **Kontoführungsgebühren**, the customary 16 EUR. Small, but it is the kind
    of figure a filer never remembers and the interview could simply offer.

  Each addition has to satisfy what the existing categories already do, and that
  is the real cost of one: a line on the form
  ([ADR 0002](adr/0002-expenses-carry-official-form-lines.md)), its rule in the
  year-keyed module ([ADR 0008](adr/0008-everything-year-dependent-lives-in-one-year-keyed-module.md)),
  a decision on whether it carries into a second year
  ([ADR 0011](adr/0011-a-second-return-remembers-what-the-year-does-not-change.md)),
  question text in every locale, and a seeded defect in `eval/seeded.py` so the
  Reviewer is measured on it rather than assumed to handle it. A category added
  without the last of these is a category nobody checks.

- [ ] **Expand and structure the official-source coverage.** Track a coverage
  matrix by form, tax year, catalogue category and source authority; fill the
  gaps needed by the supported Anlage N workflow first, including the missing
  insurance source above. Add adjacent Anlage only together with an explicit
  product-scope change, year metadata and evaluation cases, so a broader KB does
  not silently promise a broader filing product.
- [ ] **Add a second supported tax year only as a complete vertical package.**
  It requires the official Anlage N and Anleitung, rates/caps/form lines, blank
  PDF and calibrated box map, a versioned KB snapshot and filtered retrieval,
  year-aware Question/UI wording, migration tests and evaluation cases. This is
  also what finally activates profile memory; before then the measured carry-over
  saving is an offline projection, not user-visible value. Reconcile memory on
  undo/edit/delete and promote only confirmed values — today every answer is
  remembered immediately while stepping back clears only the Tax Case copy.
- [ ] **Implement the two chat-to-case entrances from ADR 0007.** Add “use this in
  my Tax Case” beneath an answer and a separate structured fact-extraction call
  over the user's message, both with explicit confirmation and provenance before
  writing `field_values`. Do not put Tax Case state into the RAG chat prompt, and
  do not conduct the typed interview inside chat.
- [ ] **Make locale part of the Tax Case and agent run.** Question controls are
  localized by the frontend, but Interviewer rationales, gap justifications,
  Reviewer findings and calculator traces are generated or stored in English;
  the gap justifier explicitly requests English. Persist `ui_language`, pass it
  to every model/text formatter, store locale-neutral structured facts where
  possible, and test a full Tax Case in de/en/ru/tr rather than only the chat.
- [ ] **Expand the agent evaluation beyond the current ten synthetic profiles.**
  Keep the existing three-arm benchmark as the controlled comparison, then add a
  separate robustness set with realistic edge cases and adversarial combinations:
  contradictory profile answers, unsupported tax topics, missing or irrelevant
  retrieval, implausible amounts, repeated items, model failures and interrupted
  sessions. Report results by scenario and severity so the larger suite is
  evidence of robustness rather than a larger smoke test.
- [ ] **Strengthen RAG evaluation at chunk level.** The current document-level
  `context_hit` can pass when the expected document arrived but the chunk carrying
  the answer did not; the domestic Verpflegungsmehraufwand case demonstrates this.
  Correct the reference authority, add answer-bearing chunk expectations, and
  compare a reranker/query-language strategy over the top candidates instead of
  increasing `k`. Grow toward 100+ cases, deeper multilingual coverage, realistic
  traffic-derived questions, multiple judges/model candidates and cost-quality
  curves before making statistical superiority claims.
- [ ] **Add product validation, not only technical evaluation.** Run moderated
  usability/accessibility sessions over the complete Tax Case, measure completion,
  abandonment, corrections, trust in Trace and understanding of RAG Assistant
  versus Tax Case, and feed anonymised production failures back into the scenario
  sets under an explicit consent/retention policy.
- [ ] **Audit frontend resilience and accessibility as a product-wide concern.**
  Standardise loading, empty, error and retry states; verify keyboard and screen
  reader behaviour; keep asynchronous case state recoverable; and strengthen
  component boundaries and tests around those states. Preserve the landing
  page's concrete examples, honest Anlage N/2025 scope and multilingual entry
  points while doing so.

- [ ] **Harden authentication and hosting for real users.** Replace the project-
  wide two-emails-per-hour built-in mailer with custom SMTP and/or OAuth, localize
  the first-contact email reliably, configure preview redirect URLs where previews
  are used, and either remove the free-tier cold start or make every long wait and
  retry state explicit. Keep the templates and sender identity under release
  control rather than as an undocumented dashboard dependency.

- [ ] Return interview progress from the backend so a refresh does not reset
  the visible answered-question count to zero.
- [ ] Finish Turkish question-catalogue coverage or clearly label the current
  English fallback, and keep the document `lang` attribute in sync with the UI
  locale.
- [ ] Translate backend error codes into user-facing locale messages instead of
  displaying raw English details.
- [ ] Replace internal form identifiers such as `anlage_n 27-50` with readable,
  localised labels while preserving the exact identifier in exported data.

## Explicitly outside the current Capstone

- Direct submission through ELSTER, tax-advice positioning, and an unreviewed
  “file this for me” flow remain out of scope. The Capstone may prepare structured
  data and a clearly marked draft/final document, but the human files it.
- Self-employment, capital gains, VAT, corporate tax and non-resident cases remain
  out of scope. **The boundary is the filer, not the form count** — decided on
  2026-08-29, replacing the earlier rule that a second form was out of scope at all.
  What an employee (Arbeitnehmer) files is in scope; what belongs to another kind of
  filer is not. A form still earns its place only with its own KB sources, form
  lines, calculators and evaluation cases: adding one to demonstrate more agents was
  never a reason and still is not. See "Cover the forms an employed filer actually
  files" above for what one costs. Progressionsvorbehalt *calculation* stays out of
  scope — capturing an Einkommensersatzleistung is not the same as recomputing the
  rate on every other kind of income.
- Storing original payslips/receipts, showing scans later and building a permanent
  document archive remain excluded by ADR 0004. The product stores only the file
  name and user-confirmed structured values unless a new privacy decision replaces
  that ADR.
- Building the full 77k-chunk corpus is not the Capstone deliverable. The ingestion,
  storage, indexes, metadata and evaluation must be designed and load-tested for
  that target; populating roughly ten Anlagen is later content work.
- A third agent or an agent per document/calculator/category remains out of scope.
  Documents, calculations, validation, rendering and migration stay deterministic
  workflows or bounded single calls unless a new irreversible trade-off justifies
  another ADR.

## Non-regression constraints

The infrastructure, KB and frontend work above must preserve the parts that are
already strong: deterministic tax calculations with the formula, substituted
values, official form line and provenance visible to the user; hybrid retrieval
with inspectable citations; database RLS plus backend user filtering; and the
explicit boundary between deterministic rules and agent decisions. Add regression
coverage before changing those boundaries.

## Recommended Capstone scope and order

1. **Core — make the live product truthful and recoverable.** Remove fixture and
   inert privacy UI, close the data-lifecycle/delete contract, validate and version
   every resume, and introduce durable idempotent execution for long runs.
2. **Core — complete one traceable Tax Case vertical slice.** Real document intake
   and confirmation → relational answers/expenses → repeated-item editing →
   evidence-capable Reviewer with persisted resolutions → finalized report/PDF
   carrying document provenance and snapshot-scoped KB citations.
3. **Core — build the KB release boundary.** Independent ingestion, persistent
   pgvector/Postgres, immutable snapshots, validity metadata, tax-year filtering,
   rollback and the scale-dependent indexes/acceptance evaluation from ADR 0006.
4. **Core — prove robustness.** Acceptance tests for failure/reconnect/privacy
   scenarios, expanded agent profiles, chunk-level RAG evaluation, multilingual
   end-to-end cases and frontend accessibility/usability validation.
5. **Extension — activate product breadth only after the core passes.** A complete
   second tax year, the employee forms beyond Anlage N, chat-to-case entrances,
   broader Werbungskosten catalogue/KB, production auth polish and shared
   multi-instance limits. Treat these as separate scope decisions rather than
   allowing all of them to enter the core implicitly. The 2026 groundwork is the
   exception: it is a constraint on how the core is built, not a later step, because
   retrofitting a year seam costs more than keeping one.

Review this list before enabling the Tax Case environment variables in Vercel
and Render. Completed items should be removed or linked to the ADR or test that
now owns the invariant.
