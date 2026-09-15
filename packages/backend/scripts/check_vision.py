"""Ask the configured vision model for one document and check what comes back.

**Why this cannot be answered from the model catalogue.** `anthropic/claude-opus-4.7`
advertises `structured_outputs: true`, answers HTTP 200, and returns valid JSON under
keys of its own invention - `dokumenttyp`, `arbeitgeber`, `bescheinigungszeitraum` -
in 3 of 3 runs on every test document (issue #65). So a deploy cannot learn whether
`VISION_MODEL` honours a strict schema by reading `supported_parameters`; it has to
send a document and look at the reply. `services/documents/extract.py` says this
script is where that failure is meant to surface, because the alternative is
discovering it on a real upload, where `read_twice` deliberately does *not* fall back:
an unhonoured schema is a misconfiguration, not a bad day at the provider, and
retrying it on the fallback would hide it behind a doubled bill on every document.

**Why the values are checked too, and not only the shape.** There are two measured
failure modes, not one. The other is silent: `claude-haiku-4.5` inverted a German
`DD.MM.YYYY` date (#11), and `gemini-2.5-flash` moves amounts between rows of a
skewed form (#65). A model that returns the right keys with the wrong contents passes
a shape check and puts the wrong figure on a tax return. So the reply is compared
against the recorded truth of the document it read.

**Why this document.** `payslip-part-year.jpg` runs `01.02.2025 - 30.09.2025`. The
start date is the only probe in the set whose day and month differ while both are
<= 12, so an inverted date reads as `2025-01-02` instead of `2025-02-01` and is
caught here. The full-year payslip cannot catch it: `01.01` inverts to itself.

Not a startup check. One vision pass costs money and takes seconds, and Render
restarts a process more often than anybody changes `VISION_MODEL`; a deploy gate is
the right place, so this runs by hand or from CI:

    python -m scripts.check_vision              # VISION_MODEL
    python -m scripts.check_vision --fallback   # VISION_FALLBACK_MODEL

Exit status is 0 when the model honoured the schema and read the document correctly,
1 otherwise, so it can gate a deploy without anybody reading the output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from core.config import get_settings  # noqa: E402
from core.llm import OpenRouterClient  # noqa: E402
from services.documents import extract  # noqa: E402
from services.documents.intake import check  # noqa: E402
from services.documents.schemas import MODEL_FOR  # noqa: E402
from services.documents.sensitivity import DocumentKind  # noqa: E402

DOCUMENTS = BACKEND / "eval" / "vision_sweep" / "documents"
PROBE = "payslip-part-year.jpg"
KIND = DocumentKind.lohnsteuerbescheinigung


def expected() -> dict:
    """The recorded truth of the probe, narrowed to what the product extracts.

    `ground-truth.json` grades everything the document carries, because the sweep it
    belongs to was measuring models. The production schema is deliberately much
    smaller (`schemas.py`), so comparing the whole of it would fail on fields this
    product does not ask for and must not store.
    """
    truth = json.loads((DOCUMENTS / "ground-truth.json").read_text())[PROBE]
    asked_for = MODEL_FOR[KIND].model_fields
    return {key: value for key, value in truth.items() if key in asked_for}


def client_for(model: str) -> OpenRouterClient:
    settings = get_settings()
    # Built here rather than through `core.dependencies`, which caches one client per
    # process and would hand back the primary when this script asks for the fallback.
    return OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=model,
        temperature=0.0,
        timeout=90.0,
    )


async def run(model: str) -> int:
    data = (DOCUMENTS / PROBE).read_bytes()
    upload = check(data, file_name=PROBE)
    print(f"model:    {model}")
    print(f"document: {PROBE} ({upload.file_format.value}, {upload.size_bytes} bytes)")

    try:
        read = await extract.one_pass(client_for(model), data, upload, KIND)
    except extract.ExtractionFailed as failure:
        print(f"\nFAIL ({failure.code}): {failure.detail}")
        if failure.code == "unexpected_shape":
            print("The model answered in keys this document type does not have. It is "
                  "not honouring the strict schema - see issue #65 - and document "
                  "intake cannot run on it.")
        return 1

    wanted = expected()
    wrong = {key: (value, read.values.get(key))
             for key, value in wanted.items() if read.values.get(key) != value}

    print(f"cost:     {_cost(model, read)}")
    print(f"\nschema:   honoured, {len(read.values)} fields validated")
    if not wrong:
        print(f"values:   all {len(wanted)} match the recorded truth")
        print("\nOK")
        return 0

    print(f"values:   {len(wrong)} of {len(wanted)} wrong")
    for key, (want, got) in sorted(wrong.items()):
        print(f"  {key}: expected {want!r}, read {got!r}")
    print("\nFAIL: the model honoured the schema and misread the document. Two passes "
          "cannot catch this - both make the same mistake - so it has to be caught "
          "here.")
    return 1


def _cost(model: str, read: extract.Read) -> str:
    from core.pricing import cost_usd

    usd = cost_usd(model, read.usage.get("prompt_tokens", 0),
                   read.usage.get("completion_tokens", 0))
    return "not listed" if usd is None else f"{usd * 100:.3f} cents for one pass"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fallback", action="store_true",
        help="check VISION_FALLBACK_MODEL instead of VISION_MODEL",
    )
    args = parser.parse_args()
    settings = get_settings()
    model = (settings.vision_fallback_model or settings.vision_model) if args.fallback \
        else settings.vision_model
    return asyncio.run(run(model))


if __name__ == "__main__":
    raise SystemExit(main())
