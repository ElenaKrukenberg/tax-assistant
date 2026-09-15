-- The Reviewer names the topic a finding is about ("entfernungspauschale"), and
-- until now that name had nowhere to go: `findings` could only point at a row in
-- `expenses`, which this build never writes — expenses are recomputed on read from
-- domain/estimate.py so the screens can never show a figure the graph disagrees
-- with. So the column the Review screen actually needs was missing, and the
-- findings themselves were never stored at all: they lived in the graph checkpoint,
-- were shown once inside the interview, and vanished.
--
-- Empty string, not null: a finding about the case as a whole belongs to no single
-- topic, and "no topic" is a real answer rather than missing data.

alter table findings add column if not exists category text not null default '';

comment on column findings.category is
    'The expense category the finding is about, or empty for the case as a whole. '
    'Matches the keys in domain/questions.py, so the frontend can label it.';
