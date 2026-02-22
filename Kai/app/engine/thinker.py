"""Thinker shared utilities — prompt builders, block helpers, test helpers.

Used by thinker_stream.py which owns the orchestration and SSE streaming.
"""

import json
import logging

from app.engine.executor import execute_block_standalone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Prompt builders
# ─────────────────────────────────────────────


def _build_block_catalog(blocks: list[dict]) -> str:
    """Build a rich block catalog string including use_when, tags, and one example per block."""
    entries = []
    for b in blocks:
        entry = {
            "id": b["id"],
            "name": b["name"],
            "description": b["description"],
            "input_schema": b.get("input_schema", {}),
            "output_schema": b.get("output_schema", {}),
        }
        if b.get("use_when"):
            entry["use_when"] = b["use_when"]
        if b.get("tags"):
            entry["tags"] = b["tags"]
        examples = b.get("examples", [])
        if examples:
            entry["example"] = examples[0]
        entries.append(entry)
    return json.dumps(entries, indent=2)


def build_decompose_prompts(intent: str) -> tuple[str, str]:
    """Build decompose prompts using IO-driven decomposition.

    All blocks are Python. Blocks that need LLM reasoning call `call_llm()` from
    their source code — this is just Python code like any other API call.
    """
    system = """You are an IO-driven task decomposer for AgentFlow, an AI agent platform.

Your job is to deconstruct the user's intent into an executable pipeline by:
1. Identifying what INPUTS are needed (data, parameters, external resources)
2. Identifying what OUTPUTS must be produced (deliverables, results)
3. Deriving the ordered STEPS that transform inputs into outputs
4. Mapping each step to an atomic block with explicit input/output schemas

## Thinking Process (follow this internally)

### Step 1 — Input Dependencies
What information, data sources, or parameters does this task require?
Classify each as:
- SYSTEM-RETRIEVABLE: can be fetched via web search, API, scraping
- USER-PROVIDED: specific values from the user's intent (queries, URLs, thresholds)
- DERIVED: computed from previous steps

### Step 2 — Desired Outputs
What are the concrete, observable outputs the user expects?

### Step 3 — Dependency Chain
Map the transformation: Inputs → Step 1 → Step 2 → ... → Outputs
Each step must explicitly reference what it USES (from inputs or previous steps)
and what it PRODUCES (available to subsequent steps).

### Step 4 — Map to Blocks
Convert each step into an atomic block definition.

## All Blocks Are Python
Every block is a Python block with `execution_type: "python"`. Each block gets an
`async def execute(inputs, context) -> dict` function.

## Core System Blocks (ALREADY EXIST — reuse these IDs exactly)
- web_search: Search the web (Serper API) and return organic results
- web_scrape: Fetch and extract text content from a URL
- memory_read: Read a value from persistent user memory
- memory_write: Write a value to persistent user memory
- notify_in_app: Send an in-app notification to the user

If any step can be satisfied by one of the core blocks above, use it instead of
creating a new block. Do NOT invent duplicates of these capabilities.

Blocks have access to these capabilities:
- **HTTP requests**: `httpx` for web scraping, API calls, search
- **LLM reasoning**: `call_llm(system, user)` and `parse_json_output(text)` for
  analysis, generation, summarization, synthesis, or any task requiring intelligence
- **Standard library**: json, math, re, datetime, collections, itertools, random, os, statistics

A block that needs to analyze, summarize, or reason about data simply calls `call_llm()`
within its Python code — this is just another function call, like calling an API.

## Example blocks (for format reference only)
- web_search (python): Search the web via API. Inputs: {query: string}. Outputs: {results: array}
- web_scrape (python): Fetch URL content via httpx. Inputs: {url: string}. Outputs: {content: string}
- summarize (python): Summarize text using call_llm(). Inputs: {content: string}. Outputs: {summary: string}
- analyze_sentiment (python): Analyze sentiment using call_llm(). Inputs: {text: string}. Outputs: {sentiment: string, score: number}
- filter_and_rank (python): Filter/rank items by criteria. Inputs: {items: array, criteria: string}. Outputs: {ranked: array}

## Rules
1. Each block does ONE atomic thing — single intent, single system boundary
2. List blocks in execution order matching your dependency chain
3. Every block's input must come from either the user's intent or a previous block's output
4. ALL blocks use execution_type "python" — there is no other type
5. For tasks requiring reasoning, analysis, or text generation: the block's Python code
   will call `call_llm()` internally — this is still a python block
6. Blocks MUST be generic and reusable — they describe a CAPABILITY, not this specific task.
   - GOOD: "web_search" with input {query: string} — the specific query is a runtime input
   - BAD:  "search_cnn_headlines" — this bakes the task into the block definition
   - GOOD: "extract_fields" with input {content: string, fields: array}
   - BAD:  "extract_airpods_price" — too specific, not reusable
   Task-specific values (URLs, keywords, thresholds, names) belong in the input_schema
   as parameters that the pipeline will fill in at wiring time — NEVER in the block name,
   description, or logic.

## Output
Return ONLY a JSON object (no markdown, no explanation):
{"required_blocks": [
  {"suggested_id": "...", "description": "...", "execution_type": "python",
   "depends_on": ["suggested_id_of_previous_block"],
   "input_schema": {"type": "object", "properties": {...}, "required": [...]},
   "output_schema": {"type": "object", "properties": {...}}}
]}"""

    user = f'User intent: "{intent}"'
    return system, user


