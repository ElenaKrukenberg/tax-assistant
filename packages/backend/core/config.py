from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    debug: bool = False
    api_port: int = 8000

    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # comma-separated extra CORS origins for deployed frontends,
    # e.g. "https://tax-assistant.vercel.app"
    cors_extra_origins: str = ""

    # Denial-of-wallet guard on /ask — see core/rate_limit.py for why there are
    # two windows. Either limit is disabled by setting it to 0.
    rate_limit_per_ip: int = 10
    rate_limit_per_ip_window_seconds: int = 60
    rate_limit_global: int = 240
    rate_limit_global_window_seconds: int = 3600
    # True only when exactly one trusted proxy (Render, Fly, a load balancer) sits
    # in front: then the rightmost X-Forwarded-For entry is the real client. Left
    # false, per-IP counting sees the proxy and puts everyone in one bucket; set
    # true without a proxy, and clients pick their own bucket via the header.
    trust_proxy_header: bool = False

    chroma_path: str = "./data/chroma"
    chroma_collection: str = "tax_kb_2025"

    # Embeddings via OpenRouter (OpenAI-compatible /embeddings endpoint)
    embedding_model: str = "openai/text-embedding-3-small"

    # --- Supabase: authentication and the Postgres a Tax Case lives in (ADR 0003) ---
    #
    # Empty by default so every existing test and the chat tab keep running without
    # a database: the Tax Case routes check for it and fail with a clear message
    # rather than the whole app refusing to start.
    #
    # `database_url` must be the *pooler* connection string, not the direct one.
    # Supabase gives new projects an IPv6-only direct host, and Render's free plan
    # is IPv4, so the direct string works locally and fails once deployed — the
    # worst way round to discover it. Transaction mode (port 6543) also forbids
    # prepared statements, which is why db/ sets prepare_threshold to 0.
    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    # For verifying the JWT the frontend sends. This project signs with asymmetric
    # keys (ES256), so there is no shared secret to hold: the backend fetches the
    # public key from the project's JWKS endpoint and caches it.
    supabase_jwks_url: str = ""

    # --- LangSmith (core/tracing.py) ---
    # Empty key = no tracing at all, which is what tests and offline runs want.
    # Explicit wiring, not the LANGSMITH_TRACING autopilot: the autopilot's own
    # client has no anonymizer and would upload unredacted runs.
    langsmith_api_key: str = ""
    langsmith_project: str = "tax-assistant"
    # Only for an EU-region account (eu.smith.langchain.com); empty = the default
    # US endpoint, which is what api-keys from smith.langchain.com expect.
    langsmith_endpoint: str = ""

    # --- The money guards on the public deployment (Q23, db/usage.py) ---
    # 0 disables a limit. Cases per user is checked at creation; the two call
    # quotas are counted in Postgres so a deploy cannot reset the month.
    cases_per_user: int = 2
    interview_calls_per_user_per_day: int = 150   # ~7 full interviews
    interview_calls_global_per_month: int = 3000  # ~$10/month on haiku
    # Documents are counted separately: one upload is two vision passes, ~0.62 cents
    # measured (issue #65), so 20 a day per person and 500 a month across the demo is
    # roughly $3 - and running out of them leaves the interview working.
    document_reads_per_user_per_day: int = 20
    document_reads_global_per_month: int = 500
    # How long an upload may wait for the user's decision before it is expired and its
    # extraction thrown away. The two readings live in the intake checkpoint until
    # then, so this is the number that makes "temporary" mean something (ADR 0004).
    document_confirmation_ttl_hours: int = 24

    # A user created by hand in the dashboard, for the tests that run against the
    # real database. Creating one from a test would need the service_role key, which
    # this project deliberately holds nowhere.
    test_user_id: str = ""

    # How long a caller waits for a connection, and how long the pool's own worker
    # goes on retrying behind it. The second one is the dangerous default: psycopg_pool
    # retries for five minutes, so one wrong password becomes a queue of failed
    # authentications rather than a single clean error - and that is what Supabase's
    # pooler counts before it trips its circuit breaker and blocks new connections for
    # everyone. Serving a request wants patience; a test wants to be told at once.
    db_pool_timeout_seconds: float = 20.0
    db_reconnect_timeout_seconds: float = 300.0

    log_level: str = "INFO"
    # What limits the choice here is a model allowlist on the course account, not a
    # privacy setting. Probing every vision-capable model on OpenRouter returned 34
    # reachable out of 184 (issue #15), so "anthropic/claude-sonnet-5" is not blocked
    # by a setting anyone can change and will not come back by opening a data policy;
    # the Anthropic model this key does permit is "anthropic/claude-opus-4.7". The data
    # policy this project sends is PROVIDER_POLICY in core/llm.py, and this default
    # returns 200 under it.
    llm_model: str = "anthropic/claude-haiku-4.5"

    # The Reviewer runs on a different, stronger model than the Interviewer - the
    # independence is meant to be more than a prompt (docs/DECISIONS.md). Named here
    # rather than left empty: empty falls back to llm_model, and then a fresh clone
    # with no .env has the Interviewer's model auditing the Interviewer's work with
    # nothing to say so. openai/gpt-5.4 is reachable and is what render.yaml sets.
    reviewer_model: str = "openai/gpt-5.4"

    # Document intake reads a document with a vision model, and these two are the
    # outcome of a measured sweep over every vision model this key can reach, not a
    # preference: `google/gemini-3.7-flash` at `reasoning: {"effort": "low"}` read all
    # three test documents perfectly at 0.310 cents a pass, the cheapest of the
    # 24 candidates that did (issues #11 and #65,
    # docs/research/vision-model-for-document-intake.md).
    #
    # The fallback is deliberately *not* a cheaper Gemini. `gemini-2.5-flash` and
    # `-flash-lite` each moved amounts between rows of a skewed form while reporting
    # high confidence, and two passes cannot catch a mistake both passes make.
    # `x-ai/grok-4.5` was also perfect, at 0.358 cents, and is a different vendor.
    vision_model: str = "google/gemini-3.7-flash"
    vision_fallback_model: str = "x-ai/grok-4.5"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
