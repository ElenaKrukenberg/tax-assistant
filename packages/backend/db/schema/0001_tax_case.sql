-- Tax Case storage.
--
-- Apply through the Supabase SQL editor (there is no local stack: ADR 0003), then
-- add the next change as 0002_*.sql rather than editing this file — an applied
-- migration is history.
--
-- The shape follows domain/fields.py, which is why there is no column per tax
-- field: values live in `field_values`, keyed by the same strings the question
-- catalogue and the frontend already use ("employed_months",
-- "entfernungspauschale.commuting_days"). A column per field would have to be
-- migrated every time a category is added, and the catalogue is expected to grow.
--
-- Two domain rules are enforced here rather than only in code, because both are
-- the kind that a bug quietly breaks: one case per user per year, and a finalized
-- case is read-only until it is explicitly reopened.

create extension if not exists pgcrypto;

-- --------------------------------------------------------------------------
-- The case
-- --------------------------------------------------------------------------

create table tax_cases (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users (id) on delete cascade,
    tax_year     integer not null check (tax_year between 2020 and 2100),
    status       text not null default 'gathering'
                 check (status in ('gathering', 'validating', 'reviewing',
                                   'needs_user_input', 'finalized')),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    finalized_at timestamptz,

    -- One case per user per year, enforced by the database and not by hope
    unique (user_id, tax_year),
    constraint finalized_has_a_timestamp
        check ((status = 'finalized') = (finalized_at is not null))
);

comment on table tax_cases is
    'One user''s working file for one tax year. Read-only once finalized.';

-- --------------------------------------------------------------------------
-- Every value in the case, with where it came from
-- --------------------------------------------------------------------------

create table field_values (
    case_id     uuid not null references tax_cases (id) on delete cascade,
    key         text not null,
    item_index  integer not null default 0,
    value       jsonb not null,
    provenance  text not null check (provenance in ('answer', 'document', 'assumed')),
    source      text not null default '',
    confirmed   boolean not null default false,
    updated_at  timestamptz not null default now(),

    primary key (case_id, key, item_index),

    -- An assumption has to say why it is defensible (ADR 0010)
    constraint an_assumption_carries_its_reason
        check (provenance <> 'assumed' or length(source) > 0)
);

comment on column field_values.key is
    'The catalogue key: "employed_months" or "entfernungspauschale.commuting_days".';
comment on column field_values.item_index is
    'Second and further items of a repeating category — three purchases, three rows.';
comment on column field_values.provenance is
    'answer | document | assumed. An assumed value must be confirmed before a report.';

-- --------------------------------------------------------------------------
-- Documents: the values a document yielded, never the document
-- --------------------------------------------------------------------------

