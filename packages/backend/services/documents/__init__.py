"""Document intake: the plain functions the workflow orchestrates.

Nothing here is an agent and nothing here holds state. `docs/AGENT_ARCHITECTURE.md`
puts intake under "rule-based workflow": file checks, the vision call, comparing two
reads, mapping values onto Fact keys and deciding a category are ordinary functions
with ordinary tests. What is stateful - the failure branches, the two-pass
disagreement gate, the mandatory human confirmation - lives in
`workflows/document_intake.py` and calls into here.

The uploaded bytes never reach this package's callers twice: they are read in memory,
handed to the model, and dropped (ADR 0004).
"""
