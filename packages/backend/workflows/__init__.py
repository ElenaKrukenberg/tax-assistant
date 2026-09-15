"""Stateful workflows that are not agents.

`docs/AGENT_ARCHITECTURE.md` draws the line this package sits on: an agent is where
an LLM chooses the next step in a loop, and there are exactly two of those (the
Interviewer and the Reviewer, in `agents/`). Document intake uses a model - twice per
document - but the sequence is fixed and known in advance, so it belongs here.

What LangGraph earns here is not routing intelligence. It is the checkpoint that lets
extraction pause for a human decision and resume, the conditional failure paths, and
the structural guarantee that no extracted value reaches the case before the user has
confirmed it. A plain `upload -> extract -> save` handler would not need any of it.
"""
