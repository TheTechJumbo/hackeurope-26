"""Template resolver — turns {{n1.results}} into actual values from state."""

import re
from typing import Any


def resolve_templates(inputs: dict, state: dict) -> dict:
    """Resolve all {{ref}} templates in an inputs dict against pipeline state."""
    return _resolve_value(inputs, state)


def _resolve_value(value: Any, state: dict) -> Any:
    """Recursively resolve templates in any value type."""
    if isinstance(value, str):
        return _resolve_string(value, state)
    if isinstance(value, dict):
        return {k: _resolve_value(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item, state) for item in value]
    return value


def _resolve_string(value: str, state: dict) -> Any:
    # Whole string is a single {{ref}} → return raw value (preserves type)
    match = re.fullmatch(r"\{\{(\w+)\.(\w+(?:\.\w+)*)\}\}", value.strip())
    if match:
        return _lookup(match.group(1), match.group(2), state)

    # Mixed text + refs → string interpolation
    def replacer(m):
        result = _lookup(m.group(1), m.group(2), state)
        return str(result) if result is not None else ""

    return re.sub(r"\{\{(\w+)\.(\w+(?:\.\w+)*)\}\}", replacer, value)


def _lookup(namespace: str, path: str, state: dict) -> Any:
    """Look up a value by namespace and dotted path.

    Namespaces:
      - "memory" → state["memory"]
      - "user"   → state["user"]
      - anything else (e.g. "n1") → state["results"]["n1"]
    """
    keys = path.split(".")
    if namespace in ("memory", "user"):
        obj = state.get(namespace, {})
    else:
        obj = state.get("results", {}).get(namespace, {})
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k)
        else:
            return None
    return obj
