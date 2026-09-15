"""Security layer: prompt-injection defence, and PII redaction for logs.

Injection is handled at three levels, because no single one of them holds:

  input   — `scan_input` refuses high-confidence override and exfiltration
            attempts before any LLM call, so a manipulated question cannot even
            reach the analysis stage (and costs no tokens);
  prompt  — `sanitize` strips the structural tokens that would let text escape
            its block, and the generation prompt (see services/tax_service.py)
            states that both the question and the context documents are data;
  output  — `scan_output` checks the finished answer for a verbatim span of our
            own instructions or an API-key shape, in case the first two missed.

The user question and the knowledge base are different threats. The question is
untrusted input; the KB is ours, but it is 47 official PDFs converted to
Markdown, and a chunk of one could contain anything a Ministry PDF contains —
so retrieved text is sanitized on the same path rather than trusted.

`redact` is the other half of the module: everything that reaches a log line
goes through it, because real questions carry salaries, IBANs and tax IDs.
"""

import hashlib
import re
from dataclasses import dataclass, field

# The delimiter the generation prompt wraps the user question in. Text that
# contains it could otherwise close the block early and be read as instructions.
QUESTION_TAG = "user_question"

# --- input-level checks -----------------------------------------------------
#
# Two tiers, because refusing a legitimate question is also a failure. Patterns
# only earn a place in BLOCK if a genuine Anlage N question would not contain
# them: "ignore" alone is fine ("can I ignore the Pauschbetrag?"), "ignore all
# previous instructions" is not. Anything merely structural is sanitized and
# flagged instead, so someone pasting an XML-ish snippet still gets an answer.
#
# German, Russian and Turkish patterns are here for the same reason the rest of
# the pipeline is multilingual: the UI ships in four languages, and an
# English-only guard would be a guard on one quarter of the traffic.

BLOCK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("instruction_override", re.compile(
        r"(ignore|disregard|forget|override)\s+"
        r"(?:all\s+|any\s+|the\s+|your\s+|these\s+|previous\s+|prior\s+|above\s+|earlier\s+)*"
        r"(instructions?|prompts?|rules?|guidelines?|directives?)"
        r"|(ignore|disregard|forget)\s+(everything|all)\s+(above|before|prior)",
        re.I)),
    ("prompt_exfiltration", re.compile(
        r"system[\s\-_]?prompt"
        r"|(reveal|show|print|repeat|output|display|list|give\s+me|tell\s+me)\s+"
        r"(?:me\s+)?(?:your|the)\s+(?:full\s+|exact\s+|original\s+|initial\s+)?"
        r"(instructions?|prompt|rules|guidelines)",
        re.I)),
    ("secret_exfiltration", re.compile(
        r"api[\s\-_]?key|access\s+token|secret\s+key|sk-or-|\.env\b"
        r"|environment\s+variables?",
        re.I)),
    ("role_override", re.compile(
        r"you\s+are\s+now\b|from\s+now\s+on,?\s+you\s+(are|will|must)"
        r"|pretend\s+(that\s+)?you|act\s+as\s+if\s+you|forget\s+(that\s+)?you\s+are"
        r"|developer\s+mode|dan\s+mode|jailbreak|unrestricted\s+mode"
        r"|no\s+longer\s+bound|without\s+any\s+restrictions",
        re.I)),
    ("remote_execution", re.compile(
        r"(execute|run|eval)\s+(the\s+)?(following|this)\s+(code|command|script|python)",
        re.I)),
    # German
    ("instruction_override_de", re.compile(
        r"(ignorier(e|en)?|vergiss|missachte)\s+(alle\s+|die\s+)?"
        r"(vorherigen|bisherigen|obigen|alten)\s+(anweisungen|regeln|befehle|vorgaben)"
        r"|du\s+bist\s+(jetzt|ab\s+jetzt)\b|tu\s+so,?\s+als\s+(ob|wärst)",
        re.I)),
    # Russian
    ("instruction_override_ru", re.compile(
        r"(игнорир\w+|забудь|забудьте)\s+(все\s+)?"
        r"(предыдущие|прежние|прошлые|вышеуказанные)?\s*(инструкц\w+|указан\w+|правил\w+)"
        r"|систем\w+\s+промпт|ты\s+теперь\b|представь,?\s+что\s+ты",
        re.I)),
    # Turkish
    ("instruction_override_tr", re.compile(
        r"(önceki|tüm|yukarıdaki)\s+(talimatları|kuralları)\s*"
        r"(görmezden\s+gel|yoksay|unut|dikkate\s+alma)"
        r"|sistem\s+(istemi|talimatları)|artık\s+sen\b",
        re.I)),
]

