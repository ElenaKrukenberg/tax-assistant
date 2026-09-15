import json

import pytest

from api.schemas.tax import TaxQuestionRequest
from services.tax_service import TaxService
from services.tools import ALLOWED_TOOLS, TOOL_DEFINITIONS, execute_tool
from tests.conftest import FakeLLMClient, FakeRetriever

ANALYSIS_CALC = (
    '{"intent": "calculation", "search_query_de": "Entfernungspauschale berechnen",'
    ' "topics": ["entfernungspauschale"], "line": null, "form_id": null, "user_language": "en"}'
)


def tool_call_message(name, args, call_id="call_1"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }],
    }


# --- execute_tool dispatcher ---

def test_execute_calculation():
    out = json.loads(execute_tool("calculate_tax_amount", {
        "calculation_type": "entfernungspauschale",
        "params": {"commuting_days": 220, "distance_km": 25},
    }))
    assert out["amount_eur"] == 1738.0
    assert out["breakdown"]


def test_execute_validation_tool():
    out = json.loads(execute_tool("validate_tax_data", {"homeoffice_days": 250}))
    assert out["valid"] is False
    assert out["findings"][0]["rule_id"] == "V03"


def test_execute_checklist_tool():
    out = json.loads(execute_tool("build_document_checklist", {"categories": ["arbeitsmittel", "nonsense"]}))
    assert len(out["checklists"]) == 1
    assert out["skipped_unknown_categories"] == ["nonsense"]


def test_execute_tool_bad_params_returns_error_not_raise():
    out = json.loads(execute_tool("calculate_tax_amount", {
        "calculation_type": "entfernungspauschale",
        "params": {"commuting_days": 0, "distance_km": 25},   # ge=1 violated
    }))
    assert out["error"] == "Invalid parameters"
    assert any("commuting_days" in p for p in out["problems"])


def test_execute_unknown_tool():
    """A name that is not on the allowlist is refused before any dispatch."""
    out = json.loads(execute_tool("hack_the_finanzamt", {}))
    assert "not allowed" in out["error"]


def test_allowlist_is_derived_from_the_definitions():
    """Nothing can be dispatchable without also being offered to the model."""
    assert ALLOWED_TOOLS == {t["function"]["name"] for t in TOOL_DEFINITIONS}


def test_oversized_arguments_are_refused_unparsed():
    out = json.loads(execute_tool("validate_tax_data", '{"x": "' + "A" * 5000 + '"}'))
    assert out["error"] == "Arguments too large"


def test_non_object_arguments_are_refused():
    out = json.loads(execute_tool("validate_tax_data", "[1, 2, 3]"))
    assert "JSON object" in out["error"]


def test_tool_definitions_shape():
    names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
    assert names == ["calculate_tax_amount", "validate_tax_data", "build_document_checklist"]
    assert all(t["function"]["parameters"] for t in TOOL_DEFINITIONS)


# --- service tool loop ---

@pytest.mark.asyncio
async def test_tool_loop_executes_and_answers():
    llm = FakeLLMClient(replies=[
        ANALYSIS_CALC,
        tool_call_message("calculate_tax_amount", {
            "calculation_type": "entfernungspauschale",
            "params": {"commuting_days": 220, "distance_km": 25},
        }),
        "Your commuting allowance for 2025 is 1,738.00 EUR [lsth-2025-par-9-werbungskosten].",
    ])
    service = TaxService(llm, FakeRetriever())
    resp = await service.answer_question(TaxQuestionRequest(text="220 days, 25 km — how much?", language="en"))

    assert "1,738.00" in resp.summary
    tool_steps = [t for t in resp.trace if t.label.startswith("Tool:")]
    assert len(tool_steps) == 1
    assert "1738.0 EUR" in tool_steps[0].detail
    # the tool result was fed back to the model as a role=tool message
    final_call_messages = llm.calls[-1]["messages"]
    assert any(m.get("role") == "tool" for m in final_call_messages)
    # tools were bound on generation calls
    assert llm.calls[1]["tools"] is not None
    # no "tools unavailable" warning anymore
    assert not any("not available" in w for w in resp.warnings)
    # structured result exposed for UI cards
    assert resp.tool_results[0].tool == "calculate_tax_amount"
    assert resp.tool_results[0].data["amount_eur"] == 1738.0


@pytest.mark.asyncio
async def test_tool_loop_error_roundtrip():
    """Model sends bad args, receives the error, retries correctly."""
    llm = FakeLLMClient(replies=[
        ANALYSIS_CALC,
        tool_call_message("calculate_tax_amount", {
            "calculation_type": "entfernungspauschale",
            "params": {"distance_km": 25},               # commuting_days missing
        }, call_id="c1"),
        tool_call_message("calculate_tax_amount", {
            "calculation_type": "entfernungspauschale",
            "params": {"commuting_days": 220, "distance_km": 25},
        }, call_id="c2"),
        "After correction: 1,738.00 EUR.",
    ])
    service = TaxService(llm, FakeRetriever())
    resp = await service.answer_question(TaxQuestionRequest(text="calc", language="en"))

    tool_steps = [t for t in resp.trace if t.label.startswith("Tool:")]
    assert len(tool_steps) == 2
    assert "error" in tool_steps[0].detail
    assert "1738.0 EUR" in tool_steps[1].detail
    assert "1,738.00" in resp.summary


@pytest.mark.asyncio
async def test_tool_loop_round_limit():
    """A model that never stops calling tools hits the round cap gracefully."""
    endless = tool_call_message("validate_tax_data", {"homeoffice_days": 10})
    llm = FakeLLMClient(replies=[ANALYSIS_CALC, endless, endless, endless, endless, endless])
    service = TaxService(llm, FakeRetriever())
    resp = await service.answer_question(TaxQuestionRequest(text="loop", language="en"))
    assert any("did not converge" in w for w in resp.warnings)
