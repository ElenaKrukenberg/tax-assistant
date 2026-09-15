import json

import pytest
from fastapi.testclient import TestClient

from core.config import get_settings
from main import app
from core.dependencies import get_llm_client, get_retriever, get_reviewer_client
from services.retrieval import RetrievedChunk, RetrievalResult

# --- a test gives up on an unreachable database at once -----------------------------
#
# Fail at once instead of waiting, and above all instead of retrying. Serving a
# request is worth being patient about; a test is not, and the default patience is
# actively harmful here: psycopg_pool keeps reconnecting for five minutes behind a
# caller that has already given up, so one unreachable database turns a test run into
# a burst of connection attempts. Supabase's pooler counts failed authentications and
# trips a circuit breaker that then blocks new connections for everyone - which is how
# a stale password in one place takes the database away from everybody for an hour.
_settings = get_settings()
_settings.db_pool_timeout_seconds = 3.0
_settings.db_reconnect_timeout_seconds = 3.0

ANALYSIS_REPLY = (
    '{"intent": "knowledge", "search_query_de": "Entfernungspauschale Höhe",'
    ' "topics": ["entfernungspauschale"], "line": null, "form_id": null}'
)
ANSWER_REPLY = "The commuting allowance is 0.30 EUR/km [lsth-2022-anhang-14-entfernungspauschalen]."


