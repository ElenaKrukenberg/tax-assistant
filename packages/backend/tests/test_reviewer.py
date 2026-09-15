"""The Reviewer without a provider: the tools, the guards, the degraded mode.

Whether a live model actually catches the planted defects is measured by
`eval/review_score.py` against the real provider; here the concern is that the
machinery around the model cannot lie — a recomputation that flatters the claim, a
verdict that crashes on malformed findings, or an outage that silently produces an
empty, reassuring review.
"""

import asyncio
import json

import pytest

from agents.reviewer import (
    ClaimedExpense,
    Finding,
    ReviewCase,
    _recompute,
    _validation,
    review,
)
from eval.seeded import PlantedDefect, build_seeded_cases

SEEDED = {c.id: c for c in build_seeded_cases()}
BROKEN_1 = SEEDED["broken-1-unbacked-and-contradictory"]
BROKEN_2 = SEEDED["broken-2-inflated-claim"]


def run(coro):
    return asyncio.run(coro)


class ScriptedChat:
    """Plays back a list of prepared responses, one per round."""

    def __init__(self, *responses, raises: bool = False):
        self.responses = list(responses)
        self.raises = raises
        self.transcripts: list[list[dict]] = []

    async def chat_raw(self, messages, tools=None):
        self.transcripts.append(list(messages))
        if self.raises:
            raise RuntimeError("provider is down")
        return self.responses.pop(0), {}


def tool_call(name: str, args: dict) -> dict:
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "function": {"name": name,
                                                     "arguments": json.dumps(args)}}]}


def verdict(*findings: dict) -> dict:
    return tool_call("finish_review", {"findings": list(findings)})


# --- the tools tell the truth -----------------------------------------------------

def test_recompute_exposes_the_inflated_claim():
    out = _recompute(BROKEN_2.case, "entfernungspauschale", 0)
    assert out["computable"]
    assert out["computed_eur"] == pytest.approx(3073.04)
    assert out["claimed_eur"] == 4100.00
    assert out["matches_claim"] is False


def test_recompute_confirms_an_honest_claim():
    out = _recompute(BROKEN_1.case, "entfernungspauschale", 0)
    assert out["matches_claim"] is True


def test_validation_sees_the_contradictory_days():
    out = _validation(BROKEN_1.case)
    assert not out["valid"]
    assert any(f["rule"] == "V02" for f in out["findings"])


def test_recompute_refuses_a_category_it_does_not_know():
    assert "error" in _recompute(BROKEN_1.case, "sonderausgaben", 0)


# --- the verdict is guarded --------------------------------------------------------

def test_a_clean_verdict_comes_back_as_given():
    chat = ScriptedChat(verdict(
        {"severity": "blocking", "title": "Days contradict",
         "reasoning": "268 > 220", "category": "homeoffice_tagespauschale"},
    ))
    result = run(review(BROKEN_1.case, chat))
    assert result.from_model
    assert [f.title for f in result.findings] == ["Days contradict"]
    assert result.findings[0].severity == "blocking"


def test_an_empty_verdict_is_legitimate():
    result = run(review(BROKEN_1.case, ScriptedChat(verdict())))
    assert result.from_model
    assert result.findings == []


def test_malformed_findings_are_dropped_not_fatal():
    chat = ScriptedChat(verdict(
        {"severity": "fatal", "title": "Wrong severity", "reasoning": "demoted"},
        {"severity": "warning", "title": "", "reasoning": "no title, dropped"},
        {"severity": "warning", "title": "No reasoning, dropped", "reasoning": ""},
        {"severity": "warning", "title": "Duplicate", "reasoning": "kept once"},
        {"severity": "warning", "title": "Duplicate", "reasoning": "kept once"},
        {"severity": "warning", "title": "Bad category", "reasoning": "category cleared",
         "category": "sonderausgaben"},
    ))
    result = run(review(BROKEN_1.case, chat))
    titles = [f.title for f in result.findings]
    assert titles == ["Wrong severity", "Duplicate", "Bad category"]
    assert result.findings[0].severity == "warning", "unknown severity demoted"
    assert result.findings[2].category is None, "unknown category cleared"


