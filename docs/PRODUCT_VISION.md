# German Tax Assistant — product vision

## Status

Sprint 2 delivered a RAG chat over Anlage N (53 official documents, Chroma, 775
chunks), deterministic calculators, security guards and an evaluation harness,
in four UI languages. Sprint 3 builds the agentic workspace on top of it.

## Long-term goal

Not a Q&A chatbot: a tool that prepares the Werbungskosten part of a German
employee's tax return — collects, checks and documents the figures — comparable
in function to WISO Steuer, Taxfix or Steuerbot. Unlike a chat, the product
keeps state per **Tax Case** across the year: documents, expenses, questions,
report — a workspace, not a dialog window.

## Target user

An employee (Arbeitnehmer) in Germany filing Anlage N themselves, who distrusts
one-size-fits-all questionnaires and wants to understand *why* an expense
counts, not just get a total. Secondary audience: people whose German is weak
(hence en/ru/tr) — official Finanzamt wording is a barrier by itself.

## What the product should eventually do

- Collect return data as documents arrive through the year, not in one sitting.
- Work as a workspace: cases, documents, expenses, review status — not chat only.
- Read tax documents and extract structured data.
- Classify expenses into Werbungskosten categories.
- Compute amounts by fixed rules (Pendlerpauschale, Homeoffice-Pauschale, AfA…).
- Find likely-forgotten deductions relevant to the profile.
- Check required fields and contradictions between documents and answers.
- Produce the final document: expenses, amounts, justifications, document and
  source references — the file the user currently assembles by hand each year.
- Later: help prepare data for filing (not the ELSTER filing itself yet).
- Support de/en/ru/tr; use the existing German tax KB.
- For every expense explain: why it counts, how the amount was computed, which
  document backs it, which source allows it — a **trace**, not just a figure.
  That trace is the competitive difference from WISO/Taxfix/Steuerbot.

## Explicitly out of scope (for now)

- Real filing via ELSTER (legal integration, beyond a study project).
- Full coverage of all Anlagen — years of work.
- Legal tax advice: a disclaimer everywhere, the human decides
  (human-in-the-loop, see AGENT_ARCHITECTURE).

## Target KB scale (non-functional requirement)

Today: 53 documents, 775 chunks, Anlage N. The design target is **at least
×100** — about ten Anlagen covering an employee fully (~77k chunks); the far
horizon is ×1000 (the full tax corpus). Written as a number so "design for
scale" is checkable: every retrieval decision is tested against "does this
survive 77k chunks?" — and the number also shows what *not* to build (no
sharding, no dedicated vector DB at ×100).

What follows from ×100: an HNSW index (needed from ~10–20k chunks), a `pg_trgm`
GIN index for the lexical tier, partial indexes or partitioning by `form_id`,
and a **paid database** — at 1536 dims a vector is 6 KB, so ×100 is ~460 MB of
vectors and the Supabase free tier (500 MB) ends there. At ×1000 add
partitioning per form and probably 512-dim embeddings — so 1536 dims must not
become a baked-in assumption.

## Competitive context

WISO/Taxfix/Steuerbot walk a questionnaire and output a total; they rarely
explain per line or keep a year-round workspace of receipts and notes as the
primary object. This product's niche is explainability plus an adaptive
interview instead of a fixed questionnaire — which is also what justifies using
an agent at all (see AGENT_ARCHITECTURE), not a UI difference.
