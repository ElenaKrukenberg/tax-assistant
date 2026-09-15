import pytest
from fastapi.testclient import TestClient

from main import app
from core.dependencies import get_llm_client, get_retriever
from core.llm import LLMError
from tests.conftest import FakeRetriever


class ExplodingLLM:
    """LLM stand-in that fails like a provider outage, with internal details."""

    model = "fake/model"

    async def chat_structured(self, messages, schema):
        # The analysis stage is the first provider call a request makes, so this is
        # where an outage surfaces. A schema-constrained call fails the same way.
        raise LLMError("OpenRouter request failed: 503 at https://internal-url/secret")

    async def chat_with_usage(self, messages):
        raise LLMError("OpenRouter request failed: 503 at https://internal-url/secret")


class ExplodingRetriever:
    def search(self, *args, **kwargs):
        raise RuntimeError("chroma exploded: /Users/elena/secret/path")


@pytest.fixture
def error_client():
    # raise_server_exceptions=False lets the global handlers produce responses
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_validation_error_contract(error_client):
    r = error_client.post("/api/v1/tax/ask", json={"text": ""})
    assert r.status_code == 422
    body = r.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "text" in body["detail"]


def test_llm_provider_error_contract(error_client):
    app.dependency_overrides[get_llm_client] = lambda: ExplodingLLM()
    app.dependency_overrides[get_retriever] = lambda: FakeRetriever()
    r = error_client.post("/api/v1/tax/ask", json={"text": "Pendlerpauschale?"})
    assert r.status_code == 502
    body = r.json()
    assert body["error_code"] == "LLM_PROVIDER_ERROR"
    # internal details (provider URL etc.) must not leak to the client
    assert "internal-url" not in body["detail"]
    assert "secret" not in body["detail"]


def test_validation_error_log_does_not_carry_the_question(error_client, caplog):
    """Pydantic puts the rejected value in `input` — for us that is the question itself."""
    salary_question = "My gross salary is 91500 EUR, how much can I deduct? " * 40
    with caplog.at_level("WARNING"):
        error_client.post("/api/v1/tax/ask", json={"text": salary_question})
    logged = str([r.msg for r in caplog.records])
    assert "91500" not in logged
    assert "gross salary" not in logged
    assert "request_validation_failed" in logged


def test_unhandled_error_contract(error_client):
    app.dependency_overrides[get_llm_client] = lambda: ExplodingLLM()
    app.dependency_overrides[get_retriever] = lambda: ExplodingRetriever()
    # retriever is reached only after analysis, so make the LLM succeed first
    from tests.conftest import FakeLLMClient

    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    r = error_client.post("/api/v1/tax/ask", json={"text": "Pendlerpauschale?"})
    assert r.status_code == 500
    body = r.json()
    assert body["error_code"] == "INTERNAL_ERROR"
    # no filesystem paths or exception internals in the public message
    assert "/Users/" not in body["detail"]
    assert "chroma" not in body["detail"].lower()


def test_the_browser_may_read_the_headers_the_frontend_depends_on():
    """CORS: a response header the page cannot read is the same as one never sent.

    Found by the browser smoke test, not by anything here: the Anlage N download
    worked while the note beside it read "the form is complete", because the count of
    figures the form could not take was invisible to a cross-origin fetch. Listed as
    a guard so the next header added to a response is added to this list too.
    """
    from starlette.middleware.cors import CORSMiddleware

    import main

    cors = next(m for m in main.app.user_middleware if m.cls is CORSMiddleware)
    exposed = set(cors.options["expose_headers"])
    assert {"X-Request-ID", "Retry-After",
            "Content-Disposition", "X-Unplaced-Count"} <= exposed
