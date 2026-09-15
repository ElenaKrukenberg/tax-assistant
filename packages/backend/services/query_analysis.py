import json
import re
from dataclasses import dataclass, field
from typing import Literal, Optional, get_args

from pydantic import BaseModel, Field, ValidationError

from core.llm import OpenRouterClient

# The vocabularies are the Literal types below rather than plain lists: the same
# definition then reaches the model as a JSON-schema enum and reaches our own code as a
# validated type. The lists are derived, not maintained in parallel.
Intent = Literal[
    "knowledge", "field_explanation", "calculation", "validation",
    "classification", "checklist", "clarification_required", "out_of_scope",
]

Topic = Literal[
    "anlage_n_grundlagen", "form_fields", "entfernungspauschale", "homeoffice_pauschale",
    "arbeitszimmer", "arbeitsmittel", "fortbildung", "reisekosten",
    "doppelte_haushaltsfuehrung", "umzugskosten", "bewerbungskosten", "arbeitskleidung",
    "telefon_internet", "berufsverbaende", "pauschbetrag", "lohnsteuerbescheinigung",
    "lohnersatzleistungen", "expense_classification", "belege", "validation",
    "sachbezuege", "entschaedigungen", "vermoegensbeteiligungen", "auslandslohn",
    "grenzgaenger", "mobilitaetspraemie",
]

FormId = Literal["anlage_n", "anlage_n_dhf", "anlage_n_aus", "anlage_n_gre",
                 "mobilitaetspraemie", "est_1a"]

UserLanguage = Literal["en", "de", "tr", "ru"]

INTENTS = list(get_args(Intent))
TOPICS = list(get_args(Topic))
FORM_IDS = list(get_args(FormId))

MAX_TOPICS = 2


class QueryPlan(BaseModel):
    """What the analysis stage asks the model for.

    Sent as a JSON schema, so the enums are enforced where the tokens are produced
    instead of being filtered out afterwards. Only the two fields the pipeline cannot
    proceed without are required; every other field has a safe default, because a
    missing topic costs precision while a failed parse costs the whole analysis.

    Every description below is billed on every request — the schema travels with the
    prompt — so they are written as instructions to the model, not as documentation for
    us. Reasoning that only a reader needs goes in comments, which cost nothing.
    """

    intent: Intent = Field(description="What the user wants.")
    search_query_de: str = Field(
        description="German search query for the knowledge base; translate the question "
                    "into German tax terminology and resolve what it only implies.",
    )
    topics: list[Topic] = Field(
        default_factory=list,
        description=f"Up to {MAX_TOPICS} relevant topics; empty if unsure.",
    )
    # Two things are deliberate here. No `ge=1`: pydantic renders it as `"minimum": 1`
    # and Anthropic's structured output rejects the whole request with "For 'integer'
    # type, property 'minimum' is not supported" — measured against Anthropic, Bedrock
    # and Azure through OpenRouter, all three refuse it, so the bound lives in
    # _from_plan. And "never inferred" stays in the description even though it is the
    # longest one here: dropping it is what let the analyzer invent line 31 for ten of
    # the twenty-six evaluation questions, and the rule appears nowhere else.
    line: Optional[int] = Field(
        default=None,
        description="Only if the question names a line explicitly; never inferred.",
    )
    form_id: Optional[FormId] = Field(
        default=None, description="Only if clearly about a sub-form.",
    )
    user_language: UserLanguage = Field(
        default="en", description="Language the question is written in.",
    )


def _wire_schema() -> dict:
    """The JSON schema actually sent, derived from QueryPlan rather than written twice.

    Pydantic emits three things the provider does not need and the request pays for on
    every question: a `title` per field, a `default` per optional field, and
    `anyOf: [{...}, {"type": "null"}]` where a nullable type would do. Measured on one
    question, stripping them took the analysis call from 1352 to 1224 prompt tokens;
    with the shortened descriptions above, five mixed questions now average ~1180
    against ~1460 before. The top-level `title` stays — LangChain uses it as the
    function name and rejects a schema without one.

    What is deliberately *not* traded away: the topic enum. Dropped to a free-form
    string list it costs 32 tokens instead of 204, and the model then invents topics no
    document carries — measured, in one run: "Fahrtkosten", "Werbungskosten",
    "Anlage N", none of them in the vocabulary. Abbreviating the values to codes
    (`t01`…`t26`) saves less and takes the meaning the model selects on with it.

    Only mechanical removal happens here. Nothing is renamed and no constraint is
    dropped, so the schema still validates into QueryPlan on the way back.
    """
    schema = QueryPlan.model_json_schema()
    schema.pop("description", None)          # the class docstring is for us, not the model
    schema["title"] = "QueryPlan"

    for field in schema["properties"].values():
        field.pop("title", None)
        field.pop("default", None)
        if "anyOf" not in field:
            continue
        variants = field.pop("anyOf")
        actual = next(v for v in variants if v.get("type") != "null")
        if "enum" in actual:
            field["enum"] = [*actual["enum"], None]
        else:
            field["type"] = [actual["type"], "null"]

    return schema


WIRE_SCHEMA = _wire_schema()


