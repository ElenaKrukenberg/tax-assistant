# Which vision model reads the documents

Research for [issue #11](https://github.com/TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1/issues/11),
**re-measured 2026-09-01 for [issue #65](https://github.com/TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1/issues/65)** across the whole permitted model
set. Measured against OpenRouter with this project's own `OPENROUTER_API_KEY`
(`packages/backend/.env`). Every price below is the `usage.cost` OpenRouter itself
billed for that call, not a per-million rate multiplied out by hand.

**The harness is now committed**, which it was not the first time: see
`packages/backend/eval/vision_sweep/` for the probe, the document generator, the
sweep and its README, the three test documents and their ground truth, with every
raw answer in `packages/backend/eval/results/vision-sweep.json`. The first sweep
committed only this note, so its numbers could not be re-derived. These can.

Two things about the first pass turned out to be wrong, and both are corrected below:

- **The unreachable models were never a privacy setting.** They are a model allowlist
  on the course account, which is not Elena's to change
  ([issue #15](https://github.com/TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1/issues/15)). §1 is rewritten.
- **The first sweep probed 31 models and measured 8.** A full probe of all 226
  vision-capable candidates finds **24 reachable**, so two thirds of the permitted
  set had never been measured — including `x-ai/grok-4.5`, which is where the
  recommendation now lands.

---

## Recommendation

**Unchanged from the first pass, and now measured against the whole permitted set:
use `google/gemini-3.7-flash` with `reasoning: {"effort": "low"}`, a strict
`response_format` JSON schema, and two passes per document.**

Of the 23 models this key can call, two read all three documents with **no wrong
field in any of 3 runs**: `google/gemini-3.7-flash` and `x-ai/grok-4.5`. At default
effort grok is marginally cheaper (0.358 c against 0.411 c per pass); `effort: "low"`
takes gemini to **0.310 c with the same perfect result** and does nothing for grok,
which appears to ignore the parameter. So gemini wins on price among equals, and it
wins having been compared against every alternative rather than a third of them.

| | |
|---|---|
| Model string | `google/gemini-3.7-flash`, `reasoning: {"effort": "low"}` |
| Cost, one pass, A4 scan | **0.37 cents** |
| Cost, one pass, phone photo | **0.21 cents** |
| Cost, one pass, degraded scan | **0.35 cents** |
| Cost, two passes, per document | **~0.62 cents** |
| 20 testers x 3 documents = 60 docs, two-pass | **~$0.37** |
| Submission day, ~5 uploads, two-pass | **~3.1 cents** |
| Accuracy, all three documents | **16/16, 10/10 and 16/16 fields correct, 3/3 runs each** |
| Runner-up | `x-ai/grok-4.5`, also perfect, 0.358 c/pass, unaffected by `effort` |

**The cost model from the first pass needs a small restatement: ~0.62 c per document
two-pass, not ~0.55 c.** The figure moved for two measurement reasons, not because
prices changed: this sweep grades 16 payslip fields against the first pass's 9, and it
averages over three documents including the degraded scan rather than two clean ones.
Nothing downstream depends on the third decimal — at 0.62 c, a thousand uploads is
$6.20, still nowhere near the money guards in `core/config.py`.

**`effort: "low"` is still free accuracy.** 0.411 c to 0.310 c per pass, identical
field-level results on all three documents. The saving is completion tokens (666 down
to 551 on the A4 scan, 678 down to 213 on the photo), which is thinking, not answer.

### What the wider set changed

**Two thirds of the permitted models had never been measured, and none of them beat
the incumbent.** The 16 newly-measured models are in the [comparison
table](#comparison-table); the ranking that matters is *silent* errors, then total
wrong, then price.

**The one Anthropic flagship this key permits cannot do structured output at all.**
`anthropic/claude-opus-4.7` — the model `core/config.py` calls the preferred
long-term choice — answers HTTP 200 with valid JSON under **keys of its own
invention**: `dokumenttyp`, `arbeitgeber`, `arbeitnehmer`, `bescheinigungszeitraum`,
`betraege`. The values are right; the shape is not the one requested, in 3 of 3 runs
on every document, and `supported_parameters` claims `structured_outputs: true`.
`anthropic/claude-3-haiku` does the same with capitalised German keys. This is the
first pass's finding #2 in [§3](#3-structured-output), except that it now applies to
the flagship rather than only to a legacy model — **so the comment at
`core/config.py:77` about switching to the Anthropic line is not a plan that can be
carried out for document intake.** ([Pin the provider data policy in code and correct
the model comments](https://github.com/TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1/issues/66) owns that edit.)

**The cheap Gemini fallbacks are more dangerous than the first pass reported, not
less.** `google/gemini-2.5-flash` at 0.140 c and `-flash-lite` at 0.033 c each got 4
fields wrong on the degraded scan and **all 4 were silent** — identical in all three
runs, non-null, so two passes cannot catch them. On `gemini-2.5-flash` those were:

    solidarity_surcharge_eur   0,00      ->  615,78     (the church-tax row, shifted)
    church_tax_eur             615,78    ->  348,00     (the row below it)
    care_insurance_employee_eur  710,86  ->  710,06
    employer_name  Möbelwerkstatt Krämer -> Möbeleerkstatt Kramer

The first two would put €615.78 of solidarity surcharge into a tax return that never
withheld any. **Revised fallback advice: if `gemini-3.7-flash` becomes unreachable,
fall back to `x-ai/grok-4.5`, not to a cheaper Gemini.** Neither 2.5 model is safe for
money fields without the arithmetic cross-check from [§4](#4-confidence), and that
check is what would have caught these.

**`anthropic/claude-haiku-4.5` — the current `LLM_MODEL` — remains the wrong choice,
now for a second reason.** It is clean on the clean A4 scan under this schema, so the
first pass's date inversion did not reproduce (a different `Bescheinigungszeitraum`
was rendered; see [open questions](#open-questions)). But it has 4 silent errors
across the photo and the degraded scan, including a scrambled invoice: right item
descriptions, wrong prices attached to them —

    Bürostuhl Drehstuhl Aristo    1 x 312,61  ->  2 x  46,25
    Monitorarm Duo                2 x  46,25  ->  1 x 689,00
    Schreibtisch Ergoline         1 x 689,00  ->  1 x 312,61

— identical in all three runs. Every line is individually plausible and the total is
wrong. It also costs 0.354 c, more than the recommended model.

Three reasons from the first pass survive unchanged:

1. **Self-reported confidence is not a confidence signal.** Reproduced across this
   sweep's 216 runs; `confidence` is not graded here for that reason. See
   [§4](#4-confidence).
2. **A typed schema survives the OpenRouter hop — and fails silently when it does
   not.** See [§3](#3-structured-output), which now also records two provider limits
   on the schema itself that were not known before.
3. **A phone photo is not the hard case; a bad scan is.** 20 of 21 gradeable models
   read the 3024x3948 rotated invoice with at most one field wrong. The 623x862
   quality-35 payslip is where every model that fails, fails.

### What ADR 0004 implies for this

[ADR 0004](../adr/0004-documents-are-read-then-discarded.md) discards the file after
reading, so extraction is one transient pass and the model can never re-read the
document. Three consequences follow, and they drive the recommendation more than
raw model quality does:

- **The two-pass check must happen inside that one transient window**, before the
  bytes are dropped — not later as a re-read. Both calls have to be made while the
  upload is still in memory. At 0.62 c per document this is affordable; the design
  question is only where the second call sits in the request path.
- **There is no cheap second chance**, so the failure that matters is the *silent*
  one: a wrong value that looks right. That is exactly the haiku date error, and
  exactly why a deterministic per-field error is worse than a noisy one.
- **Per-document citations would have been the ideal audit trail and are not
  available.** Anthropic's direct API can return citation blocks pointing at the
  page and text that produced a value, which would have survived the file's deletion
  as evidence. They do not survive the OpenRouter hop ([§3](#3-structured-output)),
  so the only provenance the project can keep is what `field_values.provenance`
  already records: `'document'` plus the file name.

---

## Comparison table

All 23 models this key can call, measured 2026-09-01 with the same German
instruction, the same strict `response_format` schema per document type, 3 runs per
document, `temperature: 0`, and `provider={"zdr": True}` on every call. Default
reasoning effort — the `effort: "low"` control is in the
[recommendation](#recommendation).

Read the columns as **wrong / silent**:

- **wrong** — a graded field whose value differs from ground truth.
- **silent** — wrong, identical in all 3 runs, and not `null`: an error no second
  pass and no `null` check can catch. **This is the column that decides the
  recommendation.** A caught error costs one more call; a silent one puts a wrong
  figure in a tax return with nothing to flag it.
- **schema ignored** — the model answered HTTP 200 with valid JSON under keys it
  invented rather than the ones the schema required. Not graded field by field,
  because it never filled the fields in; scoring it as "every field wrong but every
  one caught" would read as caution rather than as unusability.

Rows are ordered by silent errors, then total wrong, then price.

| Model string | Clean A4 | Phone photo | Degraded scan | Total silent | Cost per pass |
|---|---|---|---|---|---|
| `x-ai/grok-4.5` | **0** | **0** | **0** | **0** | 0.358 c |
| `google/gemini-3.7-flash` | **0** | **0** | **0** | **0** | 0.411 c |
| `openai/gpt-4o` | **0** | **0** | 1 / 0 | **0** | 0.457 c |
| `openai/gpt-5.6-luna` | **0** | 1 / 0 | 1 / 0 | **0** | 0.186 c |
| `openai/gpt-5.2` | **0** | **0** | 2 / 0 | **0** | 1.166 c |
| `openai/gpt-5.5` | **0** | **0** | 2 / 0 | **0** | 3.312 c |
| `google/gemma-4-31b-it` | **0** | 1 / 0 | 3 / 0 | **0** | 0.020 c |
| `openai/gpt-5-mini` | **0** | 1 / 0 | 3 / 0 | **0** | 0.303 c |
| `openai/gpt-5.2-codex` | **0** | 1 / 0 | 3 / 0 | **0** | 1.374 c |
| `openai/gpt-5.6-terra` | **0** | 1 / 0 | 3 / 0 | **0** | 1.540 c |
| `openai/gpt-4o-mini` | **0** | **0** | 5 / 0 | **0** | 0.391 c |
| `openai/gpt-5.4-mini` | **0** | 1 / 0 | 6 / 0 | **0** | 0.175 c |
| `openai/gpt-4.1-nano` | **0** | 1 / 0 | 7 / 0 | **0** | 0.026 c |
| `openai/gpt-5-nano` | **0** | **0** | 10 / 0 | **0** | 0.127 c |
| `openai/gpt-5.4-nano` | 5 / 0 | 3 / 0 | 10 / 0 | **0** | 0.043 c |
| `openai/gpt-5.4` | **0** | **0** | 3 / 1 silent | **1** | 0.498 c |
| `openai/gpt-4.1-mini` | **0** | 1 / 1 silent | 2 / 1 silent | **2** | 0.081 c |
| `openai/gpt-5.6-sol` | **0** | **0** | 3 / 2 silent | **2** | 2.660 c |
| `google/gemini-2.5-flash-lite` | **0** | **0** | 4 / 4 silent | **4** | 0.033 c |
| `google/gemini-2.5-flash` | **0** | **0** | 4 / 4 silent | **4** | 0.140 c |
| `anthropic/claude-haiku-4.5` | **0** | 1 / 1 silent | 7 / 3 silent | **4** | 0.354 c |
| `anthropic/claude-3-haiku` | **schema ignored** | **schema ignored** | **schema ignored** | – | – |
| `anthropic/claude-opus-4.7` | **schema ignored** | **schema ignored** | **schema ignored** | – | – |

Graded fields: 16 on the payslip (both the clean and the degraded render), 10 on the
invoice including all three line items compared as a set. `confidence` is requested
but not graded — see [§4](#4-confidence).

Every raw answer is in `packages/backend/eval/results/vision-sweep.json`;
`eval/vision_sweep/sweep.py --regrade` rescores it without paying for calls again.

Test documents, held to the first pass's specs and now committed at
`packages/backend/eval/vision_sweep/documents/`: a synthetic *Ausdruck der
elektronischen Lohnsteuerbescheinigung für 2025* at A4 150 dpi (1240x1754 px, 134 KB
JPEG, 11 numbered lines including `Bruttoarbeitslohn 41.238,76`), a synthetic German
invoice as a phone photo (3024x3948 px, 364 KB JPEG, rotated 3.5°, quality 70), and a
deliberately degraded render of the payslip (623x862 px, quality 35, blurred, noise
added, rotated 1.8° so row labels and amount columns no longer line up).

**These are not byte-identical to the first pass's documents**, which no longer exist,
so ground truth was recreated with them and the two tables' *absolute* field counts
are not comparable — 16 graded payslip fields here against 9 there. What is comparable
is the ranking, and the failure modes, which reproduced.

## 1. Which vision-capable models are actually reachable

**This section said the wrong thing the first time.** It attributed the 404s to the
account's privacy toggle at <https://openrouter.ai/settings/privacy>, and recommended
re-running the sweep if that toggle were changed.
[Issue #15](https://github.com/TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1/issues/15) established the actual cause: **a model allowlist on the course
account**, which is not Elena's to change and will not be changed. `claude-sonnet-5`
will never be reachable with this key. The privacy toggle is a separate thing, and it
is not currently blocking anything at all.

OpenRouter's model list ([`GET /api/v1/models`](https://openrouter.ai/api/v1/models),
retrieved 2026-09-01) returns 418 models, of which **249 declare `image` in
`architecture.input_modalities`**. Dropping aliases (`~…-latest`, `openrouter/…`,
whose target can change under the name) and image *generators* (`image` in
`output_modalities`) leaves **226 real candidates**.

**Probing all 226 finds 24 reachable.** A blocked model 404s before any billing, so
the probe cost $0.0099 in total — only the reachable ones bill, and only for a 32x32
image. `eval/vision_sweep/probe.py` is the probe; `reachable-zdr.json` its output.

*Reachable (24):* `anthropic/claude-3-haiku`, `anthropic/claude-haiku-4.5`,
`anthropic/claude-opus-4.7`, `google/gemini-2.5-flash`,
`google/gemini-2.5-flash-lite`, `google/gemini-3.7-flash`, `google/gemma-4-31b-it`,
`openai/gpt-4.1-mini`, `openai/gpt-4.1-nano`, `openai/gpt-4o`,
`openai/gpt-4o-2024-11-20`, `openai/gpt-4o-mini`, `openai/gpt-5-mini`,
`openai/gpt-5-nano`, `openai/gpt-5.2`, `openai/gpt-5.2-codex`, `openai/gpt-5.4`,
`openai/gpt-5.4-mini`, `openai/gpt-5.4-nano`, `openai/gpt-5.5`,
`openai/gpt-5.6-luna`, `openai/gpt-5.6-sol`, `openai/gpt-5.6-terra`,
`x-ai/grok-4.5`.

**`anthropic/claude-opus-4.7` is reachable** — the first pass tried `claude-opus-4.8`
and `claude-opus-4.5`, both 404, and never `4.7`. It is the one Anthropic flagship the
allowlist permits, and [§3](#3-structured-output) is why it cannot be used anyway.

The other 202 fall into four groups, and only the first is the allowlist:

| Response | Count | What it means |
|---|---|---|
| 404 "No endpoints available matching your guardrail restrictions and data policy" | 102 | The account allowlist. Not changeable from here. |
| 404 "This model is only available through the Batch API" | 57 | A different endpoint (`/api/beta/batches`), not a block. Useless for an interactive upload either way. |
| 404 "No endpoints found matching your data policy (Zero data retention)" | 39 | Caused by the probe's own `provider={"zdr": True}`. See below. |
| 400 / 403 | 4 | Age confirmation, agentic-harness-only models, and provider faults. |

### What `provider={"zdr": True}` costs in reachability: one model

Issue #15 decided that every call sends `provider={"zdr": True}`, so the sweep does
too. Probed both ways, that policy removes exactly **one** of the 24:
`openai/gpt-4o-2024-11-20`, a dated pin of `openai/gpt-4o`, which is itself reachable
under ZDR. **So ZDR is close to free here** — 23 of 24 models survive it, and the one
lost duplicates a survivor.

Worth stating plainly because it is the opposite of what the first pass assumed: the
zero-data-retention requirement is not what narrows the field. The allowlist is.

Two things about this measurement are worth keeping, because both cost time:

- **Two models were reported blocked by a transient fault.** `openai/gpt-4o` returned
  429 on the first ZDR probe and 200 on a re-probe. A single probe pass therefore
  understates reachability; `probe.py` retries a 400 once, and a 429 needs re-probing
  by hand.
- **A 1x1 pixel probe image reports reachable models as blocked.** The first probe
  used one, and several providers answered HTTP 400 "Provider returned error" —
  indistinguishable from a real block, and it put the reachable count at 4 instead of
  24. 32x32 is the smallest size every provider tested accepts, and is what `probe.py`
  now sends.

Two incidental findings from the first pass, still standing:

- `core/pricing.py` lists `anthropic/claude-sonnet-5` at $3.00/$15.00 per 1M. The
  OpenRouter list publishes **$2.00/$10.00**. Stale, not a bug — and moot, since the
  model is not reachable.
- `openai/gpt-4o-mini` billed 8509 prompt tokens for a **32x32 pixel** image on the
  first pass. Unexplained.

**Reachability is a property of the account, not of this repo.** Whatever model is
chosen, the startup check should call it once rather than trust `render.yaml` — the
allowlist can change without any code change here, and the first pass's advice on that
point was right even though its explanation was not.

## 2. Price per document, with the token maths

### The vendor formulas

**Anthropic.** "Claude views images in patches instead of pixels. Each patch is a
28x28-pixel block of the image, referred to as a visual token. An image, therefore,
costs `⌈width / 28⌉ x ⌈height / 28⌉` visual tokens."
(<https://platform.claude.com/docs/en/build-with-claude/vision>)

For the A4 payslip at 1240x1754: `⌈1240/28⌉ x ⌈1754/28⌉ = 45 x 63 = 2835` visual
tokens. Measured `prompt_tokens` was **3022**, leaving ~187 tokens for the German
instruction and the schema — the formula predicts the observed bill. At Haiku 4.5's
$1.00/1M input that is $0.0028 of image, and the call cost $0.004014 in total
(187 completion tokens at $5.00/1M).

The same page documents two resolution tiers — standard (max long edge 1568 px,
max 1568 visual tokens) and high-resolution (2576 px / 4784 tokens, for "Claude 4.7
and later models"). The measured 2835 tokens for a 1754 px-tall image exceeds the
standard tier's 1568-token cap without being downscaled, so `claude-haiku-4.5` as
served through OpenRouter did **not** apply the standard-tier cap. I could not
reconcile this with the documented tier table and have not resolved it (see
[open questions](#open-questions)).

**Google.** "258 tokens if both dimensions <= 384 pixels"; larger images are tiled
into 768x768 crops at 258 tokens each
(<https://ai.google.dev/gemini-api/docs/image-understanding>). Confirmed directly:
the 32x32 probe billed exactly **260** prompt tokens on `gemini-2.5-flash` (258 image
+ 2 text). For the A4 payslip the doc's crop rule gives `floor(min(1240,1754)/1.5) =
826`, so `⌈1240/826⌉ x ⌈1754/826⌉ = 2 x 3 = 6` tiles = 1548 image tokens; measured
`prompt_tokens` was 1890 including prompt and schema.

**OpenAI.** 32x32 patches, `patch_count = ⌈width/32⌉ x ⌈height/32⌉`, capped at a
2500-patch budget for `detail: high`, then multiplied by a per-model multiplier
(1.2x for GPT-5.4, 1.62x for GPT-4.1-mini)
(<https://developers.openai.com/api/docs/guides/images-vision>). For the A4 payslip
`⌈1240/32⌉ x ⌈1754/32⌉ = 39 x 55 = 2145` patches; at 1.2x that is 2574 image tokens
against a measured 2997 total. I could **not** reproduce OpenAI's numbers exactly
from the measured totals across both documents (the implied multiplier for
`gpt-5.4-mini` came out near 1.3x on the A4 scan and near 1.6x on the degraded one),
so treat the OpenAI figures in the table as measured-only.

### Measured cost per document

`usage.cost` as billed by OpenRouter, one call, strict schema, ~200 tokens of German
instruction:

**The table below is the first pass's, on 8 models and 2 documents.** The
re-measurement's cost per pass for all 23 models, over 3 documents, is in the
[comparison table](#comparison-table); the two sets of figures differ by a few
hundredths of a cent because the schema here is larger. Both are `usage.cost` as
billed.

| Model | A4 scan 1240x1754 | Phone photo 3024x3948 |
|---|---|---|
| `google/gemini-2.5-flash-lite` | $0.000213 (0.021 c) | $0.000499 (0.050 c) |
| `openai/gpt-5.4-nano` | $0.000801 (0.080 c) | $0.000911 (0.091 c) |
| `google/gemini-2.5-flash` | $0.001192 (0.119 c) | $0.001719 (0.172 c) |
| `openai/gpt-4.1-mini` | $0.001375 (0.137 c) | $0.001428 (0.143 c) |
| `openai/gpt-5.4-mini` | $0.001435 (0.144 c) | $0.003378 (0.338 c) |
| `openai/gpt-5-mini` | $0.002197 (0.220 c) | $0.003275 (0.328 c) |
| **`google/gemini-3.7-flash`, effort low** | **$0.002299 (0.230 c)** | **$0.002385–0.003139 (0.24–0.31 c)** |
| `google/gemini-3.7-flash`, default effort | $0.004536 (0.454 c) | $0.003649 (0.365 c) |
| `anthropic/claude-haiku-4.5` | $0.004014 (0.401 c) | $0.004210 (0.421 c) |

**`reasoning: {"effort": "low"}` halves the Gemini 3.7 bill at no measured accuracy
cost** — 0.454 c to 0.230 c on the clean scan and 0.485 c to 0.282 c on the degraded
one, identical field-level results in both. `"effort": "none"` is rejected with
HTTP 400 "Reasoning is mandatory for this endpoint and cannot be disabled", so `low`
is the floor. The saving is entirely in completion tokens (1025 down to 182), which
is thinking, not answer.

### Cohort

20 testers x 3 documents = 60 documents, at the recommended two-pass configuration
(~0.62 c per document, re-measured 2026-09-01): **~$0.37 total.** Single-pass: ~$0.19.
On `x-ai/grok-4.5` two-pass it would be ~$0.43; on `claude-haiku-4.5` ~$0.42; on
`gemini-2.5-flash` ~$0.17; on `gemini-2.5-flash-lite` ~$0.04. The two cheap Gemini
options are the ones with 4 silent errors each — see the
[recommendation](#recommendation).

None of these figures is near the money guards in `core/config.py`
(`interview_calls_global_per_month: 3000`, ~$10/month). Document intake is not the
cost risk in this project — at 0.62 c a document, 1000 uploads is $6.20. What
constrains the design is silent wrongness, not spend.

## 3. Structured output

**OpenRouter accepts the OpenAI shape and passes it through.** 21 of the 23 reachable
models returned valid, schema-conforming JSON that `json.loads` parsed with no repair
step, across 207 calls in the re-measurement (and all twelve models the first pass
tried), using:

```json
{
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "payslip",
      "strict": true,
      "schema": { "type": "object", "additionalProperties": false, "required": ["..."], "properties": { "...": {} } }
    }
  }
}
```

Nullable typed fields (`{"type": ["number", "null"]}`), a `confidence` enum, and a
nested array of line items were all honoured. `supported_parameters` in the model
list includes `structured_outputs` and `response_format` for every reachable
candidate; the filtered list is at
<https://openrouter.ai/models?supported_parameters=structured_outputs>
(<https://openrouter.ai/docs/features/structured-outputs>).

**Three things do not survive the hop, and two of them fail silently.**

1. **Anthropic's native `output_config` is silently ignored.** The direct Anthropic
   API takes `output_config: {format: {type: "json_schema", schema: {...}}}` and
   guarantees conformance by constrained decoding
   (<https://platform.claude.com/docs/en/build-with-claude/structured-outputs>).
   Sending that field to `anthropic/claude-haiku-4.5` through OpenRouter returns
   **HTTP 200** and a markdown-fenced code block:

   ````
   ```json
   {
     "employer": "ACME"
   }
   ```
   ````

   No error, no constraint — the parameter is dropped and the reply is prose that
   happens to contain JSON. Use `response_format`, never `output_config`.

2. **`strict: true` is silently ignored on models that do not support it.** The
   OpenRouter docs say an unsupported request "will fail with an error indicating
   lack of support". It does not. `anthropic/claude-3-haiku`, whose OpenRouter
   metadata reports `structured_outputs: false`, accepted the identical strict
   `response_format` and returned **HTTP 200** with `"Okay, got it. ACME is the
   employer in this case."` — free prose where a typed object was requested. This is
   the failure mode the ticket is worried about: the parsing step fails, not the
   request. **The code must check `supported_parameters` against the configured
   model at startup and validate every parsed result**, because neither OpenRouter
   nor the provider will raise.

3. **Anthropic's per-document citations do not come through.** The direct API can
   return citation blocks tying each claim to a page and span. Sending
   `"citations": {"enabled": true}` inside the OpenRouter `file` block returned
   HTTP 200 with `annotations: null` and a message object whose only keys were
   `content`, `reasoning`, `refusal`, `role` — the model wrote *"Quelle: Ausdruck
   der elektronischen Lohnsteuer…"* as prose instead. No structured provenance.

### Re-measurement, 2026-09-01: it holds on 21 of 23 — and the schema itself has limits

Finding 2 above was measured on a legacy model. It is worse than that.

**`anthropic/claude-opus-4.7` ignores the strict schema, and its metadata says it
does not.** Its `supported_parameters` lists `structured_outputs` and
`response_format`. Sending a strict `response_format` returns HTTP 200 and valid JSON
under keys the model invented:

```json
{
  "dokumenttyp": "Lohnsteuerbescheinigung",
  "jahr": 2025,
  "arbeitgeber": {"name": "Möbelwerkstatt Krämer GmbH & Co. KG", "steuernummer": "143/815/49302"},
  "arbeitnehmer": {"name": "Anna Beispiel", "geburtsdatum": "1989-03-14", "etin": "AB1234567890"},
  "bescheinigungszeitraum": {"von": "2025-01-01", "bis": "2025-12-31"}
}
```

The *values* are right — it read the document correctly. The shape is nested German
of its own devising, in 3 of 3 runs on all three documents, and the requested keys
(`employer_name`, `gross_salary_eur`, …) are absent. `anthropic/claude-3-haiku`
behaves the same way with capitalised German keys. **Every other reachable model
honoured the schema exactly**, with no repair step, across 207 calls.

The consequence is concrete: **the "preferred long-term choice" comment at
`core/config.py:77` cannot be carried out for document intake.** Not because the
Anthropic line is unreachable — `claude-opus-4.7` is reachable — but because the one
permitted flagship will not fill in a typed schema through OpenRouter.

**Two provider limits constrain the schema itself, and neither is documented by
OpenRouter.** Both come from Amazon Bedrock, which is the provider OpenRouter routed
`anthropic/claude-haiku-4.5` to, and both reject the whole request with HTTP 400
carrying the provider's own message inside `error.metadata.raw`:

1. **A nullable enum is refused.** `{"type": ["string", "null"], "enum": [..., null]}`
   returns *"Invalid schema: Enum value 'lohnsteuerbescheinigung' does not match
   declared type '['string', 'null']'"*. Use a plain `{"type": "string"}` enum with an
   explicit "unknown" member instead of `null`.
2. **At most 16 union-typed parameters per schema.** *"Schemas contains too many
   parameters with union types (24 parameters with type arrays or anyOf). This causes
   exponential compilation cost. Reduce the number of nullable or union-typed
   parameters (limit: 16 parameters with unions)."* Every nullable field counts,
   nested ones included.

The second one shapes the extraction design: **a single union schema covering every
document type will not be servable.** This sweep started with one — 26 fields across
payslip and invoice, 24 of them nullable — and had to split it into one schema per
document type (15 unions and 12) before `claude-haiku-4.5` would answer at all. That
is the right shape for the product anyway, since it knows or classifies the document
type before it asks, but it is a constraint rather than a preference. The first
attempt scored `claude-haiku-4.5` as unusable when what was unusable was the schema.

Because the strict schema does hold on the reachable models, extracted values can go
straight into `field_values` (`value jsonb`, `provenance = 'document'`) with no
free-text parsing step, which is what the ticket asked for — **provided the configured
model is one of the 21 that honour it**, which the startup check must verify by
calling it, not by reading `supported_parameters`.

## 4. Confidence

**No candidate returns a per-field confidence signal.** What they return when asked
for one is worse than nothing.

The schema included a `confidence: "high" | "medium" | "low"` enum on every field.
All models filled it in, and it did not track correctness. On the degraded scan:

- `openai/gpt-5.4-mini` returned employer names `"Möbelwerkstatt Krause GmbH & Co.
  KG"`, `"Möbelwerkstatt Krauter GmbH & Co. KG"` and `"Möbelspedition Krüger GmbH &
  Co. KG"` across three runs (truth: *Möbelwerkstatt Krämer GmbH & Co. KG*), moved
  `615,78` from the church-tax row into `solidarity_surcharge_eur`, and in a second
  set of three runs also reported `tax_year: 2023` and `employment_period_end:
  2023-12-22` — with `confidence: "high"` on the tax year and the surcharge, and
  `"medium"` on the one field it actually hedged, the employer name.
- `anthropic/claude-haiku-4.5` returned `"Mittelbeschaffung Krämer GmbH & Co. KG"`,
  `"Mäbbelspedition Krämer GmbH & Co. KG"` and `"Müller/Scharf Krämer GmbH & Co.
  KG"`, all at `confidence: "high"`.
- On the *clean* scan, `claude-haiku-4.5` returned the wrong date at
  `confidence: "high"` in 5 of 5 runs.

### The proxies, ranked by cost to implement

1. **Two passes disagreeing — cheapest and by far the most effective.** Same model,
   same prompt, twice; compare field by field. Measured recall over 30 runs:

   | Model, degraded scan (n=3) | fields wrong | flagged by disagreement | flagged by `null` | missed |
   |---|---|---|---|---|
   | `google/gemini-3.7-flash` | 1 | 1 | 0 | **0** |
   | `google/gemini-2.5-flash` | 2 | 1 | 0 | 1 |
   | `openai/gpt-5.4-mini` | 5 | 4 | 0 | 1 |
   | `google/gemini-2.5-flash-lite` | 4 | 3 | 2 | **0** |
   | `anthropic/claude-haiku-4.5` | 6 | 4 | 4 | **0** |
   | **total** | **18** | **13** | **6** | **2** |

   Cost: exactly one extra call, ~0.25 c. Implementation: one dict comparison. It
   catches the noisy errors — which is most of them — and it is the reason
   `gpt-5.4-mini`'s bad behaviour is survivable while `claude-haiku-4.5`'s date bug
   is not: **a deterministic error agrees with itself.** A third pass would not help
   there either.

   **Re-measured across all 21 gradeable models, 2026-09-01 — the recall holds at a
   much larger n, and so does the ceiling.** 96 wrong fields in total:

   | | count | share |
   |---|---|---|
   | flagged by two passes disagreeing | 49 | 51 % |
   | flagged by a `null` | 30 | 31 % |
   | **silent — agreed across 3 runs, not `null`** | **17** | **18 %** |

   So the two cheap proxies together catch **82 %** of wrong fields at n=288
   graded-field comparisons, against 89 % at the first pass's n=18. **Roughly one
   wrong field in five is invisible to both**, which is the number that justifies
   proxy 3 below rather than treating two passes as sufficient. On the recommended
   model the count is different only because there were no wrong fields at all.

2. **A `null` value.** Works, and is honest. Every model returned
   `commuting_days: null` for the field genuinely absent from the payslip, in every
   single run — no model invented a value for it. `gemini-2.5-flash-lite` also
   nulled `church_tax_eur` on the degraded scan rather than guessing. Free: it is
   just a nullable schema type. Pairs naturally with `field_values` simply having no
   row for that key.

3. **Typed validation failing.** Free, and it catches a real class of error: the
   schema's `{"type": ["number","null"]}` already rejects `"41.238,76"` as a string,
   and a range or checksum rule (net + VAT = gross; a date inside the tax year; a
   `Lohnsteuerbescheinigung` line 4 not exceeding line 3) would have caught
   `gpt-5.4-mini` putting 615.78 into the surcharge field. Worth adding regardless
   of the model, because it is the only proxy that catches an error two passes agree
   on.

4. **Logprobs — a real per-token signal, but only from OpenAI models.** OpenRouter
   returns `choices[0].logprobs` for `openai/gpt-5.4-mini` and
   `openai/gpt-4.1-mini`, **and it works alongside a strict `json_schema`**, which is
   the combination that matters. `anthropic/claude-haiku-4.5`,
   `google/gemini-3.7-flash` and `google/gemini-2.5-flash` all return `logprobs:
   null`. Note that `logprobs` is *not* listed in `supported_parameters` for any of
   these models, yet works on the OpenAI ones — the metadata understates it.

   It is genuinely diagnostic. On the degraded scan, the least-likely tokens in
   `gpt-5.4-mini`'s 156-token reply were `' Krä'` at p=0.145 (the umlaut in the
   employer name), `'415'` at p=0.582 (a hallucinated surcharge digit) and `'78'` at
   p=0.436 — the model's own uncertainty landed exactly on the characters it got
   wrong, while its self-reported `confidence` field said `"high"`. Cost to
   implement: mapping token spans back to schema fields, which is real work. Not
   worth it now, and unavailable on the recommended model, but it is the honest
   answer to "does anything return a usable confidence signal" — **yes, OpenAI
   models, via logprobs, not via anything the model says about itself.**

**Recommended: two passes plus nullable fields plus arithmetic validation.** That is
proxies 1–3, costs one extra call, and needs no model-specific code.

## 5. German-language and scan-quality caveats

What the vendors document:

- **Anthropic** states plainly: "Claude might hallucinate or make mistakes when
  interpreting low-quality, rotated, or very small images under 200 pixels", and
  warns that lossy compression "can make text difficult to read", especially with
  multiple compression passes. Max 8000x8000 px, max 10 MB base64 per image, JPEG /
  PNG / GIF / WebP only, animations unsupported
  (<https://platform.claude.com/docs/en/build-with-claude/vision>). Nothing specific
  about German or about handwriting.
- **OpenAI** lists the model's known weaknesses as "rotated text, small text, medical
  imaging, and tasks requiring precise spatial localization"
  (<https://developers.openai.com/api/docs/guides/images-vision>).
- **Google** gives the most directly usable guidance: "Rotate pages to the correct
  orientation before uploading" and "Avoid blurry pages"
  (<https://ai.google.dev/gemini-api/docs/document-processing>). PDF pages are scaled
  to at most 3072x3072 and small pages scaled *up* to 768x768. For dense document
  parsing the Gemini 3 migration notes point at `media_resolution_high`
  (<https://ai.google.dev/gemini-api/docs/gemini-3>).

**No vendor documents handwriting accuracy at all**, for any of the three. Nothing
in this research supports or refutes a claim about handwritten receipts, and none of
the test documents was handwritten — an untested gap, not a cleared one.

What the measurements add, which the docs do not say:

- **German `DD.MM.YYYY` dates are the concrete language risk, not umlauts.**
  `claude-haiku-4.5` inverted `01.02.2025` 5/5 times; `gpt-5.4-mini` produced
  `2025-01-01`, `2023-01-02` and `2025-01-02` for the same field on the degraded
  scan. Every other reachable model got it right on the clean scan. Whatever model is
  chosen, **the prompt must state the input date format explicitly** and a
  same-month/adjacent-day result should be treated as suspicious.
- **Umlauts degrade before digits do.** At 623x862 px, `gemini-2.5-flash` and
  `-flash-lite` returned `"Mobelwerkstatt Kramer"` (umlauts stripped) while reading
  `41.238,76` correctly. Employer name is therefore a *worse* candidate for silent
  auto-acceptance than an amount, which is the opposite of the intuitive ordering.
- **Skew moves values between rows.** The degraded scan was rotated 1.8°, which
  visually offset the amount column against its row labels. That single artefact
  produced most of the errors seen: `gemini-2.5-flash` reported
  `church_tax_eur: 0.00` instead of `615,78`; `gpt-5.4-mini` reported
  `solidarity_surcharge_eur: 615.78`. For a line-numbered German form this is the
  dangerous failure, because every value is individually plausible. An arithmetic
  cross-check is the only thing that catches it.
- **A phone photo is not the hard case; a bad scan is.** Every model read the
  3024x3948 rotated JPEG-70 invoice perfectly, including all three line items. The
  623x862 quality-35 payslip broke four of five models.

**Re-measured across all 21 gradeable models, 2026-09-01 — every claim above
reproduced except the date one:**

- **Skew moving values between rows is confirmed as the dominant failure, and as the
  one that stays silent.** `gemini-2.5-flash` put the church-tax figure `615,78` into
  `solidarity_surcharge_eur` and the row below it (`348,00`) into `church_tax_eur`,
  identically in all three runs. `gpt-4.1-mini` made the same surcharge substitution.
  Every value is individually plausible, so nothing but an arithmetic cross-check
  catches it.
- **Umlauts still degrade before digits.** `gemini-2.5-flash` returned
  *"Möbeleerkstatt Kramer"* while reading `41.238,76` correctly.
- **A bad scan is still where models fail, and by a wide margin.** Across the 21
  gradeable models: 5 wrong fields in total on the clean A4 scan, 12 on the phone
  photo, **79 on the degraded one**.
- **The date claim is the exception, and it is untested rather than refuted** — the
  regenerated payslip has no ambiguous date in it. See
  [open question 7](#open-questions).

## 6. How the document reaches the model

**Images — base64 `image_url` block.** One `content` array, text first, then the
image; `image_url.url` takes either a public HTTPS URL or a
`data:image/jpeg;base64,…` data URL
(<https://openrouter.ai/docs/guides/overview/multimodal/image-understanding>).
Accepted formats: PNG, JPEG, WebP, GIF. This is the shape used for every measurement
above and it worked on every reachable model, all 23 of them:

```json
{
  "model": "google/gemini-3.7-flash",
  "reasoning": {"effort": "low"},
  "messages": [{"role": "user", "content": [
    {"type": "text", "text": "Du liest ein deutsches Steuerdokument …"},
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQ…"}}
  ]}],
  "response_format": {"type": "json_schema", "json_schema": {"name": "payslip", "strict": true, "schema": {"…": {}}}},
  "usage": {"include": true}
}
```

Base64, not a URL, is the only option compatible with ADR 0004 — a URL would mean
hosting the document somewhere first, which is the thing the ADR forbids.
`"usage": {"include": true}` is what returns the real `cost` field, and is how every
price in this document was obtained.

**PDFs — a `file` block, no client-side conversion needed.** A two-page,
image-only PDF (no text layer) was read correctly end to end by
`anthropic/claude-haiku-4.5`, `google/gemini-3.7-flash` and `openai/gpt-5.4-mini`,
each naming both page types, both issuers and both key amounts:

```json
{"type": "file", "file": {"filename": "scan.pdf", "file_data": "data:application/pdf;base64,…"}}
```

OpenRouter routes it through a `file-parser` plugin whose engine is selectable
(<https://openrouter.ai/docs/features/multimodal/pdfs>). Measured on the same
two-page scanned PDF:

| Engine | haiku-4.5 | gemini-3.7-flash | gpt-5.4-mini | Result |
|---|---|---|---|---|
| `native` | $0.00401, pt 3210 | $0.00297, pt 1108 | $0.00194, pt 1929 | correct, both pages |
| `mistral-ocr` | $0.00589, pt 996 | $0.00688, pt 880 | $0.00508, pt 750 | correct, both pages |
| `pdf-text` | $0.00051, pt 190 | $0.00122, pt 168 | $0.00043, pt 145 | **silently empty** |

- **`native`** hands the file straight to the model. It is the cheapest correct
  option and adds no per-page fee, and it is available because all three vendors
  declare `file` in `input_modalities`. **This is the one to use.**
- **`mistral-ocr`** adds $2 per 1000 pages on top of tokens — visible as the ~$0.002
  gap on a 2-page document — and returns reusable `annotations` so a re-parse can be
  skipped. ADR 0004 removes that benefit: there is no second request to reuse them
  in.
- **`pdf-text`** is the trap. On an image-only PDF it costs almost nothing, returns
  HTTP 200, and the model reports *"beide Seiten im bereitgestellten Dokument sind
  leer"* — a confident, cheap, wrong answer. A scanned document has no text layer, so
  this engine must never be selected for user uploads.
- **The observed default, with no `plugins` field, was `native`**, not the documented
  `mistral-ocr`: `gpt-5.4-mini` billed $0.00159 with `annotations: null`, matching its
  `native` run ($0.00194) and not its `mistral-ocr` run ($0.00508). The docs say the
  default engine is `mistral-ocr`; measurement says a model with native file support
  bypasses the parser. **Set the engine explicitly rather than rely on either.**

Anthropic's own limits, for reference, if the project ever calls the API directly:
32 MB per request, 600 pages (100 when the context window is under 1M tokens), no
encrypted PDFs, and "each page typically uses 1,500–3,000 tokens per page depending
on content density" *plus* image tokens for the page render
(<https://platform.claude.com/docs/en/build-with-claude/pdf-support>). Google's are
50 MB / 1000 pages at 258 tokens per page
(<https://ai.google.dev/gemini-api/docs/document-processing>).

---

## Open questions

1. **Handwriting is entirely untested and undocumented.** No vendor publishes
   accuracy guidance for handwritten content, and none of the three test documents
   was handwritten. If a handwritten receipt is in scope, it needs its own test.
2. **Anthropic's resolution tiers do not match what was billed.** The documented
   standard tier caps images at 1568 visual tokens, but `claude-haiku-4.5` billed
   2835 visual tokens for a 1240x1754 image — the exact un-downscaled patch count —
   which is high-resolution-tier behaviour on a model the tier table lists as
   standard ("Claude 4.7 and later" for high-resolution). Either the table or
   OpenRouter's routing is doing something not described. It does not change the
   recommendation (haiku is not recommended), but it means Anthropic image costs
   cannot be predicted from the tier table alone.
3. **OpenAI's patch multipliers could not be reproduced.** The measured
   `prompt_tokens` for `gpt-5.4-mini` imply a multiplier near 1.3x on one document
   and near 1.6x on another; the docs give per-model multipliers but not one for
   `gpt-5.4-mini` specifically. The measured costs stand; the formula behind them
   does not.
4. **Gemini's `media_resolution` token counts are not published.** Google's Gemini 3
   notes recommend `media_resolution_high` for dense document parsing but give no
   token count per level, so the cost of that lever is unknown. It may improve the
   degraded-scan result; untested.
5. ~~**Reachability is a moving account setting.**~~ **Resolved, and the premise was
   wrong.** The blocked models are a course-account allowlist, not the privacy toggle
   ([issue #15](https://github.com/TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1/issues/15)); `claude-sonnet-5` will never be reachable with this key, and
   there is nothing to re-run when a setting changes. The sweep that this question
   asked for has now been run across all 24 reachable models
   ([issue #65](https://github.com/TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1/issues/65)). The allowlist can still change from outside, so the startup
   check should call the configured model rather than assume it.
6. ~~**`gemini-3.7-flash`'s one persistent error was a single digit.**~~ **Did not
   reproduce.** On the re-measured documents `gemini-3.7-flash` read all three
   correctly in 3 of 3 runs each, at both default and low effort. The cent-digit
   check may still be worth having, but there is no measured error behind it now.
7. **The first pass's `claude-haiku-4.5` date inversion did not reproduce, and the
   reason is a document difference, not a model change.** That finding rested on a
   `Bescheinigungszeitraum` beginning `01.02.2025`, a date whose day and month are
   both ≤ 12 and therefore ambiguous. The regenerated payslip runs the full calendar
   year (`01.01.2025 – 31.12.2025`), which cannot express the inversion. **The
   underlying risk is untested, not cleared** — a German `DD.MM.YYYY` date with a day
   ≤ 12 remains the concrete language hazard, and the next revision of the test
   documents should carry one deliberately.
8. **`openai/gpt-5.5` answers intermittently.** Its endpoint returns HTTP 200 whose
   body is an upstream `{"code": 502, "message": "no healthy upstream"}` with no
   `choices` — roughly one call in three. It is measured here (2 wrong on the degraded
   scan, both caught, 3.312 c per pass, far too dear to matter), but its availability
   would need checking before anyone relied on it. Note the shape of the fault: a
   client that only checks the HTTP status records this as an empty answer, which is
   how the first run of this sweep scored the model unusable.
9. **The degraded document is easier than the first pass's.** Five models read it
   perfectly here; the first pass reported errors from every model it tried. Same
   nominal recipe — 623x862, quality 35, blur, noise, 1.8° rotation — but the
   underlying render differs, so difficulty is not calibrated between the two sweeps.
   The ranking is comparable; "how hard is a bad scan" is not.
10. **The two-pass proxy was measured at n=3 per model on one degraded document.**
   Disagreement or a `null` flagged 16 of 18 wrong fields, which is encouraging, not
   conclusive. Both misses were the same field, `church_tax_eur`, returned as `0.00`
   instead of `615,78` identically in every pass — the skew-induced row shift, which
   is exactly the deterministic-error class that defeats the method and the reason
   proxy 3 (arithmetic validation) is not optional.
