import json

import structlog
from langchain_core.messages import AIMessage, convert_to_messages
from langchain_openai import ChatOpenAI

logger = structlog.get_logger(__name__)

# Attempts per provider call, including the first. Transient failures — a connection
# reset, a 429, a 5xx, a timeout — are retried with the SDK's own exponential backoff
# before the call is declared failed.
#
# This is stated rather than inherited. The OpenAI SDK already defaults to two retries,
# so a blip was never fatal here, but a number nobody wrote down is not a decision: it
# can change under a dependency bump and nothing in this repo would notice. It matters
# because both agents degrade on LLMError — the Interviewer to the deterministic filter,
# the Reviewer to rules-only — and that degradation is meant to be the last line against
# a real outage, not the first response to a dropped packet.
MAX_RETRIES = 3

# The provider data policy, sent on every call. Zero Data Retention means the provider
# stores the request for no period at all and therefore cannot train on it. OpenRouter
# drops every retaining endpoint from routing and returns 404 when none is left, so a
# violation is a failed call rather than a silent send to a training provider.
#
# In code and not in an account setting, because the account setting was never what
# limited this key: the 404s that looked like a privacy block are a model allowlist on
# the course account (issue #15), and providers that may train on inputs are reachable
# right now. It costs no reachability - measured 2026-09-01, google/gemini-3.7-flash,
# anthropic/claude-haiku-4.5 and openai/gpt-5.4 each return 200 under it - and it is
# what makes ADR 0004 an end-to-end promise instead of one about this project's disk.
PROVIDER_POLICY = {"zdr": True}


class LLMError(Exception):
    """Raised when the LLM provider call fails."""


