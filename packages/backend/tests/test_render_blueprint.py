"""render.yaml declares each environment variable exactly once.

A Render blueprint is a YAML list, not a mapping, so a variable named twice is
not a parse error: the service starts, and the later entry quietly wins. That is
how RATE_LIMIT_PER_IP came to be declared as 60 next to the comment explaining
why an interview needs 60, and as 10 eighty lines further down (#22). The
deployed limit was 10 and the comment said otherwise, which is the failure mode
worth a test - nobody reads a blueprint top to bottom looking for a repeat.

Parsed by hand, though not for the reason first claimed here. `envVars` is a list
of `{key, value}` objects, so `yaml.safe_load` keeps both entries and can see the
repeat perfectly well - it is a mapping key that a loader collapses, and there is
no mapping here. The text parser earns its place by grouping each `- key:` under
the service block it sits in: the same name in two services is normal, twice in
one service is the bug, and that distinction is the whole test.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

BLUEPRINT = Path(__file__).resolve().parents[3] / "render.yaml"

_SERVICE = re.compile(r"^  - (?:type|name):\s*(\S+)")
_ENV_KEY = re.compile(r"^      - key:\s*(\S+)")


def _env_keys_by_service() -> dict[str, list[str]]:
    """Every `- key:` entry, grouped by the service block it sits in."""
    found: dict[str, list[str]] = {}
    service = "(before the first service)"
    for line in BLUEPRINT.read_text(encoding="utf-8").splitlines():
        start = _SERVICE.match(line)
        if start:
            service = start.group(1)
            found.setdefault(service, [])
            continue
        key = _ENV_KEY.match(line)
        if key:
            found.setdefault(service, []).append(key.group(1))
    return found


def test_blueprint_is_readable():
    """Guards the parser itself: a rename that breaks it must not pass silently."""
    keys = _env_keys_by_service()
    assert keys, "no service block found in render.yaml"
    everything = [k for names in keys.values() for k in names]
    assert "DATABASE_URL" in everything
    assert "RATE_LIMIT_PER_IP" in everything


def test_no_environment_variable_is_declared_twice():
    for service, keys in _env_keys_by_service().items():
        repeated = sorted(name for name, n in Counter(keys).items() if n > 1)
        assert not repeated, f"{service} declares {', '.join(repeated)} more than once"
