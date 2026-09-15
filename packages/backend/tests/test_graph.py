"""The graph: pauses, resumes, routing. Offline throughout.

The intelligence in the nodes is tested elsewhere (test_interviewer, test_reviewer);
here the concern is the machinery the harness could not exercise — that a pause
carries a typed payload, that a resumed run continues instead of restarting, that a
declined proposal goes back to questions, and that the paused state survives being
picked up by a fresh graph instance, which is the sprint's "case survives a new
session" criterion in miniature.
"""

import asyncio
import uuid

import pytest

from tests import dbguard
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agents.graph import MAX_REVISION_ROUNDS, build_graph
from eval.baseline import load_profiles

P01 = next(p for p in load_profiles() if p.id.startswith("p01"))
P03 = next(p for p in load_profiles() if p.id.startswith("p03"))


def thread() -> dict:
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def pause(result) -> dict:
    """The interrupt payload of a paused run."""
    assert "__interrupt__" in result, f"expected a pause, got: {list(result)}"
    return result["__interrupt__"][0].value


async def drive_interview(graph, config, profile, max_steps=60):
    """Answer questions from the profile until the graph proposes to stop."""
    result = await graph.ainvoke(
        {"tax_year": 2025, "known": {}, "asked": []}, config)
    for _ in range(max_steps):
        payload = pause(result)
        if payload["type"] != "question":
            return result, payload
        value = profile.answers.get(payload["field"])
        result = await graph.ainvoke(Command(resume={"value": value}), config)
    raise AssertionError("the interview never proposed to stop")


def run(coro):
    return asyncio.run(coro)


# --- pausing and resuming ----------------------------------------------------------

def test_the_first_pause_is_a_typed_question():
    graph = build_graph()
    result = run(graph.ainvoke({"tax_year": 2025, "known": {}, "asked": []}, thread()))
    payload = pause(result)
    assert payload["type"] == "question"
    assert payload["question_id"] == "profile.employed_months"
    assert payload["answer_type"] == "integer"
    assert set(payload["text"]) == {"en", "de", "ru"}


def test_an_answer_lands_in_the_state_and_the_next_question_follows():
    graph = build_graph()
    config = thread()
    run(graph.ainvoke({"tax_year": 2025, "known": {}, "asked": []}, config))
    result = run(graph.ainvoke(Command(resume={"value": 12}), config))

    state = graph.get_state(config).values
    assert state["known"]["profile.employed_months"] == 12
    assert state["asked"] == ["profile.employed_months"]
    assert pause(result)["type"] == "question"


def test_dont_know_is_recorded_as_asked_but_no_value_lands():
    graph = build_graph()
    config = thread()
    run(graph.ainvoke({"tax_year": 2025, "known": {}, "asked": []}, config))
    run(graph.ainvoke(Command(resume={"value": None}), config))

    state = graph.get_state(config).values
    assert "profile.employed_months" not in state["known"]
    assert "profile.employed_months" in state["asked"]


def test_a_paused_run_survives_a_new_graph_instance():
    """The acceptance criterion in miniature: the pause outlives the process.

    Two separately built graphs share nothing but the checkpointer and the thread
    id — the second one picks the interview up mid-question, which is exactly what
    "the case survives a new session" means once the checkpointer is Postgres.
    """
    saver = InMemorySaver()
    config = thread()

    first = build_graph(checkpointer=saver)
    run(first.ainvoke({"tax_year": 2025, "known": {}, "asked": []}, config))
    run(first.ainvoke(Command(resume={"value": 12}), config))

    second = build_graph(checkpointer=saver)
    result = run(second.ainvoke(Command(resume={"value": 1}), config))

    state = second.get_state(config).values
    assert state["known"]["profile.employed_months"] == 12, "answered before the 'restart'"
    assert state["known"]["profile.employer_count"] == 1, "answered after it"
    assert pause(result)["type"] == "question"


# --- the whole path ------------------------------------------------------------------

def test_the_full_path_of_a_plain_case_ends_finalized():
    graph = build_graph()
    config = thread()

    result, payload = run(drive_interview(graph, config, P03))
    assert payload["type"] == "confirm_stop"

    result = run(graph.ainvoke(Command(resume=True), config))
    payload = pause(result)
    # p03's rules-only review finds nothing blocking (V20 is info), so the next
    # pause is the final gate, expenses attached.
    assert payload["type"] == "final_approval"
    assert any(e["category"] == "entfernungspauschale" for e in payload["expenses"])
    assert payload["expenses"][0]["trace"], "an expense travels with its trace"

    decisions = {
        position["position_id"]: "accepted"
        for position in payload["tax_positions"]
        if position["assessment_status"] == "identified"
    }
    result = run(graph.ainvoke(Command(resume={"approve": True, "decisions": decisions}), config))
    assert "__interrupt__" not in result
    assert graph.get_state(config).values["status"] == "finalized"


