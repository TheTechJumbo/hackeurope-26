"""The Thinker — takes user intent, produces Pipeline JSON via SSE stream.

Pipeline: decompose → search → create (if missing) → wire

Yields SSE events between each LLM call so the frontend can show live
progress. Shared helpers (prompts, block finalization, testing) live in
thinker.py.
"""

import asyncio
import json
import time
from typing import AsyncGenerator

from app.engine.schemas import validate_stage_output
from app.engine.state import ThinkerState
from app.engine.thinker import (
    _finalize_created_block,
    _is_good_match,
    _test_block,
    build_create_block_prompt,
    build_decompose_prompts,
    build_wire_prompts,
)
from app.llm.service import call_llm, parse_json_output
from app.registry.registry import registry


def _event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    payload = json.dumps({"type": event_type, "ts": time.time(), **data})
    return f"event: {event_type}\ndata: {payload}\n\n"


async def run_thinker_stream(intent: str, user_id: str) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE events for each Thinker stage."""

    state: ThinkerState = {
        "user_intent": intent,
        "user_id": user_id,
        "required_blocks": [],
        "matched_blocks": [],
        "missing_blocks": [],
        "pipeline_json": None,
        "status": "decomposing",
        "error": None,
        "log": [],
    }

    yield _event("start", {"intent": intent, "user_id": user_id})
    await asyncio.sleep(0)

    # ── Stage 1: DECOMPOSE ──
    yield _event("stage", {"stage": "decompose", "status": "running",
                           "message": "Breaking intent into atomic blocks..."})
    await asyncio.sleep(0)

    system, user = build_decompose_prompts(intent)

    yield _event("llm_prompt", {"stage": "decompose", "system": system, "user": user})
    await asyncio.sleep(0)

    t0 = time.time()
    response = await call_llm(system=system, user=user)
    elapsed = round(time.time() - t0, 2)

    yield _event("llm_response", {"stage": "decompose", "raw": response, "elapsed_s": elapsed})
    await asyncio.sleep(0)

    parsed = parse_json_output(response)
    required_blocks = parsed.get("required_blocks", [])

    state = {
        **state,
        "required_blocks": required_blocks,
        "status": "searching",
        "log": state["log"] + [{"step": "decompose", "required_blocks": required_blocks}],
    }

    yield _event("stage_result", {
        "stage": "decompose",
        "status": "done",
        "required_blocks": required_blocks,
        "count": len(required_blocks),
    })
    await asyncio.sleep(0)

    # Emit decompose_blocks summary for the UI
    yield _event("decompose_blocks", {
        "blocks": [
            {"suggested_id": b.get("suggested_id", "?"),
             "description": b.get("description", ""),
             "execution_type": b.get("execution_type", "python")}
            for b in required_blocks
        ]
    })
    await asyncio.sleep(0)

    try:
        validate_stage_output("decompose", {"required_blocks": required_blocks})
        yield _event("validation", {"stage": "decompose", "valid": True})
    except Exception as e:
        yield _event("validation", {"stage": "decompose", "valid": False, "error": str(e)})
    await asyncio.sleep(0)

    # ── Stage 2: SEARCH ──
    yield _event("stage", {"stage": "search", "status": "running",
                           "message": "Searching registry for matching blocks..."})
    await asyncio.sleep(0)

    matched = []
    missing = []
    for req in state["required_blocks"]:
        description = req.get("description", "")
        suggested_id = req.get("suggested_id", req.get("block_id", "?"))

        # Search by description only — compare desired functionality to existing
        query = description or suggested_id.replace("_", " ")

        # Hybrid search in Supabase
        candidates = await registry.search(query, limit=5)

        # Find the best match
        found = False
        for candidate in candidates:
            if _is_good_match(candidate, req):
                matched.append(candidate)
                yield _event("search_found", {
                    "suggested_id": suggested_id,
                    "matched_block_id": candidate["id"],
                    "name": candidate["name"],
                    "description": candidate.get("description", description),
                    "block_def": candidate,
                })
                found = True
                break

        if not found:
            missing.append(req)
            yield _event("search_missing", {
                "suggested_id": suggested_id,
                "description": description or "new block",
                "candidates_checked": len(candidates),
            })
        await asyncio.sleep(0)

    state = {
        **state,
        "matched_blocks": matched,
        "missing_blocks": missing,
        "status": "creating" if missing else "wiring",
        "log": state["log"] + [{
            "step": "search",
            "matched": [b["id"] for b in matched],
            "missing": [m.get("suggested_id") or m.get("block_id", "?") for m in missing],
        }],
    }

    yield _event("stage_result", {
        "stage": "search",
        "status": "done",
        "matched": len(matched),
        "missing": len(missing),
        "next": "create" if missing else "wire",
    })
    await asyncio.sleep(0)

    # ── Stage 3: CREATE (if needed) ──
    if not state["missing_blocks"]:
        yield _event("stage", {"stage": "create", "status": "skipped",
                                "message": "All blocks found in registry — skipping create."})
        await asyncio.sleep(0)
        yield _event("stage_result", {"stage": "create", "status": "skipped"})
        await asyncio.sleep(0)

    if state["status"] == "creating" and state["missing_blocks"]:
        yield _event("stage", {"stage": "create", "status": "running",
                               "message": f"Creating {len(missing)} new block(s)..."})
        await asyncio.sleep(0)

        created = []
        creation_failures = []
        for i, spec in enumerate(state["missing_blocks"]):
            block_name = spec.get("suggested_id", f"block_{i}")
            yield _event("creating_block", {
                "index": i,
                "total": len(state["missing_blocks"]),
                "suggested_id": block_name,
                "description": spec.get("description", ""),
            })
            await asyncio.sleep(0)

            system, user = build_create_block_prompt(spec)

            yield _event("llm_prompt", {"stage": f"create:{block_name}", "system": system, "user": user})
            await asyncio.sleep(0)

            t0 = time.time()
            response = await call_llm(system=system, user=user)
            elapsed = round(time.time() - t0, 2)

            yield _event("llm_response", {"stage": f"create:{block_name}", "raw": response, "elapsed_s": elapsed})
            await asyncio.sleep(0)

            parsed = parse_json_output(response)

            try:
                parsed = _finalize_created_block(parsed, spec)
            except (SyntaxError, ValueError) as exc:
                # Finalize failed (compile error or missing source_code) — treat as test failure
                # so the retry loop below can fix it
                error = str(exc)
                block_id = parsed.get("id", spec.get("suggested_id", f"block_{i}"))
                yield _event("block_test_failed", {"block_id": block_id, "error": error, "retry": True})
                await asyncio.sleep(0)
                # Retry creation with error context
                retry_user = (
                    f"{user}\n\nIMPORTANT: The previous version failed with this error:\n"
                    f"{error}\n\nFix the code so it does not produce this error. "
                    f"You MUST include a 'source_code' field with valid Python."
                )
                response = await call_llm(system=system, user=retry_user)
                parsed = parse_json_output(response)
                try:
                    parsed = _finalize_created_block(parsed, spec)
                except (SyntaxError, ValueError):
                    # Second finalize failure — will be caught by test loop
                    parsed.setdefault("id", spec.get("suggested_id", f"block_{i}"))
                    parsed["execution_type"] = "python"
                    parsed.setdefault("source_code", "async def execute(inputs, context):\n    return {}\n")

            block_id = parsed["id"]

            yield _event("block_created", {
                "block_id": block_id,
                "name": parsed["name"],
                "description": parsed.get("description", ""),
                "execution_type": parsed["execution_type"],
                "has_prompt": bool(parsed.get("prompt_template")),
                "has_source_code": bool(parsed.get("source_code")),
                "block_def": parsed,
            })
            await asyncio.sleep(0)

            # Test block with sample inputs — retry up to 3 times
            MAX_TEST_RETRIES = 3
            passed, error = await _test_block(parsed)
            retry_user = user
            for attempt in range(1, MAX_TEST_RETRIES + 1):
                if passed:
                    yield _event("block_test_passed", {"block_id": block_id})
                    await asyncio.sleep(0)
                    break

                will_retry = attempt < MAX_TEST_RETRIES
                yield _event("block_test_failed", {"block_id": block_id, "error": error, "retry": will_retry})
                await asyncio.sleep(0)

                if not will_retry:
                    parsed.setdefault("metadata", {})
                    parsed["metadata"]["test_passed"] = False
                    break

                # Retry creation with error context
                retry_user = (
                    f"{retry_user}\n\nIMPORTANT: The previous version failed at runtime with this error:\n"
                    f"{error}\n\nFix the code so it does not produce this error."
                )
                response = await call_llm(system=system, user=retry_user)
                parsed = parse_json_output(response)
                try:
                    parsed = _finalize_created_block(parsed, spec)
                except (SyntaxError, ValueError) as exc:
                    error = str(exc)
                    passed = False
                    continue
                block_id = parsed["id"]
                passed, error = await _test_block(parsed)

            if parsed.get("metadata", {}).get("test_passed") is False:
                creation_failures.append(block_id)
                yield _event("block_create_failed", {
                    "block_id": block_id,
                    "error": error,
                    "message": "Block failed all test retries — not saved to registry.",
                })
                await asyncio.sleep(0)
            else:
                await registry.save(parsed)
                created.append(parsed)

        state = {
            **state,
            "matched_blocks": state["matched_blocks"] + created,
            "missing_blocks": [],
            "status": "wiring",
            "log": state["log"] + [{
                "step": "create",
                "created": [b["id"] for b in created],
                "failed": creation_failures,
            }],
        }

        yield _event("stage_result", {
            "stage": "create",
            "status": "done",
            "created": [b["id"] for b in created],
            "failed": creation_failures,
        })
        await asyncio.sleep(0)

    # ── Stage 4: WIRE ──
    yield _event("stage", {"stage": "wire", "status": "running",
                           "message": "Wiring blocks into executable pipeline..."})
    await asyncio.sleep(0)

    system, user = build_wire_prompts(state["user_intent"], state["matched_blocks"])

    yield _event("llm_prompt", {"stage": "wire", "system": system, "user": user})
    await asyncio.sleep(0)

    t0 = time.time()
    response = await call_llm(system=system, user=user)
    elapsed = round(time.time() - t0, 2)

    yield _event("llm_response", {"stage": "wire", "raw": response, "elapsed_s": elapsed})
    await asyncio.sleep(0)

    parsed = parse_json_output(response)

    parsed.setdefault("id", "pipeline_generated")
    parsed.setdefault("name", "Generated Pipeline")
    parsed.setdefault("user_prompt", state["user_intent"])
    parsed.setdefault("nodes", [])
    parsed.setdefault("edges", [])
    parsed.setdefault("memory_keys", [])

    state = {
        **state,
        "pipeline_json": parsed,
        "status": "done",
        "log": state["log"] + [{"step": "wire", "pipeline_id": parsed.get("id")}],
    }

    try:
        validate_stage_output("wire", {"pipeline_json": parsed})
        yield _event("validation", {"stage": "wire", "valid": True})
    except Exception as e:
        yield _event("validation", {"stage": "wire", "valid": False, "error": str(e)})
    await asyncio.sleep(0)

    yield _event("stage_result", {
        "stage": "wire",
        "status": "done",
        "pipeline_json": parsed,
    })
    await asyncio.sleep(0)

    # ── Done ──
    yield _event("complete", {
        "status": state["status"],
        "pipeline": state["pipeline_json"],
        "log": state["log"],
    })


async def run_thinker(intent: str, user_id: str) -> dict:
    """Run the full Thinker pipeline via the stream, return the final state.

    Consumes all SSE events and extracts the result from the 'complete' event.
    Used by non-streaming API endpoints that still need the final result.
    """
    result: dict = {"pipeline_json": None, "status": "error", "log": [], "missing_blocks": []}
    async for event_str in run_thinker_stream(intent, user_id):
        # Each event_str is "event: ...\ndata: {...}\n\n"
        for line in event_str.strip().split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("type") == "complete":
                    result["pipeline_json"] = data.get("pipeline")
                    result["status"] = data.get("status", "done")
                    result["log"] = data.get("log", [])
    return result
