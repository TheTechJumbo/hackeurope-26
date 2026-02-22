"""Demo-style automation endpoints (clarify, create-agent, run pipeline)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.engine.clarifier import clarify
from app.engine.thinker_stream import run_thinker, run_thinker_stream
from app.engine.doer import run_pipeline
from app.storage.memory import memory_store

router = APIRouter(prefix="/api", tags=["automation"])


class ClarifyRequest(BaseModel):
    message: str
    history: list[dict] = []


class ClarifyResponseModel(BaseModel):
    ready: bool
    refined_intent: str | None = None
    question: str | None = None


class CreateAgentRequest(BaseModel):
    intent: str
    user_id: str


class CreateAgentResponse(BaseModel):
    pipeline_json: dict | None
    status: str
    log: list[dict]
    missing_blocks: list[dict]


class RunPipelineRequest(BaseModel):
    pipeline: dict
    user_id: str


class RunPipelineResponse(BaseModel):
    run_id: str
    status: str
    results: dict
    log: list[dict]


@router.post("/clarify", response_model=ClarifyResponseModel)
async def clarify_endpoint(req: ClarifyRequest):
    result = await clarify(req.message, req.history)
    return ClarifyResponseModel(
        ready=result.get("ready", True),
        refined_intent=result.get("refined_intent"),
        question=result.get("question"),
    )


@router.post("/create-agent", response_model=CreateAgentResponse)
async def create_agent(req: CreateAgentRequest):
    try:
        result = await run_thinker(req.intent, req.user_id)
    except NotImplementedError as e:
        raise HTTPException(501, detail=str(e))

    return CreateAgentResponse(
        pipeline_json=result.get("pipeline_json"),
        status=result.get("status", "done"),
        log=result.get("log", []),
        missing_blocks=result.get("missing_blocks", []),
    )


@router.post("/create-agent/stream")
async def create_agent_stream(req: CreateAgentRequest):
    return StreamingResponse(
        run_thinker_stream(req.intent, req.user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/pipeline/run", response_model=RunPipelineResponse)
async def run_pipeline_endpoint(req: RunPipelineRequest):
    try:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        result = await run_pipeline(req.pipeline, req.user_id, run_id=run_id, broadcast=True)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

    return RunPipelineResponse(
        run_id=run_id,
        status="completed",
        results=result.get("results", {}),
        log=result.get("log", []),
    )


@router.post("/automate")
async def automate(req: CreateAgentRequest):
    try:
        thinker_result = await run_thinker(req.intent, req.user_id)
    except NotImplementedError as e:
        raise HTTPException(501, detail=str(e))

    if thinker_result.get("status") != "done" or not thinker_result.get("pipeline_json"):
        return {
            "status": "failed",
            "reason": "Could not create pipeline",
            "missing_blocks": thinker_result.get("missing_blocks", []),
            "log": thinker_result.get("log", []),
        }

    try:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        doer_result = await run_pipeline(thinker_result["pipeline_json"], req.user_id, run_id=run_id, broadcast=True)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

    return {
        "status": "completed",
        "pipeline": thinker_result["pipeline_json"],
        "results": doer_result.get("results", {}),
        "log": thinker_result.get("log", []) + doer_result.get("log", []),
    }


@router.get("/memory/{user_id}")
async def get_memory(user_id: str):
    return memory_store.get_memory(user_id) or {}
