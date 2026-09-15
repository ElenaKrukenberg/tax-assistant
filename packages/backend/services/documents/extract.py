"""The vision read: two independent passes, in memory, and nothing kept.

The model and the settings are not preferences - they are the outcome of two
measured sweeps (issues #11 and #65), and the numbers are worth having beside the
code that depends on them:

* **`google/gemini-3.7-flash` at `reasoning: {"effort": "low"}`** - 0.310 cents a
  pass, the cheapest of the 24 reachable vision models that reads a German tax
  document correctly.
* **The fallback is `x-ai/grok-4.5`, never a cheaper Gemini.** `gemini-2.5-flash`
  and `-flash-lite` silently move amounts between rows of a skewed form, which two
  passes cannot catch, because both passes make the same mistake.
* **A PDF goes as a `file` block with the parser named explicitly.** Measured on a
  two-page image-only scan: `native` is correct and cheapest, `mistral-ocr` is
  correct and dearer, and `pdf-text` costs almost nothing and returns an *empty*
  document - it reads the text layer a scan does not have. The observed default was
  `native`, the documentation says `mistral-ocr`, and where those two disagree the
  only safe move is to say which one you want.

Two passes rather than one because a model that reports its own confidence does not
track its own correctness (#11), while two reads that disagree do (`compare.py`).
They are sent concurrently: the second pass is not a retry of the first and does not
wait for it.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Any, Optional

import structlog
from pydantic import ValidationError

from core.llm import LLMError, OpenRouterClient
from services.documents.intake import CheckedUpload, FileFormat
from services.documents.schemas import MODEL_FOR, SCHEMA_FOR
from services.documents.sensitivity import DocumentKind, may_be_sent_to_a_model

logger = structlog.get_logger(__name__)

PASSES = 2

REASONING_EFFORT = "low"

# Named rather than left to the provider's default, which measurement and
# documentation disagree about.
PDF_PLUGINS = [{"id": "file-parser", "pdf": {"engine": "native"}}]

# German, because the documents are German and the sweep measured this wording. Kept
# in step with `schemas.py` by hand and on purpose: the rules a reader has to follow
# are prose, and generating them from a schema would produce something a model reads
# worse rather than better.
PROMPT = """Du liest ein deutsches Steuerdokument und überträgst seinen Inhalt in das
vorgegebene JSON-Schema.

Regeln:
- Übertrage ausschließlich, was im Dokument steht. Rechne nichts um und schätze nichts.
- Beträge als Zahl in Euro, Punkt als Dezimaltrennzeichen: aus "41.238,76" wird 41238.76.
- Datumsangaben im Format JJJJ-MM-TT.
- Felder, die im Dokument nicht vorkommen oder nicht lesbar sind, setze auf null.
- Ordne jeden Betrag der Zeile zu, in der er steht. Verschiebe keinen Betrag in eine
  Nachbarzeile, auch wenn das Dokument schief oder unscharf ist.
- Wenn das Dokument nicht dem angeforderten Typ entspricht, setze "document_type" auf
  den Typ, den du siehst, oder auf "unbekannt". Erfinde keine Felder dazu.

Antworte nur mit dem JSON-Objekt."""


class ExtractionFailed(RuntimeError):
    """The document could not be read into the schema. The user is offered another try."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Read:
    """One pass: the values, what the call cost, and which model answered."""

    values: dict[str, Any]
    usage: dict
    # Which model produced this. Worth carrying rather than assuming from settings:
    # once there is a fallback, the configured model is not always the one that read
    # the document, and a trace that says the wrong one is worse than none.
    model: str = ""


def data_url(data: bytes, file_format: FileFormat) -> str:
    return f"data:{file_format.value};base64,{base64.b64encode(data).decode()}"


def content_blocks(data: bytes, upload: CheckedUpload, kind: DocumentKind) -> list[dict]:
    """The user message: one line of instruction and the document itself."""
    asked_for = f"Angefordertes Dokument: {kind.value}."
    if upload.file_format is FileFormat.pdf:
        document: dict = {
            "type": "file",
            "file": {
                "filename": upload.file_name,
                "file_data": data_url(data, upload.file_format),
            },
        }
    else:
        document = {
            "type": "image_url",
            "image_url": {"url": data_url(data, upload.file_format)},
        }
    return [{"type": "text", "text": asked_for}, document]


async def one_pass(
    client: OpenRouterClient, data: bytes, upload: CheckedUpload, kind: DocumentKind,
) -> Read:
    """A single read. Raises `ExtractionFailed` for anything the caller can retry."""
    import json

    raw, usage = await client.read_document(
        prompt=PROMPT,
        content=content_blocks(data, upload, kind),
        json_schema=SCHEMA_FOR[kind],
        reasoning_effort=REASONING_EFFORT,
        plugins=PDF_PLUGINS if upload.file_format is FileFormat.pdf else None,
    )

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ExtractionFailed(
            "unreadable_reply", "The model's answer was not the requested JSON."
        ) from exc

    if not isinstance(parsed, dict):
        raise ExtractionFailed("unreadable_reply", "The model's answer was not an object.")

    try:
        # Validated, not merely parsed. A reply under keys of the model's own
        # invention is a measured failure mode, not a hypothetical: `claude-opus-4.7`
        # advertises structured output and answered with `dokumenttyp` and `arbeitgeber`
        # in 3 of 3 runs (#65). `extra="forbid"` is what turns that into a failure here
        # instead of an empty document later.
        values = MODEL_FOR[kind].model_validate(parsed).model_dump()
    except ValidationError as exc:
        raise ExtractionFailed(
            "unexpected_shape",
            "The model answered in a shape this document type does not have.",
        ) from exc

    return Read(values=values, usage=usage, model=client.model)


