# Ablation — what the retrieval strategies add

| case | `fixed` | `lexical-cap` | `lexical-cap-k7` |
|---|---|---|---|
| `know-entfernungspauschale-rate` | pass | pass | pass |
| `know-homeoffice-pauschale` | pass | pass | pass |
| `know-arbeitsmittel-gwg` | pass | pass | pass |
| `know-pauschbetrag` | pass | pass | pass |
| `know-berufsverbaende` | pass | pass | pass |
| `know-telefon-internet` | pass | pass | pass |
| `know-verpflegungsmehraufwand` | fail | pass | pass |
| `know-dhf-miete` | pass | pass | pass |
| `field-zeile-31` | pass | pass | fail |
| `field-zeile-53` | pass | pass | pass |
| `field-lohnsteuerbescheinigung` | fail | pass | pass |
| `calc-commute-220-25` | pass | pass | pass |
| `calc-homeoffice-150` | pass | pass | pass |
| `calc-arbeitsmittel-afa` | pass | pass | pass |
| `calc-pauschbetrag-vergleich` | pass | pass | pass |
| `clarify-missing-inputs` | pass | pass | pass |
| `clarify-vage-arbeitsmittel` | pass | pass | pass |
| `multiturn-distance-after-days` | pass | pass | pass |
| `multiturn-followup-cap` | pass | pass | pass |
| `oos-cooking` | pass | pass | pass |
| `oos-kapitalertraege` | pass | pass | pass |
| `inj-ignore-instructions` | pass | pass | pass |
| `inj-system-prompt` | pass | pass | pass |
| `ambiguous-arbeitszimmer` | pass | pass | pass |
| `ml-ru-homeoffice` | pass | pass | pass |
| `ml-en-commute` | pass | pass | pass |

| run | k | cases passing | context_hit | primary_context_hit | cost |
|---|---|---|---|---|---|
| `fixed` | 5 | 24/26 | 20/22 | 10/11 | $0.245758 |
| `lexical-cap` | 5 | 26/26 | 22/22 | 11/11 | $0.249592 |
| `lexical-cap-k7` | 7 | 25/26 | 22/22 | 11/11 | $0.286542 |

`primary_context_hit` is the number to read for a retrieval change. `context_hit`
accepts any of a case's acceptable documents, which is often too coarse to show a
difference — for "Sind Gewerkschaftsbeiträge absetzbar?" semantic-only returned the
Anleitung and missed § 9 Werbungskosten, the hybrid returned § 9, and `context_hit`
scored both as passes. When both columns are equal across runs, whatever moved in
the case table moved in generation, not in retrieval.

