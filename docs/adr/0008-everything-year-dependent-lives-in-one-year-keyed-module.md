# Everything that depends on the tax year lives in one module, keyed by year

Rates, thresholds, the Pauschbetrag and the official form lines are held in a
single typed structure keyed by tax year, which `calculations.py` reads using the
Tax Case's own `tax_year` instead of the module-level constants it uses today
(`TAX_YEAR = 2025`, `RATE_KM_FIRST_20 = 0.30`, `PAUSCHBETRAG = 1230.0`, and the
rest). Chunk metadata gains a `tax_year` field at ingest for the same reason,
though retrieval does not filter on it yet — with one year in the KB there is
nothing to filter, but backfilling the field later means re-ingesting everything.

The obligation this makes explicit already existed: every rate in the calculators,
every document in the KB and now every form line is specific to one tax year, and
German rates and line numbers both move between years. Recording an Expense's form
line ([ADR 0002](0002-expenses-carry-official-form-lines.md)) does not create the
annual addition, it joins it. Doing the gathering while exactly one year exists
costs about two hours and changes nothing but names; doing it in January, when 2026
arrives and the values are scattered across calculators, KB filenames and a form-line
table, costs a search through the whole codebase.

A data file (YAML or JSON) was the alternative and would suit a project where
somebody other than a programmer assembles each new year's release. Here a typed Python
module wins: the values feed calculations covered by unit tests, so a typo should
fail at import or type-check time rather than in a tax figure at runtime, and no
parser or validation schema has to exist for it.

The annual routine this creates, in order: fetch the new Anlage N and its
Anleitung, build a new Tax-year knowledge snapshot beside the existing snapshots,
check whether the Zeilen have shifted, and add the new year's rates and form-line
block. No historical document or rule block is updated in place. Nothing else
should need touching — and if it does, that is the defect to fix. See
[ADR 0012](0012-tax-year-knowledge-snapshots-are-immutable.md).
