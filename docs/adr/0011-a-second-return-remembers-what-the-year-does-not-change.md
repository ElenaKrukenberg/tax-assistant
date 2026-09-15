# A second return remembers what the tax year does not change

A person filing for the second time should not be asked again how far they live
from work. Almost nothing in a case survives the year — days worked, amounts,
purchases are all new — but a few facts are properties of the person rather than of
the year: the commute distance, whether they drive it, whether the employer provides
a desk. Those are carried into the next case and offered back for confirmation.

Which fields carry is a judgement made once, declaratively, in `fields.py` — the
same file and the same shape as the assumption rule in [ADR 0010](./0010-the-system-may-assume-but-never-silently.md).
Two invariants fence it, and both are enforced at import rather than by review:

- **A gate never carries.** The six gate questions are one cheap yes/no that opens
  or closes a whole category, and the interview's entire measured saving comes from
  asking them. Carrying last year's "no" over would close a category in silence and
  lose the deduction without anybody deciding to — the same failure the gate guard
  already exists to prevent, arriving by a different door.
- **A repeating field never carries.** A price or a purchase month belongs to one
  item, not to the person.

A carried value is not an answer, and the report has to be able to say so. It gets a
provenance of its own — `remembered`, alongside `answer`, `document` and `assumed` —
rather than being folded into `assumed`, because "you told us this last year" and "we
guessed because you could not say" are different claims and the product's whole
promise is that a figure can say which it is. What the two share is that neither is
something the user has said about *this* year, so both are unconfirmed until looked
at and `finalize` refuses to write a report over either.

Where they are confirmed is the stop card, and that is the part worth writing down,
because the two obvious alternatives are both wrong. Confirming at the start of the
interview would show somebody who did not commute this year a distance they have no
use for: relevance is not known until the gates are answered. Confirming at the end,
on the final approval screen, would mean the figure was already in the report before
anybody agreed to it. The stop proposal is the one pause that happens *after* every
gate is answered and *before* anything is computed — the gate guard guarantees the
first half — so the card shows only carried values this year actually needs, and
shows them while they can still be corrected. Rejecting one deletes it from the case
and reopens the interview, which puts its question back in front of the filter; a
carried value the year turned out not to need is never shown and is deleted rather
than left to block the report.

The profile itself lives in a LangGraph `Store` keyed by user id, not in a table of
ours and not in the checkpointer. It belongs to the person, outlives every case, and
is namespaced exactly as the checkpointer's threads already are. What lands in a case
is a copy, written into `field_values` with its provenance, so
[ADR 0005](./0005-tax-case-lives-in-tables-not-in-the-checkpointer.md) holds
unchanged: the tables are still the only thing that knows what the case says. The
store is a convenience for the *next* case, and it is treated as one — unreachable
store, unapplied migration, a value whose shape changed between releases each
degrade to "this person has no profile memory", logged once and never raised. A
shortcut that can fail the thing it shortens is not worth having.

Newest year wins, by tax year and not by clock: somebody filing 2024 in 2026, after
they have already done 2025, must not roll the commute back to the older figure.

One thing to be plain about: this build knows one tax year, and a case may only be
created for a year that has rules ([ADR 0008](./0008-everything-year-dependent-lives-in-one-year-keyed-module.md)).
Nobody can have a second return yet, so nothing carries in production today — the
machinery, the migration, the card and the measurement are all in place and asleep.
They wake the day a second year's rules land, and the eval arm (`eval/carry_over.py`)
already says what they will be worth when they do: 24 questions across ten profiles.
Building it now was a choice about when the design is cheapest to get right, not a
claim that it is doing anything for a user this week.
