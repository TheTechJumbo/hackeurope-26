"""State definitions for the Thinker and Doer pipelines.

Plain TypedDicts — no framework-specific reducers needed.
"""

from __future__ import annotations

from typing import Any, TypedDict


class ThinkerState(TypedDict):
    # ── Input ──
    user_intent: str
    user_id: str

    # ── Decomposition ──
    required_blocks: list[dict]

    # ── Matching ──
    matched_blocks: list[dict]
    missing_blocks: list[dict]

    # ── Pipeline construction ──
    pipeline_json: dict | None

    # ── Control ──
    status: str  # "decomposing" | "matching" | "wiring" | "done" | "error"
    error: str | None
    log: list[dict]


class PipelineState(TypedDict):
    user_id: str
    pipeline_id: str

    # ── DATA BUS ── every block reads/writes here
    # {"n1": {"results": [...]}, "n2": {"summary": "..."}}
    results: dict[str, Any]

    user: dict[str, Any]
    memory: dict[str, Any]
    log: list[dict]
