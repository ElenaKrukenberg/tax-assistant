# Uploaded documents are read by a vision model and then discarded

An uploaded PDF or photo goes straight to a vision model that returns structured
fields; no OCR engine is installed, and the file itself is never stored — only
the extracted values, after the user has confirmed them. Skipping Tesseract
removes a system dependency to deploy, an image-preprocessing step to tune, and
a layer of errors, at the cost of a non-deterministic extraction, which is why
confirmation by the user is mandatory rather than optional. Not storing the file
is the more consequential half: the demo is publicly deployed, and a stranger's
Lohnsteuerbescheinigung is not something a student project should be holding.
The consequence to accept is that a document cannot be re-read later or shown
next to the report as evidence — only the values it yielded and its file name
survive.

What *is* kept between the reading and the user's decision, and for how long. The
file is never stored, but the values read out of it have to survive long enough for
the user to look at them: two independent extraction passes, what they disagreed
about, and the values proposed from them. Those live in the intake run's checkpoint
and nowhere else - not in `documents`, which holds only the confirmed result - and
they go when the run does: on confirm, on discard, when the case is deleted, or
after `DOCUMENT_CONFIRMATION_TTL_HOURS` (24) if nobody decided at all
(`services/documents/retention.py`). So "temporary" has an end even when the user
walks away, which is the difference between a proposal and a record.

What the provider retains is the other half of that promise, and it is enforced in
code rather than by an account setting: every call carries OpenRouter's Zero Data
Retention policy (`PROVIDER_POLICY` in `packages/backend/core/llm.py`), which drops
every retaining endpoint from routing and fails with a 404 when only such an
endpoint is left. So a request that would reach a provider permitted to retain it
does not quietly succeed. The account setting that
appeared to do this never did: what limited this key was a model allowlist, and
providers that may train on inputs were reachable the whole time (issue #15).
Without that one field the paragraph above would be a promise about this project's
own disk, which is not how a reader takes it.

**What does leave, stated plainly.** The interview itself carries no identity data at
all - `domain/fields.py` has no name, no address, no email and no Steuer-ID, so there
is nothing to strip out of an Interviewer prompt, and `tests/test_no_pii_leaves.py`
keeps it that way. A document is different. The image is sent whole, because reading
only the relevant part of a page would require recognising the page first, which is
the thing being asked for. So a Lohnsteuerbescheinigung reaches the model carrying the
employee's name, the eTIN, the tax class and the Kirchensteuer line - and the last of
those says whether the person belongs to a church that levies it, which is religious
belief in the Art. 9 GDPR sense, printed on a tax form.

Three things are done about it and none of them is "the model did not see it": the
field is not extracted, so it cannot be stored, logged or traced by accident
(`services/documents/schemas.py`); only two document types may be sent at all, and the
user is told so before uploading (`services/documents/sensitivity.py`); and the call
carries Zero Data Retention like every other. Local recognition would remove the
exposure and there is none, so this is a boundary of the current design rather than a
task waiting to be done - and it is written here because a reader of this ADR would
otherwise finish it believing nothing sensitive leaves.
