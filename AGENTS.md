## Project reminders

- When work touches the Sprint 3 README, evaluation, demo script, or project
  submission, use only the evidence recorded in `packages/backend/eval/AGENT_EVAL.md`
  and its result artifacts. The evaluated baseline is generated from the Question
  catalogue (35 questions in the preserved runs); the two preserved live runs saved
  15 and 14 questions over the deterministic filter, with zero amount-affecting
  fields lost and zero wrong stop proposals. Present these as dated observations,
  not as a general performance guarantee. Do not introduce the unmeasured
  illustration of roughly 50 questions versus roughly four.

## Agent skills

### Issue tracker

GitHub Issues in `TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1` — the `origin` remote,
not the `personal` deploy remote. See `docs/agents/issue-tracker.md`.

### ELSTER licence obligations

Elena accepted the ERiC licence agreement on 2026-08-31. Before touching ERiC, anything
ELSTER-named or ELSTER-branded, document storage and retention, or a publish to the
public `personal` remote, read `docs/agents/elster-obligations.md` and say which rule you
checked. The agreement text and its data-protection annex live in `elster/`, which is
gitignored on purpose.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See
`docs/agents/domain.md`.
