-- One column comment, left behind by 0007.
--
-- `field_values.key` still describes itself with the spelling the rename removed:
-- '"employed_months" or "entfernungspauschale.commuting_days"'. Both are now
-- '"profile.employed_months"' and '"commute.commuting_days"', so the comment a person
-- reads in the dashboard - or `\d+ field_values` - says the opposite of what the
-- column holds.
--
-- Its own file rather than an edit to 0007: that one is applied, and this repository's
-- rule is that an applied file is history (db/README.md). A comment is worth a file;
-- a file that no longer matches what ran is not.

comment on column field_values.key is
    'The Fact key: "profile.employed_months" or "commute.commuting_days", with "#1" '
    'and up for the second and further items of a repeating category. Keyed by what '
    'the value means, never by the category that consumes it (CONTEXT.md, issue #61).';

insert into schema_versions (version) values ('0008')
on conflict (version) do nothing;