def build_create_block_prompt(spec: dict) -> tuple[str, str]:
    """Build a focused coding-agent prompt for creating a single Python block.

    Each block creation is treated as an isolated coding task: given the input schema,
    output schema, and description, produce excellent Python code.
    """
    system = f"""You are a specialist Python code generator for AgentFlow blocks.

Your SOLE job: write a complete, working Python block as a JSON definition.
A block is a self-contained Python module with an `async def execute(inputs, context) -> dict` function.

## Execution Environment

The `execute` function receives:
- `inputs`: dict with keys matching `input_schema` properties
- `context`: dict with `user` (dict), `memory` (dict), `user_id` (str), `supabase` (client or None)

The function MUST return a dict matching `output_schema`.

## Available Functions & Modules (pre-loaded in namespace, no import needed)

### LLM Access (for reasoning, analysis, generation, summarization)
- `call_llm(system: str, user: str) -> str` — async, calls an LLM and returns text response
- `call_llm_messages(messages: list[dict]) -> str` — async, multi-turn LLM conversation
- `parse_json_output(text: str) -> dict` — extracts first JSON object from LLM text

### HTTP & Data
- `httpx` — async HTTP client (use `async with httpx.AsyncClient() as client:`)
- `json` — JSON encoding/decoding
- `re` — regular expressions
- `math`, `statistics` — numerical operations
- `datetime` — date/time handling
- `collections`, `itertools`, `functools` — data structures & utilities
- `random` — random number generation
- `os` — environment variables only (os.environ, os.getenv)

### FORBIDDEN (will crash at runtime)
time, requests, urllib, bs4, subprocess, sys, pathlib, socket, aiohttp, selenium, scrapy, numpy, pandas

## Code Quality Requirements

1. Handle edge cases: empty inputs, missing optional fields, API failures
2. Use `try/except` around external calls (httpx, call_llm) with meaningful error messages
3. Always return a dict matching the output_schema, even on partial failure
4. Use type hints in the function signature
5. Keep code clean and readable — no unnecessary complexity

## LLM Block Pattern

When the block needs reasoning/analysis/generation, use this pattern:
```python
async def execute(inputs: dict, context: dict) -> dict:
    system_prompt = "You are a ... Return JSON with fields: ..."
    user_prompt = f"Analyze the following: {{inputs['content']}}"

    response = await call_llm(system=system_prompt, user=user_prompt)
    result = parse_json_output(response)

    return {{
        "field1": result.get("field1", ""),
        "field2": result.get("field2", []),
    }}
```

## HTTP Block Pattern

```python
async def execute(inputs: dict, context: dict) -> dict:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(inputs["url"])
        resp.raise_for_status()
    return {{"content": resp.text, "status": resp.status_code}}
```

## REUSABILITY RULES (CRITICAL)
- The block MUST be generic and reusable, not task-specific
- Task-specific values are INPUTS — they come via input_schema at runtime
- Every property in input_schema and output_schema MUST have a "description" field
- output_schema MUST have a "required" array listing mandatory output fields
- You MUST include "use_when" (string) — guidance on when to use this block
- You MUST include "tags" (list of strings) — semantic keywords for discovery
- You MUST include "examples" (list) — at least one realistic sample input/output pair

Return ONLY a JSON object (no markdown, no explanation).
The JSON MUST include a "source_code" field containing the complete Python source code."""

    user = f"""Create a Python block for:
- ID: {spec.get('suggested_id', 'new_block')}
- Description: {spec.get('description', 'No description')}
- Input schema: {json.dumps(spec.get('input_schema', {}), indent=2)}
- Output schema: {json.dumps(spec.get('output_schema', {}), indent=2)}

Return:
{{
  "id": "{spec.get('suggested_id', 'new_block')}",
  "name": "Human Readable Name",
  "description": "Generic description of the capability",
  "category": "process",
  "execution_type": "python",
  "input_schema": {json.dumps(spec.get('input_schema', {}))},
  "output_schema": {json.dumps(spec.get('output_schema', {}))},
  "source_code": "async def execute(inputs: dict, context: dict) -> dict:\\n    ...\\n    return {{...}}\\n",
  "use_when": "When to use this block",
  "tags": ["tag1", "tag2"],
  "examples": [{{"inputs": {{...}}, "outputs": {{...}}}}],
  "metadata": {{"created_by": "thinker", "tier": 2}}
}}"""
    return system, user


