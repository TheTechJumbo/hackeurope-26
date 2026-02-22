"""Shared dependencies for API routers."""

from __future__ import annotations

from functools import lru_cache

from app.blocks.loader import load_all_implementations
from app.registry.registry import BlockRegistry
from app.registry.registry import registry as supabase_registry


@lru_cache(maxsize=1)
def get_registry() -> BlockRegistry:
    """Return the singleton BlockRegistry with all implementations loaded."""
    registry = supabase_registry
    load_all_implementations()
    return registry
