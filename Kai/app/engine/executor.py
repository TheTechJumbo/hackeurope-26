"""Block executor — all blocks are Python (exec from source_code).

Blocks that need LLM access call `call_llm()` / `parse_json_output()` directly
from their source_code — these functions are available in the exec namespace.
"""

from __future__ import annotations

import json
import logging
import re
import traceback
from typing import Any

from app.engine.resolver import resolve_templates
from app.llm.service import call_llm, call_llm_messages, parse_json_output
from app.registry.registry import registry
from app.storage.supabase_client import get_supabase
from app.blocks.executor import get_implementation

logger = logging.getLogger(__name__)

# Compiled function cache: block_id → execute function
_compiled_blocks: dict[str, Any] = {}


def _validate_inputs(inputs: dict, schema: dict) -> dict:
    """Validate and coerce inputs against a JSON schema.

    - Checks all required fields are present
    - Coerces types: str→float for numbers, list/dict→json.dumps for strings
    - Logs warnings for coercions but does not fail
    """
    if not schema:
        return inputs

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # Check required fields
    for field in required:
        if field not in inputs:
            logger.warning("Missing required input field '%s'", field)

    # Type coercion
    coerced = dict(inputs)
    for key, prop in properties.items():
        if key not in coerced:
            continue
        expected_type = prop.get("type")
        value = coerced[key]

        if expected_type == "number" and isinstance(value, str):
            try:
                coerced[key] = float(value)
                logger.info("Coerced input '%s' from str to float", key)
            except (ValueError, TypeError):
                pass
        elif expected_type == "integer" and isinstance(value, str):
            try:
                coerced[key] = int(value)
                logger.info("Coerced input '%s' from str to int", key)
            except (ValueError, TypeError):
                pass
        elif expected_type == "string" and isinstance(value, (list, dict)):
            coerced[key] = json.dumps(value)
            logger.info("Coerced input '%s' from %s to JSON string", key, type(value).__name__)

    return coerced


def _convert_legacy_llm_block(block: dict) -> dict:
    """Convert a legacy llm-type block to python by generating source_code from its prompt_template.

    This handles old blocks stored in the registry with execution_type='llm'.
    """
    template = block.get("prompt_template", "")
    output_schema = block.get("output_schema", {})
    description = block.get("description", "")
    name = block.get("name", block.get("id", "unknown"))

    # Build the output schema description for the system prompt
    output_props = output_schema.get("properties", {})
    required_fields = output_schema.get("required", [])
    fields_desc = ", ".join(
        f'"{k}" ({v.get("type", "any")}: {v.get("description", "no description")})'
        for k, v in output_props.items()
    )
    required_note = f"Required fields: {', '.join(required_fields)}" if required_fields else ""

    examples = block.get("examples", [])
    example_json = json.dumps(examples[0]["outputs"]) if examples and "outputs" in examples[0] else ""

    # Generate Python source that replicates run_llm_block behavior
    source_code = f'''"""Legacy LLM block: {name} — auto-converted to Python."""

import json as _json
import re as _re

_PROMPT_TEMPLATE = """{template}"""
_DESCRIPTION = """{description}"""
_NAME = """{name}"""
_FIELDS_DESC = """{fields_desc}"""
_REQUIRED_NOTE = """{required_note}"""
_EXAMPLE_JSON = """{example_json}"""

def _safe_format(tmpl, values):
    def replacer(m):
        key = m.group(1)
        if key in values:
            return values[key]
        return m.group(0)
    return _re.sub(r"\\{{(\\w+)}}", replacer, tmpl)

async def execute(inputs, context):
    # Apply defaults from schema
    str_inputs = {{}}
    for k, v in inputs.items():
        str_inputs[k] = _json.dumps(v) if not isinstance(v, str) else v

    prompt = _safe_format(_PROMPT_TEMPLATE, str_inputs)

    system = (
        f"You are executing the block: {{_NAME}}.\\n"
        f"Task: {{_DESCRIPTION}}\\n\\n"
        f"IMPORTANT RULES:\\n"
        f"1. Return ONLY a JSON object (no markdown, no explanation).\\n"
        f"2. The JSON must contain these fields: {{_FIELDS_DESC}}.\\n"
        f"3. Populate every field with REAL, substantive data.\\n"
        f"4. Use your knowledge to produce the best possible answer.\\n"
        f"5. If asked to search or look up information, use your training knowledge."
    )
    if _EXAMPLE_JSON:
        system += f"\\n6. Example output for reference: {{_EXAMPLE_JSON}}"
    if _REQUIRED_NOTE:
        system += f"\\n{{_REQUIRED_NOTE}}"

    response = await call_llm(system=system, user=prompt)
    return parse_json_output(response)
'''

    converted = dict(block)
    converted["execution_type"] = "python"
    converted["source_code"] = source_code
    logger.info("Auto-converted legacy llm block '%s' to python", block.get("id"))
    return converted


