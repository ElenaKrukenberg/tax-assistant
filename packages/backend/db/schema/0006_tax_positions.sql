-- Material tax positions are separate from raw facts and calculated expense rows.
-- The generator consumes only positions that have passed upstream assessment and
-- user authority checks.

create table tax_positions (
    id                    uuid primary key default gen_random_uuid(),
    case_id               uuid not null references tax_cases (id) on delete cascade,
    position_key          text not null,
    category              text not null,
    assessment_status     text not null
                          check (assessment_status in ('identified', 'criteria_not_met', 'unclear')),
    user_decision         text not null default 'pending'
                          check (user_decision in ('pending', 'accepted', 'rejected', 'needs_reconfirmation')),
    dependent_facts       jsonb not null default '[]'::jsonb,
    source_refs           jsonb not null default '[]'::jsonb,
    calculator_version    text,
    rule_version          text,
    proposed_amount_eur   numeric(10, 2) check (proposed_amount_eur >= 0),
    origin                text not null
                          check (origin in ('user_input', 'deterministic_rule', 'retrieved_source', 'ai_suggestion')),
    missing_facts         jsonb not null default '[]'::jsonb,
    provenance            jsonb not null default '[]'::jsonb,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now(),
    unique (case_id, position_key)
);

comment on table tax_positions is
    'Tax position assessment and user decision. It is not a legal conclusion and is not derived by the form generator.';
comment on column tax_positions.dependent_facts is
    'Fact ids with the versions used when this position was assessed.';
comment on column tax_positions.user_decision is
    'User authority: accepted positions may enter the draft only while dependencies are current.';
comment on column tax_positions.provenance is
    'Structured assessment, calculation, source, and decision provenance; no chain-of-thought.';

alter table tax_positions enable row level security;

create policy tax_positions_owner on tax_positions
    using (exists (
        select 1 from tax_cases c where c.id = tax_positions.case_id and c.user_id = auth.uid()
    ));

create trigger tax_positions_respect_finalized
    before insert or update or delete on tax_positions
    for each row execute function reject_change_to_finalized_case();

create trigger tax_positions_touch before update on tax_positions
    for each row execute function touch_updated_at();

insert into schema_versions (version) values ('0006')
on conflict (version) do nothing;
