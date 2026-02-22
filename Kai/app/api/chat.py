"""POST /api/chat — Natural language -> pipeline via Orchestra Agent."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.builder import BuilderAgent
from app.agents.orchestra import OrchestraAgent
from app.api.dependencies import get_registry
from app.database import get_db
from app.engine.runner import PipelineRunner
from app.memory.store import memory_store

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
    with get_db() as conn:
        row = conn.execute(
            "SELECT history FROM chat_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if row:
        return json.loads(row["history"])
    return []


def _save_session(session_id: str, history: list[dict[str, str]]) -> None:
    """Upsert a chat session with updated history."""
    history_json = json.dumps(history)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO chat_sessions (id, history, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(id) DO UPDATE SET history = ?, updated_at = datetime('now')""",
            (session_id, history_json, history_json),
        )
        conn.commit()


def _delete_session(session_id: str) -> None:
    """Clean up a completed session."""
    with get_db() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        conn.commit()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Decompose a natural language request into a pipeline and optionally execute it.

    Supports multi-turn clarification: if the Orchestra Agent needs more info,
    it returns a clarification response with questions. The frontend sends the
    user's answer back with the same session_id.
    """
    registry = get_registry()
    orchestra = OrchestraAgent(registry)

    # Load conversation history if this is a follow-up
    conversation_history: list[dict[str, str]] = []
    session_id = request.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    if request.session_id:
        conversation_history = _load_session(request.session_id)

    # Decompose with conversation context
    try:
        decomposition = await orchestra.decompose(
            request.message,
            conversation_history=conversation_history or None,
        )
    except (RuntimeError, ValueError) as e:
        logger.exception("Decomposition failed for message: %.200s", request.message)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        logger.exception("Decomposition failed for message: %.200s", request.message)
        raise HTTPException(
            status_code=500,
            detail="Failed to decompose your request. Please try rephrasing.",
        )

    # Handle clarification response
    if decomposition.get("type") == "clarification":
        # Save conversation so far: user message + assistant clarification
        conversation_history.append({"role": "user", "content": request.message})
        conversation_history.append({
            "role": "assistant",
            "content": json.dumps(decomposition),
        })
        _save_session(session_id, conversation_history)

        return ChatResponse(
            response_type="clarification",
            session_id=session_id,
            clarification_message=decomposition.get("message", "I need more details:"),
            questions=decomposition.get("questions", []),
        )

    # Pipeline response — handle missing blocks
    missing = decomposition.get("missing_blocks", [])
    if missing:
        builder = BuilderAgent(registry)
        await builder.create_missing_blocks(missing)

    # Build pipeline
    pipeline = orchestra.build_pipeline(request.message, decomposition)

    # Clean up session if it existed (conversation complete)
    if request.session_id:
        _delete_session(request.session_id)

    response = ChatResponse(
        response_type="pipeline",
        pipeline_id=pipeline.id,
        user_intent=pipeline.user_intent,
        trigger_type=pipeline.trigger.type.value,
        trigger=pipeline.trigger.model_dump(),
        nodes=[n.model_dump() for n in pipeline.nodes],
        edges=[e.model_dump() for e in pipeline.edges],
        missing_blocks=missing,
        session_id=session_id,
    )

    # Auto-execute if requested
    if request.auto_execute:
        runner = PipelineRunner(registry=registry, memory=memory_store)
        result = await runner.run(pipeline)
        response.execution_result = result.model_dump()

    return response
