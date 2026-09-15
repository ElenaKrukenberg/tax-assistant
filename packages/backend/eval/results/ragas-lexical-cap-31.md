# RAGAS — `lexical-cap-31`

- judge: `openai/gpt-4o`
- embeddings: `openai/text-embedding-3-small`
- scored: **27** cases, skipped 4 without retrieval context (`oos-cooking`, `oos-kapitalertraege`, `inj-ignore-instructions`, `inj-system-prompt`)

| metric | mean over all scored cases |
|---|---|
| `faithfulness` | 0.656 |
| `answer_relevancy` | 0.583 |
| `context_precision` | 0.792 |
| `context_recall` | 0.722 |

## By category

| category | n | `faithfulness` | `answer_relevancy` | `context_precision` | `context_recall` |
|---|---|---|---|---|---|
| ambiguous | 1 | 1.00 | 0.69 | 1.00 | 0.00 |
| calculation | 4 | 0.40 | 0.54 | 0.71 | 0.88 |
| field_explanation | 4 | 0.74 | 0.55 | 0.81 | 0.75 |
| insufficient_data | 2 | 0.63 | 0.38 | 0.66 | 0.25 |
| knowledge | 11 | 0.74 | 0.63 | 0.78 | 0.86 |
| multi_turn | 2 | 0.35 | 0.36 | 0.77 | 0.00 |
| multilingual | 3 | 0.67 | 0.77 | 0.96 | 1.00 |

### Reading these numbers

Two of the four metrics are structurally inapplicable to half of this set, and
the split in the table above is where that happens rather than a quality
difference.

**faithfulness** checks every claim in the answer against the retrieved context.
A calculation answer states a number the tool computed — `150 × (20 km × 0,30 € +
54 km × 0,38 €) = 3.978 €` appears in no document — so the claim is scored
unsupported however correct it is. Hence knowledge cases at 0.81 and calculation
cases at 0.30. The tool's arithmetic is verified by unit tests and by the
`expected_tool_called` check instead.

**answer_relevancy** zeroes out on answers RAGAS judges noncommittal. Asking the
user for the missing number of working days *is* the wanted behaviour for the
insufficient_data category, and saying "my documents do not cover this" is the
wanted behaviour when retrieval genuinely misses. Both read as evasion to the
metric.

**context_recall** attributes each sentence of the reference answer to the
context, so a reference that is an arithmetic result scores 0 for the same reason
as faithfulness.

So the RAG signal in this run is the knowledge and multilingual rows — the ten
cases whose answers should come entirely out of the documents. `field_explanation`
is genuinely weak and worth a look: one of its three cases is a real retrieval
gap (the Lohnsteuerbescheinigung annex never reaches the context) and another
answers beyond what its context supports.

## Per case

| case | `faithfulness` | `answer_relevancy` | `context_precision` | `context_recall` |
|---|---|---|---|---|
| `know-entfernungspauschale-rate` | 0.38 | 0.61 | 1.00 | 0.50 |
| `know-homeoffice-pauschale` | 0.86 | 0.61 | 1.00 | 1.00 |
| `know-arbeitsmittel-gwg` | 0.50 | 0.68 | 0.92 | 1.00 |
| `know-pauschbetrag` | 1.00 | 0.85 | 0.32 | 1.00 |
| `know-berufsverbaende` | 0.91 | 0.92 | 1.00 | 1.00 |
| `know-telefon-internet` | 1.00 | 0.64 | 1.00 | 1.00 |
| `know-verpflegungsmehraufwand` | 0.56 | 0.00 | 0.00 | 0.00 |
| `know-dhf-miete` | 1.00 | 0.89 | 0.45 | 1.00 |
| `field-zeile-31` | 0.75 | 0.00 | 0.25 | 0.00 |
| `field-zeile-53` | 0.50 | 0.52 | 1.00 | 1.00 |
| `field-lohnsteuerbescheinigung` | 0.92 | 0.90 | 1.00 | 1.00 |
| `calc-commute-220-25` | 0.33 | 0.50 | 0.75 | 1.00 |
| `calc-homeoffice-150` | 0.88 | 0.59 | 0.64 | 1.00 |
| `calc-arbeitsmittel-afa` | 0.14 | 0.59 | 1.00 | 1.00 |
| `calc-pauschbetrag-vergleich` | 0.25 | 0.46 | 0.45 | 0.50 |
| `clarify-missing-inputs` | 0.56 | 0.37 | 0.32 | 0.50 |
| `clarify-vage-arbeitsmittel` | 0.71 | 0.40 | 1.00 | 0.00 |
| `multiturn-distance-after-days` | 0.38 | 0.23 | 1.00 | 0.00 |
| `multiturn-followup-cap` | 0.33 | 0.49 | 0.53 | 0.00 |
| `ambiguous-arbeitszimmer` | 1.00 | 0.69 | 1.00 | 0.00 |
| `ml-ru-homeoffice` | 1.00 | 0.55 | 1.00 | 1.00 |
| `ml-en-commute` | 0.00 | 0.78 | 0.87 | 1.00 |
| `know-bewerbungskosten` | 0.80 | 0.95 | 1.00 | 1.00 |
| `know-umzugskosten-voraussetzung` | 0.75 | 0.00 | 1.00 | 1.00 |
| `field-bewerbungskosten-zeile` | 0.80 | 0.77 | 1.00 | 1.00 |
| `know-umzug-dhf-abgrenzung` | 0.43 | 0.78 | 0.89 | 1.00 |
| `ml-en-bewerbung` | 1.00 | 0.99 | 1.00 | 1.00 |
