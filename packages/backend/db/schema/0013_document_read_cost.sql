-- What reading a document actually cost, kept instead of logged and forgotten.
--
-- Document intake is the product's first new paid call since the chat, and the chat is
-- the only thing whose cost and latency were ever measured. `extract.py` already
-- computes the model, the token counts and the price of both passes - it writes them
-- to a log line and throws them away, so nobody can answer "what has this case cost"
-- from the tables the product actually owns.
--
-- On the document row because that is the unit that was paid for: one upload, two
-- passes, one price. The run-level instrumentation the Interviewer and the Reviewer
-- also need is issue #39's full shape and is not this.
--
-- No prompt, no reply, no extracted values beyond what `extracted` already holds: this
-- is an accounting record, and a copy of what a model saw on somebody's payslip is
-- exactly what ADR 0004 exists to prevent.

alter table documents
    add column if not exists read_by_model text,
    add column if not exists read_prompt_tokens integer,
    add column if not exists read_completion_tokens integer,
    add column if not exists read_cost_usd numeric(10, 6);

comment on column documents.read_by_model is
    'The model that actually read this document - not the configured one, which is a '
    'different fact when the primary was unreachable and the fallback answered.';
comment on column documents.read_cost_usd is
    'Both passes together, at the provider''s list price when they ran. Null for a '
    'model with no price on file rather than zero, which would be a claim.';

insert into schema_versions (version) values ('0013')
on conflict (version) do nothing;