class FakeLLMClient:
    """Stand-in for OpenRouterClient: returns queued replies, no network.

    A queued reply may be a plain string (text answer) or a full message
    dict (e.g. containing tool_calls) — mirrors chat_raw semantics.
    """

    model = "fake/model"

    def __init__(self, replies=None):
        self.replies = list(replies or [ANALYSIS_REPLY, ANSWER_REPLY])
        self.calls = []

    async def chat_raw(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        reply = self.replies.pop(0) if self.replies else "fallback reply"
        message = {"role": "assistant", "content": reply} if isinstance(reply, str) else reply
        return message, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    async def chat_structured(self, messages, schema):
        """Mimic a schema-constrained call, which returns an object and not prose.

        The provider is what enforces the schema, so the fake does not: a queued reply
        that is JSON comes back as the parsed object, exactly as a structured reply
        would, and the caller validates it. Anything else comes back as `None` plus the
        raw text — the path the analysis stage salvages or falls back from.
        """
        self.calls.append({"messages": list(messages), "schema": schema})
        reply = self.replies.pop(0) if self.replies else "fallback reply"
        text = reply if isinstance(reply, str) else (reply.get("content") or "")
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        try:
            return json.loads(text), usage, text
        except json.JSONDecodeError:
            return None, usage, text

    async def chat_with_usage(self, messages):
        message, usage = await self.chat_raw(messages)
        return message.get("content") or "", usage

    async def chat(self, messages):
        text, _ = await self.chat_with_usage(messages)
        return text


class FakeRetriever:
    """Stand-in for Retriever: returns canned chunks, records search args."""

    def __init__(self, chunks=None, strategies=None):
        default = [RetrievedChunk(
            text="Die Entfernungspauschale beträgt 0,30 € je Entfernungskilometer.",
            metadata={
                "source_id": "lsth-2022-anhang-14-entfernungspauschalen",
                "title": "LStH Anhang 14", "section": "Anhang 14",
                "topic_entfernungspauschale": True,
            },
            distance=0.3,
        )]
        self.result = RetrievalResult(
            chunks=default if chunks is None else chunks,
            strategies=["metadata"] if strategies is None else strategies,
        )
        self.searches = []

    def search(self, query, topics=None, line=None, form_id=None, k=5):
        self.searches.append({"query": query, "topics": topics, "line": line, "form_id": form_id})
        return self.result


# --- no test may reach a real provider ---------------------------------------------
#
# `Settings` reads `.env` (core/config.py), and the integration suite needs `.env` for
# DATABASE_URL - so on every local run the real OPENROUTER_API_KEY and
# LANGSMITH_API_KEY are sitting right there, loaded. Until this existed, the only
# thing between a test and a paid provider call was each test file remembering to
# override `get_llm_client`, and `@lru_cache` made forgetting worse than local: one
# test that built a real client left it cached for every test after it.
#
# So the two guards below are autouse and apply to the whole suite, integration
# included. They belong here and not in the application: code that knows it is under
# test is a worse thing than the problem it solves.


class RealProviderForbidden(RuntimeError):
    """A test tried to build a real provider client.

    Raised at the seam rather than at the socket, which makes the traceback name the
    call site. If you see this, the test needs a fake - `fake_llm`, `fake_retriever`,
    or an explicit `app.dependency_overrides` entry - not an exception here.
    """


def _forbidden(*args, **kwargs):
    raise RealProviderForbidden(
        "a test reached for the real provider. Override the dependency with a fake "
        "(see tests/conftest.py) instead of letting the call out."
    )


@pytest.fixture(autouse=True)
def forbid_real_providers(monkeypatch):
    """Make a real provider call impossible, whatever a test forgets.

    `ChatOpenAI` and `OpenAIEmbeddings` are the two constructors every paid call
    passes through, so blocking them covers the model and the embeddings at once and
    keeps working when a call site moves. `test_llm.py` and `test_embeddings.py`
    patch the same names in their own fixtures, which run after this one and
    therefore win - they are testing the adapter around the client, with a fake in
    place of it, which is exactly what should still be allowed.

    LangSmith is silenced the same way and for the same reason: a traced run from a
    test suite is a real upload of test data to a third party, and with a key in
    `.env` that is what would happen.
    """
    from core import dependencies, embeddings as embeddings_module, llm as llm_module, tracing
    from core.config import get_settings

    monkeypatch.setattr(llm_module, "ChatOpenAI", _forbidden)
    monkeypatch.setattr(embeddings_module, "OpenAIEmbeddings", _forbidden)
    monkeypatch.setattr(get_settings(), "langsmith_api_key", "", raising=False)
    tracing.callbacks.cache_clear()

    # Cleared on the way in as well as out: a real client cached by anything that ran
    # before this fixture existed - or by a test that clears the patch itself - must
    # not be handed to the next test as if it were a fake.
    cached = (dependencies.get_llm_client, dependencies.get_reviewer_client,
              dependencies.get_retriever)
    for factory in cached:
        factory.cache_clear()
    yield
    for factory in cached:
        factory.cache_clear()
    tracing.callbacks.cache_clear()


@pytest.fixture(autouse=True)
def fake_providers_by_default(forbid_real_providers):
    """Every test gets a working fake model and retriever without asking for one.

    The default is a fake that answers rather than one that raises: a test that
    forgot the override should keep working, not fail on a line that has nothing to
    do with what it is checking. `forbid_real_providers` is what makes "fake" a
    guarantee; this is what makes it convenient.

    A file that wants something else says so - `test_cases_api.py` overrides both
    models with `None` on purpose, to interview through the deterministic filter and
    review through the rules-only pass. Those fixtures are function-scoped and run
    after this one, so they win.
    """
    llm = FakeLLMClient()
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_reviewer_client] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: FakeRetriever()
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def only_the_test_database(request):
    """Before any integration test runs, make the database prove it is the test one.

    Here rather than at module import, because importing a test module must not open
    a connection: a plain offline `pytest` imports the integration modules too, so a
    probe there cost one connection attempt per run - and a failed one, whenever the
    password is stale, which is how the pooler's circuit breaker gets tripped by
    nothing more than running the fast suite.

    The check itself is `tests/dbguard.py`: it asks the database whether it carries
    the row from `db/test_database_marker.sql`, which is applied to the development
    project and to nothing else.
    """
    if request.node.get_closest_marker("integration") is None:
        return
    from tests import dbguard

    dbguard.check_marker()


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Start every test with empty rate-limit counters.

    TestClient reports one client address for the whole suite, so without this the
    tests would share a per-IP bucket and whichever test happened to run eleventh
    would fail with a 429.
    """
    from core.rate_limit import get_limiter

    get_limiter().reset()


@pytest.fixture
def fake_llm():
    return FakeLLMClient()


@pytest.fixture
def fake_retriever():
    return FakeRetriever()


@pytest.fixture
def client(fake_llm, fake_retriever):
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    app.dependency_overrides[get_retriever] = lambda: fake_retriever
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def sample_tax_question():
    return {
        "text": "Can I deduct my home office as a remote employee?",
        "language": "en",
    }
