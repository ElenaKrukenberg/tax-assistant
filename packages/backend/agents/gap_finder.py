"""The gap finder: deductions the profile points at that the case does not hold.

Two halves, split exactly as the architecture prescribes (AGENT_ARCHITECTURE §5):
finding the candidates is rules — a profile signal says the user is likely
entitled to a category, and the case holds no computable expense for it — and
only the justification is a model: one retrieval over the KB plus one call to
phrase why this user, specifically, appears entitled, grounded in the retrieved
passage.

Where it fires: when the Interviewer proposes to stop. A candidate at that moment
means the interview is about to end with an entitlement on the table — the user
sees it on the stop card, with the citation, and decides. It also shows on the
dashboard rule-only (no model, no cost) as "worth a look".

Without a retriever or a model the rationale degrades to a fixed sentence per
category and no quote — labelled by the absent citation, never invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from domain.estimate import estimate
from domain.fields import ExpenseCategory

# Profile signal → the category it points at. A signal is a gate the user
# answered with yes; the commute needs no gate, employment itself implies it.
SIGNALS: dict[str, ExpenseCategory] = {
    "profile.works_remotely": ExpenseCategory.homeoffice_tagespauschale,
    "profile.bought_work_equipment": ExpenseCategory.arbeitsmittel,
    "profile.claims_phone_internet": ExpenseCategory.telefon_internet,
    "profile.further_education": ExpenseCategory.fortbildungskosten,
    "profile.moved_for_work": ExpenseCategory.umzugskosten,
    "profile.searched_for_job": ExpenseCategory.bewerbungskosten,
}

# What retrieval is asked for, per category. German, because the KB is German.
KB_QUERIES: dict[ExpenseCategory, str] = {
    ExpenseCategory.homeoffice_tagespauschale: "Homeoffice Tagespauschale Voraussetzungen",
    ExpenseCategory.arbeitsmittel: "Arbeitsmittel Werbungskosten absetzen",
    ExpenseCategory.telefon_internet: "Telefon Internet beruflich Werbungskosten pauschal",
    ExpenseCategory.fortbildungskosten: "Fortbildungskosten Werbungskosten abziehbar",
    ExpenseCategory.umzugskosten: "Umzugskosten beruflich veranlasst Werbungskosten",
    ExpenseCategory.bewerbungskosten: "Bewerbungskosten Werbungskosten",
}

FALLBACK_RATIONALE: dict[ExpenseCategory, str] = {
    ExpenseCategory.homeoffice_tagespauschale:
        "You said you work from home; each home-office day is worth 6 EUR.",
    ExpenseCategory.arbeitsmittel:
        "You said you bought something for work; work equipment is deductible.",
    ExpenseCategory.telefon_internet:
        "You said you use your own phone or internet for work; a share of the bill counts.",
    ExpenseCategory.fortbildungskosten:
        "You said you paid for training; training in your profession is deductible.",
    ExpenseCategory.umzugskosten:
        "You said you moved for work; a professionally caused move is deductible.",
    ExpenseCategory.bewerbungskosten:
        "You said you applied for jobs; unreimbursed application costs are deductible.",
}


@dataclass
class GapCandidate:
    category: ExpenseCategory
    rationale: str
    citation_title: str = ""
    citation_quote: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "rationale": self.rationale,
            "citation_title": self.citation_title,
            "citation_quote": self.citation_quote,
        }


def find_candidates(known: dict[str, Any]) -> list[ExpenseCategory]:
    """Rules only: signalled, and not yet a computable expense. No model, no cost."""
    computable = {category for category, entry in estimate(known).per_category.items()
                  if entry.computable}
    return [category for signal, category in SIGNALS.items()
            if known.get(signal) is True and category not in computable]


# The justifier's shape, so the graph can be handed a fake in tests and nothing
# here imports a provider client.
Justifier = Callable[[list[ExpenseCategory], dict[str, Any]],
                     Awaitable[list[GapCandidate]]]


async def plain_justifier(categories: list[ExpenseCategory],
                          known: dict[str, Any]) -> list[GapCandidate]:
    """The degraded justification: fixed sentence, no quote. Never invents one."""
    return [GapCandidate(category, FALLBACK_RATIONALE[category])
            for category in categories]


def kb_justifier(retriever: Any, chat: Any) -> Justifier:
    """The real justification: retrieval for the passage, one call for the sentence.

    One provider call per candidate, and candidates at a stop proposal are rare
    (usually zero or one), so this is not the place for batching cleverness.
    """

    async def justify(categories: list[ExpenseCategory],
                      known: dict[str, Any]) -> list[GapCandidate]:
        out: list[GapCandidate] = []
        for category in categories:
            candidate = GapCandidate(category, FALLBACK_RATIONALE[category])
            try:
                result = retriever.search(KB_QUERIES[category], k=2)
                if result.chunks:
                    top = result.chunks[0]
                    candidate.citation_title = top.metadata.get("title", "")
                    candidate.citation_quote = top.text[:280].strip()
                    candidate.rationale = await _phrase(chat, category, known, top.text)
            except Exception:  # noqa: BLE001 — a gap hint must never sink the stop
                pass
            out.append(candidate)
        return out

    return justify


async def _phrase(chat: Any, category: ExpenseCategory,
                  known: dict[str, Any], passage: str) -> str:
    """One grounded sentence. Anything unusable falls back to the fixed one."""
    messages = [
        {"role": "system", "content":
            "You write one sentence, in English, telling a taxpayer why a deduction "
            "category looks relevant to them, grounded ONLY in the official passage "
            "given. No figures the passage does not contain, no advice, no promises. "
            "One sentence, nothing else."},
        {"role": "user", "content":
            f"Category: {category.value}\n"
            f"What the user said: {_signals_of(known)}\n"
            f"Official passage:\n{passage[:1200]}"},
    ]
    try:
        message, _usage = await chat.chat_raw(messages)
        text = str(message.get("content") or "").strip()
        # A sentence, not an essay; anything else is the model being chatty.
        if 20 <= len(text) <= 300:
            return text
    except Exception:  # noqa: BLE001
        pass
    return FALLBACK_RATIONALE[category]


def _signals_of(known: dict[str, Any]) -> str:
    yes = [signal for signal in SIGNALS if known.get(signal) is True]
    return ", ".join(yes) or "nothing yet"
