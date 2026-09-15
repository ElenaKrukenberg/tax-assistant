-- Every stored fact is keyed by what it means, not by the category that consumes it.
--
-- `entfernungspauschale.commuting_days` becomes `commute.commuting_days`, and the
-- profile's bare `employed_months` becomes `profile.employed_months` (issues #61 and
-- #36, shape decided in #14). The reason it is done now rather than later is this
-- file: with a handful of cases in the database the rename is a data migration
-- nobody will notice, and with twenty testers it is a data migration on other
-- people's tax data.
--
-- Data only - no table, column or constraint changes. `ExpenseCategory` is
-- deliberately untouched: `expenses.category` still names the tax category in
-- German, because that is what it is. What moves is the key of a *fact*.

-- The map, once, so every statement below reads the same list.
create temporary table key_rename (old text primary key, new text not null)
    on commit drop;

insert into key_rename (old, new) values
    ('employed_months', 'profile.employed_months'),
    ('employer_count', 'profile.employer_count'),
    ('working_days_total', 'profile.working_days_total'),
    ('works_remotely', 'profile.works_remotely'),
    ('has_minijob', 'profile.has_minijob'),
    ('benefit_type', 'profile.benefit_type'),
    ('benefit_amount_eur', 'profile.benefit_amount_eur'),
    ('has_paper_benefit_certificate', 'profile.has_paper_benefit_certificate'),
    ('bought_work_equipment', 'profile.bought_work_equipment'),
    ('claims_phone_internet', 'profile.claims_phone_internet'),
    ('moved_for_work', 'profile.moved_for_work'),
    ('searched_for_job', 'profile.searched_for_job'),
    ('further_education', 'profile.further_education'),
    ('entfernungspauschale.commuting_days', 'commute.commuting_days'),
    ('entfernungspauschale.distance_km', 'commute.distance_km'),
    ('entfernungspauschale.own_car', 'commute.own_car'),
    ('entfernungspauschale.public_transport_cost_eur', 'commute.public_transport_cost_eur'),
    ('homeoffice_tagespauschale.homeoffice_days', 'homeoffice.homeoffice_days'),
    ('homeoffice_tagespauschale.other_workplace_available', 'homeoffice.other_workplace_available'),
    ('homeoffice_tagespauschale.commute_days', 'homeoffice.commuting_days'),
    ('arbeitsmittel.price_eur', 'equipment.price_eur'),
    ('arbeitsmittel.price_is_net', 'equipment.price_is_net'),
    ('arbeitsmittel.purchase_month', 'equipment.purchase_month'),
    ('arbeitsmittel.is_digital', 'equipment.is_digital'),
    ('arbeitsmittel.useful_life_years', 'equipment.useful_life_years'),
    ('arbeitsmittel.professional_share_pct', 'equipment.professional_share_pct'),
    ('telefon_internet.monthly_bill_eur', 'telecom.monthly_bill_eur'),
    ('telefon_internet.months', 'telecom.months'),
    ('fortbildungskosten.amount_eur', 'education.amount_eur'),
    ('fortbildungskosten.kind', 'education.kind'),
    ('fortbildungskosten.reimbursed_eur', 'education.reimbursed_eur'),
    ('umzugskosten.amount_eur', 'moving.amount_eur'),
    ('umzugskosten.move_date', 'moving.move_date'),
    ('umzugskosten.reason', 'moving.reason'),
    ('bewerbungskosten.amount_eur', 'applications.amount_eur'),
    ('bewerbungskosten.kind', 'applications.kind');


-- 1. Refuse rather than guess -----------------------------------------------------
--
-- If one case holds both spellings of the same fact for the same item - which mixed
-- code could have written - then renaming would collide with a row that already
-- exists, and picking a winner is not a migration's decision.
do $$
declare
    clash text;
begin
    select string_agg(format('case %s item %s: %s vs %s', v.case_id, v.item_index,
                             r.old, r.new), '; ')
      into clash
      from field_values v
      join key_rename r on r.old = v.key
     where exists (
        select 1 from field_values w
         where w.case_id = v.case_id and w.item_index = v.item_index and w.key = r.new
     );

    if clash is not null then
        raise exception 'both the old and the new key exist for the same fact: %', clash
            using hint = 'decide which value is right, delete the other, then re-run';
    end if;
end $$;


