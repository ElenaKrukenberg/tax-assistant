"""The guard that stops a test spending money, tested.

A guard nobody checks is a guard that quietly stops working - which is the same
failure the four-name redaction list had, one layer up. So this file asserts the two
promises `tests/conftest.py` makes: no test can build a real provider client, and
every test already has a fake without asking.

Why it matters here rather than in general: `Settings` reads `.env`, and the
integration suite needs `.env` for DATABASE_URL, so a real OPENROUTER_API_KEY is
loaded on every local run. Before the guard, one test that forgot an override made a
paid call - and because the factories are `@lru_cache`d, it handed the real client to
every test after it too.
"""

from __future__ import annotations

import pytest

from core import dependencies, embeddings as embeddings_module, llm as llm_module
from core.tracing import callbacks
from core.vectorstore import get_embeddings_client
from main import app
from tests.conftest import RealProviderForbidden


def test_the_model_factory_refuses_to_build_a_real_client():
    """The path a forgotten override takes, and where it now stops."""
    with pytest.raises(RealProviderForbidden):
        dependencies.get_llm_client()


def test_the_reviewer_factory_refuses_too():
    """Its own factory and its own cache, so it needs its own assertion."""
    with pytest.raises(RealProviderForbidden):
        dependencies.get_reviewer_client()


def test_the_embeddings_factory_refuses_to_build_a_real_client():
    """Embeddings are billed as well, and reach the provider by another route."""
    with pytest.raises(RealProviderForbidden):
        get_embeddings_client()


def test_the_seam_is_the_constructor_both_paths_share():
    """Blocking `ChatOpenAI` and `OpenAIEmbeddings` is what makes the cover complete.

    Asserted by name rather than by behaviour so that moving a call site cannot
    quietly slip past the guard: if either of these stops being the constructor the
    adapters use, this fails and says so.
    """
    assert llm_module.ChatOpenAI.__name__ == "_forbidden"
    assert embeddings_module.OpenAIEmbeddings.__name__ == "_forbidden"


def test_no_trace_leaves_a_test_run():
    """With a key in `.env`, a traced test run would be a real upload of test data."""
    assert callbacks() == []


def test_a_test_that_asks_for_nothing_still_has_a_fake_model():
    """The other half of the promise: guaranteed, not merely possible.

    No fixture is requested here beyond the autouse ones, and the override is
    already in place - which is what a new test file gets for free.
    """
    assert dependencies.get_llm_client in app.dependency_overrides
    assert dependencies.get_reviewer_client in app.dependency_overrides
    assert dependencies.get_retriever in app.dependency_overrides


def test_the_default_fake_answers_instead_of_raising():
    """Deliberate: a forgotten override should not fail on an unrelated line."""
    import asyncio

    fake = app.dependency_overrides[dependencies.get_llm_client]()
    message, usage = asyncio.run(fake.chat_raw([{"role": "user", "content": "hi"}]))
    assert message["role"] == "assistant"
    assert usage["total_tokens"] > 0


def test_a_file_can_still_choose_its_own_override(fake_llm):
    """`test_cases_api.py` overrides both models with None on purpose.

    The autouse default must not take that away, or the interview would run through
    a fake model where that suite wants the deterministic filter.
    """
    app.dependency_overrides[dependencies.get_llm_client] = lambda: None
    assert app.dependency_overrides[dependencies.get_llm_client]() is None
    app.dependency_overrides[dependencies.get_llm_client] = lambda: fake_llm
    assert app.dependency_overrides[dependencies.get_llm_client]() is fake_llm
