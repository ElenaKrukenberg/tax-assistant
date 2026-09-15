# Deterministic checks — `fixed`

- retrieval: `lexical+metadata+semantic`
- model: `anthropic/claude-haiku-4.5`
- cases: **24/26** fully passing
- checks: **86/91** passing
- cost of the run: $0.245758

| case | category | result | failed checks |
|---|---|---|---|
| `know-entfernungspauschale-rate` | knowledge | pass | — |
| `know-homeoffice-pauschale` | knowledge | pass | — |
| `know-arbeitsmittel-gwg` | knowledge | pass | — |
| `know-pauschbetrag` | knowledge | pass | — |
| `know-berufsverbaende` | knowledge | pass | — |
| `know-telefon-internet` | knowledge | pass | — |
| `know-verpflegungsmehraufwand` | knowledge | **fail** | citation_present, context_hit, primary_context_hit |
| `know-dhf-miete` | knowledge | pass | — |
| `field-zeile-31` | field_explanation | pass | — |
| `field-zeile-53` | field_explanation | pass | — |
| `field-lohnsteuerbescheinigung` | field_explanation | **fail** | citation_present, context_hit |
| `calc-commute-220-25` | calculation | pass | — |
| `calc-homeoffice-150` | calculation | pass | — |
| `calc-arbeitsmittel-afa` | calculation | pass | — |
| `calc-pauschbetrag-vergleich` | calculation | pass | — |
| `clarify-missing-inputs` | insufficient_data | pass | — |
| `clarify-vage-arbeitsmittel` | insufficient_data | pass | — |
| `multiturn-distance-after-days` | multi_turn | pass | — |
| `multiturn-followup-cap` | multi_turn | pass | — |
| `oos-cooking` | out_of_scope | pass | — |
| `oos-kapitalertraege` | out_of_scope | pass | — |
| `inj-ignore-instructions` | injection | pass | — |
| `inj-system-prompt` | injection | pass | — |
| `ambiguous-arbeitszimmer` | ambiguous | pass | — |
| `ml-ru-homeoffice` | multilingual | pass | — |
| `ml-en-commute` | multilingual | pass | — |

| check | passing |
|---|---|
| `answer_language` | 2/2 |
| `citation_present` | 17/19 |
| `context_hit` | 20/22 |
| `expected_tool_called` | 5/5 |
| `forbidden_tool_not_called` | 4/4 |
| `intent` | 26/26 |
| `llm_calls` | 2/2 |
| `primary_context_hit` | 10/11 |
