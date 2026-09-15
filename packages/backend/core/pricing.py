"""Token pricing: turns provider token counts into a USD cost estimate.

Prices are USD per 1M tokens, as billed by OpenRouter (which passes the
provider's own rates through). They are a snapshot, not a live feed — verify
against https://openrouter.ai/models before quoting them to anyone. An unknown
model yields None rather than 0.0, so the UI can say "unknown" instead of
showing a request as free.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    prompt: float       # USD per 1M input tokens
    completion: float   # USD per 1M output tokens


# Checked 2026-07-29.
PRICES = {
    # chat models
    "anthropic/claude-haiku-4.5": ModelPrice(prompt=1.00, completion=5.00),
    "anthropic/claude-sonnet-5": ModelPrice(prompt=3.00, completion=15.00),
    "anthropic/claude-opus-5": ModelPrice(prompt=5.00, completion=25.00),
    # The Reviewer's model (REVIEWER_MODEL): a different vendor from the
    # Interviewer on purpose. Price as listed by OpenRouter on 2026-08-22.
    "openai/gpt-5.4": ModelPrice(prompt=2.50, completion=15.00),
    # Embeddings: priced per input token only, nothing is generated. Not part of
    # the per-request total reported to the UI — embedding one question costs
    # around $0.0000002, which is below the rounding below, and the ingestion run
    # that embedded the whole knowledge base is a one-off, not a request cost.
    "openai/text-embedding-3-small": ModelPrice(prompt=0.02, completion=0.0),
    # Document intake (VISION_MODEL and its fallback), as listed by OpenRouter on
    # 2026-09-08. Gemini prices an image at the prompt rate and its own reasoning at
    # the completion rate, so a page read at `effort: "low"` lands near the 0.31
    # cents a pass that issue #65 measured - the sweep is the authority on what a
    # document actually costs, this table on what one call costs.
    "google/gemini-3.7-flash": ModelPrice(prompt=0.75, completion=3.75),
    "x-ai/grok-4.5": ModelPrice(prompt=2.00, completion=6.00),
}


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Cost of one call, or None if the model is not in the price table."""
    price = PRICES.get(model)
    if price is None:
        return None
    cost = (prompt_tokens * price.prompt + completion_tokens * price.completion) / 1_000_000
    # 6 decimals: a single question costs fractions of a cent, and rounding to
    # cents would report every request as $0.00.
    return round(cost, 6)
