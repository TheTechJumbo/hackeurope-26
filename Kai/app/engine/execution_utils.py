"""Helpers for building execution records from pipeline runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_node_results(pipeline: dict, results: dict) -> tuple[list[dict[str, Any]], str, dict]:
    node_results: list[dict[str, Any]] = []
    shared_context = results if isinstance(results, dict) else {}

    for node in pipeline.get("nodes", []):
        node_id = node.get("id")
        node_output = shared_context.get(node_id)
        node_error = None
        status = "completed"
        if node_output is None or (isinstance(node_output, dict) and "error" in node_output):
            status = "failed"
            node_error = node_output.get("error") if isinstance(node_output, dict) else "no output"
        node_results.append({
            "id": len(node_results) + 1,
            "node_id": node_id,
            "status": status,
            "output_data": node_output,
            "error": node_error,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })

    overall_status = "completed" if all(n["status"] == "completed" for n in node_results) else "failed"
    return node_results, overall_status, shared_context
