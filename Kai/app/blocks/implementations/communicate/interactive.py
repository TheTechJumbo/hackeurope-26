from __future__ import annotations

import logging
from typing import Any

from app.blocks.executor import register_implementation
from app.storage.memory import memory_store

logger = logging.getLogger("agentflow.blocks.interactive")


@register_implementation("ask_user_confirm")
async def ask_user_confirm(inputs: dict[str, Any]) -> dict[str, Any]:
    """Pause pipeline and ask user for confirmation.

    Auto-confirms for now, but records the confirmation request as a
    notification so users can see it on the Activity dashboard.
    """
    question = inputs["question"]
    details = inputs.get("details", {})
    context = inputs.get("__context", {})
    pipeline_id = context.get("pipeline_id")
    run_id = context.get("run_id")
    node_id = context.get("node_id")
    user_id = context.get("user_id")

    logger.info("User confirmation requested: %s (details: %s)", question, details)

    memory_store.add_notification({
        "user_id": user_id,
        "pipeline_id": pipeline_id,
        "run_id": run_id,
        "node_id": node_id,
        "title": "Confirmation Requested",
        "message": question,
        "level": "warning",
        "category": "confirmation",
        "metadata": {"details": details, "auto_confirmed": True},
    })

    return {
        "confirmed": True,
        "user_message": "Auto-confirmed (demo mode)",
    }


@register_implementation("present_summary_card")
async def present_summary_card(inputs: dict[str, Any]) -> dict[str, Any]:
    """Format data as a summary card for display. Persists to Activity dashboard."""
    title = inputs["title"]
    data = inputs["data"]
    highlight = inputs.get("highlight", "")
    context = inputs.get("__context", {})
    pipeline_id = context.get("pipeline_id")
    run_id = context.get("run_id")
    node_id = context.get("node_id")
    user_id = context.get("user_id")

    if isinstance(data, str):
        fields = [{"label": "Summary", "value": data}]
    elif isinstance(data, dict):
        fields = [
            {"label": key.replace("_", " ").title(), "value": str(value)}
            for key, value in data.items()
        ]
    else:
        fields = [{"label": "Data", "value": str(data)}]

    card = {"title": title, "fields": fields, "highlight": highlight}

    memory_store.add_notification({
        "user_id": user_id,
        "pipeline_id": pipeline_id,
        "run_id": run_id,
        "node_id": node_id,
        "title": title,
        "message": highlight or "Summary card generated",
        "level": "info",
        "category": "summary_card",
        "metadata": {"card": card},
    })

    return {"card": card}
