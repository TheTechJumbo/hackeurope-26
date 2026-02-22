"""Pipeline CRUD and execution endpoints (Supabase-backed)."""

from __future__ import annotations

import logging
from typing import Any
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.dependencies import get_registry
from app.engine.doer import run_pipeline
from app.engine.execution_utils import build_node_results
from app.engine.scheduler import list_scheduled, remove_schedule, schedule_pipeline
from app.storage.memory import memory_store

logger = logging.getLogger("agentflow.api.pipelines")
router = APIRouter(prefix="/api", tags=["pipelines"])


class PipelineCreate(BaseModel):
    pipeline: dict


class PipelineListItem(BaseModel):
    id: str
    user_intent: str
    status: str
    trigger_type: str
    node_count: int
    nodes: list[dict]
    edges: list[dict]
    trigger: dict


def _edges_to_engine(edges: list[dict]) -> list[dict]:
    converted = []
    for e in edges:
        converted.append({
            "from": e.get("from") or e.get("from_node"),
            "to": e.get("to") or e.get("to_node"),
            "condition": e.get("condition"),
        })
    return converted


def _edges_to_ui(edges: list[dict]) -> list[dict]:
    converted = []
    for e in edges:
        converted.append({
            "from_node": e.get("from") or e.get("from_node"),
            "to_node": e.get("to") or e.get("to_node"),
            "condition": e.get("condition"),
        })
    return converted


@router.post("/pipelines")
async def create_pipeline(request: PipelineCreate) -> dict[str, str]:
    """Store a pipeline definition."""
    p = request.pipeline
    pipeline_id = p.get("id") or f"pipe_{uuid.uuid4().hex[:10]}"

    trigger = p.get("trigger", {"type": p.get("trigger_type", "manual")})
    trigger_type = trigger.get("type", p.get("trigger_type", "manual"))

    nodes = p.get("nodes", [])
    edges_engine = _edges_to_engine(p.get("edges", []))

    memory_store.save_pipeline(pipeline_id, {
        "id": pipeline_id,
        "name": p.get("name", "Untitled"),
        "user_prompt": p.get("user_intent", p.get("user_prompt", "")),
        "user_id": p.get("user_id", "default_user"),
        "nodes": nodes,
        "edges": edges_engine,
        "memory_keys": p.get("memory_keys", []),
        "status": p.get("status", "created"),
        "trigger_type": trigger_type,
        "trigger": trigger,
    })

    # Auto-schedule cron/interval pipelines
    if trigger_type in {"cron", "interval"}:
        schedule_pipeline(
            pipeline_id,
            schedule=trigger.get("schedule"),
            interval_seconds=trigger.get("interval_seconds"),
        )
        logger.info("Auto-scheduled pipeline %s on creation", pipeline_id)

    return {"id": pipeline_id, "status": "created"}


@router.get("/pipelines", response_model=list[PipelineListItem])
async def list_pipelines() -> list[PipelineListItem]:
    """List all pipelines."""
    items = []
    for row in memory_store.list_pipelines():
        nodes = [{**n, "config": n.get("config", {})} for n in row.get("nodes", [])]
        items.append(PipelineListItem(
            id=row["id"],
            user_intent=row.get("user_prompt", ""),
            status=row.get("status", "created"),
            trigger_type=row.get("trigger_type", "manual"),
            node_count=len(nodes),
            nodes=nodes,
            edges=_edges_to_ui(row.get("edges", [])),
            trigger=row.get("trigger", {"type": row.get("trigger_type", "manual")}),
        ))
    return items


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str) -> dict[str, Any]:
    """Get a pipeline by ID."""
    row = memory_store.get_pipeline(pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    return {
        "id": row["id"],
        "user_intent": row.get("user_prompt", ""),
        "status": row.get("status", "created"),
        "definition": {
            **row,
            "nodes": [{**n, "config": n.get("config", {})} for n in row.get("nodes", [])],
            "edges": _edges_to_ui(row.get("edges", [])),
        },
        "created_at": row.get("created_at"),
    }


@router.post("/pipelines/{pipeline_id}/run")
async def run_pipeline_endpoint(pipeline_id: str) -> dict[str, Any]:
    """Execute a stored pipeline."""
    row = memory_store.get_pipeline(pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline = dict(row)
    pipeline["edges"] = row.get("edges", [])

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    result = await run_pipeline(pipeline, "default_user", run_id=run_id, broadcast=True)

    results_data = result.get("results", {})
    node_results, status, shared_context = build_node_results(pipeline, results_data)

    execution = {
        "run_id": run_id,
        "pipeline_id": pipeline_id,
        "pipeline_intent": row.get("user_prompt", row.get("name", "")),
        "pipeline_name": row.get("name", ""),
        "node_count": len(pipeline.get("nodes", [])),
        "status": status,
        "nodes": node_results,
        "shared_context": shared_context,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "user_id": "default_user",
    }
    memory_store.save_execution(run_id, execution)

    # Update pipeline status
    row["status"] = status
    memory_store.save_pipeline(pipeline_id, row)

    # Schedule recurring pipelines (cron/interval)
    trigger = row.get("trigger", {"type": row.get("trigger_type", "manual")})
    trigger_type = trigger.get("type", row.get("trigger_type", "manual"))
    if trigger_type in {"cron", "interval"}:
        schedule_pipeline(
            pipeline_id,
            schedule=trigger.get("schedule"),
            interval_seconds=trigger.get("interval_seconds"),
        )

    return {
        "pipeline_id": pipeline_id,
        "run_id": run_id,
        "status": status,
        "shared_context": execution["shared_context"],
        "node_results": node_results,
        "errors": [],
    }


@router.delete("/pipelines/{pipeline_id}")
async def delete_pipeline(pipeline_id: str) -> dict[str, str]:
    """Delete a pipeline."""
    remove_schedule(pipeline_id)
    memory_store.delete_pipeline(pipeline_id)
    return {"id": pipeline_id, "status": "deleted"}


@router.get("/schedules")
async def get_schedules() -> list[dict]:
    """List all actively scheduled pipeline jobs."""
    return list_scheduled()
