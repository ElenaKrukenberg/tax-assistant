"""The Reviewer: an independent audit of a finished case.

The second and last agent in the system, and it exists for one structural reason:
whoever built the case is biased towards it — what the Interviewer thought relevant,
the Interviewer also confirmed. So this agent sees only the finished state, never
the interview dialogue, not even a summary of it (docs/AGENT_ARCHITECTURE.md §15),
and its brief is adversarial: find what is unbacked, inconsistent or implausible,
not confirm what is there.

It does not trust the case's own figures either. It is given tools to recompute any
expense from the raw values and to run the deterministic validation rules — a
reviewer that can only reread the numbers it was handed can only quibble with
wording, and would not justify being an agent at all.

What it must catch is defined by the seeded cases in `eval/seeded.py`: an expense no
document backs, day counts that contradict each other, a claimed amount that does
not match its own inputs. Catching those is the acceptance criterion; anything it
finds beyond them is judgement, which is the part a rulebook cannot do.

When the provider fails, the review degrades to the deterministic validation rules
alone, labelled as such — a case must never be blocked from review by an outage,
and a rules-only review must never masquerade as the full one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from agents.interviewer import Chat
from domain.estimate import CALCULATORS, SUMMED, estimate, to_params
from domain.calculations import calculate
from domain.fields import ExpenseCategory, key_for
from domain.tax_years import for_year
from domain.validation import TaxData, validate_tax_data

MAX_ROUNDS = 8
MAX_FINDINGS = 12
SEVERITIES = ("blocking", "warning", "suggestion")


@dataclass(frozen=True)
class ClaimedExpense:
    """One expense as the case claims it, before the Reviewer has checked anything."""

    category: str
    amount_eur: float
    item_index: int = 0
    trace: tuple[str, ...] = ()
    document: Optional[str] = None  # file name of the backing document, if any


@dataclass(frozen=True)
class ReviewCase:
    """The finished case, and nothing else — no dialogue, no rationales.

    The absence is the design: independence that shares the builder's context is
    not independence (ADR-less on purpose; see AGENT_ARCHITECTURE §15).
    """

    tax_year: int
    fields: dict[str, Any]
    expenses: tuple[ClaimedExpense, ...]
    documents: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    severity: str
    title: str
    reasoning: str
    category: Optional[str] = None


@dataclass
class ReviewResult:
    findings: list[Finding] = field(default_factory=list)
    from_model: bool = True
    rounds: int = 0
    note: str = ""


TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "recompute_expense",
            "description": (
                "Recompute one claimed expense from the case's raw values with the "
                "official calculators, and compare against the claimed amount. Trust "
                "no figure you have not recomputed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string",
                                 "enum": [c.value for c in ExpenseCategory]},
                    "item_index": {"type": "integer", "minimum": 0},
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_validation",
            "description": (
                "Run the deterministic plausibility rules (V01-V26) over the case's "
                "values: day-count contradictions, legal caps, year membership."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_review",
            "description": (
                "Deliver the verdict. Findings only for real objections — an empty "
                "list is a legitimate verdict and better than an invented quibble."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "severity": {"type": "string", "enum": list(SEVERITIES)},
                                "title": {"type": "string"},
                                "reasoning": {"type": "string"},
                                "category": {"type": "string"},
                            },
                            "required": ["severity", "title", "reasoning"],
                        },
                    },
                },
                "required": ["findings"],
            },
        },
    },
]

SYSTEM = """You audit a finished German tax case (Anlage N, Werbungskosten) that
somebody else prepared. You were deliberately given no record of how it was
prepared — only the final state. Your brief is adversarial: assume the case is
wrong until its figures survive your checks.

Work through, in order:
1. Recompute every claimed expense with recompute_expense. A claimed amount that
   does not match its recomputation is a blocking finding.
2. Run run_validation and read its findings; a broken rule is at least a warning,
   a legal cap breached is blocking.
3. Backing: an expense above trivial size with no document behind it is a warning —
   the Finanzamt may ask for proof that does not exist.
4. Judgement: amounts implausible for their category, categories that contradict
   each other, anything a careful human examiner would query.

