# Tracing policy

Where the agents' traces go, how long they stay there, and how they are deleted.

Written because `docs/KNOWN_LIMITATIONS.md` item 9 requires it before real tax data
reaches a third party, and because until it existed nobody could answer the question
at all. It records what is true, including the parts that are not yet good enough.

## What a trace is, and why there is one

Traces show *why the agent chose what it chose* - which questions the Interviewer
considered, which passage the retrieval returned, which findings the Reviewer raised.
That is the product's central promise made debuggable, and it is the whole reason the
project sends anything at all.

Observability does not overrule the privacy decision (ADR 0004, `docs/DECISIONS.md`).
Nobody needs the user's salary in cleartext to see which branch a graph took.

## Where they go

| | |
| --- | --- |
| Service | LangSmith, operated by LangChain |
| Region | GCP EU, `https://eu.api.smith.langchain.com` |
| Set by | `LANGSMITH_ENDPOINT` in `render.yaml` |
| Project | `tax-assistant` (`LANGSMITH_PROJECT`) |
| Off switch | an empty `LANGSMITH_API_KEY`, which sends nothing at all |

The region is a property of the **organisation**, chosen when it is created and not
changeable afterwards. LangSmith does not migrate data between regions.

Two things follow, and both are easy to get wrong.

**`LANGSMITH_ENDPOINT` must stay set.** Unset, the SDK falls back to its default
`https://api.smith.langchain.com`, which is GCP US - so leaving it out does not mean
"no region", it means the wrong one, silently.

**The key and the endpoint have to belong to the same organisation.** A key issued in
one region fails authentication against another, and the uploads are then dropped in a
background thread with no error the request can see: nothing arrives anywhere, and it
looks from the outside like tracing simply being quiet.

## How long they are kept

Free plan, no trace usage limits configured, **base retention: 14 days**. Nothing is
kept deliberately beyond that; nothing is archived elsewhere.

## What is redacted, and what is not

`core/tracing.py` replaces values before a run is uploaded and leaves the field names
in place, so a trace still shows which values a case holds and which branch the agent
took - only not what those values say.

**The set is derived, not listed.** It is built from `domain/fields.py` the same way
`CARRY_OVER_FIELDS` is: every profile field and every category field, in both the bare
and the qualified spelling, and with a repeating item's `#1` suffix. Marking a field
in the catalogue is the whole of adding one, so a field added tomorrow is covered
tomorrow rather than when somebody notices.

Both spellings, still, though since issue #61 a *stored* fact is always qualified -
`commute.distance_km`, `profile.employed_months`. The bare name stays in the set
because a prompt or a tool argument may still carry it, and a name that redacts
nothing costs nothing.

That replaced four names written by hand, which is worth recording because of how it
failed. Of the four, one existed in the live case model. Thirteen that did exist -
`distance_km`, `commuting_days`, `homeoffice_days`, `employed_months`,
`employer_count`, `has_minijob`, `benefit_type`, `price_eur`, `purchase_month`,
`monthly_bill_eur`, `amount_eur`, `move_date` and the reason given for a move -
travelled in the open, and nothing said so, because the only thing checking the list
was somebody remembering it.

Three things are covered beyond the catalogue:

- **Booleans too.** A gate answer is still a fact about someone's employment, and
  "covered by default" means nothing if the default has exceptions. The branch stays
  legible anyway: the Interviewer's prompt prints a per-category state line beside the
  values, and that is what explains the choice.
- **Computed totals.** The running per-category figure and the claimed expense, both
  shaped `- category: 252.00 EUR`. No catalogue key sits beside them, but they are
  this person's answers added up.
- **The document intake's field names**, before the intake exists. Nothing writes
  `documents.extracted` yet, so they cannot come from the catalogue; they are listed
  so the first traced run after intake lands is already safe.

**What is still not covered**, recorded rather than left to be found: the Reviewer's
prompt prints each expense's trace, which is the formula with this person's numbers
already substituted (`220 days x 12 km x 0.30 EUR/km`). A rule broad enough to catch
those would also take the Pauschbetrag and the statutory rate beside them - public
figures that protect nobody and without which a calculation cannot be read at all.
Closing it properly means the trace carrying its inputs as fields rather than as
prose. Issue #73.

## How a trace is deleted

**Today: only wholesale.** `langsmith==0.10.11` offers `Client.delete_project`, which
takes every trace in the project at once, and nothing finer. There is a REST endpoint
`POST /api/v1/runs/delete` that accepts trace ids with a session id, or metadata with
a time range - but runs currently carry no case id and no user id, because
`core/tracing.py` builds a bare `LangChainTracer` and sets no metadata. So there is
nothing to select on: a single person's traces cannot be picked out.

Deletion is also **deferred**. LangSmith processes these requests in batches, returns
no confirmation, and the result has to be checked by asking again. It can therefore
never sit inside a synchronous delete that returns 204.

What follows from that, and is the honest statement of the position:

- Deleting a Tax Case does **not** delete its traces. `services/case_erasure.py` says
  so in its own table rather than leaving it to be discovered.
- Until runs carry a case id, "delete my traces" cannot be offered as a user-facing
  operation without lying about it.
- The 14-day retention is what actually bounds the exposure in the meantime.

Both halves - tagging runs, then deleting them per person - are issue #73.

## If the region has to change again

1. Create an organisation in the target region. The region is chosen at creation.
2. Issue an API key **in that organisation**.
3. Set `LANGSMITH_ENDPOINT` in `render.yaml` and the new `LANGSMITH_API_KEY` in the
   Render dashboard, in that order, and redeploy. `get_settings()` and `callbacks()`
   are both cached for the life of the process, so the change only takes effect on a
   restart.
4. Delete the project in the old region. Its traces do not follow and nothing else
   will remove them.
