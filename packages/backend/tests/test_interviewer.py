"""The Interviewer, without a provider.

Every test here uses a fake chat: the ordinary suite must stay fast and offline, and
what needs testing is not the model's taste but the guards around it. A model that
names a question it was not offered, returns nothing, returns broken JSON or fails
outright must all leave the interview able to continue — otherwise a provider hiccup
looks like the agent's own behaviour in the measurement.
"""

import asyncio
import json

import pytest

from agents.interviewer import (
    MAX_ROUNDS,
    Ask,
    Conclude,
    decide,
    decide_deterministically,
)
from domain.questions import CATALOGUE


class FakeChat:
    """Returns one prepared tool call and remembers what it was shown."""

    def __init__(self, name: str = "ask_question", args: dict | None = None,
                 raises: bool = False, no_calls: bool = False,
                 raw_arguments: str | None = None):
        self.name = name
        self.args = args or {}
        self.raises = raises
        self.no_calls = no_calls
        self.raw_arguments = raw_arguments
        self.calls = 0
        self.prompt = ""

    async def chat_raw(self, messages, tools=None):
        self.calls += 1
        self.prompt = messages[-1]["content"]
        self.tools = tools
        if self.raises:
            raise RuntimeError("provider is down")
        if self.no_calls:
            return {"role": "assistant", "content": "I would ask about the commute."}, {}
        arguments = (self.raw_arguments if self.raw_arguments is not None
                     else json.dumps(self.args))
        return (
            {"role": "assistant", "content": "",
             "tool_calls": [{"function": {"name": self.name, "arguments": arguments}}]},
            {},
        )


def run(coro):
    return asyncio.run(coro)


ANSWERED_PLAIN = {
    "profile.employed_months": 12,
    "profile.employer_count": 1,
    "profile.working_days_total": 224,
    "profile.works_remotely": False,
    "profile.has_minijob": False,
    "profile.benefit_type": "none",
    "profile.bought_work_equipment": False,
    "profile.claims_phone_internet": False,
    "profile.moved_for_work": False,
    "profile.searched_for_job": False,
    "profile.further_education": False,
    "commute.commuting_days": 210,
    "commute.distance_km": 4,
    "commute.own_car": True,
}


# One gate short of finished: the commute is computed at 252.00 EUR, and exactly one
# candidate is still open. A fully answered state would make the model never be called
# at all, which quietly turns any assertion about the prompt into a test of nothing.
MOSTLY_ANSWERED = {k: v for k, v in ANSWERED_PLAIN.items() if k != "profile.further_education"}

# Every gate answered, one non-gate candidate (the car question) still open: the one
# state in which the model is called AND allowed to propose ending the interview.
GATES_DONE = {k: v for k, v in ANSWERED_PLAIN.items()
              if k != "commute.own_car"}


# --- without a model ------------------------------------------------------------

def test_with_no_provider_it_is_the_filter():
    decision = run(decide({}, frozenset()))
    assert isinstance(decision, Ask)
    assert decision.question.id == "profile.employed_months"
    assert decision.from_model is False


def test_it_concludes_once_nothing_is_left_to_ask():
    decision = run(decide(ANSWERED_PLAIN, frozenset()))
    assert isinstance(decision, Conclude)


def test_a_finished_case_does_not_cost_a_provider_call():
    """No candidates, no call. The cheapest correct behaviour, and easy to lose."""
    chat = FakeChat()
    decision = run(decide(ANSWERED_PLAIN, frozenset(), chat))
    assert isinstance(decision, Conclude)
    assert chat.calls == 0


# --- the model's choice ---------------------------------------------------------

def test_a_candidate_the_model_picks_is_asked_with_its_rationale():
    chat = FakeChat(args={"question_id": "profile.further_education",
                          "rationale": "Training costs are often forgotten."})
    decision = run(decide({}, frozenset(), chat))
    assert isinstance(decision, Ask)
    assert decision.question.id == "profile.further_education"
    assert decision.rationale == "Training costs are often forgotten."
    assert decision.from_model is True


def test_the_model_may_propose_ending_once_every_gate_is_answered():
    chat = FakeChat(name="conclude_interview",
                    args={"reason": "Itemising cannot beat the flat allowance here."})
    decision = run(decide(GATES_DONE, frozenset(), chat))
    assert isinstance(decision, Conclude)
    assert "flat allowance" in decision.reason
    assert decision.from_model is True


def test_concluding_without_a_reason_still_ends_the_interview():
    chat = FakeChat(name="conclude_interview", args={})
    decision = run(decide(GATES_DONE, frozenset(), chat))
    assert isinstance(decision, Conclude)
    assert decision.reason


