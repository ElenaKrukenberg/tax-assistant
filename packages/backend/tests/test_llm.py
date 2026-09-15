import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import core.llm as llm_module
from core.llm import LLMError, OpenRouterClient


class FakeChatModel:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.bound_tools = None
        self.messages = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return self.response


def make_client(monkeypatch, fake):
    monkeypatch.setattr(llm_module, "ChatOpenAI", lambda **kwargs: fake)
    return OpenRouterClient(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1/",
        model="test/model",
    )


@pytest.mark.asyncio
async def test_chat_raw_uses_langchain_messages_and_normalizes_usage(monkeypatch):
    fake = FakeChatModel(AIMessage(
        content="Hallo",
        usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    ))
    client = make_client(monkeypatch, fake)

    message, usage = await client.chat_raw([
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "question"},
    ])

    assert isinstance(fake.messages[0], SystemMessage)
    assert isinstance(fake.messages[1], HumanMessage)
    assert message == {"role": "assistant", "content": "Hallo"}
    assert usage == {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}


@pytest.mark.asyncio
async def test_chat_raw_binds_tools_and_preserves_tool_call_contract(monkeypatch):
    fake = FakeChatModel(AIMessage(
        content="",
        tool_calls=[{
            "name": "calculate_tax_amount",
            "args": {"calculation_type": "home_office", "days": 100},
            "id": "call_1",
            "type": "tool_call",
        }],
    ))
    client = make_client(monkeypatch, fake)
    tools = [{
        "type": "function",
        "function": {
            "name": "calculate_tax_amount",
            "description": "Calculate a tax amount.",
            "parameters": {"type": "object", "properties": {}},
        },
    }]

    message, _ = await client.chat_raw(
        [{"role": "user", "content": "calculate"}], tools=tools
    )

    assert fake.bound_tools == tools
    assert message["tool_calls"][0]["id"] == "call_1"
    assert message["tool_calls"][0]["function"]["name"] == "calculate_tax_amount"
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {
        "calculation_type": "home_office",
        "days": 100,
    }


@pytest.mark.asyncio
async def test_chat_raw_converts_tool_round_history(monkeypatch):
    fake = FakeChatModel(AIMessage(content="done"))
    client = make_client(monkeypatch, fake)

    await client.chat_raw([
        {"role": "user", "content": "calculate"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "calculate_tax_amount", "arguments": "{\"days\":100}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "{\"amount\":600}"},
    ])

    assert isinstance(fake.messages[1], AIMessage)
    assert fake.messages[1].tool_calls[0]["name"] == "calculate_tax_amount"
    assert isinstance(fake.messages[2], ToolMessage)
    assert fake.messages[2].tool_call_id == "call_1"


@pytest.mark.asyncio
async def test_provider_errors_keep_the_existing_error_contract(monkeypatch):
    fake = FakeChatModel(error=RuntimeError("provider unavailable"))
    client = make_client(monkeypatch, fake)

    with pytest.raises(LLMError, match="OpenRouter request failed"):
        await client.chat_raw([{"role": "user", "content": "question"}])


def test_every_call_carries_the_zero_data_retention_policy(monkeypatch):
    """An uploaded payslip may not reach a provider allowed to keep it (ADR 0004).

    Asserted rather than trusted, and asserted on the constructor: the account
    setting that looked like it did this never did (issue #15), so this one field
    is the whole of what stands between a document and a training provider - and
    it has to hold for chat_raw and every structured call alike.
    """
    captured: dict = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return FakeChatModel()

    monkeypatch.setattr(llm_module, "ChatOpenAI", capture)
    OpenRouterClient(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1/",
        model="test/model",
    )

    assert captured["extra_body"] == {"provider": {"zdr": True}}


def test_a_document_read_keeps_the_data_policy_it_could_have_overwritten(monkeypatch):
    """The trap in the vision path, closed by a test.

    `extra_body` carries two unrelated things: the Zero Data Retention policy, set
    once in the constructor, and the OpenRouter-only fields a document read needs -
    `reasoning` and the PDF parser `plugins`. A bound `extra_body` replaces the
    constructor's rather than merging with it, so the one call that carries a
    stranger's payslip is exactly the call that could have lost the policy.
    """
    bound: dict = {}

    class FakeVisionModel(FakeChatModel):
        def bind(self, **kwargs):
            bound.update(kwargs)
            return self

    fake = FakeVisionModel(AIMessage(content='{"document_type": "rechnung"}'))
    client = make_client(monkeypatch, fake)

    text, _ = asyncio.run(client.read_document(
        prompt="p",
        content=[{"type": "text", "text": "x"}],
        json_schema={"name": "rechnung", "schema": {}},
        reasoning_effort="low",
        plugins=[{"id": "file-parser", "pdf": {"engine": "native"}}],
    ))

    assert text == '{"document_type": "rechnung"}'
    assert bound["extra_body"]["provider"] == {"zdr": True}
    assert bound["extra_body"]["reasoning"] == {"effort": "low"}
    assert bound["extra_body"]["plugins"][0]["pdf"]["engine"] == "native"
    assert bound["response_format"]["type"] == "json_schema"