def test_a_declined_stop_goes_back_to_questions():
    graph = build_graph()
    config = thread()
    result, payload = run(drive_interview(graph, config, P03))
    assert payload["type"] == "confirm_stop"

    result = run(graph.ainvoke(Command(resume=False), config))
    state = graph.get_state(config).values
    assert state["status"] == "gathering"
    # Nothing is left to ask on a fully answered case, so the very next decision
    # proposes stopping again — but it went through decide_next to get there.
    assert pause(result)["type"] == "confirm_stop"


def test_a_blocking_finding_pauses_for_resolution_and_dismiss_reaches_the_gate():
    graph = build_graph()
    config = thread()
    # p01 whose home-office days contradict the total: rules-only review raises
    # V02 as an error, which maps to blocking.
    profile = P01
    result = run(graph.ainvoke({"tax_year": 2025, "known": {}, "asked": []}, config))
    for _ in range(60):
        payload = pause(result)
        if payload["type"] != "question":
            break
        value = profile.answers.get(payload["field"])
        if payload["field"] == "homeoffice.homeoffice_days":
            value = 220  # 220 + 88 commuting > 220 total: the planted contradiction
        result = run(graph.ainvoke(Command(resume={"value": value}), config))

    assert payload["type"] == "confirm_stop"
    result = run(graph.ainvoke(Command(resume=True), config))
    payload = pause(result)
    assert payload["type"] == "findings"
    assert any(f["severity"] == "blocking" for f in payload["findings"])

    result = run(graph.ainvoke(Command(resume={"action": "dismiss"}), config))
    assert pause(result)["type"] == "final_approval"
    assert graph.get_state(config).values["status"] == "needs_user_input"


def test_the_revision_loop_is_capped():
    """Past the cap, the human decides over the case as it stands.

    A revision sends the flow back to the interview, and a contradiction nobody
    fixes survives every pass — so without the cap the review and the revision
    would ping-pong for as long as the finding persists. The user here always
    chooses "revise" and never fixes anything, which is exactly the pathological
    loop the cap exists for.
    """
    graph = build_graph()
    config = thread()
    result = run(graph.ainvoke({"tax_year": 2025, "known": {}, "asked": []}, config))

    revisions = 0
    payload = pause(result)
    for _ in range(40):
        if payload["type"] == "question":
            value = P01.answers.get(payload["field"])
            if payload["field"] == "homeoffice.homeoffice_days":
                value = 220  # the contradiction that keeps the finding alive
            result = run(graph.ainvoke(Command(resume={"value": value}), config))
        elif payload["type"] == "confirm_stop":
            result = run(graph.ainvoke(Command(resume=True), config))
        elif payload["type"] == "findings":
            revisions += 1
            result = run(graph.ainvoke(Command(resume={"action": "revise"}), config))
        else:
            break
        payload = pause(result)

    assert payload["type"] == "final_approval", "the cap hands the case to the human"
    assert revisions == MAX_REVISION_ROUNDS + 1,         "revise is offered exactly until the cap, then the gate takes over"


def test_declining_the_final_approval_reopens_the_interview():
    graph = build_graph()
    config = thread()
    result, _ = run(drive_interview(graph, config, P03))
    result = run(graph.ainvoke(Command(resume=True), config))       # confirm stop
    assert pause(result)["type"] == "final_approval"

    result = run(graph.ainvoke(Command(resume=False), config))      # decline report
    state = graph.get_state(config).values
    assert state["status"] != "finalized"
    assert pause(result)["type"] in ("question", "confirm_stop")


@pytest.mark.integration
def test_a_pause_survives_on_the_real_postgres_checkpointer():
    """The sprint's acceptance criterion, for real: the pause outlives the process,
    on the same Supabase Postgres the tables live in."""
    from core.config import get_settings

    if not get_settings().database_url:
        dbguard.require_test_database()

    from agents.graph import postgres_checkpointer

    config = thread()

    async def scenario():
        async with postgres_checkpointer() as saver:
            await saver.setup()
            first = build_graph(checkpointer=saver)
            await first.ainvoke({"tax_year": 2025, "known": {}, "asked": []}, config)
            await first.ainvoke(Command(resume={"value": 12}), config)

        # A separate connection and a separate graph: nothing shared but the database.
        async with postgres_checkpointer() as saver:
            second = build_graph(checkpointer=saver)
            result = await second.ainvoke(Command(resume={"value": 1}), config)
            state = (await second.aget_state(config)).values
            return result, state

    result, state = run(scenario())
    assert state["known"]["profile.employed_months"] == 12
    assert state["known"]["profile.employer_count"] == 1
    assert pause(result)["type"] == "question"


