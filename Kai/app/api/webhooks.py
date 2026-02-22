"""Webhook and file upload trigger endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, File

from app.engine.doer import run_pipeline
from app.engine.execution_utils import build_node_results
from app.storage.memory import memory_store

router = APIRouter(prefix="/api", tags=["triggers"])

logger = logging.getLogger("agentflow.api.webhooks")

UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/webhooks/{webhook_path:path}")
async def receive_webhook(webhook_path: str, request: Request) -> dict[str, Any]:
    """Receive an incoming webhook and trigger the associated pipeline."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            body = {}
    else:
        body = {}

    logger.info("Webhook received at /%s", webhook_path)

    pipeline = memory_store.get_pipeline_by_webhook(webhook_path)
    if not pipeline:
        return {
            "received": True,
            "webhook_path": webhook_path,
            "payload": body,
            "trigger_id": f"wh_{uuid.uuid4().hex[:8]}",
            "status": "no_pipeline",
        }

    # Inject webhook payload into trigger_webhook nodes
    pipeline = dict(pipeline)
    updated_nodes = []
    for node in pipeline.get("nodes", []):
        if node.get("block_id") == "trigger_webhook":
            inputs = dict(node.get("inputs", {}))
            inputs.update({
                "payload": body,
                "headers": dict(request.headers),
                "method": request.method,
            })
            updated_nodes.append({**node, "inputs": inputs})
        else:
            updated_nodes.append(node)
    pipeline["nodes"] = updated_nodes

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    try:
        result = await run_pipeline(pipeline, "default_user", run_id=run_id, broadcast=True)
        node_results, status, shared_context = build_node_results(pipeline, result.get("results", {}))
        memory_store.save_execution(run_id, {
            "run_id": run_id,
            "pipeline_id": pipeline.get("id"),
            "pipeline_intent": pipeline.get("user_prompt", pipeline.get("name", "")),
            "pipeline_name": pipeline.get("name", ""),
            "node_count": len(pipeline.get("nodes", [])),
            "status": status,
            "nodes": node_results,
            "shared_context": shared_context,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "user_id": "default_user",
        })
    except Exception as e:
        logger.exception("Webhook pipeline execution failed: %s", e)

    return {
        "received": True,
        "webhook_path": webhook_path,
        "payload": body,
        "trigger_id": f"wh_{uuid.uuid4().hex[:8]}",
        "pipeline_id": pipeline.get("id"),
        "run_id": run_id,
    }


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a file and return metadata for trigger_file_upload."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    # Sanitize filename: strip directory components, allowlist characters
    original_name = Path(file.filename or "upload").name
    safe_name = re.sub(r'[^\w.\-]', '_', original_name)
    safe_filename = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    file_path = UPLOAD_DIR / safe_filename

    # Verify resolved path is inside upload directory
    if not file_path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")

    with open(file_path, "wb") as f:
        f.write(content)

    logger.info("File uploaded: %s (%d bytes)", safe_filename, len(content))

    return {
        "file_id": safe_filename,
        "file_type": file.content_type or "application/octet-stream",
        "file_size_bytes": len(content),
    }
