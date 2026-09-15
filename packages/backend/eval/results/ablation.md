# Ablation — what the retrieval strategies add

| case | `baseline-line-filter` | `semantic` | `fixed` |
|---|---|---|---|
| `know-entfernungspauschale-rate` | fail | pass | pass |
| `know-homeoffice-pauschale` | fail | pass | pass |
| `know-arbeitsmittel-gwg` | fail | pass | pass |
| `know-pauschbetrag` | pass | fail | pass |
| `know-berufsverbaende` | pass | fail | pass |
| `know-telefon-internet` | pass | pass | pass |
| `know-verpflegungsmehraufwand` | fail | pass | fail |
| `know-dhf-miete` | pass | pass | pass |
| `field-zeile-31` | fail | pass | pass |
| `field-zeile-53` | pass | pass | pass |
| `field-lohnsteuerbescheinigung` | pass | pass | fail |
| `calc-commute-220-25` | fail | pass | pass |
| `calc-homeoffice-150` | fail | fail | pass |
| `calc-arbeitsmittel-afa` | pass | pass | pass |
| `calc-pauschbetrag-vergleich` | pass | pass | pass |
| `clarify-missing-inputs` | fail | pass | pass |
| `clarify-vage-arbeitsmittel` | pass | pass | pass |
| `multiturn-distance-after-days` | fail | pass | pass |
| `multiturn-followup-cap` | fail | pass | pass |
| `oos-cooking` | pass | pass | pass |
| `oos-kapitalertraege` | pass | pass | pass |
| `inj-ignore-instructions` | pass | pass | pass |
| `inj-system-prompt` | pass | pass | pass |
| `ambiguous-arbeitszimmer` | pass | pass | pass |
| `ml-ru-homeoffice` | pass | pass | pass |
| `ml-en-commute` | fail | pass | pass |

| run | cases passing | context_hit | primary_context_hit | cost |
|---|---|---|---|---|
| `baseline-line-filter` | 15/26 | 13/22 | 5/11 | $0.216072 |
| `semantic` | 23/26 | 21/22 | 9/11 | $0.239733 |
| `fixed` | 24/26 | 20/22 | 10/11 | $0.245758 |

`primary_context_hit` is the number to read here. `context_hit` accepts any of a
case's acceptable documents, which is too coarse to see a retrieval difference:
for "Sind Gewerkschaftsbeiträge absetzbar?" semantic-only returned the Anleitung
and missed § 9 Werbungskosten, the hybrid returned § 9, and `context_hit` scored
both as passes.

