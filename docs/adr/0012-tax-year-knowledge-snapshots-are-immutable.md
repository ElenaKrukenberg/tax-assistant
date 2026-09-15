---
status: accepted
---

# Tax-year knowledge snapshots are immutable

Official sources and derived knowledge are stored as a separate immutable snapshot
for each Tax year because a user filing in 2026 may still prepare a 2023 or 2024
return. Adding support for a new year creates a new snapshot beside the old ones;
it never updates, deletes or repoints historical documents to the latest online
text, and retrieval must select the snapshot using the Tax Case's `tax_year`.

If an authority publishes a correction for the same Tax year, it is added as a new
revision with its own provenance and checksum while the superseded artifact remains
available. This preserves reproducibility without forcing a known official
correction to masquerade as the document originally collected.

## When this takes effect

The rule binds from the moment the knowledge base holds sources for **more than one Tax
year** — or, sooner, from the first correction revision issued for a year already
collected. Until then it describes how the second year must arrive, not a property the
current system has.

Today only 2025 is supported, so there is no second snapshot a query could wrongly reach
into, and retrieval does not yet filter by `tax_year`. That filtering is tracked as
*Version the KB and enforce temporal retrieval* (issue #33 in the submission repository),
scheduled after the 15 September 2026 Capstone hand-in. Scheduling it later is deliberate:
before a second year exists the filter can only be written, never exercised.

Two obligations do apply immediately, because they are cheap now and expensive to
retrofit:

- **A snapshot is chosen by the Tax Case's year, never by recency.** Even with one
  snapshot, code that reaches for "the current index" rather than "the index for this
  case's year" is code that will silently pick the wrong one the day a second appears.
- **No Tax Case may be prepared for a year whose snapshot does not exist.** Failing
  loudly is the required behaviour; answering from another year's rules is not, and this
  matches how `for_year()` already refuses an unsupported year.