ANALYSIS_PROMPT = """You are the query-analysis stage of a German tax assistant \
covering the Anlage N form (employment income), tax year 2025.

Analyze the user's question and fill in the required structure.

Rules:
- The question may continue an earlier exchange, which is given above it. Read
  "search_query_de" as a standalone query: resolve anything the question only
  implies. A bare "74 km" following a commute question is
  "Entfernungspauschale 74 km einfache Entfernung", not "74 km". Same for intent
  and topics — judge the question in the context of the conversation, so a bare
  "car, 150 days" after a commute question is a calculation, not out of scope.
- Users ask in any language (EN/DE/TR/RU/UA). Questions about work-related
  deductions — home office, commuting, work equipment, training, business trips,
  job-related moves etc. — are IN SCOPE regardless of language: assume they are
  about German employment income tax unless another country is explicitly named.
- "out_of_scope": ONLY when clearly unrelated to German employment income tax /
  Anlage N (other tax forms, another country's taxes named explicitly, or
  completely unrelated subjects like cooking or sports).
- "clarification_required": on-topic, but a key fact needed to answer is missing.
- "calculation" / "validation" / "checklist": the user wants numbers computed,
  their data checked, or a document checklist.
- "field_explanation": asks what a specific form line/field means.
- Otherwise "knowledge".
"""


@dataclass
class QueryAnalysis:
    intent: str = "knowledge"
    search_query: str = ""
    topics: list = field(default_factory=list)
    line: int | None = None
    form_id: str | None = None
    user_language: str = "en"
    usage: dict = field(default_factory=dict)


def _extract_json(text: str) -> dict:
    """Parse the model reply as JSON, tolerating code fences and prose around it."""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON object in reply: {text[:200]}")
    return json.loads(m.group(0))


# The analysis stage only needs enough of an earlier answer to see what was asked
# for, not the answer itself — the retrieved context is fetched fresh every turn.
ANALYSIS_TURN_CHARS = 400


def _with_history(question: str, history: list[dict]) -> str:
    """Render the question with its conversation, or alone if there is none."""
    if not history:
        return question
    lines = [f"{t['role']}: {t['text'][:ANALYSIS_TURN_CHARS]}" for t in history]
    return ("Conversation so far (oldest first):\n" + "\n".join(lines)
            + f"\n\nLatest question: {question}")


def _from_plan(plan: QueryPlan, question: str, usage: dict) -> QueryAnalysis:
    return QueryAnalysis(
        intent=plan.intent,
        search_query=plan.search_query_de or question,
        # Trimmed here rather than bounded in the schema: a model that returns three
        # topics has still analysed the question correctly, and rejecting the whole
        # reply over the third one would cost the intent and the search query too.
        topics=plan.topics[:MAX_TOPICS],
        # A line number only ever promotes chunks, so an implausible one costs nothing
        # but noise in the trace — drop it here, since the schema cannot say `minimum`.
        line=plan.line if plan.line and plan.line > 0 else None,
        form_id=plan.form_id,
        user_language=plan.user_language,
        usage=usage,
    )


def _salvage(raw_text: str, question: str, usage: dict) -> QueryAnalysis | None:
    """Read a reply that missed the schema, keeping whatever fields are usable.

    The strict path is the normal one; this exists because losing the intent and the
    German search query over one out-of-vocabulary topic would be a worse failure than
    the imprecision it prevents. Same lenient reading the stage used before the schema.
    """
    try:
        data = _extract_json(raw_text)
    except (ValueError, json.JSONDecodeError):
        return None

    line = data.get("line")
    return QueryAnalysis(
        intent=data.get("intent") if data.get("intent") in INTENTS else "knowledge", # type: ignore
        search_query=data.get("search_query_de") or question,
        topics=[t for t in (data.get("topics") or []) if t in TOPICS][:MAX_TOPICS],
        line=int(line) if isinstance(line, (int, str)) and str(line).isdigit() else None,
        form_id=data.get("form_id") if data.get("form_id") in FORM_IDS else None,
        user_language=(data.get("user_language")
                       if data.get("user_language") in get_args(UserLanguage) else "en"), # type: ignore
        usage=usage,
    )


async def analyze_query(llm: OpenRouterClient, question: str, history: list | None = None) -> QueryAnalysis:
    """Classify intent, translate the query to German and extract retrieval filters.

    `history` is what makes a follow-up analyzable: without it, "74 km" produces a
    search query of "74 km" and retrieval returns noise.

    Degrades in two steps rather than failing — analysis must never break the
    pipeline: a reply that misses the schema is read leniently, and a reply with no
    JSON in it at all becomes a plain knowledge query over the original question.
    """
    messages = [
        {"role": "system", "content": ANALYSIS_PROMPT},
        {"role": "user", "content": _with_history(question, history or [])},
    ]
    # A dict schema comes back as a dict, so the validation happens here rather than
    # inside LangChain. Same guarantee, and the wire format stays ours to trim.
    raw_plan, usage, raw_text = await llm.chat_structured(messages, WIRE_SCHEMA)

    if isinstance(raw_plan, dict):
        try:
            return _from_plan(QueryPlan.model_validate(raw_plan), question, usage)
        except ValidationError:
            pass

    return _salvage(raw_text, question, usage) or QueryAnalysis(search_query=question, usage=usage)
