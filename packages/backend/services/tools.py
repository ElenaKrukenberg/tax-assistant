"""Tool layer: OpenAI-format tool definitions + dispatcher.

The JSON schemas are generated from the domain Pydantic models so the LLM
contract can never drift from the actual validation. execute_tool() never
raises: validation/execution problems come back as an {"error": ...} payload
the model can read and correct (tool error handling).
"""

import json

from pydantic import ValidationError

from domain.calculations import CalculationType, PARAMS_BY_TYPE, calculate
from domain.checklist import ChecklistCategory, build_document_checklist
from domain.validation import TaxData, validate_tax_data


def _params_union_schema() -> dict:
    """anyOf over the five per-type params models, labeled for the LLM."""
    return {
        "anyOf": [
            {**model.model_json_schema(), "title": ctype.value}
            for ctype, model in PARAMS_BY_TYPE.items()
        ]
    }


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "calculate_tax_amount",
            "description": (
                "Calculate a Werbungskosten amount for Anlage N, tax year 2025. "
                "Types: entfernungspauschale (commute allowance; needs commuting_days, distance_km), "
                "homeoffice_pauschale (needs homeoffice_days), "
                "arbeitsmittel (GWG/AfA for work equipment; needs price_eur, purchase_month), "
                "pauschbetrag_comparison (itemising vs the 1230 EUR flat allowance; needs total_werbungskosten_eur), "
                "telefon_internet (phone/internet flat rate; needs monthly_bill_eur)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "calculation_type": {
                        "type": "string",
                        "enum": [t.value for t in CalculationType],
                    },
                    "params": _params_union_schema(),
                },
                "required": ["calculation_type", "params"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_tax_data",
            "description": (
                "Check the user's tax figures against plausibility rules and hard legal caps "
                "(working days, home-office day/amount caps, DHF rent cap, GWG threshold, "
                "Pauschbetrag comparison, tax-year check). Pass only the fields the user provided."
            ),
            "parameters": TaxData.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_document_checklist",
            "description": (
                "Build a checklist of documents/receipts the user should keep per expense "
                "category (Belegvorhaltepflicht)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "categories": {
                        "type": "array",
                        "items": {"type": "string", "enum": [c.value for c in ChecklistCategory]},
                        "minItems": 1,
                    }
                },
                "required": ["categories"],
            },
        },
    },
]


# Allowlist, derived from the definitions above so the two cannot drift: a name
# the model was never offered is refused before any dispatch. The dispatch chain
# below would already fall through to "Unknown tool", but that is an accident of
# how it is written — this makes the boundary explicit and gives the caller
# something to log as a security event rather than a typo.
ALLOWED_TOOLS = frozenset(t["function"]["name"] for t in TOOL_DEFINITIONS)

# A tool call is a handful of numbers. Anything larger is not a calculation
# request, and parsing it is work done on an attacker's behalf.
MAX_ARGUMENTS_CHARS = 4000


def execute_tool(name: str, arguments: str | dict) -> str:
    """Run a tool call and return a JSON string (result or structured error)."""
    if name not in ALLOWED_TOOLS:
        return json.dumps({"error": f"Tool not allowed: {name}"})

    if isinstance(arguments, str) and len(arguments) > MAX_ARGUMENTS_CHARS:
        return json.dumps({"error": "Arguments too large", "problems": [
            f"argument payload exceeds {MAX_ARGUMENTS_CHARS} characters"
        ]})

    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON arguments: {e}"})

    if not isinstance(args, dict):
        return json.dumps({"error": "Arguments must be a JSON object"})

    try:
        if name == "calculate_tax_amount":
            ctype = CalculationType(args["calculation_type"])
            result = calculate(ctype, args.get("params") or {})
            return result.model_dump_json()

        if name == "validate_tax_data":
            report = validate_tax_data(TaxData(**args))
            return report.model_dump_json()

        if name == "build_document_checklist":
            categories = []
            skipped = []
            for c in args.get("categories", []):
                try:
                    categories.append(ChecklistCategory(c))
                except ValueError:
                    skipped.append(c)
            lists = build_document_checklist(categories)
            payload = {"checklists": [c.model_dump() for c in lists]}
            if skipped:
                payload["skipped_unknown_categories"] = skipped
            return json.dumps(payload)

        # Unreachable while ALLOWED_TOOLS is derived from TOOL_DEFINITIONS; kept
        # so adding a definition without a branch fails loudly instead of silently.
        return json.dumps({"error": f"Unknown tool: {name}"})

    except ValidationError as e:
        # readable per-field errors so the model can fix its arguments and retry
        problems = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        return json.dumps({"error": "Invalid parameters", "problems": problems})
    except (KeyError, ValueError) as e:
        return json.dumps({"error": f"Bad tool arguments: {e}"})
