import openai
from langchain_openai import OpenAIEmbeddings

from core.llm import PROVIDER_POLICY, LLMError

# Texts per request. The endpoint accepts far more, but a smaller batch keeps a single
# failure cheap to retry.
DEFAULT_BATCH_SIZE = 64

# Retry the request on 429/5xx with LangChain's backoff. There were no retries before,
# and the place that needed them is the build: render.yaml ends its build command with
# `python ingest.py --reset`, so one rate-limited batch out of thirteen failed the whole
# deploy — after the earlier batches had already been paid for.
MAX_RETRIES = 3


class OpenRouterEmbeddings:
    """Embeddings client for OpenRouter's OpenAI-compatible /embeddings endpoint.

    A thin adapter over LangChain's ``OpenAIEmbeddings`` keeping the two-method contract
    (``embed``, ``embed_one``) that the ingestion CLI and the retriever already use, and
    keeping provider failures inside our own ``LLMError`` so the error contract in
    main.py still applies.

    Synchronous on purpose: both callers are. Ingestion is a CLI, and retrieval already
    runs off the event loop in a threadpool because the Chroma client it calls in the
    same function is synchronous too.
    """

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 60.0,
                 batch_size: int = DEFAULT_BATCH_SIZE):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.batch_size = batch_size
        self._embeddings = OpenAIEmbeddings(
            model=model,
            api_key=api_key,
            base_url=self.base_url,
            timeout=timeout,
            chunk_size=batch_size,
            max_retries=MAX_RETRIES,
            # Send the text, not tiktoken token ids. The length safety this turns off
            # only matters above 8191 tokens, and core/chunking.py caps a chunk at 2200
            # characters — roughly 700 tokens of German, an order of magnitude below it.
            # In exchange the build does not fetch a BPE encoder from a third host while
            # embedding the knowledge base.
            check_embedding_ctx_length=False,
            # The same Zero Data Retention policy the chat client sends
            # (core/llm.py). It belongs here too: what reaches this endpoint at
            # runtime is the user's own question, embedded before retrieval, so
            # without it "the policy covers every production call" would be false.
            # Nested under model_kwargs["extra_body"] because OpenAIEmbeddings has
            # no extra_body field of its own, and model_kwargs={"provider": ...}
            # would hand `provider` straight to openai.Embeddings.create() as an
            # unknown argument and fail before any HTTP request.
            #
            # Measured on this endpoint, 2026-09-08: openai/text-embedding-3-small is
            # served by azure and openai; pinned to azure it returns 200 with and
            # without the flag, pinned to openai it returns 200 without it and 404
            # "No endpoints found matching your data policy" with it. So the flag
            # narrows routing here rather than decorating the request - and without
            # it a query could be embedded by the retaining endpoint.
            model_kwargs={"extra_body": {"provider": PROVIDER_POLICY}},
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts, batching requests and preserving input order."""
        try:
            return self._embeddings.embed_documents(texts)
        except openai.OpenAIError as e:
            # Connection and timeout failures subclass OpenAIError too, so this covers
            # transport without swallowing our own programming errors — those should
            # surface as INTERNAL_ERROR, not as "the provider is unavailable".
            raise LLMError(f"Embeddings request failed: {e}") from e

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
