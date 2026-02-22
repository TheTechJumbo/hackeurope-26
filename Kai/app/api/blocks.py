"""Block registry endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import get_registry

router = APIRouter(prefix="/api", tags=["blocks"])


class BlockSearchRequest(BaseModel):
    query: str = Field(..., max_length=500)


def _normalize_block(block: dict) -> dict:
    metadata = block.get("metadata", {}) or {}
    return {
        "id": block["id"],
        "name": block.get("name", block["id"]),
        "description": block.get("description", ""),
        "category": block.get("category", "control"),
        "organ": block.get("organ", "system"),
        "input_schema": block.get("input_schema", {}),
        "output_schema": block.get("output_schema", {}),
        "api_type": block.get("api_type", "real"),
        "tier": metadata.get("tier", 1),
        "examples": block.get("examples", []),
    }


@router.get("/blocks")
async def list_blocks(category: str | None = None) -> list[dict]:
    """List all blocks, optionally filtered by category."""
    registry = get_registry()
    blocks = registry.list_all()
    if category:
        blocks = [b for b in blocks if b.get("category") == category]
    return [_normalize_block(b) for b in blocks]


@router.get("/blocks/{block_id}")
async def get_block(block_id: str) -> dict:
    """Get a block by ID."""
    registry = get_registry()
    try:
        block = registry.get(block_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Block not found")
    return _normalize_block(block)


@router.get("/blocks/{block_id}/source")
async def get_block_source(block_id: str) -> dict:
    """Return the source_code or prompt_template for a block."""
    registry = get_registry()
    try:
        block = registry.get(block_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Block not found")

    if block.get("source_code"):
        return {"source": block["source_code"], "type": "python"}
    if block.get("prompt_template"):
        return {"source": block["prompt_template"], "type": "llm"}
    raise HTTPException(status_code=404, detail="Block has no source code or prompt template")


@router.post("/blocks/search")
async def search_blocks(request: BlockSearchRequest) -> list[dict]:
    """Search blocks by keyword."""
    registry = get_registry()
    results = await registry.search(request.query)
    return [_normalize_block(b) for b in results]
