from __future__ import annotations

from typing import Any

from app.blocks.executor import register_implementation
from app.memory.store import memory_store


@register_implementation("memory_read")
async def memory_read(inputs: dict[str, Any]) -> dict[str, Any]:
    """Read a value from the key-value memory store."""
    key = inputs["key"]
    context = inputs.get("__context", {})
    namespace = inputs.get("namespace") or context.get("user_id") or "default"
    value = memory_store.read(key, namespace)
    return {"value": value, "found": value is not None}


@register_implementation("memory_write")
async def memory_write(inputs: dict[str, Any]) -> dict[str, Any]:
    """Write a value to the key-value memory store."""
    key = inputs["key"]
    value = inputs["value"]
    context = inputs.get("__context", {})
    namespace = inputs.get("namespace") or context.get("user_id") or "default"
    memory_store.write(key, value, namespace)
    return {"success": True, "key": key}


@register_implementation("memory_append")
async def memory_append(inputs: dict[str, Any]) -> dict[str, Any]:
    """Append a value to a list in memory."""
    key = inputs["key"]
    value = inputs["value"]
    context = inputs.get("__context", {})
    namespace = inputs.get("namespace") or context.get("user_id") or "default"
    length = memory_store.append(key, value, namespace)
    return {"success": True, "list_length": length}
