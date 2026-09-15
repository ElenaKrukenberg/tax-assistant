# Ablation on k — when does each reference document become reachable?

- retrieval: `lexical+metadata+semantic`, ranked to k=12
- analyzer: `anthropic/claude-haiku-4.5` (one call per case, cached)

`k` does not change the ranking — the strategies overfetch to `FETCH_K` and the
pooled result is sorted before `[:k]` slices it — so the rank below is the
smallest k at which that document enters the context.

| case | reference doc at k= | primary doc at k= | candidates ranked |
|---|---|---|---|
| `know-entfernungspauschale-rate` | 1 | 1 | 12 |
| `know-homeoffice-pauschale` | 1 | n/a | 12 |
| `know-arbeitsmittel-gwg` | 1 | n/a | 12 |
| `know-pauschbetrag` | 5 | 5 | 12 |
| `know-berufsverbaende` | 1 | 3 | 12 |
| `know-telefon-internet` | 1 | 2 | 12 |
| `know-verpflegungsmehraufwand` | 1 | 1 | 12 |
| `know-dhf-miete` | 1 | 1 | 12 |
| `field-zeile-31` | 3 | 3 | 12 |
| `field-zeile-53` | 1 | 1 | 12 |
| `field-lohnsteuerbescheinigung` | 1 | n/a | 12 |
| `calc-commute-220-25` | 1 | 1 | 12 |
| `calc-homeoffice-150` | 2 | n/a | 12 |
| `calc-arbeitsmittel-afa` | 1 | n/a | 12 |
| `calc-pauschbetrag-vergleich` | 2 | n/a | 12 |
| `clarify-missing-inputs` | 1 | n/a | 12 |
| `clarify-vage-arbeitsmittel` | 1 | n/a | 12 |
| `multiturn-distance-after-days` | 1 | 1 | 12 |
| `multiturn-followup-cap` | 2 | n/a | 12 |
| `ambiguous-arbeitszimmer` | 2 | n/a | 12 |
| `ml-ru-homeoffice` | 2 | n/a | 12 |
| `ml-en-commute` | 1 | 1 | 12 |
| `know-bewerbungskosten` | 1 | 1 | 12 |
| `know-umzugskosten-voraussetzung` | 1 | 1 | 12 |
| `field-bewerbungskosten-zeile` | 1 | 1 | 12 |
| `know-umzug-dhf-abgrenzung` | 1 | 1 | 12 |
| `ml-en-bewerbung` | 1 | 1 | 12 |

| k | context_hit | primary_context_hit |
|---|---|---|
| 5 | 27/27 | 16/16 |
| 6 | 27/27 | 16/16 |
| 7 | 27/27 | 16/16 |
| 8 | 27/27 | 16/16 |
| 10 | 27/27 | 16/16 |
| 12 | 27/27 | 16/16 |

A dash means the document is not in the top 12 at all, so no k in this range reaches it.
