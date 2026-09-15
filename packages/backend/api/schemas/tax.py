from pydantic import BaseModel, Field
from typing import Optional


# Sixteen turns is eight exchanges. A clarification thread ("how many days?" → "150"
# → "and the distance?" → "74 km") eats three or four on its own, and follow-up
# questions come after it, so five exchanges ran out while the user was still on the
# same topic. The bound stays because the whole history is replayed on every request:
# at this size it adds roughly 5k prompt tokens, which is about two cents a question.
# The client sends the most recent turns and draws a divider where they stop.
MAX_HISTORY_TURNS = 16


class HistoryTurn(BaseModel):
    """One earlier turn of the conversation, as replayed by the client."""
    role: str = Field(..., pattern="^(user|assistant)$")
    text: str = Field(..., min_length=1, max_length=4000)


class TaxQuestionRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    # "auto" = detect the question language and answer in it
    language: str = Field(default="auto", pattern="^(auto|en|de|tr|ru)$")
    # How much of an answer the user asked for, from the Settings screen. Travels the
    # same path as `language`: a value here becomes a line of the generation prompt.
    # The default is what every earlier client sent implicitly, so an old client and
    # a user who never touched the control get the same answer they got before.
    depth: str = Field(default="balanced", pattern="^(concise|balanced|detailed)$")
    context: Optional[dict] = Field(default=None)
    # Earlier turns, oldest first, excluding `text`. The API is stateless: the model
    # only knows what this list carries, which is why a bare "74 km" was previously
    # unanswerable. Client-supplied, therefore untrusted — see services/tax_service.py.
    history: list[HistoryTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)


class SourceResponse(BaseModel):
    title: str
    ref: str = ""
    url: str = ""
    # advanced-RAG fields (additive, frontend uses title/ref/url)
    source_id: str = ""
    section: str = ""
    snippet: str = ""


class TraceStep(BaseModel):
    label: str
    detail: str


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # how many provider calls the answer took (analysis + generation + tool rounds)
    llm_calls: int = 0
    model: str = ""
    # None when the model is not in the price table — an unpriced request must not
    # be shown as a free one
    cost_usd: Optional[float] = None


class ToolResult(BaseModel):
    """Successful tool execution, structured for card rendering in the UI."""
    tool: str
    data: dict


class TaxAnswerResponse(BaseModel):
    summary: str
    explanation: list[str]
    sources: list[SourceResponse]
    trace: list[TraceStep] = Field(default_factory=list)
    # advanced-RAG fields (additive)
    intent: str = "knowledge"
    warnings: list[str] = Field(default_factory=list)
    usage: UsageInfo = Field(default_factory=UsageInfo)
    # structured tool outputs for UI cards (calculation/validation/checklist)
    tool_results: list[ToolResult] = Field(default_factory=list)
    # correlates this answer with its server-side log line; the frontend sends it
    # back with 👍/👎 so feedback can be tied to what actually happened
    request_id: str = ""


class FeedbackRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    rating: str = Field(..., pattern="^(up|down)$")
    comment: Optional[str] = Field(default=None, max_length=1000)


class FeedbackResponse(BaseModel):
    status: str = "recorded"


class ErrorResponse(BaseModel):
    detail: str
    error_code: str
