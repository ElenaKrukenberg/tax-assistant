import openai
import pytest

import core.embeddings as embeddings_module
from core.embeddings import MAX_RETRIES, OpenRouterEmbeddings
from core.llm import LLMError


class FakeEmbeddings:
    """Stands in for langchain_openai.OpenAIEmbeddings."""

    def __init__(self, vectors=None, error=None, **kwargs):
        self.kwargs = kwargs
        self.vectors = vectors
        self.error = error
        self.seen: list[list[str]] = []

    def embed_documents(self, texts):
        self.seen.append(list(texts))
        if self.error:
            raise self.error
        return self.vectors if self.vectors is not None else [[float(len(t))] for t in texts]


@pytest.fixture
def fake(monkeypatch):
    made = {}

    def factory(**kwargs):
        made["instance"] = FakeEmbeddings(**kwargs)
        return made["instance"]

    monkeypatch.setattr(embeddings_module, "OpenAIEmbeddings", factory)
    return made


def make_client(**kwargs):
    return OpenRouterEmbeddings(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1/",
        model="openai/text-embedding-3-small",
        **kwargs,
    )


def test_configures_the_chat_model_for_openrouter(fake):
    make_client(batch_size=32, timeout=12.0)
    kwargs = fake["instance"].kwargs

    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"   # trailing slash dropped
    assert kwargs["model"] == "openai/text-embedding-3-small"
    assert kwargs["chunk_size"] == 32
    assert kwargs["timeout"] == 12.0
    assert kwargs["max_retries"] == MAX_RETRIES
    # raw text rather than tiktoken ids: no BPE download during the deploy build
    assert kwargs["check_embedding_ctx_length"] is False


def test_embed_preserves_order_and_returns_one_vector_per_text(fake):
    client = make_client()

    vectors = client.embed(["aa", "bbbb", "c"])

    assert vectors == [[2.0], [4.0], [1.0]]
    assert fake["instance"].seen == [["aa", "bbbb", "c"]]


def test_embed_one_unwraps_the_single_vector(fake):
    client = make_client()

    assert client.embed_one("hallo") == [5.0]


def test_provider_failures_keep_the_existing_error_contract(fake):
    client = make_client()
    fake["instance"].error = openai.APIConnectionError(request=None)

    with pytest.raises(LLMError, match="Embeddings request failed"):
        client.embed(["anything"])


def test_our_own_errors_are_not_disguised_as_provider_failures(fake):
    """A bug here must reach the 500 handler, not the 502 "provider unavailable" one."""
    client = make_client()
    fake["instance"].error = TypeError("bad argument")

    with pytest.raises(TypeError):
        client.embed(["anything"])


def test_the_query_embedding_carries_the_zero_data_retention_policy(fake):
    """The user's own question goes to this endpoint, so the policy has to reach it.

    Nested under model_kwargs because OpenAIEmbeddings has no extra_body field;
    the flat form would fail inside the OpenAI SDK rather than at the provider,
    which is why the exact shape is what is asserted (core/embeddings.py).
    """
    make_client()

    assert fake["instance"].kwargs["model_kwargs"] == {
        "extra_body": {"provider": {"zdr": True}},
    }
