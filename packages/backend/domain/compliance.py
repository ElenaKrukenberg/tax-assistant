"""Deterministic policy guard for tax-position actions and wording."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from domain.positions import AssessmentStatus, Origin, TaxPosition, UserDecision


class PolicyAction(str, Enum):
    allow = "allow"
    rewrite = "rewrite"
    block = "block"
    requires_confirmation = "requires_confirmation"


@dataclass(frozen=True)
class PolicyResult:
    action: PolicyAction
    reason: str
    code: str


_DEFINITIVE_PATTERNS = (
    re.compile(r"\byou are entitled to\b", re.I),
    re.compile(r"\byou should claim\b", re.I),
    re.compile(r"\bthis (?:expense|item) is deductible\b", re.I),
    re.compile(r"\bthe finanzamt must accept\b", re.I),
)


def check_position(position: TaxPosition) -> PolicyResult:
    """Check the attempted action, not just the text describing it."""
    if position.user_decision is UserDecision.rejected:
        return PolicyResult(PolicyAction.allow, "user explicitly rejected the position",
                            "position_rejected")
    if position.assessment_status is AssessmentStatus.unclear:
        return PolicyResult(PolicyAction.block, "ambiguous assessment needs facts or rules", "ambiguous_assessment")
    if position.origin is Origin.ai_suggestion and position.user_decision is not UserDecision.accepted:
        return PolicyResult(PolicyAction.requires_confirmation,
                            "AI suggestion cannot enter the draft without user confirmation",
                            "confirmation_required")
    if position.user_decision is UserDecision.needs_reconfirmation:
        return PolicyResult(PolicyAction.requires_confirmation,
                            "dependent facts changed since confirmation", "stale_confirmation")
    if position.assessment_status is AssessmentStatus.criteria_not_met:
        return PolicyResult(PolicyAction.allow, "assessment criteria are not met; no draft action", "criteria_not_met")
    if position.user_decision is UserDecision.accepted:
        return PolicyResult(PolicyAction.allow, "identified position is explicitly confirmed",
                            "confirmed_position")
    return PolicyResult(PolicyAction.requires_confirmation,
                        "material tax position needs an explicit user decision",
                        "confirmation_required")


def check_wording(text: str) -> PolicyResult:
    """Reject definitive individualized conclusions; criteria wording is allowed."""
    if any(pattern.search(text) for pattern in _DEFINITIVE_PATTERNS):
        return PolicyResult(PolicyAction.rewrite,
                            "definitive individualized tax conclusion", "definitive_tax_wording")
    return PolicyResult(PolicyAction.allow, "wording contains no prohibited conclusion", "wording_allowed")


def check_output(position: TaxPosition, text: str) -> PolicyResult:
    """The action check is authoritative; wording cannot upgrade an unsafe action."""
    action = check_position(position)
    if action.action in (PolicyAction.block, PolicyAction.requires_confirmation):
        return action
    wording = check_wording(text)
    return wording
