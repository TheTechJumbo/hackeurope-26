"""POST /api/chat — Natural language -> pipeline via Demo Thinker."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import get_registry
from app.engine.clarifier import clarify
from app.engine.thinker_stream import run_thinker
from app.engine.doer import run_pipeline
from app.engine.execution_utils import build_node_results
from app.storage.memory import memory_store

logger = logging.getLogger("agentflow.api.chat")
router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="Natural language automation request")
    auto_execute: bool = Field(default=False, description="Execute immediately without approval")
    session_id: str | None = Field(default=None, description="Session ID for multi-turn conversations")


class ChatResponse(BaseModel):
    response_type: str = "pipeline"  # "pipeline" | "clarification"
    pipeline_id: str = ""
    user_intent: str = ""
    trigger_type: str = ""
    trigger: dict[str, Any] = {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    missing_blocks: list[dict[str, Any]] = []
    execution_result: dict[str, Any] | None = None
    # Clarification fields
    session_id: str = ""
    clarification_message: str = ""
    questions: list[str] = []


def _load_session(session_id: str) -> list[dict[str, str]]:
    """Load conversation history from a chat session."""
    return memory_store.get_chat_session(session_id)


def _save_session(session_id: str, history: list[dict[str, str]]) -> None:
    """Upsert a chat session with updated history."""
    memory_store.save_chat_session(session_id, history)


def _delete_session(session_id: str) -> None:
    """Clean up a completed session."""
    memory_store.delete_chat_session(session_id)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Decompose a natural language request into a pipeline and optionally execute it.

    Uses Demo clarifier + thinker. Supports multi-turn clarification via
    stored chat sessions in Supabase.
    """
    get_registry()  # ensure registry/implementations are loaded

    # Load conversation history if this is a follow-up
    conversation_history: list[dict[str, str]] = []
    session_id = request.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    if request.session_id:
        conversation_history = _load_session(request.session_id)

    # Clarify intent if needed
    try:
        clarification = await clarify(request.message, conversation_history)
    except Exception as e:
        logger.exception("Clarification failed for message: %.200s", request.message)
        raise HTTPException(status_code=500, detail=str(e))

    if not clarification.get("ready", True):
        conversation_history.append({"role": "user", "content": request.message})
        conversation_history.append({
            "role": "assistant",
            "content": clarification.get("question", ""),
        })
        _save_session(session_id, conversation_history)

        return ChatResponse(
            response_type="clarification",
            session_id=session_id,
            clarification_message=clarification.get("question", "I need more details:"),
            questions=[clarification.get("question", "")],
        )

    refined_intent = clarification.get("refined_intent") or request.message

    # Run thinker (non-streaming)
    try:
        thinker_result = await run_thinker(refined_intent, "default_user")
    except Exception as e:
        logger.exception("Thinker failed for message: %.200s", refined_intent)
        raise HTTPException(status_code=500, detail=str(e))

    pipeline_json = thinker_result.get("pipeline_json") or {}
    if not pipeline_json:
        raise HTTPException(status_code=500, detail="Failed to create pipeline")

    # Convert edges to Kai shape for UI
    nodes = pipeline_json.get("nodes", [])
    edges = pipeline_json.get("edges", [])
    edges_ui = [{"from_node": e.get("from"), "to_node": e.get("to"), "condition": e.get("condition")} for e in edges]

    pipeline_id = pipeline_json.get("id", f"pipe_{uuid.uuid4().hex[:10]}")
    pipeline_json["id"] = pipeline_id

    # Clean up session if it existed (conversation complete)
    if request.session_id:
        _delete_session(request.session_id)

    response = ChatResponse(
        response_type="pipeline",
        pipeline_id=pipeline_id,
        user_intent=refined_intent,
        trigger_type="manual",
        trigger={"type": "manual"},
        nodes=[{**n, "config": n.get("config", {})} for n in nodes],
        edges=edges_ui,
        missing_blocks=[],
        session_id=session_id,
    )

    # Auto-execute if requested
    if request.auto_execute:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        result = await run_pipeline(pipeline_json, "default_user", run_id=run_id, broadcast=True)
        node_results, status, shared_context = build_node_results(pipeline_json, result.get("results", {}))
        memory_store.save_execution(run_id, {
            "run_id": run_id,
            "pipeline_id": pipeline_id,
            "pipeline_intent": refined_intent,
            "pipeline_name": pipeline_json.get("name", ""),
            "node_count": len(pipeline_json.get("nodes", [])),
            "status": status,
            "nodes": node_results,
            "shared_context": shared_context,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "user_id": "default_user",
        })
        response.execution_result = {
            "pipeline_id": pipeline_id,
            "run_id": run_id,
            "status": status,
            "shared_context": shared_context,
            "node_results": node_results,
            "errors": [],
        }

    return response
