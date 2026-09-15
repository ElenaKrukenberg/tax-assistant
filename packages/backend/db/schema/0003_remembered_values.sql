-- A fourth provenance: a value carried over from the same person's earlier case.
--
-- Apply after 0002_usage.sql, through the Supabase SQL editor. Until it is applied
-- the backend simply does not carry anything over — profile memory fails soft and
-- logs, rather than breaking an interview against an unmigrated database.
--
-- Why a provenance of its own rather than reusing 'assumed': the product's promise
-- is that every figure can say where it came from, and "you told us this last year"
-- is a different claim from "we guessed because you could not say". Both are
-- unconfirmed until the user looks at them, which is what the two constraints below
-- keep true; only the sentence shown to the user differs.

alter table field_values drop constraint if exists field_values_provenance_check;
alter table field_values add constraint field_values_provenance_check
    check (provenance in ('answer', 'document', 'assumed', 'remembered'));

-- Widened from an_assumption_carries_its_reason: a remembered value has to name the
-- year it came from for the same reason an assumption has to name its reason — a
-- value the user is asked to confirm must say what it is they are confirming.
alter table field_values drop constraint if exists an_assumption_carries_its_reason;
alter table field_values add constraint a_value_the_user_must_confirm_says_why
    check (provenance not in ('assumed', 'remembered') or length(source) > 0);

comment on column field_values.provenance is
    'answer | document | assumed | remembered. Assumed and remembered values must be '
    'confirmed before a report.';
