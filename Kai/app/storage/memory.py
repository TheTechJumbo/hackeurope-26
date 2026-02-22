"""Storage layer for pipelines, executions, notifications, and user memory.

Supabase is the single source of truth. Local JSON is kept only as an
optional fallback for development, but is not used by default.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings
from postgrest.exceptions import APIError

from app.storage.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_MISSING_PIPELINE_COLUMN_RE = re.compile(
    r'column "?pipelines"?(?:\.)?"?([a-zA-Z0-9_]+)"? does not exist'
)
_OPTIONAL_PIPELINE_COLUMNS = {"trigger", "webhook_path"}


def _missing_pipeline_columns(exc: Exception) -> list[str]:
    return _MISSING_PIPELINE_COLUMN_RE.findall(str(exc))


class StorageSettings(BaseSettings):
    storage_backend: str = "supabase"  # local | supabase
    local_storage_path: str = "storage/local_store.json"
    model_config = {"env_file": ".env", "extra": "ignore"}


class LocalStore:
    """Simple JSON-backed store for local development."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()

    def _default_state(self) -> dict[str, Any]:
        return {
            "users": {},
            "memory": {},
            "pipelines": {},
            "executions": {},
            "notifications": [],
            "counters": {"notifications": 1},
        }

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return self._default_state()
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            logger.warning("Failed to read local store, starting fresh: %s", exc)
            return self._default_state()
        if not isinstance(data, dict):
            return self._default_state()
        for key, default in self._default_state().items():
            data.setdefault(key, default)
        data.setdefault("counters", {}).setdefault("notifications", 1)
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=True, sort_keys=True)
        tmp_path.replace(self._path)

    # ── User Memory ──

    def get_memory(self, user_id: str) -> dict | None:
        with self._lock:
            data = self._load()
            return dict(data.get("memory", {}).get(user_id, {}))

    def save_memory(self, user_id: str, data: dict):
        with self._lock:
            store = self._load()
            store.setdefault("memory", {})[user_id] = data or {}
            self._save(store)

    # ── Pipelines ──

    def get_pipeline(self, pipeline_id: str) -> dict | None:
        with self._lock:
            store = self._load()
            pipeline = store.get("pipelines", {}).get(pipeline_id)
            return dict(pipeline) if pipeline else None

    def save_pipeline(self, pipeline_id: str, data: dict):
        with self._lock:
            store = self._load()
            pipelines = store.setdefault("pipelines", {})
            existing = pipelines.get(pipeline_id, {})
            now = datetime.now(timezone.utc).isoformat()

            pipeline = dict(data)
            pipeline.setdefault("id", pipeline_id)
            pipeline.setdefault("name", "Untitled")
            pipeline.setdefault("user_prompt", "")
            pipeline.setdefault("user_id", "default_user")
            pipeline.setdefault("nodes", [])
            pipeline.setdefault("edges", [])
            pipeline.setdefault("memory_keys", [])
            pipeline.setdefault("status", "created")
            pipeline.setdefault("trigger_type", "manual")
            pipeline["node_count"] = len(pipeline.get("nodes", []))
            pipeline["created_at"] = existing.get("created_at", now)
            pipeline["updated_at"] = now

            pipelines[pipeline_id] = pipeline
            self._save(store)

    def list_pipelines(self) -> list[dict]:
        with self._lock:
            store = self._load()
            pipelines = list(store.get("pipelines", {}).values())
        pipelines.sort(key=lambda p: p.get("created_at", ""), reverse=True)
        return [
            {
                "id": p.get("id"),
                "name": p.get("name", "Untitled"),
                "user_intent": p.get("user_prompt", ""),
                "user_prompt": p.get("user_prompt", ""),
                "status": p.get("status", "created"),
                "trigger_type": p.get("trigger_type", "manual"),
                "node_count": p.get("node_count", len(p.get("nodes", []))),
                "created_at": p.get("created_at", ""),
            }
            for p in pipelines
        ]

    def delete_pipeline(self, pipeline_id: str):
        with self._lock:
            store = self._load()
            pipelines = store.get("pipelines", {})
            pipelines.pop(pipeline_id, None)
            self._save(store)

    def get_pipeline_summary(self, pipeline_id: str) -> dict | None:
        return self.get_pipeline(pipeline_id)

    def save_pipeline_summary(self, pipeline_id: str, data: dict):
        self.save_pipeline(pipeline_id, data)

    def delete_pipeline_summary(self, pipeline_id: str):
        self.delete_pipeline(pipeline_id)

    # ── Executions ──

    def save_execution(self, run_id: str, data: dict):
        with self._lock:
            store = self._load()
            executions = store.setdefault("executions", {})
            execution = dict(data)
            execution.setdefault("run_id", run_id)
            execution.setdefault("finished_at", datetime.now(timezone.utc).isoformat())
            executions[run_id] = execution
            self._save(store)

    def list_executions(self, limit: int = 50) -> list[dict]:
        with self._lock:
            store = self._load()
            executions = list(store.get("executions", {}).values())
        executions.sort(key=lambda e: e.get("finished_at", ""), reverse=True)
        return executions[:limit]

    def get_execution(self, run_id: str) -> dict | None:
        with self._lock:
            store = self._load()
            execution = store.get("executions", {}).get(run_id)
            return dict(execution) if execution else None

    # ── Notifications ──

    def add_notification(self, notif: dict):
        with self._lock:
            store = self._load()
            notifications = store.setdefault("notifications", [])
            counters = store.setdefault("counters", {})
            next_id = counters.get("notifications", 1)

            notification = dict(notif)
            notification.setdefault("id", next_id)
            notification.setdefault("read", False)
            notification.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            notifications.append(notification)

            counters["notifications"] = next_id + 1
            self._save(store)

    def list_notifications(self, limit: int = 50) -> list[dict]:
        with self._lock:
            store = self._load()
            notifications = list(store.get("notifications", []))
        notifications.sort(key=lambda n: n.get("created_at", ""), reverse=True)
        return notifications[:limit]

    def mark_notification_read(self, notif_id: int):
        with self._lock:
            store = self._load()
            notifications = store.get("notifications", [])
            for notif in notifications:
                if notif.get("id") == notif_id:
                    notif["read"] = True
                    break
            self._save(store)


