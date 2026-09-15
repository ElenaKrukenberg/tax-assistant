-- What a Document row has to hold once intake is real.
--
-- `documents` has existed since 0001 with the shape a mock needed: a file name, a
-- type, a state and an `extracted` blob. Four things are missing before a real
-- upload can be trusted, and one of them is a deliberate *absence*.
--
-- Not added, on purpose: a column for the two extraction passes or for what they
-- disagreed about. Those are two unconfirmed readings of somebody's payslip, and the
-- product has no use for them after the user has decided - so they live in the
-- intake run's checkpoint and go when the thread does
-- (`workflows/document_intake.py`). `extracted` holds the *confirmed, normalised*
-- result and nothing else, which is also what makes several payslips add up rather
-- than overwrite: the confirmed employment period of each document is readable
-- afterwards.

-- 1. Idempotency. A dropped connection makes the browser retry the upload, and
-- without this the retry is a second Document and two more paid model calls on the
-- same page. Partial index, so rows written before this migration (and any future
-- caller with nothing to deduplicate) are unaffected.
alter table documents add column if not exists idempotency_key text;

create unique index if not exists documents_one_per_idempotency_key
    on documents (case_id, idempotency_key)
    where idempotency_key is not null;

-- 2. Why it failed, in the words the user was shown. A `state = 'failed'` with no
-- reason is a screen that can only say "something went wrong", which is the kind of
-- honesty this product is trying not to practise.
alter table documents add column if not exists failure_code text;
alter table documents add column if not exists failure_detail text;

-- 3. When it last changed, which is what the retention sweep reads: an upload left
-- at `awaiting_confirmation` is a proposal nobody accepted, and "temporary" has to
-- mean something. `services/documents/retention.py` expires them.
alter table documents add column if not exists updated_at timestamptz not null default now();

create trigger documents_touch before update on documents
    for each row execute function touch_updated_at();

-- 4. The states and types intake actually produces. `discarded` is what the user
-- choosing "no" leaves behind - kept rather than deleted so the case can still say
-- a document was uploaded and rejected, with no values from it anywhere. And
-- `doc_type` stops being free text: two types are supported and sent to a model
-- (`services/documents/sensitivity.py`), and a third one appearing here would mean
-- something reached a provider that should not have.
alter table documents drop constraint if exists documents_state_check;
alter table documents add constraint documents_state_check
    check (state in ('reading', 'awaiting_confirmation', 'confirmed', 'discarded', 'failed'));

alter table documents drop constraint if exists documents_doc_type_check;
alter table documents add constraint documents_doc_type_check
    check (doc_type is null or doc_type in ('lohnsteuerbescheinigung', 'rechnung'));

alter table documents drop constraint if exists a_failed_document_says_why;
alter table documents add constraint a_failed_document_says_why
    check (state <> 'failed' or failure_code is not null);

comment on column documents.extracted is
    'The confirmed, normalised values this document yielded - never the two raw '
    'extraction passes, which are unconfirmed personal data and live only in the '
    'intake checkpoint until the user decides (ADR 0004).';
comment on column documents.idempotency_key is
    'One upload per key per case: a retried request returns the first document '
    'rather than paying for a second pair of model calls.';

insert into schema_versions (version) values ('0009')
on conflict (version) do nothing;
