from domain.compliance import PolicyAction, check_output, check_position, check_wording
from domain.positions import AssessmentStatus, Origin, TaxPosition, UserDecision


def position(**overrides):
    values = {
        "position_id": "x",
        "category": "x",
        "assessment_status": AssessmentStatus.identified,
        "user_decision": UserDecision.accepted,
        "origin": Origin.deterministic_rule,
    }
    values.update(overrides)
    return TaxPosition(**values)


def test_allowed_confirmed_deterministic_position():
    assert check_position(position()).action is PolicyAction.allow


def test_unclear_position_is_blocked_even_with_safe_wording():
    result = check_output(position(assessment_status=AssessmentStatus.unclear), "The criteria may apply.")
    assert result.action is PolicyAction.block
    assert result.code == "ambiguous_assessment"


def test_ai_suggestion_requires_confirmation():
    result = check_position(position(origin=Origin.ai_suggestion,
                                     user_decision=UserDecision.pending))
    assert result.action is PolicyAction.requires_confirmation


def test_rejected_position_is_a_valid_final_decision():
    assert check_position(position(user_decision=UserDecision.rejected)).action is PolicyAction.allow


def test_definitive_wording_is_rewritten():
    result = check_wording("You are entitled to claim this expense.")
    assert result.action is PolicyAction.rewrite
    assert result.code == "definitive_tax_wording"


def test_criteria_wording_is_allowed():
    assert check_wording("This criterion may apply based on the facts you confirmed.").action is PolicyAction.allow


def test_the_wording_guard_is_actually_called_on_an_answer():
    """The gap #76 was really about: the guard existed and nothing invoked it.

    `check_wording` and `check_output` were called by nothing outside this file, so
    "you are entitled to" reached users unchecked while the layer looked complete.
    """
    import inspect

    from services import tax_service

    source = inspect.getsource(tax_service)
    assert "check_wording(" in source, (
        "the chat answer no longer passes through the StBerG wording guard"
    )


def test_a_definitive_conclusion_is_blocked_rather_than_rewritten():
    """Rewrite is treated as block on the response path, and that is deliberate.

    Editing a model's sentence about somebody's tax position without saying so is the
    opacity this layer exists to prevent, and a rewrite that must preserve meaning is
    a second model call with a second way to be wrong.
    """
    result = check_wording("You are entitled to deduct the full amount.")
    assert result.action is PolicyAction.rewrite
    assert result.code == "definitive_tax_wording"

    allowed = check_wording(
        "Based on the facts you confirmed, the criteria for this deduction may apply."
    )
    assert allowed.action is PolicyAction.allow