class SupabaseStore:
    """Persistent store backed by Supabase tables."""

    # ── User Memory ──

    def get_memory(self, user_id: str) -> dict | None:
        """Get all memory key-value pairs for a user."""
        sb = get_supabase()
        result = sb.table("user_memory").select("key, value").eq("user_id", user_id).execute()
        if not result.data:
            return {}
        memory = {}
        for row in result.data:
            val = row["value"]
            # value is stored as jsonb, so it may already be parsed
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
            memory[row["key"]] = val
        return memory

    def save_memory(self, user_id: str, data: dict):
        """Save full memory dict for a user (upserts each key)."""
        sb = get_supabase()
        for key, value in data.items():
            sb.table("user_memory").upsert({
                "user_id": user_id,
                "key": key,
                "value": json.dumps(value) if not isinstance(value, (str, int, float, bool)) else json.dumps(value),
            }).execute()

    # ── Pipelines ──

    def get_pipeline(self, pipeline_id: str) -> dict | None:
        sb = get_supabase()
        result = sb.table("pipelines").select("*").eq("id", pipeline_id).execute()
        if not result.data:
            return None
        row = result.data[0]
        return self._row_to_pipeline(row)

    def get_pipeline_by_webhook(self, webhook_path: str) -> dict | None:
        sb = get_supabase()
        try:
            result = sb.table("pipelines").select("*").eq("webhook_path", webhook_path).limit(1).execute()
        except APIError as exc:
            missing = _missing_pipeline_columns(exc)
            if missing and all(col in _OPTIONAL_PIPELINE_COLUMNS for col in missing) and "webhook_path" in missing:
                logger.warning("Supabase schema missing pipelines.webhook_path; webhook lookup disabled.")
                return None
            raise
        if not result.data:
            return None
        return self._row_to_pipeline(result.data[0])

    def save_pipeline(self, pipeline_id: str, data: dict):
        sb = get_supabase()
        trigger = data.get("trigger", {}) or {}
        row = {
            "id": pipeline_id,
            "name": data.get("name", "Untitled"),
            "user_prompt": data.get("user_prompt", ""),
            "user_id": data.get("user_id", "default_user"),
            "nodes": data.get("nodes", []),
            "edges": data.get("edges", []),
            "memory_keys": data.get("memory_keys", []),
            "status": data.get("status", "created"),
            "trigger_type": data.get("trigger_type", "manual"),
            "node_count": len(data.get("nodes", [])),
            "trigger": trigger,
            "webhook_path": trigger.get("webhook_path"),
        }
        try:
            sb.table("pipelines").upsert(row).execute()
        except APIError as exc:
            missing = _missing_pipeline_columns(exc)
            if missing and all(col in _OPTIONAL_PIPELINE_COLUMNS for col in missing):
                trimmed = {key: value for key, value in row.items() if key not in missing}
                logger.warning(
                    "Supabase schema missing pipelines columns: %s. Retrying without them.",
                    ", ".join(missing),
                )
                sb.table("pipelines").upsert(trimmed).execute()
                return
            raise

    def list_pipelines(self) -> list[dict]:
        sb = get_supabase()
        columns = [
            "id",
            "name",
            "user_prompt",
            "status",
            "trigger_type",
            "node_count",
            "created_at",
            "nodes",
            "edges",
            "trigger",
        ]
        try:
            result = sb.table("pipelines").select(", ".join(columns)).order("created_at", desc=True).execute()
        except APIError as exc:
            missing = _missing_pipeline_columns(exc)
            if missing and all(col in _OPTIONAL_PIPELINE_COLUMNS for col in missing):
                fallback_columns = [col for col in columns if col not in missing]
                logger.warning(
                    "Supabase schema missing pipelines columns: %s. Retrying without them.",
                    ", ".join(missing),
                )
                result = sb.table("pipelines").select(", ".join(fallback_columns)).order("created_at", desc=True).execute()
            else:
                raise
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "user_intent": r.get("user_prompt", ""),
                "user_prompt": r.get("user_prompt", ""),
                "status": r.get("status", "created"),
                "trigger_type": r.get("trigger_type", "manual"),
                "node_count": r.get("node_count", 0),
                "created_at": r.get("created_at", ""),
                "nodes": r.get("nodes", []),
                "edges": r.get("edges", []),
                "trigger": r.get("trigger", {"type": r.get("trigger_type", "manual")}),
            }
            for r in (result.data or [])
        ]

    def delete_pipeline(self, pipeline_id: str):
        sb = get_supabase()
        sb.table("pipelines").delete().eq("id", pipeline_id).execute()

    # Aliases for backward compatibility with main.py
    def get_pipeline_summary(self, pipeline_id: str) -> dict | None:
        return self.get_pipeline(pipeline_id)

    def save_pipeline_summary(self, pipeline_id: str, data: dict):
        # Pipeline summary is now just the pipeline row itself
        self.save_pipeline(pipeline_id, data)

    def delete_pipeline_summary(self, pipeline_id: str):
        self.delete_pipeline(pipeline_id)

    # ── Executions ──

    def save_execution(self, run_id: str, data: dict):
        sb = get_supabase()
        finished_at = data.get("finished_at") or datetime.now(timezone.utc).isoformat()
        row = {
            "run_id": run_id,
            "pipeline_id": data.get("pipeline_id"),
            "pipeline_name": data.get("pipeline_name", ""),
            "pipeline_intent": data.get("pipeline_intent", ""),
            "user_id": data.get("user_id", "default_user"),
            "status": data.get("status", "completed"),
            "node_count": data.get("node_count", 0),
            "node_results": data.get("nodes", []),
            "shared_context": data.get("shared_context", {}),
            "errors": data.get("errors", []),
            "finished_at": finished_at,
        }
        sb.table("executions").upsert(row).execute()

    def list_executions(self, limit: int = 50) -> list[dict]:
        sb = get_supabase()
        result = sb.table("executions").select("*").order("finished_at", desc=True).limit(limit).execute()
        return result.data or []

    def get_execution(self, run_id: str) -> dict | None:
        sb = get_supabase()
        result = sb.table("executions").select("*").eq("run_id", run_id).execute()
        if not result.data:
            return None
        return result.data[0]

    def get_last_execution_for_pipeline(self, pipeline_id: str) -> dict | None:
        sb = get_supabase()
        result = sb.table("executions").select("*").eq("pipeline_id", pipeline_id).order("finished_at", desc=True).limit(1).execute()
        if not result.data:
            return None
        return result.data[0]

    # ── Notifications ──

    def add_notification(self, notif: dict):
        sb = get_supabase()
        result = sb.table("notifications").insert({
            "user_id": notif.get("user_id", "default_user"),
            "pipeline_id": notif.get("pipeline_id"),
            "run_id": notif.get("run_id"),
            "node_id": notif.get("node_id"),
            "title": notif.get("title", ""),
            "message": notif.get("message", ""),
            "level": notif.get("level", "info"),
            "category": notif.get("category", "notification"),
            "metadata": notif.get("metadata", {}),
            "read": bool(notif.get("read", False)),
        }).execute()

        # Best-effort SSE push
        try:
            from app.api.sse import notification_bus
            notif_id = None
            if result.data:
                notif_id = result.data[0].get("id")
            notification_bus_payload = {
                "id": notif_id or notif.get("id"),
                "pipeline_id": notif.get("pipeline_id"),
                "run_id": notif.get("run_id"),
                "node_id": notif.get("node_id"),
                "title": notif.get("title", ""),
                "message": notif.get("message", ""),
                "level": notif.get("level", "info"),
                "category": notif.get("category", "notification"),
            }
            # Publish asynchronously without blocking
            import asyncio
            asyncio.create_task(notification_bus.publish(notification_bus_payload))
        except Exception:
            logger.debug("SSE push failed for notification insert", exc_info=True)

    def list_notifications(self, limit: int = 50) -> list[dict]:
        sb = get_supabase()
        result = sb.table("notifications").select("*").order("created_at", desc=True).limit(limit).execute()
        data = result.data or []
        # Normalize legacy "body" field -> "message"
        for row in data:
            if "message" not in row and "body" in row:
                row["message"] = row.get("body", "")
        return data

    def mark_notification_read(self, notif_id: int):
        sb = get_supabase()
        sb.table("notifications").update({"read": True}).eq("id", notif_id).execute()

    # ── Chat Sessions ──

    def get_chat_session(self, session_id: str) -> list[dict]:
        sb = get_supabase()
        result = sb.table("chat_sessions").select("history").eq("id", session_id).execute()
        if not result.data:
            return []
        history = result.data[0].get("history", [])
        if isinstance(history, str):
            try:
                return json.loads(history)
            except json.JSONDecodeError:
                return []
        return history or []

    def save_chat_session(self, session_id: str, history: list[dict]) -> None:
        sb = get_supabase()
        sb.table("chat_sessions").upsert({
            "id": session_id,
            "history": history,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

    def delete_chat_session(self, session_id: str) -> None:
        sb = get_supabase()
        sb.table("chat_sessions").delete().eq("id", session_id).execute()

    # ── Helpers ──

    @staticmethod
    def _row_to_pipeline(row: dict) -> dict:
        """Convert a Supabase pipeline row to the dict format used by the engine."""
        return {
            "id": row["id"],
            "name": row.get("name", "Untitled"),
            "user_prompt": row.get("user_prompt", ""),
            "nodes": row.get("nodes", []),
            "edges": row.get("edges", []),
            "memory_keys": row.get("memory_keys", []),
            "status": row.get("status", "created"),
            "trigger_type": row.get("trigger_type", "manual"),
            "trigger": row.get("trigger", {"type": row.get("trigger_type", "manual")}),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }


def _select_store() -> LocalStore | SupabaseStore:
    settings = StorageSettings()
    backend = settings.storage_backend.lower().strip()

    if backend == "local":
        return LocalStore(Path(settings.local_storage_path))

    # Default: Supabase only
    return SupabaseStore()


memory_store = _select_store()
