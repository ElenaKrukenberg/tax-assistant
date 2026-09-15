"""The gap finder: rules find, models only justify.

The split is the point (AGENT_ARCHITECTURE §5): whether a candidate exists is
deterministic and tested here exhaustively; the model's only contribution is one
grounded sentence, and every way it can fail falls back to the fixed sentence
rather than to an invented citation.
"""

import asyncio

import pytest

from agents.gap_finder import (
    FALLBACK_RATIONALE,
    SIGNALS,
    find_candidates,
    kb_justifier,
    plain_justifier,
)
from domain.fields import ExpenseCategory


def run(coro):
    return asyncio.run(coro)


# --- the rules -------------------------------------------------------------------

def test_a_yes_signal_without_an_expense_is_a_candidate():
    known = {"profile.works_remotely": True}
    assert find_candidates(known) == [ExpenseCategory.homeoffice_tagespauschale]


def test_a_computable_expense_closes_its_candidate():
    known = {
        "profile.works_remotely": True,
        "homeoffice.homeoffice_days": 120,
        "homeoffice.other_workplace_available": True,
    }
    assert find_candidates(known) == []


def test_no_answered_with_no_and_unanswered_are_not_candidates():
    assert find_candidates({"profile.works_remotely": False}) == []
    assert find_candidates({}) == []


def test_every_gate_signal_maps_to_its_category():
    known = {signal: True for signal in SIGNALS}
    assert set(find_candidates(known)) == set(SIGNALS.values())


# --- the justifiers ---------------------------------------------------------------

class FakeRetriever:
    def __init__(self, chunks=None, raises=False):
        self._chunks = chunks or []
        self.raises = raises
        self.queries = []

    def search(self, query, **kwargs):
        self.queries.append(query)
        if self.raises:
            raise RuntimeError("chroma is down")

        class Result:
            chunks = self._chunks

        return Result()


class Chunk:
    def __init__(self, text, title):
        self.text = text
        self.metadata = {"title": title}


class FakeChat:
    def __init__(self, content, raises=False):
        self.content = content
        self.raises = raises

    async def chat_raw(self, messages, tools=None):
        if self.raises:
            raise RuntimeError("provider down")
        return {"role": "assistant", "content": self.content}, {}


def test_plain_justifier_gives_the_fixed_sentence_and_no_quote():
    out = run(plain_justifier([ExpenseCategory.umzugskosten], {}))
    assert out[0].rationale == FALLBACK_RATIONALE[ExpenseCategory.umzugskosten]
    assert out[0].citation_quote == ""


def test_kb_justifier_grounds_the_sentence_and_carries_the_quote():
    chunk = Chunk("Die Tagespauschale beträgt 6 Euro je Kalendertag...",
                  "Anleitung zur Anlage N 2025")
    justify = kb_justifier(FakeRetriever([chunk]),
                           FakeChat("Because you work from home, each day may be worth 6 EUR."))
    out = run(justify([ExpenseCategory.homeoffice_tagespauschale],
                      {"profile.works_remotely": True}))
    assert out[0].citation_title == "Anleitung zur Anlage N 2025"
    assert out[0].citation_quote.startswith("Die Tagespauschale")
    assert "work from home" in out[0].rationale


@pytest.mark.parametrize("chat, why", [
    (FakeChat("", raises=True), "the provider fails"),
    (FakeChat(""), "the model returns nothing"),
    (FakeChat("word"), "the model returns too little to be a sentence"),
    (FakeChat("x" * 500), "the model writes an essay"),
])
def test_an_unusable_model_falls_back_to_the_fixed_sentence(chat, why):
    chunk = Chunk("passage", "title")
    justify = kb_justifier(FakeRetriever([chunk]), chat)
    out = run(justify([ExpenseCategory.bewerbungskosten], {}))
    assert out[0].rationale == FALLBACK_RATIONALE[ExpenseCategory.bewerbungskosten], why
    assert out[0].citation_quote == "passage", "the quote is real even when the phrasing fails"


def test_a_dead_retriever_degrades_to_the_plain_rationale_without_a_quote():
    justify = kb_justifier(FakeRetriever(raises=True), FakeChat("irrelevant"))
    out = run(justify([ExpenseCategory.arbeitsmittel], {}))
    assert out[0].rationale == FALLBACK_RATIONALE[ExpenseCategory.arbeitsmittel]
    assert out[0].citation_quote == "", "no retrieval, no quote — a citation is never invented"