def test_a_conclusion_with_a_gate_unanswered_is_vetoed_with_that_gate():
    """The p08 failure, made structurally impossible.

    The model ended the first live run at 743 EUR with the education gate unasked,
    losing an 1,800 EUR category. Now a premature conclusion is answered with the
    missing gate question — code, not prompt advice, is what enforces it.
    """
    chat = FakeChat(name="conclude_interview", args={"reason": "nothing more here"})
    decision = run(decide({}, frozenset(), chat))
    assert isinstance(decision, Ask)
    assert decision.forced_gate is True
    assert decision.from_model is False
    assert decision.question.key == "profile.moved_for_work", "the first applicable gate"


def test_a_gate_answered_with_dont_know_counts_as_addressed():
    """Asked and unanswered is not the same as never asked.

    A user who cannot say whether they moved has been asked; forcing the question
    again would be the loop-forever bug wearing the gate guard as a disguise.
    """
    asked = frozenset({"profile.moved_for_work", "profile.searched_for_job",
                       "profile.further_education"})
    # The other three gates need employed_months first, so they do not apply yet.
    chat = FakeChat(name="conclude_interview", args={"reason": "done"})
    decision = run(decide({}, asked, chat))
    assert isinstance(decision, Conclude)


# --- the guards -----------------------------------------------------------------

@pytest.mark.parametrize("chat, why", [
    (FakeChat(args={"question_id": "commute.does_not_exist", "rationale": "x"}),
     "a question that does not exist"),
    (FakeChat(args={"question_id": "homeoffice.homeoffice_days", "rationale": "x"}),
     "a question this profile was not offered"),
    (FakeChat(raw_arguments="{not json"), "broken arguments"),
    (FakeChat(name="run_gap_finder", args={}), "a tool that was not offered"),
    (FakeChat(no_calls=True), "no tool call at all"),
    (FakeChat(raises=True), "a provider failure"),
])
def test_anything_unusable_falls_back_to_the_filter(chat, why):
    decision = run(decide({}, frozenset(), chat))
    assert isinstance(decision, Ask), why
    assert decision.from_model is False, why
    assert decision.question.id == "profile.employed_months", why


def test_a_question_already_asked_is_never_offered_again():
    """The loop-forever bug, guarded at the source.

    An unanswerable question stays relevant, so without this the model would be shown
    it again and again — three of the ten evaluation profiles used to loop on exactly
    this.
    """
    chat = FakeChat(name="conclude_interview", args={"reason": "done"})
    run(decide({}, frozenset({"profile.employed_months"}), chat))
    assert "profile.employed_months" not in chat.prompt


# --- what the model is shown ----------------------------------------------------

def test_the_prompt_carries_the_figure_the_decision_turns_on():
    """Without the total and the allowance, "should we stop?" is unanswerable."""
    chat = FakeChat(name="conclude_interview", args={"reason": "done"})
    run(decide(MOSTLY_ANSWERED, frozenset(), chat))

    assert chat.prompt, "the model was never called, so this proves nothing"
    assert "252.00 EUR" in chat.prompt, "the total so far"
    assert "1230" in chat.prompt, "the Pauschbetrag"
    assert "short of being worth itemising" in chat.prompt


def test_the_catalogue_is_not_pasted_into_the_prompt():
    """Only the filtered candidates go in (ADR 0001).

    With the whole catalogue in front of it the model asks for what the documents
    already answered, which is the metric the project measures.
    """
    chat = FakeChat(name="conclude_interview", args={"reason": "done"})
    run(decide(MOSTLY_ANSWERED, frozenset(), chat))

    assert chat.prompt, "the model was never called, so this proves nothing"
    # By wording, not by id: since the key rename an id is also the key a known value
    # is printed under ("Known values: - profile.employed_months = 12"), so counting
    # ids would count what the case already knows as though it were an offer. What
    # must not leak is the question itself.
    offered = [q.id for q in CATALOGUE if q.text["en"] in chat.prompt]
    assert len(offered) < 5, f"too much of the catalogue reached the prompt: {offered}"


def test_only_two_tools_are_offered():
    chat = FakeChat(name="conclude_interview", args={"reason": "done"})
    run(decide({}, frozenset(), chat))
    names = {t["function"]["name"] for t in chat.tools}
    assert names == {"ask_question", "conclude_interview"}


def test_the_round_limit_leaves_room_for_the_longest_legitimate_interview():
    """The busiest profile needs 26 questions; a limit of 20 — its first value — cut
    that interview short and scored the truncation as the agent saving questions."""
    assert MAX_ROUNDS == 40


def test_the_deterministic_arm_and_the_fallback_are_the_same_function():
    """So that "the agent did no better than the filter" is a fair statement."""
    a = decide_deterministically({}, frozenset())
    b = run(decide({}, frozenset(), FakeChat(raises=True)))
    assert isinstance(a, Ask) and isinstance(b, Ask)
    assert a.question.id == b.question.id
