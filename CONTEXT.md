# German Tax Assistant

A tool that helps an employee in Germany prepare the deductible-work-expenses
section of their income tax return, and shows the reasoning behind every figure
it produces. This glossary fixes the vocabulary used in code, in the UI and in
`docs/`. It is a glossary only — decisions live in `docs/DECISIONS.md` and
`docs/adr/`.

## The case

**Tax Case**:
One user's working file for one tax year. Holds the profile, documents,
expenses, answered questions, review findings and the report.
_Avoid_: case (alone), дело, declaration, filing, session, workspace

**Profile**:
The set of facts about the user's situation for that tax year — employment
type, number of employers, employment period, remote work, commute distance.
Distinct from the expenses it makes relevant.
_Avoid_: user data, answers, settings

**Tax year**:
The year a Tax Case covers. Not a label but a dimension: every rate, threshold,
allowance and form line belongs to exactly one tax year, and German ones change
between years.
_Avoid_: year, period, Veranlagungszeitraum, fiscal year

**Tax-year knowledge snapshot**:
The immutable collection of official sources and derived knowledge used for one
Tax year. A later Tax year gets a separate snapshot; historical sources are never
replaced by whichever text is currently published online.
_Avoid_: current KB, updated KB, latest knowledge base

**KB ingestion**:
Reading the official sources in `KB/`, chunking them, embedding every chunk and
writing the corpus into Postgres. It produces a Tax-year knowledge snapshot and
never touches a user's own documents — those are the filer's **document intake**,
which is a different act on different files.
_Avoid_: document intake, ingestion (alone), indexing, import

**Carried-over value**:
A value in a Tax Case that this user answered in an earlier year and that the tax
year does not change — the commute distance, whether they drive it, whether the
employer provides a desk. It has provenance `remembered`, is unconfirmed until the
user sees it on the stop card, and is never a gate question. The person-level
memory it comes from is the **profile memory**, which belongs to the user and
outlives every case (ADR 0011).
_Avoid_: prefill, default, cached answer, last year's data

**Finalized**:
The state a Tax Case enters once the user approves the report. A finalized case
is read-only; changing it requires reopening it, which produces a new report
revision.
_Avoid_: submitted, filed, closed, done

## Money in the case

**Expense**:
One deductible item in a Tax Case: a category, an amount, the trace that
produced the amount, the document backing it, and the form line it belongs to.
_Avoid_: cost, deduction, item, entry, position

**Provenance**:
Where one value in a case came from: an answer the user gave, a document it was
extracted from, or an assumption the system offered. Recorded per field, so a
figure can be traced value by value rather than only as a whole.
_Avoid_: source, origin, evidence type

**Assumption**:
A value the system proposed because the user could not supply it. Allowed only
where the cautious reading is obvious, always visible as an assumption, and
confirmed before a report exists — an unconfirmed one reaching the report is a
defect. Never used where assuming would enlarge the claim.
_Avoid_: default, fallback, guess, estimate

**Trace**:
The record of how an amount came to be: which formula, which values were
substituted, which document supplied them, and which official passage allows
the deduction. The product's central promise — never omit it from an Expense.
_Avoid_: explanation, audit log, reasoning, provenance

**Form line**:
The numbered line of the official paper form that an Expense is entered on,
for example Anlage N Zeile 58 for home-office days. Recorded per Expense so the
report tells the user where each figure goes.
_Avoid_: field, Zeile (alone), box, position

**Gap candidate**:
A deduction the profile suggests the user is entitled to but which no Expense
covers yet. Becomes an Expense only after the user confirms it.
_Avoid_: suggestion, missed deduction, opportunity, recommendation

## The interview

**Question catalogue**:
The fixed set of questions the system can ask, written in code. Each entry has
an id, the profile or expense field it fills, an answer type, and its
translations. Both the Interviewer and the baseline questionnaire draw from it.
_Avoid_: question bank, form, questionnaire, survey

**Question**:
One catalogue entry as asked in one Tax Case, together with its answer and the
rationale the Interviewer gave for asking it.
_Avoid_: prompt, field, step

**Fact key**:
How one value is stored in a Tax Case: a namespace, a dot and a field name -
`commute.distance_km`, `profile.employed_months`, plus `#1` and up for the second
and further items of a repeating category. The namespace says what the value
*means*, never which category consumes it: the same commute kilometres feed the
Entfernungspauschale and the Mobilitätsprämie, so a key named after one of them is
already wrong for the other. It is also, by construction, the id of the Question
that fills it. The eight namespaces are `profile`, `commute`, `homeoffice`,
`equipment`, `telecom`, `education`, `moving`, `applications`.
_Avoid_: field name (that is the half after the dot), column, attribute, slug

**Gate**:
A cheap yes/no question that opens or closes a whole category of questions —
worked from home, bought equipment, moved, applied for jobs, paid for training,
used an own phone. The interview may not propose to end while any Gate is
unanswered: until then, "nothing more will be found" is a guess.
_Avoid_: trigger, switch, screener, filter question

