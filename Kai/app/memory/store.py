from __future__ import annotations

import json
import logging
from typing import Any

from app.storage.memory import memory_store as _supabase_store

logger = logging.getLogger("agentflow.memory")


class MemoryStore:
    """Supabase-backed key-value store with namespaces."""

    def read(self, key: str, namespace: str = "default") -> Any | None:
        data = _supabase_store.get_memory(namespace) or {}
        return data.get(key)

    def write(self, key: str, value: Any, namespace: str = "default") -> None:
        data = _supabase_store.get_memory(namespace) or {}
        data[key] = value
        _supabase_store.save_memory(namespace, data)

    def append(self, key: str, value: Any, namespace: str = "default") -> int:
        existing = self.read(key, namespace)
        if existing is None:
            existing = []
        if not isinstance(existing, list):
            existing = [existing]
        existing.append(value)
        self.write(key, existing, namespace)
        return len(existing)

    def delete(self, key: str, namespace: str = "default") -> bool:
        data = _supabase_store.get_memory(namespace) or {}
        existed = key in data
        if existed:
            data.pop(key, None)
            _supabase_store.save_memory(namespace, data)
        return existed

    def list_keys(self, namespace: str = "default") -> list[str]:
        data = _supabase_store.get_memory(namespace) or {}
        return list(data.keys())

    def clear_namespace(self, namespace: str = "default") -> int:
        data = _supabase_store.get_memory(namespace) or {}
        count = len(data)
        _supabase_store.save_memory(namespace, {})
        return count


memory_store = MemoryStore()