-- 2. The facts themselves ---------------------------------------------------------
--
-- Both triggers come off for the duration. `respect_finalized` would refuse the
-- update on a finalized case, and a finalized case's facts have to be renamed too or
-- its report stops resolving; `touch` would stamp `updated_at` with today, which
-- would say the user edited their answers when nobody did.
alter table field_values disable trigger field_values_respect_finalized;
alter table field_values disable trigger field_values_touch;

update field_values v
   set key = r.new
  from key_rename r
 where v.key = r.old;

alter table field_values enable trigger field_values_touch;
alter table field_values enable trigger field_values_respect_finalized;


-- 3. The fact ids inside a saved tax position -------------------------------------
--
-- `dependent_facts` holds `{"fact_id": ..., "version": ...}` and `missing_facts` a
-- list of keys, sometimes with an item suffix (`equipment.price_eur#1`) and sometimes
-- not a key at all ("arbeitsmittel (values out of range)" names the category). The
-- version hashes stay as they are: they are hashes of values, and no value changes
-- here. `source_refs` is not touched at all - those are rule references of the form
-- `tax-year:2025:anlage-n:...`, not fact keys.
alter table tax_positions disable trigger tax_positions_respect_finalized;
alter table tax_positions disable trigger tax_positions_touch;

update tax_positions p
   set dependent_facts = coalesce((
           select jsonb_agg(
                      case when r.new is null then e.fact
                           else jsonb_set(e.fact, '{fact_id}', to_jsonb(r.new))
                      end
                      order by e.ord)
             from jsonb_array_elements(p.dependent_facts) with ordinality as e(fact, ord)
             left join key_rename r on r.old = e.fact->>'fact_id'
       ), '[]'::jsonb),
       missing_facts = coalesce((
           select jsonb_agg(
                      case when r.new is null then e.name
                           else to_jsonb(r.new || coalesce('#' || nullif(split_part(e.name #>> '{}', '#', 2), ''), ''))
                      end
                      order by e.ord)
             from jsonb_array_elements(p.missing_facts) with ordinality as e(name, ord)
             left join key_rename r on r.old = split_part(e.name #>> '{}', '#', 1)
       ), '[]'::jsonb)
 where p.dependent_facts <> '[]'::jsonb or p.missing_facts <> '[]'::jsonb;

alter table tax_positions enable trigger tax_positions_touch;
alter table tax_positions enable trigger tax_positions_respect_finalized;


-- 4. What the person is remembered by ---------------------------------------------
--
-- Profile memory lives in LangGraph's `store` table, keyed by the same catalogue key
-- (`agents/profile_memory.py`). `recall()` already ignores a key it does not know, so
-- leaving the old rows would look harmless - and would be wrong twice over: the three
-- facts that make a second return shorter would be silently forgotten, and rows
-- holding a person's commute distance would stay in the database under a name nothing
-- can reach, which `services/profile_erasure.py` exists to say is not the same as
-- gone.
do $$
declare
    clash text;
begin
    if to_regclass('public.store') is null then
        return;   -- no interview has ever run against this database
    end if;

    select string_agg(format('%s: %s vs %s', s.prefix, r.old, r.new), '; ')
      into clash
      from store s
      join key_rename r on r.old = s.key
     where exists (select 1 from store t where t.prefix = s.prefix and t.key = r.new);

    if clash is not null then
        raise exception 'profile memory holds both keys for one person: %', clash
            using hint = 'delete the stale one, then re-run';
    end if;

    update store s
       set key = r.new
      from key_rename r
     where s.key = r.old;
end $$;


-- 5. Paused interviews ------------------------------------------------------------
--
-- A paused run keeps its own copy of the case in the checkpoint (`known` in
-- CaseState), and only a *fresh* run rebuilds that from the tables. So a run paused
-- mid-interview would resume with keys the graph no longer recognises, re-ask what it
-- already knows and write the answers back under the new names beside the old.
-- Clearing the thread costs the user one resumption; leaving it costs them their
-- answers, twice over.
--
-- Only threads that belong to a Tax Case in this database, and only if the
-- checkpointer has ever created its tables here.
do $$
declare
    threads text[];
begin
    if to_regclass('public.checkpoints') is null then
        return;
    end if;

    select array_agg(c.user_id::text || ':' || c.id::text) into threads from tax_cases c;
    if threads is null then
        return;
    end if;

    delete from checkpoint_writes where thread_id = any(threads);
    delete from checkpoint_blobs  where thread_id = any(threads);
    delete from checkpoints       where thread_id = any(threads);
end $$;


insert into schema_versions (version) values ('0007')
on conflict (version) do nothing;