Then call finish_review. Do not pad: an empty findings list is a legitimate
verdict. Severity: blocking = the report must not be generated as is; warning =
the user must see it; suggestion = worth a look. Never invent rules or figures;
what you assert, you must have recomputed or read from the case."""


async def review(case: ReviewCase, chat: Optional[Chat]) -> ReviewResult:
    """Audit the case. Multi-round tool loop, one verdict at the end."""
    if chat is None:
        return _rules_only(case, note="no model configured; deterministic rules only")

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": _case_prompt(case)},
    ]

    result = ReviewResult()
    for round_number in range(1, MAX_ROUNDS + 1):
        result.rounds = round_number
        try:
            message, _usage = await chat.chat_raw(messages, tools=TOOLS)
        except Exception:  # noqa: BLE001 — an outage must not block a review
            fallback = _rules_only(case, note="provider failed mid-review; "
                                              "deterministic rules only")
            fallback.rounds = round_number
            return fallback

        calls = message.get("tool_calls") or []
        if not calls:
            # Prose instead of a verdict: remind once, then give up to the rules.
            messages.append({"role": "user", "content":
                             "Deliver the verdict with finish_review, or check "
                             "something with the tools. Prose is not a review."})
            continue

        messages.append(message)
        for call in calls:
            name = (call.get("function") or {}).get("name")
            raw_args = (call.get("function") or {}).get("arguments") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}

            if name == "finish_review":
                result.findings = _read_findings(args)
                return result

            output = _run_tool(name, args, case)
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or name or "tool",
                "content": json.dumps(output, ensure_ascii=False),
            })

    fallback = _rules_only(case, note=f"no verdict after {MAX_ROUNDS} rounds; "
                                      "deterministic rules only")
    fallback.rounds = MAX_ROUNDS
    return fallback


# --- tools ------------------------------------------------------------------------

def _run_tool(name: Optional[str], args: dict, case: ReviewCase) -> dict:
    if name == "recompute_expense":
        return _recompute(case, str(args.get("category") or ""),
                          int(args.get("item_index") or 0))
    if name == "run_validation":
        return _validation(case)
    return {"error": f"tool not offered: {name}"}


def _recompute(case: ReviewCase, category_name: str, item_index: int) -> dict:
    try:
        category = ExpenseCategory(category_name)
    except ValueError:
        return {"error": f"unknown category: {category_name}"}

    claimed = next((e for e in case.expenses
                    if e.category == category_name and e.item_index == item_index), None)

    if category in SUMMED:
        amount_field, minus_field = SUMMED[category]
        amount = case.fields.get(_key(category, amount_field, item_index))
        if amount is None:
            return {"computable": False,
                    "missing": [_key(category, amount_field, item_index)],
                    "claimed_eur": claimed.amount_eur if claimed else None}
        reimbursed = (case.fields.get(_key(category, minus_field, item_index)) or 0.0
                      if minus_field else 0.0)
        computed = round(max(float(amount) - float(reimbursed), 0.0), 2)
        return _comparison(computed, claimed, breakdown=[
            f"{amount} - {reimbursed} reimbursed = {computed}"])

    params, missing = to_params(category, case.fields, item_index)
    if missing:
        return {"computable": False, "missing": missing,
                "claimed_eur": claimed.amount_eur if claimed else None}
    try:
        outcome = calculate(CALCULATORS[category], params, case.tax_year)
    except Exception as exc:  # noqa: BLE001 — the model gets the reason, not a crash
        return {"error": f"calculator refused the values: {exc}"}
    return _comparison(outcome.amount_eur, claimed, breakdown=outcome.breakdown,
                       warnings=outcome.warnings)


def _comparison(computed: float, claimed: Optional[ClaimedExpense],
                breakdown: list[str], warnings: list[str] | None = None) -> dict:
    out: dict[str, Any] = {
        "computable": True,
        "computed_eur": computed,
        "claimed_eur": claimed.amount_eur if claimed else None,
        "breakdown": breakdown,
    }
    if warnings:
        out["rule_warnings"] = warnings
    if claimed is not None:
        out["matches_claim"] = abs(computed - claimed.amount_eur) < 0.01
    return out


def _validation(case: ReviewCase) -> dict:
    f = case.fields
    report = validate_tax_data(TaxData(
        working_days_total=f.get("profile.working_days_total"),
        commuting_days=f.get("commute.commuting_days"),
        homeoffice_days=f.get("homeoffice.homeoffice_days"),
        telecom_monthly_claim_eur=f.get("telecom.monthly_bill_eur"),
        total_werbungskosten_eur=estimate(f, for_year(case.tax_year)).total_eur,
        fortbildung_costs_eur=f.get("education.amount_eur"),
    ), for_year(case.tax_year))
    return {
        "valid": report.valid,
        "findings": [{"rule": x.rule_id, "severity": x.severity, "message": x.message}
                     for x in report.findings],
        "rules_checked": report.checked_rules,
    }


# --- reading the verdict ------------------------------------------------------------

def _read_findings(args: dict) -> list[Finding]:
    """Take the verdict apart, dropping anything malformed rather than crashing.

    Capped, deduplicated by title, severities outside the vocabulary demoted to
    warning — a reviewer that can invent severities can also bury one blocking
    finding under twenty decorative ones.
    """
    known_categories = {c.value for c in ExpenseCategory}
    findings: list[Finding] = []
    seen_titles: set[str] = set()

    for raw in (args.get("findings") or [])[:MAX_FINDINGS * 2]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        reasoning = str(raw.get("reasoning") or "").strip()
        if not title or not reasoning or title in seen_titles:
            continue
        severity = str(raw.get("severity") or "").strip()
        if severity not in SEVERITIES:
            severity = "warning"
        category = str(raw.get("category") or "").strip() or None
        if category is not None and category not in known_categories:
            category = None
        findings.append(Finding(severity, title, reasoning, category))
        seen_titles.add(title)
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


# --- the degraded review -------------------------------------------------------------

def _rules_only(case: ReviewCase, note: str) -> ReviewResult:
    """What can be said without judgement: the validation rules, and unbacked expenses.

    Explicitly labelled, because a rules-only pass silently standing in for the
    adversarial review would defeat the reason the Reviewer exists.
    """
    findings: list[Finding] = []
    report = _validation(case)
    for item in report["findings"]:
        severity = {"error": "blocking", "warning": "warning"}.get(item["severity"],
                                                                   "suggestion")
        findings.append(Finding(severity, f"Rule {item['rule']} broken",
                                item["message"]))
    for expense in case.expenses:
        if expense.document is None and expense.amount_eur >= 100:
            findings.append(Finding(
                "warning",
                f"No document behind {expense.category} ({expense.amount_eur:.2f} EUR)",
                "The Finanzamt may ask for proof that the case does not hold.",
                category=expense.category,
            ))
    return ReviewResult(findings=findings, from_model=False, note=note)


# --- prompt --------------------------------------------------------------------------

def _case_prompt(case: ReviewCase) -> str:
    lines = [f"Tax year {case.tax_year}. The finished case, as claimed:", "",
             "Values:"]
    lines.extend(f"- {k} = {v!r}" for k, v in sorted(case.fields.items()))
    lines.append("")
    lines.append("Claimed expenses:")
    for e in case.expenses:
        backing = e.document or "NO DOCUMENT"
        suffix = f"#{e.item_index}" if e.item_index else ""
        lines.append(f"- {e.category}{suffix}: {e.amount_eur:.2f} EUR, backed by {backing}")
        lines.extend(f"    trace: {t}" for t in e.trace)
    lines.append("")
    lines.append("Documents in the case: "
                 + (", ".join(case.documents) if case.documents else "none"))
    return "\n".join(lines)


def _key(category: ExpenseCategory, name: str, item_index: int) -> str:
    """The key a fact is actually stored under, from the one place that decides it.

    This used to spell the key itself as `<category>.<field>`, which was right only
    for the categories whose namespace happens to share the category's name. A fact
    is keyed by what it *means*, not by the category that consumes it (#61), so
    moving costs live at `moving.amount_eur` and applications at
    `applications.amount_eur` - and looking them up as `umzugskosten.amount_eur` and
    `bewerbungskosten.amount_eur` found nothing. The Reviewer then reported the
    expense as not recomputable, which is blocking, and the case could not be
    approved or repaired: going back changed a value the lookup still could not see.
    """
    return key_for(category, name, item_index)
