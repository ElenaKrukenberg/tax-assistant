# The KB moves from Chroma to pgvector, but after Sprint 3

The knowledge base will live in the same Supabase Postgres as the Tax Case, using
pgvector — and the work is scheduled after Sprint 3, not inside it, if time allows
at all. The reason to move is scaling, not tidiness: the retrieval's lexical tier
matches substrings, and Chroma's `$contains` is a brute-force scan with no index
available, whereas Postgres makes the same predicate indexable with a `pg_trgm`
GIN index. Filtered search across several Anlage has the same shape — Postgres
offers partial indexes and partitioning where Chroma offers nothing — and the
metadata workaround in `chunking.py`, where topics are flattened into boolean keys
because Chroma metadata must be scalar, disappears against JSONB. Moving also
ends re-embedding all 775 chunks on every deploy, which `render.yaml` currently
does because the free plan has no persistent disk.

The reason to wait is that `Retriever.search()` is a stable interface: the
gap-finder and the expense justifications built on it in Sprint 3 do not care
which store is underneath, so nothing gets written twice by postponing. Against a
budget already 14 hours over its 40, six hours that a reviewer cannot see are the
wrong six hours.

Scope when it happens is the store *and* the size-dependence together, never the
store alone: constants expressed as a share of the collection rather than absolute
counts (`LEXICAL_MAX_MATCHES`, `FETCH_K` — see `eval/LIMITATIONS.md`), the
`pg_trgm` index, topics in JSONB, a partial index per `form_id`, and HNSW once the
collection passes roughly 10–20 thousand chunks. Migrating the store alone would
leave the scaling defect in place and reduce the whole exercise to "one database
instead of two", which is the weakest argument for it.

The two cosine cutoffs carry over unchanged, since cosine distance is scale-free
and the Chroma collection is already configured with `hnsw:space: cosine`. The
acceptance criterion is therefore strict: the `lexical-cap` configuration scores
91/91 again on the same 26 cases, and the thresholds are not retuned until it does —
the thresholds are what the Sprint 2 numbers mean.

**Amended when the move was carried out (issue #32, 13 September 2026.)** Two
instructions above did not survive contact with it.

*"Revert to Chroma if it does not"* is withdrawn. Reverting restores the defect the
move exists to remove — a deploy that rebuilds every embedding, a store that does not
outlive one deploy, and an indexing failure that takes a healthy backend down with it —
so it is not an escape hatch, it is the problem. A difference in the score is
investigated per question instead. That is not softer: today's 91/91 was measured on
Chroma, which is approximate, and pgvector without an index is exact, so it can return
*different* chunks and some of them are better. A drop is therefore evidence to read,
not a verdict; what stays forbidden is turning a knob until the number goes green.

The re-run bore that out. Retrieval held — `context_hit` and `primary_context_hit`
unchanged — one question started finding its document at rank 1 instead of 5, and one
case differed for a reason that is neither the store nor the retrieval: the query
analyzer is a model call and returned a form filter on one run and not the other, which
decides whether a question about the boundary between two forms can reach the document
that draws it (issue #96).

*"Make both size constants a fraction of the collection"* is wrong as stated: they are
relative to different things. `LEXICAL_MAX_MATCHES` asks how common a term is, which is
a property of the corpus, so it is `max(40, 0.5% of the rows)`. `FETCH_K` asks how much
to overfetch before post-filtering, which is a property of the query and of `k`, so it
is `4 × k`. Both give exactly their old values at 775 chunks and k=5, which is what
keeps the acceptance run comparable.
