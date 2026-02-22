"""Activity endpoints — execution history and notifications (Supabase-backed)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.storage.memory import memory_store

router = APIRouter(prefix="/api", tags=["activity"])


@router.get("/executions")
async def list_executions(limit: int = 50) -> list[dict]:
    """List recent execution runs."""
    limit = min(limit, 500)
    rows = memory_store.list_executions(limit)
    return [
        {
            "run_id": r.get("run_id"),
            "pipeline_id": r.get("pipeline_id"),
            "pipeline_intent": r.get("pipeline_intent", "Unknown pipeline"),
            "node_count": r.get("node_count", 0),
            "status": r.get("status", "completed"),
            "finished_at": r.get("finished_at"),
        }
        for r in rows
    ]


@router.get("/executions/{run_id}")
async def get_execution(run_id: str) -> dict:
    """Get all node-level results for a specific run."""
    row = memory_store.get_execution(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Execution run not found")

    nodes = row.get("node_results", [])
    has_failure = any(n.get("status") == "failed" for n in nodes)
    return {
        "run_id": run_id,
        "pipeline_id": row.get("pipeline_id"),
        "status": "failed" if has_failure else "completed",
        "nodes": nodes,
    }


@router.get("/notifications")
async def list_notifications(limit: int = 50, unread_only: bool = False) -> list[dict]:
    """List notifications, newest first."""
    limit = min(limit, 500)
    rows = memory_store.list_notifications(limit)
    if unread_only:
        rows = [r for r in rows if not r.get("read")]
    return [
        {
            "id": r.get("id"),
            "pipeline_id": r.get("pipeline_id"),
            "run_id": r.get("run_id"),
            "node_id": r.get("node_id"),
            "title": r.get("title", ""),
            "message": r.get("message", r.get("body", "")),
            "level": r.get("level", "info"),
            "category": r.get("category", "notification"),
            "metadata": _coerce_metadata(r.get("metadata", {})),
            "read": bool(r.get("read", False)),
            "created_at": r.get("created_at"),
        }
        for r in rows
    ]


def _coerce_metadata(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int) -> dict:
    """Mark a notification as read."""
    memory_store.mark_notification_read(notification_id)
    return {"status": "ok"}