async def read_twice(
    client: OpenRouterClient,
    data: bytes,
    upload: CheckedUpload,
    kind: DocumentKind,
    fallback: Optional[OpenRouterClient] = None,
) -> tuple[Read, Read]:
    """Two independent reads of the same bytes, concurrently.

    The bytes are held by the caller for exactly as long as this takes. Nothing here
    writes them anywhere, and the workflow drops them the moment this returns
    (ADR 0004).

    **Both passes move to the fallback together, or neither does.** One pass on each
    model would make the comparison meaningless: two models disagree about things one
    model is consistent about, so every document would come back as a disagreement
    and the gate would stop meaning "this page is hard to read".

    **Only a provider failure falls back.** An answer in a shape this document type
    does not have is not a bad day at the provider, it is the configured model not
    honouring the schema - measured on `claude-opus-4.7`, which returns HTTP 200 and
    valid JSON under keys of its own invention (#65). Reading it on another model
    would hide that behind a doubled bill on every upload; `scripts/check_vision.py`
    is where it is meant to surface.
    """
    if not may_be_sent_to_a_model(kind.value):
        # Not reachable through the API, which validates the type before it gets here.
        # Kept as the last line of the allowlist anyway: the check belongs next to the
        # call that would do the sending.
        raise ExtractionFailed(
            "type_not_allowed",
            f"Documents of type {kind.value!r} are not sent to a model.",
        )

    async def both(reader: OpenRouterClient) -> tuple[Read, Read]:
        return await asyncio.gather(  # type: ignore[return-value]
            one_pass(reader, data, upload, kind),
            one_pass(reader, data, upload, kind),
        )

    try:
        first, second = await both(client)
    except LLMError as exc:
        if fallback is None or fallback.model == client.model:
            raise ExtractionFailed(
                "provider_unavailable",
                "The document could not be read just now. Try again, or type the "
                "values in.",
            ) from exc
        logger.warning("vision_fallback", failed=client.model, trying=fallback.model,
                       error=str(exc))
        try:
            first, second = await both(fallback)
        except LLMError as second_exc:
            raise ExtractionFailed(
                "provider_unavailable",
                "The document could not be read just now. Try again, or type the "
                "values in.",
            ) from second_exc

    logger.info(
        "document_extracted",
        model=first.model,
        kind=kind.value,
        file_format=upload.file_format.value,
        pages=upload.pages,
        # Never the values: they are the document's contents, and this log is not the
        # place for a stranger's salary (ADR 0004, docs/TRACING_POLICY.md).
        cost_usd=cost_of_both(first.model or client.model, first, second),
    )
    return first, second


def cost_of_both(model: str, first: Read, second: Read) -> float | None:
    """What reading this document cost, or None for a model with no listed price."""
    from core.pricing import cost_usd

    prompt = first.usage.get("prompt_tokens", 0) + second.usage.get("prompt_tokens", 0)
    completion = (first.usage.get("completion_tokens", 0)
                  + second.usage.get("completion_tokens", 0))
    return cost_usd(model, prompt, completion)


def document_type_matches(kind: DocumentKind, values: dict[str, Any]) -> Optional[str]:
    """Whether the document is the type the user said it was.

    This is what replaces a separate classification call. The user picks the type, so
    the schema is chosen before the model is asked; the model still reports what it
    sees, and a mismatch is a question for the user rather than a silent extraction
    of the wrong form. One call saved per document, which at two passes is a third of
    the cost of reading one.
    """
    seen = values.get("document_type")
    if seen == kind.value:
        return None
    if seen == "unbekannt" or not seen:
        return (
            "The model could not tell what kind of document this is. Check that the "
            "whole page is in the photo, or type the values in yourself."
        )
    return (
        f"You said this was a {kind.value}, but it reads as a {seen}. Pick the right "
        "type and upload it again."
    )


def reading_record(first: Read, second: Read, configured: str) -> dict:
    """What a document read cost, in the shape the `documents` row stores (#39).

    The model is the one that *answered*, not the one that was configured: those are
    different facts the moment the primary is unreachable and the fallback replies,
    and the cheaper of the two is the one somebody will assume was used.

    Both passes together, because both were paid for. A price of None means the model
    has none on file - kept as None rather than folded to zero, which would be a claim
    rather than a gap.
    """
    model = first.model or configured
    return {
        "model": model,
        "prompt_tokens": (first.usage.get("prompt_tokens", 0)
                          + second.usage.get("prompt_tokens", 0)),
        "completion_tokens": (first.usage.get("completion_tokens", 0)
                              + second.usage.get("completion_tokens", 0)),
        "cost_usd": cost_of_both(model, first, second),
    }