class OpenRouterClient:
    """LangChain chat-model adapter for OpenRouter's OpenAI-compatible API.

    The rest of the application intentionally keeps its small, provider-neutral
    ``chat_raw`` contract. LangChain owns message conversion, the provider call
    and tool binding; this adapter converts the resulting ``AIMessage`` back to
    the shape consumed by ``TaxService``.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.3,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        from core.tracing import callbacks

        self._chat_model = ChatOpenAI(
            model=model,
            api_key=api_key, # type: ignore
            base_url=self.base_url,
            temperature=temperature,
            timeout=timeout,
            max_retries=MAX_RETRIES,
            # LangSmith, redacted, or nothing (core/tracing.py). Constructor-level,
            # so every chat_raw / structured call is traced without threading a
            # config through the call sites.
            callbacks=callbacks(),
            # Zero Data Retention on every call, the vision read of an uploaded
            # payslip included (PROVIDER_POLICY above). extra_body is how
            # langchain_openai passes a provider-specific field through, and the
            # constructor is where it belongs: chat_raw and every structured call
            # inherit it without a call site having to remember.
            extra_body={"provider": PROVIDER_POLICY},
        )

    async def chat(self, messages: list[dict]) -> str:
        """Send chat messages to the model and return the text reply."""
        text, _ = await self.chat_with_usage(messages)
        return text

    async def chat_with_usage(self, messages: list[dict]) -> tuple[str, dict]:
        """Like chat(), but also returns the provider usage dict (token counts)."""
        message, usage = await self.chat_raw(messages)
        return message.get("content") or "", usage

    async def chat_raw(self, messages: list[dict], tools: list[dict] | None = None) -> tuple[dict, dict]:
        """Send a chat request, optionally with tools bound; return the full
        assistant message (which may contain tool_calls) and the usage dict."""
        try:
            langchain_messages = convert_to_messages(messages)
            runnable = self._chat_model.bind_tools(tools) if tools else self._chat_model
            response = await runnable.ainvoke(langchain_messages)
        except Exception as e:
            # Logged where it happens, because the caller turns this into a silent
            # degradation: without this line the only trace of an outage is a review
            # that quietly says "deterministic rules only".
            logger.warning("llm_call_failed", model=self.model,
                           attempts=MAX_RETRIES, error=str(e))
            raise LLMError(f"OpenRouter request failed: {e}") from e

        if not isinstance(response, AIMessage):
            raise LLMError(
                f"Unexpected LangChain response type: {type(response).__name__}"
            )

        return self._to_openai_message(response), self._usage_dict(response)

    async def read_document(
        self,
        *,
        prompt: str,
        content: list[dict],
        json_schema: dict,
        reasoning_effort: str | None = None,
        plugins: list[dict] | None = None,
    ) -> tuple[str, dict]:
        """One vision read of one document, constrained to `json_schema`.

        Separate from `chat_structured` on purpose, on both counts:

        * the schema is a hand-written `json_schema` payload rather than a Pydantic
          class, because the shape that was measured against 24 models is
          ``{"type": ["number", "null"]}`` and Pydantic emits the `anyOf` form
          instead (`services/documents/schemas.py` says why that matters);
        * the OpenRouter-only fields this needs - `reasoning`, and the PDF parser
          `plugins` - travel in `extra_body`, which the constructor already uses for
          the data policy. So they are merged with it here rather than replacing it:
          a bound `extra_body` overrides the constructor's, and losing the policy on
          the one call that carries a stranger's payslip is exactly the accident this
          method has to make impossible.

        Returns the raw JSON text and the usage dict. Parsing and validating is the
        caller's business (`services/documents/extract.py`), which is what lets a
        malformed answer become a second attempt rather than an exception here.
        """
        extra_body: dict = {"provider": PROVIDER_POLICY}
        if reasoning_effort:
            extra_body["reasoning"] = {"effort": reasoning_effort}
        if plugins:
            extra_body["plugins"] = plugins

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ]
        try:
            runnable = self._chat_model.bind(
                response_format={"type": "json_schema", "json_schema": json_schema},
                extra_body=extra_body,
            )
            response = await runnable.ainvoke(convert_to_messages(messages))
        except Exception as e:
            logger.warning("llm_call_failed", model=self.model, vision=True,
                           attempts=MAX_RETRIES, error=str(e))
            raise LLMError(f"OpenRouter request failed: {e}") from e

        if not isinstance(response, AIMessage):
            raise LLMError(f"Unexpected LangChain response type: {type(response).__name__}")

        return str(response.text), self._usage_dict(response)

    async def chat_structured(self, messages: list[dict], schema: type) -> tuple[object | None, dict, str]:
        """Send a chat request whose reply is constrained to ``schema``.

        Returns ``(parsed, usage, raw_text)``. ``parsed`` is ``None`` when the model
        answered but the reply did not satisfy the schema — the caller decides whether
        to salvage the raw text or fall back, because the analysis stage must degrade
        rather than fail the request.

        ``include_raw`` is what keeps the token counts: without it LangChain returns
        only the parsed object and the call would be invisible in the per-request cost.
        """
        try:
            langchain_messages = convert_to_messages(messages)
            runnable = self._chat_model.with_structured_output(schema, include_raw=True)
            response = await runnable.ainvoke(langchain_messages)
        except Exception as e:
            logger.warning("llm_call_failed", model=self.model, structured=True,
                           attempts=MAX_RETRIES, error=str(e))
            raise LLMError(f"OpenRouter request failed: {e}") from e

        raw = response.get("raw")
        if not isinstance(raw, AIMessage):
            raise LLMError(f"Unexpected LangChain response type: {type(raw).__name__}")

        return response.get("parsed"), self._usage_dict(raw), str(raw.text)

    @staticmethod
    def _to_openai_message(message: AIMessage) -> dict:
        """Translate LangChain's standard tool-call representation for TaxService."""
        result: dict[str, object] = {"role": "assistant", "content": str(message.text)}
        tool_calls = []

        for call in message.tool_calls:
            tool_calls.append({
                "id": call.get("id") or call["name"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call.get("args", {}), ensure_ascii=False),
                },
            })

        # Keep malformed provider calls visible to the existing tool dispatcher.
        # It returns a structured error that the model can correct on the next round.
        for call in message.invalid_tool_calls:
            arguments = call.get("args") or "{}"
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            tool_calls.append({
                "id": call.get("id") or call.get("name") or "invalid_tool_call",
                "type": "function",
                "function": {
                    "name": call.get("name") or "invalid_tool_call",
                    "arguments": arguments,
                },
            })

        if tool_calls:
            result["tool_calls"] = tool_calls
        return result

    @staticmethod
    def _usage_dict(message: AIMessage) -> dict:
        """Normalize LangChain/OpenAI token names to the existing API contract."""
        usage = message.usage_metadata or {}
        if usage:
            prompt = int(usage.get("input_tokens", 0) or 0)
            completion = int(usage.get("output_tokens", 0) or 0)
            total = int(usage.get("total_tokens", prompt + completion) or 0)
            return {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
            }

        provider_usage = message.response_metadata.get("token_usage", {})
        prompt = int(provider_usage.get("prompt_tokens", 0) or 0)
        completion = int(provider_usage.get("completion_tokens", 0) or 0)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": int(
                provider_usage.get("total_tokens", prompt + completion) or 0
            ),
        }