create table documents (
    id         uuid primary key default gen_random_uuid(),
    case_id    uuid not null references tax_cases (id) on delete cascade,
    file_name  text not null,
    doc_type   text,
    state      text not null default 'reading'
               check (state in ('reading', 'awaiting_confirmation', 'confirmed', 'failed')),
    extracted  jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

comment on table documents is
    'The file itself is never stored (ADR 0004): only its name and the values read from it.';

-- --------------------------------------------------------------------------
-- Expenses
-- --------------------------------------------------------------------------

create table expenses (
    id          uuid primary key default gen_random_uuid(),
    case_id     uuid not null references tax_cases (id) on delete cascade,
    category    text not null
                check (category in ('entfernungspauschale', 'homeoffice_tagespauschale',
                                    'arbeitsmittel', 'telefon_internet',
                                    'fortbildungskosten', 'umzugskosten',
                                    'bewerbungskosten')),
    item_index  integer not null default 0,
    amount_eur  numeric(10, 2) not null check (amount_eur >= 0),
    form_line   text not null,
    status      text not null default 'draft'
                check (status in ('draft', 'confirmed', 'flagged')),
    trace       jsonb not null,
    source_doc  uuid references documents (id) on delete set null,
    created_at  timestamptz not null default now(),

    unique (case_id, category, item_index)
);

comment on column expenses.amount_eur is
    'numeric, not float: this figure ends up on a tax return.';
comment on column expenses.form_line is
    'Where it goes on the form — "Zeile 60", "Zeilen 54-56" (ADR 0002).';
comment on column expenses.trace is
    'Formula, substituted values, backing document and KB citation. Never empty.';

-- --------------------------------------------------------------------------
-- The interview record
-- --------------------------------------------------------------------------

create table answers (
    id          bigserial primary key,
    case_id     uuid not null references tax_cases (id) on delete cascade,
    question_id text not null,
    item_index  integer not null default 0,
    rationale   text not null default '',
    answer      jsonb,
    asked_at    timestamptz not null default now(),
    answered_at timestamptz
);

comment on table answers is
    'Which question was asked, why the Interviewer chose it, and what came back. '
    'Kept even when the value is later overwritten: this is the audit trail.';

-- --------------------------------------------------------------------------
-- The Reviewer's objections
-- --------------------------------------------------------------------------

create table findings (
    id         uuid primary key default gen_random_uuid(),
    case_id    uuid not null references tax_cases (id) on delete cascade,
    severity   text not null check (severity in ('blocking', 'warning', 'suggestion')),
    title      text not null,
    reasoning  text not null default '',
    expense_id uuid references expenses (id) on delete set null,
    resolution text not null default 'open'
               check (resolution in ('open', 'fixed', 'dismissed')),
    note       text not null default '',
    created_at timestamptz not null default now()
);

comment on table findings is
    'A Reviewer judgement, not a validation error — the two keep separate '
    'severity vocabularies on purpose (CONTEXT.md).';

-- --------------------------------------------------------------------------
-- A finalized case is read-only
-- --------------------------------------------------------------------------

create or replace function reject_change_to_finalized_case()
returns trigger
language plpgsql
as $$
declare
    locked boolean;
    target uuid;
begin
    target := coalesce(new.case_id, old.case_id);
    select status = 'finalized' into locked from tax_cases where id = target;
    if locked then
        raise exception
            'Tax case % is finalized; reopen it before changing %', target, tg_table_name
            using errcode = 'check_violation';
    end if;
    return coalesce(new, old);
end;
$$;

create trigger field_values_respect_finalized
    before insert or update or delete on field_values
    for each row execute function reject_change_to_finalized_case();

create trigger expenses_respect_finalized
    before insert or update or delete on expenses
    for each row execute function reject_change_to_finalized_case();

create trigger answers_respect_finalized
    before insert or update or delete on answers
    for each row execute function reject_change_to_finalized_case();

-- Reopening is a status change on the case itself, so tax_cases carries no such
-- trigger: it is the one table that has to be able to lift the lock.

create or replace function touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

create trigger tax_cases_touch before update on tax_cases
    for each row execute function touch_updated_at();
create trigger field_values_touch before update on field_values
    for each row execute function touch_updated_at();

-- --------------------------------------------------------------------------
-- Row level security
-- --------------------------------------------------------------------------
--
-- The backend also filters by user_id itself. Both, deliberately: the data is
-- somebody's salary and address, and a missing WHERE clause should not be all
-- that stands between one user's case and another's.

alter table tax_cases    enable row level security;
alter table field_values enable row level security;
alter table documents    enable row level security;
alter table expenses     enable row level security;
alter table answers      enable row level security;
alter table findings     enable row level security;

create policy own_cases on tax_cases
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy own_field_values on field_values for all
    using (exists (select 1 from tax_cases c
                   where c.id = field_values.case_id and c.user_id = auth.uid()))
    with check (exists (select 1 from tax_cases c
                        where c.id = field_values.case_id and c.user_id = auth.uid()));

create policy own_documents on documents for all
    using (exists (select 1 from tax_cases c
                   where c.id = documents.case_id and c.user_id = auth.uid()))
    with check (exists (select 1 from tax_cases c
                        where c.id = documents.case_id and c.user_id = auth.uid()));

create policy own_expenses on expenses for all
    using (exists (select 1 from tax_cases c
                   where c.id = expenses.case_id and c.user_id = auth.uid()))
    with check (exists (select 1 from tax_cases c
                        where c.id = expenses.case_id and c.user_id = auth.uid()));

create policy own_answers on answers for all
    using (exists (select 1 from tax_cases c
                   where c.id = answers.case_id and c.user_id = auth.uid()))
    with check (exists (select 1 from tax_cases c
                        where c.id = answers.case_id and c.user_id = auth.uid()));

create policy own_findings on findings for all
    using (exists (select 1 from tax_cases c
                   where c.id = findings.case_id and c.user_id = auth.uid()))
    with check (exists (select 1 from tax_cases c
                        where c.id = findings.case_id and c.user_id = auth.uid()));

-- --------------------------------------------------------------------------
-- Indexes for the queries the screens actually make
-- --------------------------------------------------------------------------

create index tax_cases_by_user on tax_cases (user_id, tax_year desc);
create index expenses_by_case on expenses (case_id);
create index documents_by_case on documents (case_id);
create index answers_by_case on answers (case_id, asked_at);
create index findings_open_by_case on findings (case_id) where resolution = 'open';