# Flagged, sanitized, and answered anyway: these are how an injection is
# *delivered*, not proof that one was attempted.
SUSPICIOUS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("template_markers", re.compile(
        r"<\|[^|>]{1,40}\|>|\[/?INST\]|</?(system|assistant|user)>"
        r"|^#{2,}\s*(system|instruction)", re.I | re.M)),
    ("encoded_payload", re.compile(r"[A-Za-z0-9+/]{160,}={0,2}")),
]

# Structural tokens neutralized before any text is interpolated into a prompt.
# Replaced rather than deleted so the model still sees that something was there.
STRUCTURAL_RE = re.compile(
    rf"</?{QUESTION_TAG}>|</?context(_documents?)?>|<\|[^|>]{{1,40}}\|>"
    r"|\[/?INST\]|</?(system|assistant|user)>",
    re.I)


@dataclass
class InputVerdict:
    blocked: bool = False
    rules: list[str] = field(default_factory=list)      # matched BLOCK rules
    flags: list[str] = field(default_factory=list)      # matched SUSPICIOUS rules

    @property
    def suspicious(self) -> bool:
        return bool(self.flags)


def scan_input(text: str) -> InputVerdict:
    """Classify a user question before it reaches the model."""
    verdict = InputVerdict()
    for name, pattern in BLOCK_PATTERNS:
        if pattern.search(text):
            verdict.blocked = True
            verdict.rules.append(name)
    for name, pattern in SUSPICIOUS_PATTERNS:
        if pattern.search(text):
            verdict.flags.append(name)
    return verdict


def sanitize(text: str) -> str:
    """Neutralize structural tokens so text cannot escape its prompt block."""
    return STRUCTURAL_RE.sub("[removed]", text)


# --- output-level checks ----------------------------------------------------

# OpenRouter and OpenAI-style keys. Nothing in an answer about Werbungskosten
# has this shape, so a match means something leaked rather than was discussed.
KEY_SHAPE_RE = re.compile(r"\bsk-(?:or-)?(?:v\d-)?[A-Za-z0-9_\-]{20,}")

# Length of the word run compared against the instruction text. Long enough that
# ordinary German tax prose cannot collide with it by accident, short enough to
# catch a partial recital.
LEAK_SHINGLE_WORDS = 8

WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass
class OutputVerdict:
    leaked: bool = False
    rules: list[str] = field(default_factory=list)


def scan_output(answer: str, instructions: str) -> OutputVerdict:
    """Check a finished answer for leaked instructions or credentials.

    `instructions` must be the prompt's instruction text *without* the context
    documents: a grounded answer quotes its context on purpose, so including it
    would flag every correct answer as a leak.
    """
    verdict = OutputVerdict()
    if KEY_SHAPE_RE.search(answer):
        verdict.leaked = True
        verdict.rules.append("credential_shape")
    if _shares_long_run(answer, instructions):
        verdict.leaked = True
        verdict.rules.append("instruction_leak")
    return verdict


def _shares_long_run(answer: str, instructions: str) -> bool:
    """True if the answer repeats LEAK_SHINGLE_WORDS consecutive words of the prompt."""
    words = [w.lower() for w in WORD_RE.findall(instructions)]
    if len(words) < LEAK_SHINGLE_WORDS:
        return False
    answer_words = [w.lower() for w in WORD_RE.findall(answer)]
    if len(answer_words) < LEAK_SHINGLE_WORDS:
        return False
    shingles = {
        " ".join(words[i:i + LEAK_SHINGLE_WORDS])
        for i in range(len(words) - LEAK_SHINGLE_WORDS + 1)
    }
    return any(
        " ".join(answer_words[i:i + LEAK_SHINGLE_WORDS]) in shingles
        for i in range(len(answer_words) - LEAK_SHINGLE_WORDS + 1)
    )


# --- PII redaction ----------------------------------------------------------
#
# Applied to every string that reaches a log line. The order matters: IBANs and
# tax numbers are matched before the phone pattern, which is loose enough to
# swallow either of them.

IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}[ ]?[A-Z0-9]{1,4}\b")
# Steuer-Identifikationsnummer: exactly 11 digits, plain or grouped 2-3-3-3.
TAX_ID_RE = re.compile(r"\b\d{2}[ ]\d{3}[ ]\d{3}[ ]\d{3}\b|\b\d{11}\b")
# Steuernummer / Elster reference: 10-13 digits with slashes or spaces.
TAX_NUMBER_RE = re.compile(r"\b\d{2,3}[/ ]\d{3}[/ ]\d{4,5}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d()\-/ ]{8,}\d(?![\w.])")
# The phone pattern is deliberately loose, so it also matches things like a year
# range ("2024 - 2025"). A real number carries at least this many digits, and
# keeping tax years readable is what makes a log line worth reading.
PHONE_MIN_DIGITS = 9
# Currency-adjacent numbers, either order, in German or English grouping. The
# number is matched digit-group by digit-group rather than as a run of
# "digits, dots, commas and spaces": the loose form ran straight through a phone
# number and a comma to reach the next currency symbol, redacting the lot as one
# amount. Whether to redact is decided by magnitude in _redact_money.
MONEY_NUMBER = r"\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
MONEY_RE = re.compile(
    rf"(?:€|EUR|Euro)\s?({MONEY_NUMBER})|({MONEY_NUMBER})\s?(?:€|EUR\b|Euro\b)",
    re.I)

# Below this, an amount can only be a published rate (0,30 € per kilometre, the
# 6 € home-office day rate), so it stays readable — which is what makes a log
# line useful for debugging retrieval. At or above it, the amount is treated as
# the user's own money even when it happens to match a statutory threshold.
MONEY_REDACT_FROM = 1000


def _amount(raw: str) -> float | None:
    """Parse a German- or English-formatted amount, or None if it is not one."""
    digits = re.sub(r"[^\d.,]", "", raw)
    if not digits:
        return None
    # Whichever separator comes last is the decimal one; the other groups thousands.
    if "," in digits and "." in digits:
        decimal = "," if digits.rindex(",") > digits.rindex(".") else "."
    elif "," in digits:
        # A single comma with three trailing digits is a thousands separator.
        decimal = "" if re.search(r",\d{3}$", digits) else ","
    elif "." in digits:
        decimal = "" if re.search(r"\.\d{3}$", digits) else "."
    else:
        decimal = ""
    if decimal:
        whole, _, frac = digits.rpartition(decimal)
        digits = re.sub(r"\D", "", whole) + "." + frac
    else:
        digits = re.sub(r"\D", "", digits)
    try:
        return float(digits)
    except ValueError:
        return None


def _redact_money(match: re.Match) -> str:
    raw = match.group(1) or match.group(2) or ""
    value = _amount(raw)
    if value is None or value < MONEY_REDACT_FROM:
        return match.group(0)
    return "[AMOUNT]"


def _redact_phone(match: re.Match) -> str:
    raw = match.group(0)
    return "[PHONE]" if sum(c.isdigit() for c in raw) >= PHONE_MIN_DIGITS else raw


def redact(text: str) -> str:
    """Replace personal and financial identifiers with type markers."""
    if not text:
        return text
    text = IBAN_RE.sub("[IBAN]", text)
    text = TAX_NUMBER_RE.sub("[TAX_NUMBER]", text)
    text = TAX_ID_RE.sub("[TAX_ID]", text)
    text = MONEY_RE.sub(_redact_money, text)
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = PHONE_RE.sub(_redact_phone, text)
    return text


def safe_preview(text: str, limit: int = 120) -> str:
    """Redacted, truncated text — the only form of user input that may be logged."""
    preview = redact(text or "")
    return preview if len(preview) <= limit else preview[:limit] + "…"


def fingerprint(text: str) -> str:
    """Stable short hash: lets repeated questions be correlated without storing them."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def tool_args_summary(name: str, args: dict) -> dict:
    """Loggable shape of a tool call: which fields were passed, never their values.

    The values are the user's salary, commute and rent. The one exception is
    calculation_type, which selects the branch and carries no personal data —
    without it a log line cannot tell a commute calculation from a rent one.
    """
    summary = {"tool": name, "fields": sorted(k for k, v in args.items() if v is not None)}
    if isinstance(args.get("calculation_type"), str):
        summary["calculation_type"] = args["calculation_type"]
    return summary


# --- language guess ---------------------------------------------------------
#
# Only used for canned refusals, which are returned before the analysis call
# that normally detects the language. Wrong guesses cost nothing but a refusal
# in the wrong language, so a character-class check is enough.

CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")
# Only letters Turkish has and German does not: ö, ü and ç are shared, so
# including them would read half the German questions as Turkish.
TURKISH_RE = re.compile(r"[ıİğĞşŞ]")
GERMAN_HINT_RE = re.compile(
    r"\b(ich|nicht|kann|wie|was|und|der|die|das|mein|meine|absetzen|steuer\w*)\b", re.I)


def guess_language(text: str) -> str:
    """Best-effort language of a question, one of en/de/tr/ru."""
    if CYRILLIC_RE.search(text):
        return "ru"
    if TURKISH_RE.search(text):
        return "tr"
    if GERMAN_HINT_RE.search(text):
        return "de"
    return "en"
