import logging
import re
import time
import uuid
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import get_settings
from core.llm import LLMError
from core.rate_limit import RateLimited
from api.routes import cases, documents, meta, profile, tax

settings = get_settings()

# merge_contextvars is what carries the per-request id bound in the middleware
# below into every log line the request produces, without threading a logger
# through the service layer.
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

# Rendered as JSON in production so log lines are queryable, and as key=value in
# debug so they are readable in a terminal. Uvicorn's own records go through the
# same formatter via foreign_pre_chain.
_handler = logging.StreamHandler()
_handler.setFormatter(structlog.stdlib.ProcessorFormatter(
    processor=(structlog.dev.ConsoleRenderer(colors=False) if settings.debug
               else structlog.processors.JSONRenderer()),
    foreign_pre_chain=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ],
))
logging.basicConfig(handlers=[_handler], level=settings.log_level, force=True)

logger = structlog.get_logger()

# A client may supply its own request id for tracing, but it lands in every log
# line this request writes — so anything that is not a plain identifier is
# replaced rather than logged.
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_startup", debug=settings.debug)

    # Say at startup whether the knowledge base is loaded. It no longer arrives with
    # the deploy - that was the whole problem (#32) - so an empty one is an ordinary
    # state of a fresh database and belongs in the log rather than in an exception.
    try:
        from db.kb_store import count as kb_count

        loaded = kb_count()
        if loaded == 0:
            logger.warning(
                "kb_empty",
                message="No knowledge base loaded. Run 'python ingest.py' against "
                        "this database; the chat cannot answer until it is there.",
            )
        else:
            logger.info("kb_loaded", chunks=loaded)
    except Exception as e:  # noqa: BLE001 - startup never fails over a diagnostic
        logger.warning("kb_check_failed", error=str(e))

    # Say at startup what the database has, so drift is in the deploy log rather
    # than found later by a screen that stayed empty. The Tax Case routes refuse on
    # their own (core/dependencies.require_schema); this is only the announcement.
    try:
        from db.schema_version import status as schema_status
        schema = schema_status()
        if schema.database != "ok":
            logger.info("schema_check_skipped", database=schema.database)
        elif schema.ok:
            logger.info("schema_ok", applied=list(schema.applied),
                        unrecorded=list(schema.unrecorded))
        else:
            logger.warning("schema_drift", complaint=schema.complaint(),
                           missing=list(schema.missing),
                           contradicted=list(schema.contradicted))
    except Exception:  # noqa: BLE001 - startup never fails over a diagnostic
        logger.warning("schema_check_failed", exc_info=True)

    yield

    # The async pool the graph checkpointer and the profile store share. Closed
    # here rather than left to the interpreter: Supabase's pooler holds a server
    # connection for as long as we hold a client one, and a redeploy that walks
    # away from three of them is a redeploy that eats into the next one's budget.
    try:
        from db.connection import close_async_pool
        await close_async_pool()
    except Exception:  # noqa: BLE001 — shutdown never fails the shutdown
        logger.warning("async_pool_close_failed", exc_info=True)

    logger.info("app_shutdown")


app = FastAPI(
    title="German Tax Assistant API",
    description="RAG-powered API for German tax questions",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # localhost and 127.0.0.1 are different origins for CORS — allow both
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        # production frontend origins via env (comma-separated)
        *[o.strip() for o in settings.cors_extra_origins.split(",") if o.strip()],
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Response headers the browser is allowed to read. `allow_headers` above is about
    # the *request*; without this list a cross-origin fetch sees only the six
    # CORS-safelisted response headers and everything else is silently absent — not an
    # error, just gone.
    #
    # X-Request-ID so a client can report the id back; Retry-After off a 429; and the
    # two the Anlage N download needs — the filename to save it under and how many
    # figures the form could not take. That last pair was missing until a browser
    # smoke test found it: the download worked, and the note beside it quietly said
    # the form was complete when it was not. No unit test could have seen that.
    expose_headers=["X-Request-ID", "Retry-After",
                    "Content-Disposition", "X-Unplaced-Count"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Give every request an id, bind it to the logger, and time it."""
    supplied = request.headers.get("X-Request-ID", "")
    request_id = supplied if REQUEST_ID_RE.match(supplied) else uuid.uuid4().hex[:16]
    request.state.request_id = request_id

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        # Logged in `finally` so a request that raised is still measured; the
        # exception handlers below record what actually went wrong.
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(meta.router)
app.include_router(tax.router)
app.include_router(cases.router)
app.include_router(documents.router)
app.include_router(profile.router)


# --- error contract: every error returns {"detail": <safe text>, "error_code": <CODE>} ---
# internals are logged, never sent to the client

def _error(status_code: int, detail: str, error_code: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "error_code": error_code},
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Only the location and kind of each error, never Pydantic's `input` field:
    # for a too-long question that field is the whole question, salary included.
    problems = [{"loc": ".".join(str(p) for p in e.get("loc", [])), "type": e.get("type", "")}
                for e in exc.errors()[:5]]
    logger.warning("request_validation_failed", path=request.url.path, problems=problems)
    # Built from the actual problems, still without Pydantic's `input` field. This
    # used to be a message hardcoded for /ask ("'text' must be 1-1000 characters"),
    # which turned into a lie the day a second router appeared and masked a real
    # bug in its tests.
    where = ", ".join(sorted({p["loc"] for p in problems if p["loc"]})) or "request"
    return _error(
        422,
        f"Request validation failed: {where}.",
        "VALIDATION_ERROR",
    )


@app.exception_handler(RateLimited)
async def rate_limited_handler(request: Request, exc: RateLimited):
    # Which of the two limits tripped is logged (in the dependency), not returned:
    # the client can only act on how long to wait, and telling it whether it hit
    # the global ceiling is telling it how to tune an attack.
    return _error(
        429,
        "Too many requests. Please wait a moment and try again.",
        "RATE_LIMITED",
        headers={"Retry-After": str(exc.retry_after)},
    )


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    # log the provider detail (URL, status) but keep it out of the response
    logger.error("llm_provider_error", path=request.url.path, error=str(exc))
    return _error(
        502,
        "The language model provider is temporarily unavailable. Please try again in a moment.",
        "LLM_PROVIDER_ERROR",
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("unhandled_exception", path=request.url.path)
    return _error(500, "Internal server error. Please try again later.", "INTERNAL_ERROR")


@app.get("/")
async def root():
    return {"message": "German Tax Assistant API"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.api_port,
        reload=settings.debug,
    )
