import structlog
from fastapi import APIRouter, Depends, Request

from api.schemas.tax import (
    ErrorResponse,
    FeedbackRequest,
    FeedbackResponse,
    TaxAnswerResponse,
    TaxQuestionRequest,
)
from core import security
from core.dependencies import get_llm_client, get_retriever
from core.llm import OpenRouterClient
from core.rate_limit import enforce_rate_limit
from services.retrieval import Retriever
from services.tax_service import TaxService

router = APIRouter(prefix="/api/v1/tax", tags=["tax"])

logger = structlog.get_logger(__name__)


@router.post(
    "/ask",
    response_model=TaxAnswerResponse,
    responses={
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
    # Before anything else in the handler: a refused request must not reach the
    # provider, which is the entire point of having the limit.
    dependencies=[Depends(enforce_rate_limit)],
)
async def ask_tax_question(
    request: TaxQuestionRequest,
    http_request: Request,
    llm: OpenRouterClient = Depends(get_llm_client),
    retriever: Retriever = Depends(get_retriever),
):
    """
    Ask a question about German taxes and get a cited answer.

    - **text**: The tax question
    - **language**: Response language (auto, en, de, tr, ru)
    - **context**: Optional context about the user (marital status, income, etc.)

    The response carries the `request_id` that identifies this request in the
    server logs; POST it back to /feedback to attach a rating to it.

    Rate limited per client and globally (see `core/rate_limit.py`); over the
    limit the response is a 429 carrying `Retry-After`.

    Errors follow the contract `{"detail": <safe text>, "error_code": <CODE>}`
    via the global exception handlers in main.py (VALIDATION_ERROR,
    RATE_LIMITED, LLM_PROVIDER_ERROR, INTERNAL_ERROR); internals are logged, not
    returned.
    """
    # The backticks in that last paragraph are load-bearing. Swagger UI renders this
    # docstring as Markdown, so bare angle brackets are parsed as HTML: the placeholder
    # with a space in it was dropped as an unknown tag, leaving '"detail": ,' with no
    # value, and the other one is a real tag name, which opened an inline-code element
    # that was never closed and styled the rest of the paragraph as code. Keep any
    # angle brackets in this file's docstrings inside backticks.
    service = TaxService(llm, retriever)
    request_id = getattr(http_request.state, "request_id", "")
    return await service.answer_question(request, request_id=request_id)


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(feedback: FeedbackRequest):
    """
    Record a 👍/👎 on a previous answer.

    Ratings are written to the log against the answer's `request_id`, which is
    what makes them joinable with that request's retrieval strategies, tools and
    token usage. Free-text comments are redacted before logging — a user
    explaining a wrong answer will quote their own salary while doing it.
    """
    logger.info(
        "answer_feedback",
        rated_request_id=feedback.request_id,
        rating=feedback.rating,
        comment=security.safe_preview(feedback.comment or "", limit=500) or None,
    )
    return FeedbackResponse()


@router.get("/health")
async def health_check():
    """Health check endpoint.

    Still 200 when the schema has drifted, and deliberately so: this is the path
    Render polls, a non-200 takes the instance out of service, and drift stops Tax
    Cases without stopping the chat tab. The status body is what says so - "status"
    stays "ok" for the process, and "schema" carries the bad news.

    It reports what is already known and never asks the database itself: this route
    is polled, and the default test run has to work offline. The startup check fills
    that in, and a drifted answer goes stale on its own, so "not_checked" here means
    nobody has looked yet - which is the truth on an instance that has not finished
    starting.
    """
    from db.schema_version import cached_status

    current = cached_status()
    if current is None:
        return {"status": "ok", "schema": {"status": "not_checked"}}
    return {"status": "ok", "database": current.database,
            "schema": current.as_health()}