def build_wire_prompts(intent: str, blocks: list[dict]) -> tuple[str, str]:
    blocks_detail = _build_block_catalog(blocks)

    system = f"""You are a pipeline wirer for AgentFlow. Connect blocks into an executable Pipeline JSON.

## Wiring Rules
- Node IDs are sequential: n1, n2, n3...
- First node gets LITERAL input values derived from the user's intent.
- Later nodes reference earlier outputs with {{{{nX.field_name}}}} syntax.
  The field_name must come from the output_schema of node nX.
- Edges define execution dependencies: {{"from": "n1", "to": "n2"}} means n2 runs after n1.
- A node can depend on multiple previous nodes.

## Blocks (in suggested order)
{blocks_detail}

## Output
Return ONLY a JSON object (no markdown, no explanation)."""

    user = f"""User intent: "{intent}"

Wire the blocks above into a pipeline. Return:
{{
  "id": "pipeline_<short_snake_case_name>",
  "name": "Human Readable Name",
  "user_prompt": "{intent}",
  "nodes": [
    {{"id": "n1", "block_id": "...", "inputs": {{...}}}},
    ...
  ],
  "edges": [{{"from": "n1", "to": "n2"}}, ...],
  "memory_keys": []
}}"""
    return system, user


# ─────────────────────────────────────────────
# Shared helper: finalize a created block
# ─────────────────────────────────────────────


def _finalize_created_block(parsed: dict, spec: dict) -> dict:
    """Finalize a block created by the LLM.

    Validates source_code via compile(). If compile fails, raises so the retry loop
    can fix it — no fallback to a different execution type.
    """
    block_id = parsed.get("id", spec.get("suggested_id", "new_block"))
    parsed.setdefault("id", block_id)
    parsed.setdefault("name", block_id.replace("_", " ").title())
    parsed.setdefault("description", spec.get("description", ""))
    parsed.setdefault("category", spec.get("category", "process"))
    parsed.setdefault("execution_type", "python")
    parsed.setdefault("input_schema", spec.get("input_schema", {}))
    parsed.setdefault("output_schema", spec.get("output_schema", {}))
    parsed.setdefault("metadata", {"created_by": "thinker", "tier": 2})
    parsed.setdefault("use_when", None)
    parsed.setdefault("tags", [])
    parsed.setdefault("examples", [])

    # Normalize execution_type — everything is python
    parsed["execution_type"] = "python"

    # Handle python_source → source_code (normalize field name)
    python_source = parsed.pop("python_source", None)
    if python_source:
        parsed["source_code"] = python_source

    # Validate source_code compiles
    source_code = parsed.get("source_code")
    if source_code:
        try:
            compile(source_code, f"<block:{block_id}>", "exec")
            logger.info("Block %s: source_code validated via compile()", block_id)
        except SyntaxError as exc:
            logger.warning("Block %s: source_code failed compile(): %s", block_id, exc)
            # Re-raise so the retry loop can fix it
            raise
    else:
        raise ValueError(f"Block {block_id} has no source_code — all blocks must be Python")

    return parsed


# ─────────────────────────────────────────────
# Search helper
# ─────────────────────────────────────────────


def _is_good_match(candidate: dict, req: dict) -> bool:
    """Check if a search candidate is a good match for the required block.

    Trusts the embedding similarity search. Legacy llm blocks can be used too since
    the executor auto-converts them to python at runtime.
    """
    return True


# ─────────────────────────────────────────────
# Block testing helpers
# ─────────────────────────────────────────────


def _generate_test_inputs(schema: dict) -> dict:
    """Generate minimal valid inputs from a JSON Schema."""
    properties = schema.get("properties", {})
    required = schema.get("required", list(properties.keys()))
    inputs = {}
    for key in required:
        prop = properties.get(key, {})
        prop_type = prop.get("type", "string")
        if prop_type == "string":
            inputs[key] = "test"
        elif prop_type == "number":
            inputs[key] = 0.0
        elif prop_type == "integer":
            inputs[key] = 0
        elif prop_type == "boolean":
            inputs[key] = True
        elif prop_type == "array":
            inputs[key] = []
        elif prop_type == "object":
            inputs[key] = {}
        else:
            inputs[key] = "test"
    return inputs


async def _test_block(block: dict) -> tuple[bool, str]:
    """Test a block with its example inputs. Returns (passed, error_message)."""
    examples = block.get("examples", [])
    if examples and examples[0].get("inputs"):
        test_inputs = examples[0]["inputs"]
    else:
        test_inputs = _generate_test_inputs(block.get("input_schema", {}))

    context = {"user": {}, "memory": {}, "user_id": "test", "supabase": None}
    try:
        await execute_block_standalone(block, test_inputs, context)
        return True, ""
    except Exception as e:
        return False, str(e)
