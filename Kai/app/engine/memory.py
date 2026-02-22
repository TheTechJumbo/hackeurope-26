"""Memory load/save helpers for the Doer pipeline — delegates to storage layer."""

from __future__ import annotations

from app.storage.memory import memory_store


async def load_memory(user_id: str) -> tuple[dict, dict]:
    """Load user profile and memory from storage. Returns (user_dict, memory_dict)."""
    return (
        {},  # user profile (not used yet, could query a users table)
        memory_store.get_memory(user_id) or {},
    )


async def save_memory(user_id: str, memory: dict, pipeline_id: str = "", results: dict | None = None):
    """Persist memory to storage."""
    memory_store.save_memory(user_id, memory)
