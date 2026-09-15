# Deterministic checks — `semantic`

- retrieval: `semantic`
- model: `anthropic/claude-haiku-4.5`
- cases: **23/26** fully passing
- checks: **86/91** passing
- cost of the run: $0.239733

| case | category | result | failed checks |
|---|---|---|---|
| `know-entfernungspauschale-rate` | knowledge | pass | — |
| `know-homeoffice-pauschale` | knowledge | pass | — |
| `know-arbeitsmittel-gwg` | knowledge | pass | — |
| `know-pauschbetrag` | knowledge | **fail** | citation_present, context_hit, primary_context_hit |
| `know-berufsverbaende` | knowledge | **fail** | primary_context_hit |
| `know-telefon-internet` | knowledge | pass | — |
| `know-verpflegungsmehraufwand` | knowledge | pass | — |
| `know-dhf-miete` | knowledge | pass | — |
| `field-zeile-31` | field_explanation | pass | — |
| `field-zeile-53` | field_explanation | pass | — |
| `field-lohnsteuerbescheinigung` | field_explanation | pass | — |
| `calc-commute-220-25` | calculation | pass | — |
| `calc-homeoffice-150` | calculation | **fail** | expected_tool_called |
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
| `citation_present` | 18/19 |
| `context_hit` | 21/22 |
| `expected_tool_called` | 4/5 |
| `forbidden_tool_not_called` | 4/4 |
| `intent` | 26/26 |
| `llm_calls` | 2/2 |
| `primary_context_hit` | 9/11 |
