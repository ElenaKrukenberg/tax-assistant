# Vision sweep: which model reads a German tax document most accurately per cent

The harness behind `docs/research/vision-model-for-document-intake.md`.

It exists because the first sweep ([issue #11]) left nothing reproducible: only the
write-up was committed, and the documents and probe code lived on a branch that no
longer exists. Everything needed to re-derive the table is therefore here, the
generated JPEGs included.

## The three parts

| File | What it does |
|---|---|
| `probe.py` | Which of OpenRouter's vision models this key can call at all. A blocked model 404s before billing, so probing the blocked ones is free. |
| `make_documents.py` | Regenerates the three test documents and `documents/ground-truth.json`. |
| `sweep.py` | Reads each document with each reachable model, 3 runs each, and grades the answers against ground truth. |

`documents/*.jpg` are **committed and are the artefact of record.** Regeneration
needs a system TTF that differs between machines, so a re-render is not guaranteed
to be pixel-identical — grading against a regenerated document would not be
comparable with the published table.

## Running it

```sh
cd packages/backend
./venv/bin/python eval/vision_sweep/probe.py --out reachable-zdr.json   # ~free
./venv/bin/python eval/vision_sweep/sweep.py --estimate                 # price it first
./venv/bin/python eval/vision_sweep/sweep.py --max-spend 4              # ~$1.40
```

`--max-spend` prices the run high — the most expensive of the three vendors'
image-token formulas — and aborts above the guard rather than discovering the bill
afterwards. The table always reports `usage.cost` as OpenRouter billed it.

Results land in `eval/results/vision-sweep.json`, which keeps every raw answer, so a
regrade needs no further calls.

## What is held fixed, and why

Changing any of these makes the numbers incomparable with the published table:

- **3 runs per document.** Two-pass disagreement is the only working confidence
  proxy, and a third run distinguishes "disagrees" from "consistently wrong".
- **One German instruction**, in `sweep.PROMPT`. It names no values and gives no
  examples, so it cannot leak ground truth into an answer.
- **`temperature: 0`**, so a disagreement between runs is the model's own instability
  rather than sampling noise.
- **`provider={"zdr": True}`** on every call — the policy decided in [issue #15].
  It costs one model of the 24: `openai/gpt-4o-2024-11-20`.
- **`usage.cost` as billed**, never a per-million rate multiplied out. Issue #11
  could not reproduce OpenAI's image-token multiplier from its own bills.

## Grading

    wrong    a graded field whose value differs from ground truth
    caught   a wrong field that either disagreed across the 3 runs or came back null
    silent   wrong, identical in all 3 runs, and not null

**Silent is the number that decides the recommendation.** A caught error costs a
second pass; a silent one puts a wrong figure in a tax return with nothing to flag
it. `confidence` is not graded — issue #11 established it does not track correctness,
and this sweep reproduced that.

[issue #11]: https://github.com/TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1/issues/11
[issue #15]: https://github.com/TuringCollegeSubmissions/ekruke-AE.CAP.AFA.1.1/issues/15
