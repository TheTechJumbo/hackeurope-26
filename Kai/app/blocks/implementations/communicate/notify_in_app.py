from __future__ import annotations

import logging
from typing import Any

from app.blocks.executor import register_implementation
from app.storage.memory import memory_store

logger = logging.getLogger("agentflow.blocks.notify")


@register_implementation("notify_in_app")
async def notify_in_app(inputs: dict[str, Any]) -> dict[str, Any]:
    """Show an in-app notification. Persists to DB and pushes to SSE subscribers."""
    title = inputs["title"]
    message = inputs["message"]
    level = inputs.get("level", "info")

    context = inputs.get("__context", {})
    pipeline_id = context.get("pipeline_id")
    run_id = context.get("run_id")
    node_id = context.get("node_id")
    user_id = context.get("user_id")

    log_fn = {
        "info": logger.info,
        "success": logger.info,
        "warning": logger.warning,
        "error": logger.error,
    }.get(level, logger.info)

    log_fn("[%s] %s: %s", level.upper(), title, message)

    memory_store.add_notification({
        "user_id": user_id,
        "pipeline_id": pipeline_id,
        "run_id": run_id,
        "node_id": node_id,
        "title": title,
        "message": message,
        "level": level,
        "category": "notification",
    })

    return {"delivered": True}