async def execute_block(node_def: dict, state: dict) -> dict[str, Any]:
    """Execute a single block node. Returns its output dict.

    Args:
        node_def: {"id": "n1", "block_id": "web_search", "inputs": {...}}
        state: Current pipeline state with results, user, memory.

    Returns:
        The block's output dict.
    """
    block = registry.get(node_def["block_id"])

    # Auto-convert legacy llm blocks to python
    if block.get("execution_type") == "llm":
        block = _convert_legacy_llm_block(block)

    resolved_inputs = resolve_templates(node_def.get("inputs", {}), state)
    resolved_inputs = _validate_inputs(resolved_inputs, block.get("input_schema", {}))
    context = {
        "user": state.get("user", {}),
        "memory": state.get("memory", {}),
        "user_id": state.get("user_id", "default_user"),
        "supabase": get_supabase(),
        "pipeline_id": state.get("pipeline_id", ""),
        "node_id": node_def.get("id", ""),
        "run_id": state.get("run_id", ""),
    }

    # Inject pipeline context for blocks that rely on it
    resolved_inputs.setdefault("__context", {
        "pipeline_id": context["pipeline_id"],
        "node_id": context["node_id"],
        "run_id": context["run_id"],
        "user_id": context["user_id"],
    })

    return await run_python_block(block, resolved_inputs, context)


async def run_python_block(block: dict, inputs: dict, context: dict) -> dict:
    """Execute a python block by exec()'ing its source_code.

    The source_code must define an `async def execute(inputs, context) -> dict`.
    Compiled functions are cached by block_id for performance.
    """
    block_id = block["id"]

    if block_id not in _compiled_blocks:
        source_code = block.get("source_code")
        if not source_code:
            # Fallback to locally-registered implementation (Kai blocks)
            impl = get_implementation(block_id)
            if impl is None:
                raise ValueError(f"Block {block_id} has no source_code and no local implementation")
            return await impl(inputs)

        namespace = _build_exec_namespace()
        try:
            exec(compile(source_code, f"<block:{block_id}>", "exec"), namespace)
        except Exception:
            raise RuntimeError(
                f"Failed to compile block {block_id}:\n{traceback.format_exc()}"
            )

        if "execute" not in namespace:
            raise AttributeError(f"Block {block_id} source_code missing execute() function")

        _compiled_blocks[block_id] = namespace["execute"]

    execute_fn = _compiled_blocks[block_id]
    return await execute_fn(inputs, context)


def _build_exec_namespace() -> dict:
    """Build a safe namespace for exec() with allowed modules and LLM access."""
    import collections
    import datetime
    import functools
    import itertools
    import math
    import os
    import random
    import re as re_mod
    import statistics

    import httpx
    import json as json_mod

    # Pre-approved modules that source_code may import
    _allowed_modules = {
        "math": math,
        "statistics": statistics,
        "collections": collections,
        "itertools": itertools,
        "functools": functools,
        "re": re_mod,
        "datetime": datetime,
        "json": json_mod,
        "os": os,
        "random": random,
        "httpx": httpx,
    }

    def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        """Only allow importing pre-approved modules."""
        top = name.split(".")[0]
        if top in _allowed_modules:
            return _allowed_modules[top]
        raise ImportError(
            f"Module '{name}' is not allowed. "
            f"Available: {', '.join(sorted(_allowed_modules))}"
        )

    allowed_builtins = {
        "True": True, "False": False, "None": None,
        "int": int, "float": float, "str": str, "bool": bool,
        "list": list, "dict": dict, "tuple": tuple, "set": set,
        "frozenset": frozenset, "bytes": bytes,
        "abs": abs, "all": all, "any": any, "bin": bin,
        "chr": chr, "divmod": divmod, "enumerate": enumerate,
        "filter": filter, "format": format, "hash": hash, "hex": hex,
        "isinstance": isinstance, "issubclass": issubclass,
        "iter": iter, "len": len, "map": map, "max": max, "min": min,
        "next": next, "oct": oct, "ord": ord, "pow": pow,
        "range": range, "repr": repr, "reversed": reversed,
        "round": round, "slice": slice, "sorted": sorted,
        "sum": sum, "type": type, "zip": zip,
        "hasattr": hasattr, "getattr": getattr, "setattr": setattr,
        "print": print,
        "__import__": _restricted_import,
        "Exception": Exception, "ValueError": ValueError,
        "TypeError": TypeError, "KeyError": KeyError,
        "RuntimeError": RuntimeError, "AttributeError": AttributeError,
    }

    return {
        "__builtins__": allowed_builtins,
        # Pre-loaded modules (available without import)
        **_allowed_modules,
        # LLM functions — available directly in block source_code
        "call_llm": call_llm,
        "call_llm_messages": call_llm_messages,
        "parse_json_output": parse_json_output,
    }


async def execute_block_standalone(block: dict, inputs: dict, context: dict) -> dict[str, Any]:
    """Execute a block dict directly (no registry lookup). Used for testing blocks."""
    validated_inputs = _validate_inputs(inputs, block.get("input_schema", {}))

    # Auto-convert legacy llm blocks to python
    if block.get("execution_type") == "llm":
        block = _convert_legacy_llm_block(block)

    return await run_python_block(block, validated_inputs, context)