**Interviewer**:
The agent that decides which Question to ask next, when to look for Gap
candidates, and when the interview is over. The only place in the system where
the next step is chosen by a model rather than by code.
_Avoid_: orchestrator, assistant, chat agent, bot

**Reviewer**:
The agent that audits a complete Tax Case with no access to the interview
dialogue, only to the finished case. Its independence from the Interviewer is
the point of its existence.
_Avoid_: validator, checker, critic, auditor

**Finding**:
One objection raised by the Reviewer against a Tax Case, with a severity, the
Expense it concerns, and the user's resolution of it. Distinct from a
deterministic validation error, which is not a judgement — and the two keep
separate severity vocabularies on purpose: a Finding is blocking, a warning or a
suggestion, while a validation rule produces an error, a warning or a note.
Collapsing them would hide which of the two a screen is showing.
_Avoid_: issue, error, warning, comment, flag

## German tax terms in use

**Anlage N**:
The official form for income from employment, including the Werbungskosten
block in Zeilen 27–83. The only form this product covers.

**Hauptvordruck**:
The main form (ESt 1 A) that the Anlagen attach to. Out of scope, but named
explicitly in the report when a figure belongs there rather than in Anlage N.

**Werbungskosten**:
Expenses incurred in order to earn employment income, and therefore deductible.
The category of everything this product collects.
_Avoid_: work expenses, business expenses, deductions (alone)

**Pauschbetrag**:
The flat allowance (1,230 € for 2025) granted without proof. Itemising is only
worthwhile above it, so every Tax Case is compared against it.
_Avoid_: standard deduction, allowance, flat rate

**Entfernungspauschale**:
The per-kilometre allowance for the commute to the first place of work.
_Avoid_: Pendlerpauschale, commuter allowance, travel costs

**Homeoffice-Tagespauschale**:
The per-day allowance for days worked from home.
_Avoid_: Homeoffice-Pauschale, home office deduction, remote allowance

**Arbeitsmittel**:
Items bought for work — laptop, desk, tools, professional literature. The tax
category; the facts behind it are keyed under the `equipment` namespace
(`equipment.price_eur`), and the two are not interchangeable: one names what the
Finanzamt is being asked to deduct, the other names where a purchase price is
stored. So the _Avoid_ below is about prose and about anything a user reads - a
Fact key namespace is neither.
_Avoid_: equipment, tools, supplies, assets (as a name for the category)

**AfA**:
_Absetzung für Abnutzung_ — depreciation, the rule that an Arbeitsmittel above
the low-value threshold is deducted across its useful life rather than at once.
Never write AfA for anything else; see Agentur für Arbeit.
_Avoid_: depreciation (in identifiers), amortisation

**Agentur für Arbeit**:
The federal employment agency, which pays ALG I. Always written in full — never
abbreviated to AfA, which in this project means depreciation only.
_Avoid_: AfA, AA, employment office, job centre

**ALG I**:
_Arbeitslosengeld I_ — unemployment insurance benefit. Written in full or as
ALG I, never as ALG alone (Bürgergeld is a different benefit).
_Avoid_: ALG, unemployment benefit, Arbeitslosengeld II, Bürgergeld

**Einkommensersatzleistungen**:
Benefits replacing income — ALG I, Elterngeld, Krankengeld, Kurzarbeitergeld.
Not taxed, but they raise the tax rate on everything else
(Progressionsvorbehalt). They belong to the Hauptvordruck, never to Anlage N,
and normally nobody enters them at all: the amounts reach the Finanzamt
electronically. The term the Hauptvordruck itself uses, which is why it wins over
Lohnersatzleistungen — the word the Anleitung to Anlage N uses for the same thing.
_Avoid_: Lohnersatzleistungen, benefits, social payments, replacement income

**Lohnsteuerbescheinigung**:
The annual statement an employer issues, showing gross pay and tax withheld.
The document that establishes the employment period of a Tax Case.
_Avoid_: payslip, salary certificate, tax certificate, P60

## Evaluation

**Baseline questionnaire**:
The fixed list of questions a form would have to ask to fill every field of
every category, derived mechanically from the Question catalogue. The yardstick
the Interviewer is measured against, never hand-written for the occasion.
_Avoid_: control, questionnaire (alone), Typeform, survey

**Profile fixture**:
One synthetic user in the evaluation set: a Profile plus the answer to every
question that Profile could be asked, including which questions it cannot
answer. Drives both the Interviewer and the Baseline questionnaire.
_Avoid_: test case, persona, scenario, mock user

**Seeded defect**:
A fault deliberately planted in a Profile fixture that the Reviewer is required
to catch — an unbacked Expense, contradictory day counts. The only honest way to
show the Reviewer does something.
_Avoid_: broken case, bug, negative test