def test_the_panel_and_the_graph_agree_on_the_nodes():
    """The developer panel draws a hand-written diagram of this graph.

    Its node list (GRAPH_NODE_IDS in agent-graph-panel.tsx) must equal the
    compiled graph's nodes — this is the backend half of that contract, and the
    frontend half asserts the diagram mentions every listed node. Rename or add
    a node and both suites go red until the diagram follows.
    """
    compiled = set(build_graph().get_graph().nodes) - {"__start__", "__end__"}
    panel = {
        "decide_next", "ask_user", "confirm_stop", "build_expenses",
        "review", "resolve_findings", "final_approval",
    }
    # "finalized" is a terminal state the panel draws as a node; the graph
    # reaches it through END rather than a node of its own.
    assert compiled == panel


def test_a_premature_stop_proposal_carries_the_gaps_it_would_leave():
    """The product story's moment: the user sees the found gap and decides on it.

    The model concludes with every gate answered but the home-office values still
    missing; the stop card must then carry the home-office candidate with its
    rationale, so the user decides over a named entitlement, not a hunch.
    """
    import json as _json

    class ConcludingChat:
        async def chat_raw(self, messages, tools=None):
            return ({"role": "assistant", "content": "",
                     "tool_calls": [{"function": {
                         "name": "conclude_interview",
                         "arguments": _json.dumps({"reason": "unlikely to reach the allowance"}),
                     }}]}, {})

    graph = build_graph(interviewer_chat=ConcludingChat())
    config = thread()
    # Every gate answered, works_remotely True, but no home-office values yet.
    known = {
        "profile.employed_months": 12, "profile.employer_count": 1, "profile.working_days_total": 220,
        "profile.works_remotely": True, "profile.has_minijob": False, "profile.benefit_type": "none",
        "profile.bought_work_equipment": False, "profile.claims_phone_internet": False,
        "profile.moved_for_work": False, "profile.searched_for_job": False, "profile.further_education": False,
        "commute.commuting_days": 88,
        "commute.distance_km": 18,
        "commute.own_car": True,
    }
    result = run(graph.ainvoke({"tax_year": 2025, "known": known, "asked": []}, config))
    payload = pause(result)
    assert payload["type"] == "confirm_stop"
    gaps = payload["gaps"]
    assert [g["category"] for g in gaps] == ["homeoffice_tagespauschale"]
    assert gaps[0]["rationale"], "a named entitlement, not a bare category"


# --- going back ---------------------------------------------------------------------
#
# The mechanics the /interview/back endpoint is built on. The endpoint itself needs a
# database and lives in the integration suite; what can be tested offline is the part
# that would actually break — that the history holds one snapshot per question, and
# that replaying from one of them re-asks it with the later answers gone.

def question_snapshots(graph, config):
    """Every checkpoint that was paused on a question, newest first."""
    out = []
    for snapshot in graph.get_state_history(config):
        for task in snapshot.tasks or ():
            for intr in task.interrupts or ():
                if intr.value.get("type") == "question":
                    out.append((intr.value["question_id"], snapshot))
    return out


def answer_three(graph, config):
    result = run(graph.ainvoke({"tax_year": 2025, "known": {}, "asked": []}, config))
    for value in (12, 1, 220):
        result = run(graph.ainvoke(Command(resume={"value": value}), config))
    return result


def test_the_history_holds_one_checkpoint_per_question_asked():
    graph = build_graph(checkpointer=InMemorySaver())
    config = thread()
    answer_three(graph, config)

    asked = [qid for qid, _ in question_snapshots(graph, config)]
    assert asked == [
        "profile.works_remotely",        # on screen now
        "profile.working_days_total",    # the one going back would return to
        "profile.employer_count",
        "profile.employed_months",
    ]


def test_replaying_an_earlier_checkpoint_asks_that_question_again():
    graph = build_graph(checkpointer=InMemorySaver())
    config = thread()
    answer_three(graph, config)

    _, previous = question_snapshots(graph, config)[1]
    result = run(graph.ainvoke(None, previous.config))

    assert pause(result)["question_id"] == "profile.working_days_total"
    values = graph.get_state(config).values
    assert "profile.working_days_total" not in values["known"]
    assert values["asked"] == ["profile.employed_months", "profile.employer_count"]


def test_a_different_answer_after_going_back_is_the_one_that_counts():
    graph = build_graph(checkpointer=InMemorySaver())
    config = thread()
    answer_three(graph, config)
    _, previous = question_snapshots(graph, config)[1]
    run(graph.ainvoke(None, previous.config))

    run(graph.ainvoke(Command(resume={"value": 300}), config))
    values = graph.get_state(config).values
    assert values["known"]["profile.working_days_total"] == 300
    assert values["known"]["profile.employed_months"] == 12  # earlier answers untouched


def test_there_is_nothing_to_go_back_to_on_the_first_question():
    graph = build_graph(checkpointer=InMemorySaver())
    config = thread()
    run(graph.ainvoke({"tax_year": 2025, "known": {}, "asked": []}, config))

    assert len(question_snapshots(graph, config)) == 1
