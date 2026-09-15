# Rules written in code carry their own verified sources

Each branch of each calculator names the official passage that authorises it, from a
versioned catalogue keyed by tax year (`domain/rule_citations.py`). A calculation
reports which branches it took (`CalculationResult.applied_rule_ids`), and the trace
beside a figure shows the passages for exactly those. Nothing is retrieved and nothing
is judged by a model on the way to a deterministic figure.

The link that matters — that a given passage supports a given formula — is made by a
person writing the catalogue entry and by the review of that entry. Everything around
it is mechanical and is enforced by `tests/test_rule_citations.py` against `KB/`: the
source is `source_type: official`, its `tax_year` and `form_id` match the figure it
backs, the excerpt is present word for word, it falls inside exactly one chunk, the
recorded chunk id is that chunk, every branch a calculator can take has an entry, and
no entry exists that no branch can reach.

The alternative was the one [ADR 0006](0006-pgvector-after-the-sprint.md)'s retriever
already makes available: search the knowledge base for each figure at display time.
For seven known categories that is worse in three ways. It makes a deterministic
figure depend on a retrieval that can return something else tomorrow. It is per
request, so the same branch of the same 2025 calculator is paid for again for every
user. And it cannot tell the branches apart: "Arbeitsmittel" is three provisions — an
item under 800 EUR net deducted at once, a laptop written off in one year under a 2022
BMF letter, everything else depreciated over its useful life — and one search per
category would put a passage about low-value assets beside a depreciation figure. A
quotation that does not support the claim beside it is worse than no quotation,
because it looks checked.

The second alternative was a model asked at runtime whether a quotation supports a
claim, which is what `docs/AGENT_ARCHITECTURE.md` step 12 described. It is weaker than
a test on three counts: it costs money on every request, it can answer differently on
two identical requests, and it can approve a bad citation — so the guarantee becomes "a
model thought so once", which is not what a quotation beside a figure on a tax return
should mean. **A model verifies only what a model wrote.** The model-backed
classification of an ambiguous invoice (issue #91) and the open questions in the chat
still need entailment-style checking; a formula written in Python does not.

The excerpt is stored in the catalogue rather than fetched when the trace is rendered,
so a finished Tax Case keeps saying what it said. Reindexing the corpus or replacing a
source would otherwise let the words beside a figure drift away from the rules the
figure was computed under. The recorded chunk id is checked against the current corpus
by the test, so drift becomes a failing build rather than a silent re-pointing.

Two things this does not claim. A branch whose basis is not in `KB/` yet is carried in
the catalogue with an empty excerpt, naming the provision it is waiting for, so the gap
is visible rather than absent — today that is the professional-share reduction, and
issue #93 is where it gets a source. And two of the citations quote the Finanzamt's own
Anleitung to Anlage N rather than the statute, because § 6 Abs. 2 and § 7 Abs. 1 EStG
are not in the corpus; the same issue re-points them when it grows.

The test has already earned its place twice. The first excerpt written for the
commuting rate matched two chunks, because § 9 EStG states the same rate again for
journeys home under a second household — either chunk id would have passed a looser
check and the trace would have cited a rule about a different deduction. And the
passage for actual public-transport costs matched none, because the PDF-to-Markdown
conversion had split that sentence of § 9 Abs. 2 across a page break; the break is
repaired, and the KB carries more of them (issue #93).

Supersedes step 12 of `docs/AGENT_ARCHITECTURE.md`. Amends nothing in
[ADR 0002](0002-expenses-carry-official-form-lines.md) or
[ADR 0008](0008-everything-year-dependent-lives-in-one-year-keyed-module.md): the form
line still belongs to the year, and the catalogue is keyed by year for the same reason
the rates are.
