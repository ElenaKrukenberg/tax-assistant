# The Tax Case lives in relational tables; the checkpointer holds only the run

Ordinary Postgres tables (`tax_cases`, `documents`, `expenses`, `answers`,
`findings`) are the source of truth for a Tax Case; the LangGraph checkpointer
stores only the execution state of a graph run that is paused waiting for the
user. The tempting alternative — let the checkpointer be the only store and read
the unpacked state on every screen — fails at the first screen: a list of a
user's cases with their totals is a query over rows, and against a checkpointer
it becomes "load and deserialise every blob". Keeping both in sync was rejected
as the worst of the three. The boundary to hold: a Tax Case is data and outlives
any run; a paused interview is a run and outlives nothing.
