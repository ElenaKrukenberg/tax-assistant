from functools import lru_cache

from fastapi import HTTPException

from core.config import get_settings
from core.llm import OpenRouterClient


@lru_cache()
def get_llm_client() -> OpenRouterClient:
    """Provide the LLM client. Cached so we reuse one config across requests.

    Overridden in tests via app.dependency_overrides to avoid real network calls.
    """
    settings = get_settings()
    return OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.llm_model,
    )


@lru_cache()
def get_reviewer_client() -> OpenRouterClient:
    """The Reviewer's model: a different, stronger one from another vendor.

    Falling back to the Interviewer's model is the failure mode, not the plan - it
    removes the audit's independence without an error - so REVIEWER_MODEL carries a
    real default now and the `or` below only fires if someone empties it.
    """
    settings = get_settings()
    return OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.reviewer_model or settings.llm_model,
    )


@lru_cache()
def get_vision_client() -> OpenRouterClient:
    """The model that reads an uploaded document (VISION_MODEL).

    Its own client because it is its own model: the Interviewer's `llm_model` cannot
    read an image, and the one that can is chosen on measured accuracy per cent
    rather than on reasoning (core/config.py). Temperature 0 - a document has one
    content, and the variation this product wants between the two passes is the
    provider's own sampling, not a temperature nobody chose.
    """
    settings = get_settings()
    return OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.vision_model,
        temperature=0.0,
        # A page of a scanned PDF is 1,500 to 3,000 tokens and two of them plus a
        # schema is a slower call than a chat turn. 30 seconds was fine for text and
        # is not for this.
        timeout=90.0,
    )


@lru_cache()
def get_vision_fallback_client() -> OpenRouterClient:
    """The model that reads a document when the configured one cannot be reached.

    A different vendor on purpose (VISION_FALLBACK_MODEL, `x-ai/grok-4.5`): a
    fallback served by the provider that just failed is not a fallback. Same
    temperature and timeout as the primary, because it does the same job - two
    passes over one page, compared against each other.
    """
    settings = get_settings()
    return OpenRouterClient(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.vision_fallback_model or settings.vision_model,
        temperature=0.0,
        timeout=90.0,
    )


def require_schema() -> None:
    """Refuse a Tax Case route when the database is behind this build.

    Declared on the cases router, so it covers every route there at once rather
    than being remembered per route - the same reason the SQL lives in one module.

    An unconfigured or unreachable database is not this check's business: those
    routes already answer with their own 503, in words that fit the cause. Drift is
    the case nothing else could see (db/schema_version.py).
    """
    from db.schema_version import status

    current = status()
    if current.database != "ok" or current.ok:
        return
    raise HTTPException(
        503,
        detail=("the database schema is behind this build - "
                f"{current.complaint()}. See packages/backend/db/README.md."),
    )


@lru_cache()
def get_retriever():
    """Provide the KB retriever (Chroma collection + embeddings client).

    Imported lazily so route tests can override without a Chroma on disk.
    """
    from core.vectorstore import get_embeddings_client
    from db.kb_store import PostgresChunks
    from services.retrieval import Retriever

    return Retriever(PostgresChunks(), get_embeddings_client())