def test_tool_rounds_are_played_through_before_the_verdict():
    chat = ScriptedChat(
        tool_call("recompute_expense", {"category": "entfernungspauschale"}),
        tool_call("run_validation", {}),
        verdict({"severity": "blocking", "title": "Inflated",
                 "reasoning": "claimed 4100, computed 3073.04",
                 "category": "entfernungspauschale"}),
    )
    result = run(review(BROKEN_2.case, chat))
    assert result.rounds == 3
    assert result.findings[0].title == "Inflated"
    # The recomputation the model saw in round two must carry the honest numbers.
    tool_messages = [m for m in chat.transcripts[1] if m.get("role") == "tool"]
    payload = json.loads(tool_messages[-1]["content"])
    assert payload["matches_claim"] is False


def test_prose_without_a_verdict_is_reminded_then_rules_take_over():
    prose = {"role": "assistant", "content": "Looks broadly fine to me."}
    chat = ScriptedChat(*[dict(prose) for _ in range(8)])
    result = run(review(BROKEN_1.case, chat))
    assert result.from_model is False
    assert "no verdict" in result.note


# --- the degraded mode is labelled and still useful ---------------------------------

def test_an_outage_degrades_to_rules_and_says_so():
    result = run(review(BROKEN_1.case, ScriptedChat(raises=True)))
    assert result.from_model is False
    assert "provider failed" in result.note
    # The rules still catch what rules can catch: V02 and the unbacked laptop.
    assert any("V02" in f.title for f in result.findings)
    assert any(f.category == "arbeitsmittel" for f in result.findings)


def test_no_model_at_all_is_the_same_degraded_review():
    result = run(review(BROKEN_1.case, None))
    assert result.from_model is False
    assert result.findings, "rules-only still reports what it can"


# --- the seeded cases themselves -----------------------------------------------------

def test_the_seeded_defects_are_recognisable_from_findings():
    caught = PlantedDefect("x", "d", category="arbeitsmittel")
    assert caught.caught_by([Finding("warning", "t", "r", "arbeitsmittel")])
    assert not caught.caught_by([Finding("suggestion", "t", "r", "arbeitsmittel")]), \
        "a suggestion is not a catch"
    assert not caught.caught_by([Finding("warning", "t", "r", "umzugskosten")])

    worded = PlantedDefect("y", "d", must_mention=("day",))
    assert worded.caught_by([Finding("blocking", "Too many days", "268 > 220")])

    # The live run's lesson: a verdict may name the category in the title rather
    # than in the optional field, and that is still a catch.
    named_in_text = PlantedDefect("z", "d", category="entfernungspauschale")
    assert named_in_text.caught_by(
        [Finding("blocking", "Entfernungspauschale overclaimed", "4100 vs 3073")])


def test_the_degraded_review_alone_does_not_catch_everything():
    """The inflated claim needs recomputation, which needs the model to ask for it.

    This is the seeded case that justifies the Reviewer being an agent: if the
    rules-only pass caught it, the agent would be theatre.
    """
    result = run(review(BROKEN_2.case, None))
    defect = BROKEN_2.defects[0]
    assert not defect.caught_by(result.findings)


def test_a_summed_category_is_recomputed_from_the_key_the_fact_is_stored_under():
    """The lookup used the category's name; the fact is keyed by what it means.

    `moving.amount_eur` is where a move's cost lives (#61), and the recompute tool
    asked for `umzugskosten.amount_eur`. It found nothing, reported the expense as
    not recomputable, and that is a blocking finding - so a case with moving or
    application costs could not be approved, and going back to fix it changed a
    value the lookup still could not see.
    """
    from agents.reviewer import _recompute
    from domain.fields import ExpenseCategory

    for category, namespace in (("umzugskosten", "moving"),
                                ("bewerbungskosten", "applications"),
                                ("fortbildungskosten", "education")):
        case = ReviewCase(
            tax_year=2025,
            fields={f"{namespace}.amount_eur": 3000.0},
            expenses=(ClaimedExpense(category, 3000.0),),
        )

        result = _recompute(case, category, 0)

        assert result["computable"] is True, f"{category} was not found at {namespace}"
        assert result["computed_eur"] == 3000.0
        assert result["matches_claim"] is True
        assert ExpenseCategory(category)
