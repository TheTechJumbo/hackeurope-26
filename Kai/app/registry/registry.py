"""Block registry — Supabase-backed with hybrid search and TTL cache.

Single source of truth: every block lives in the Supabase `blocks` table.
No JSON files, no in-memory dicts except a short-lived cache.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.storage.supabase_client import get_supabase
from app.storage.embeddings import generate_embedding, block_to_search_text

logger = logging.getLogger(__name__)

# In-memory cache with TTL
_cache: dict[str, dict] = {}
_cache_ts: dict[str, float] = {}
_cache_all: list[dict] | None = None
_cache_all_ts: float = 0.0
CACHE_TTL = 300  # 5 minutes


def _row_to_block(row: dict) -> dict:
    """Convert a Supabase row to the block dict format used everywhere."""
    block = {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description", ""),
        "category": row.get("category", "process"),
        "execution_type": row.get("execution_type", "python"),
        "input_schema": row.get("input_schema", {}),
        "output_schema": row.get("output_schema", {}),
        "use_when": row.get("use_when"),
        "tags": row.get("tags", []),
        "examples": row.get("examples", []),
        "metadata": row.get("metadata", {}),
    }
    if row.get("prompt_template"):
        block["prompt_template"] = row["prompt_template"]
    if row.get("source_code"):
        block["source_code"] = row["source_code"]
    return block


class BlockRegistry:
    def get(self, block_id: str) -> dict:
        """Get a block by ID. Uses cache with TTL."""
        now = time.time()
        if block_id in _cache and (now - _cache_ts.get(block_id, 0)) < CACHE_TTL:
            return _cache[block_id]

        sb = get_supabase()
        result = sb.table("blocks").select("*").eq("id", block_id).execute()
        if not result.data:
            raise KeyError(f"Block not found: {block_id}")

        block = _row_to_block(result.data[0])
        _cache[block_id] = block
        _cache_ts[block_id] = now
        return block

    async def save(self, block: dict):
        """Save a block to Supabase (upsert). Generates embedding automatically."""
        sb = get_supabase()

        # Generate embedding
        search_text = block_to_search_text(block)
        embedding = await generate_embedding(search_text)

        row = {
            "id": block["id"],
            "name": block.get("name", block["id"].replace("_", " ").title()),
            "description": block.get("description", ""),
            "category": block.get("category", "process"),
            "execution_type": block.get("execution_type", "python"),
            "input_schema": block.get("input_schema", {}),
            "output_schema": block.get("output_schema", {}),
            "prompt_template": block.get("prompt_template"),
            "source_code": block.get("source_code"),
            "use_when": block.get("use_when"),
            "tags": block.get("tags", []),
            "examples": block.get("examples", []),
            "metadata": block.get("metadata", {}),
            "embedding": embedding,
        }

        sb.table("blocks").upsert(row).execute()

        # Update cache
        converted = _row_to_block(row)
        _cache[block["id"]] = converted
        _cache_ts[block["id"]] = time.time()
        _invalidate_list_cache()

        logger.info("Block %s saved to Supabase", block["id"])

    def list_all(self) -> list[dict]:
        """Return all blocks from Supabase."""
        global _cache_all, _cache_all_ts
        now = time.time()
        if _cache_all is not None and (now - _cache_all_ts) < CACHE_TTL:
            return _cache_all

        sb = get_supabase()
        result = sb.table("blocks").select("*").order("created_at").execute()
        blocks = [_row_to_block(r) for r in result.data]

        _cache_all = blocks
        _cache_all_ts = now

        # Warm individual cache too
        for b in blocks:
            _cache[b["id"]] = b
            _cache_ts[b["id"]] = now

        return blocks

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        """Hybrid search: full-text + semantic via Supabase RPC."""
        sb = get_supabase()

        try:
            # Generate query embedding for semantic search
            embedding = await generate_embedding(query)

            result = sb.rpc("search_blocks", {
                "query_text": query,
                "query_embedding": embedding,
                "match_limit": limit,
            }).execute()

            if result.data:
                return [_row_to_block(r) for r in result.data]
        except Exception as e:
            logger.warning("Hybrid search failed, falling back to text search: %s", e)

        # Fallback: simple text search
        return self._text_search(query)

    def _text_search(self, query: str) -> list[dict]:
        """Fallback case-insensitive search across all blocks."""
        q = query.lower()
        return [
            b for b in self.list_all()
            if q in b["id"].lower()
            or q in b["name"].lower()
            or q in b.get("description", "").lower()
            or any(q in tag.lower() for tag in b.get("tags", []))
        ]


def _invalidate_list_cache():
    global _cache_all, _cache_all_ts
    _cache_all = None
    _cache_all_ts = 0.0


registry = BlockRegistry()
