"""The Doer — executes Pipeline JSON as a parallel DAG.

Uses graphlib.TopologicalSorter for dependency ordering and
asyncio.gather for parallel execution of independent nodes.
"""

import asyncio
from graphlib import TopologicalSorter
from typing import Any

from app.engine.executor import execute_block
from app.engine.memory import load_memory, save_memory


async def run_pipeline(
    pipeline: dict,
    user_id: str,
    run_id: str | None = None,
    broadcast: bool = False,
) -> dict[str, Any]:
    """Execute a pipeline JSON — the core Doer.

    1. Build dependency graph from edges
    2. Load user memory
    3. Execute nodes in topological order, running independent nodes in parallel
    4. Save memory
    5. Return full state with results and log

    Args:
        pipeline: Pipeline JSON with "nodes" and "edges"
        user_id: The user running this pipeline

    Returns:
        {"pipeline_id": ..., "results": {...}, "log": [...]}
    """
    nodes_by_id = {n["id"]: n for n in pipeline["nodes"]}
    pipeline_id = pipeline.get("id", "unknown")

    # Build dependency graph: {node_id: set(dependency_ids)}
    graph: dict[str, set[str]] = {n["id"]: set() for n in pipeline["nodes"]}
    for edge in pipeline.get("edges", []):
        to_node = edge.get("to") or edge.get("to_node")
        from_node = edge.get("from") or edge.get("from_node")
        if to_node and from_node:
            graph[to_node].add(from_node)

    # Load memory
    user, memory = await load_memory(user_id)

    state: dict[str, Any] = {
        "user_id": user_id,
        "pipeline_id": pipeline_id,
        "run_id": run_id or "",
        "results": {},
        "user": user,
        "memory": memory,
        "log": [{"step": "_load_memory", "user_id": user_id}],
    }

    # Broadcast run_start (to both run_id and pipeline_id channels)
    if broadcast and run_id:
        await _broadcast(run_id, {
            "type": "run_start",
            "run_id": run_id,
            "pipeline_id": pipeline_id,
            "node_count": len(pipeline.get("nodes", [])),
        })
        await _broadcast(pipeline_id, {
            "type": "run_start",
            "run_id": run_id,
            "pipeline_id": pipeline_id,
            "node_count": len(pipeline.get("nodes", [])),
        })

    try:
        # Execute in topological order with parallel batching
        sorter = TopologicalSorter(graph)
        sorter.prepare()
        failed_nodes: set[str] = set()

        while sorter.is_active():
            ready = sorter.get_ready()
            if not ready:
                break

            # Run all ready nodes concurrently, skipping those with failed upstream
            tasks = []
            skipped = []
            for node_id in ready:
                upstream_failures = graph[node_id] & failed_nodes
                if upstream_failures:
                    failed_upstream = ", ".join(sorted(upstream_failures))
                    skipped.append((node_id, failed_upstream))
                else:
                    tasks.append((node_id, _execute_node(node_id, nodes_by_id[node_id], state)))

            # Mark skipped nodes
            for node_id, failed_upstream in skipped:
                state["results"][node_id] = {"error": f"Skipped: upstream node(s) {failed_upstream} failed"}
                state["log"].append({
                    "node": node_id,
                    "block": nodes_by_id[node_id].get("block_id"),
                    "error": f"Skipped: upstream node(s) {failed_upstream} failed",
                })
                failed_nodes.add(node_id)
                sorter.done(node_id)

            # Execute non-skipped nodes
            if tasks:
                if broadcast and run_id:
                    for node_id, _ in tasks:
                        await _broadcast(run_id, {"type": "node_start", "node_id": node_id, "run_id": run_id})
                        await _broadcast(pipeline_id, {"type": "node_start", "node_id": node_id, "run_id": run_id})

                results = await asyncio.gather(
                    *[coro for _, coro in tasks], return_exceptions=True
                )

                for (node_id, _), result in zip(tasks, results):
                    if isinstance(result, Exception):
                        state["results"][node_id] = {"error": str(result)}
                        state["log"].append({
                            "node": node_id,
                            "block": nodes_by_id[node_id].get("block_id"),
                            "error": str(result),
                        })
                        failed_nodes.add(node_id)
                    elif isinstance(result, dict) and "error" in result:
                        state["results"][node_id] = result
                        state["log"].append({
                            "node": node_id,
                            "block": nodes_by_id[node_id].get("block_id"),
                            "error": result["error"],
                        })
                        failed_nodes.add(node_id)
                    else:
                        state["results"][node_id] = result
                        state["log"].append({
                            "node": node_id,
                            "block": nodes_by_id[node_id].get("block_id"),
                            "output": result,
                        })
                    sorter.done(node_id)

                    if broadcast and run_id:
                        await _broadcast(run_id, {"type": "node_complete", "node_id": node_id, "run_id": run_id})
                        await _broadcast(pipeline_id, {"type": "node_complete", "node_id": node_id, "run_id": run_id})
    except Exception as exc:
        if broadcast and run_id:
            await _broadcast(run_id, {"type": "run_error", "run_id": run_id, "error": str(exc)})
            await _broadcast(pipeline_id, {"type": "run_error", "run_id": run_id, "error": str(exc)})
        raise

    # Save memory
    await save_memory(user_id, state["memory"], pipeline_id, state["results"])
    state["log"].append({"step": "_save_memory", "user_id": user_id})

    if broadcast and run_id:
        status = "failed" if failed_nodes else "completed"
        await _broadcast(run_id, {
            "type": "run_complete",
            "run_id": run_id,
            "status": status,
            "node_count": len(pipeline.get("nodes", [])),
        })
        await _broadcast(pipeline_id, {
            "type": "run_complete",
            "run_id": run_id,
            "status": status,
            "node_count": len(pipeline.get("nodes", [])),
        })

    return state


async def _execute_node(node_id: str, node_def: dict, state: dict) -> dict:
    """Execute a single node, passing current state for template resolution."""
    return await execute_block(node_def, state)


async def _broadcast(run_id: str, data: dict[str, Any]) -> None:
    """Broadcast a WebSocket message. Silently skips on failure."""
    try:
        from app.api.websocket import connection_manager
        await connection_manager.broadcast(run_id, data)
    except Exception:
        pass
