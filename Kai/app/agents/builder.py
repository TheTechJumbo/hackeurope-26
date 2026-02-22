"""Builder Agent — creates new block definitions and implementations on-the-fly."""

from __future__ import annotations

import inspect
import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.blocks.executor import register_implementation
from app.blocks.registry import BlockRegistry
from app.config import settings
from app.models.block import BlockDefinition

logger = logging.getLogger("agentflow.builder")

SYSTEM_PROMPT = """You are the Builder Agent for AgentFlow — an automation platform.

Your job: given a block specification, generate a new block definition with working Python code.

## Block Specification Format (input you receive)
{{
  "suggested_id": "unique_snake_case_id",
  "name": "Human Readable Name",
  "description": "What this block does",
  "category": "perceive|think|act|communicate|remember|control",
  "input_schema": {{ JSON Schema for inputs }},
  "output_schema": {{ JSON Schema for outputs }}
}}

## Output Format

Respond with ONLY valid JSON (no markdown, no code fences, just raw JSON):

{{
  "block_definition": {{
    "id": "the_block_id",
    "name": "Human Name",
    "description": "What it does",
    "category": "category",
    "organ": "system|web|openai|gemini|stripe|elevenlabs|miro|email",
    "input_schema": {{ ... }},
    "output_schema": {{ ... }},
    "api_type": "real",
    "tier": 2,
    "examples": [{{ "input": {{}}, "output": {{}} }}]
  }},
  "implementation_code": "async def block_fn(inputs: dict) -> dict:\\n    # Python code here\\n    return {{}}"
}}

## Rules

1. The implementation_code must be an async function that takes a dict and returns a dict.
2. You can use these imports: httpx, json, re, datetime, bs4.BeautifulSoup
3. The function must handle errors gracefully — return error info instead of raising.
4. Keep implementations simple and focused.
5. If you can't make a real implementation, return a minimal implementation that raises a clear error instead of returning fake data.
6. The function name should match the block_id.
"""


class BuilderAgent:
    def __init__(self, registry: BlockRegistry):
        self.registry = registry

    async def create_block(self, spec: dict[str, Any]) -> BlockDefinition:
        """Create a new block from a specification.

        Returns the registered BlockDefinition.
        """
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        try:
            response = await client.chat.completions.create(
                model=settings.default_model or "gpt-4o-mini",
                max_tokens=2000,
                temperature=settings.llm_temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(spec, indent=2)},
                ],
            )
        except Exception as e:
            logger.error("OpenAI API error: %s", e)
            raise RuntimeError("OpenAI API error") from e

        response_text = (response.choices[0].message.content or "").strip()

        # Strip markdown code fences if present
        md_match = re.search(r"```(?:json)?\s*\n?(.*?)```", response_text, re.DOTALL)
        if md_match:
            response_text = md_match.group(1).strip()

        try:
            result = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error("Builder returned invalid JSON: %s", response_text[:200])
            raise ValueError("Builder returned invalid JSON") from e

        block_data = result["block_definition"]
        block = BlockDefinition(**block_data)

        # Register the generated implementation
        impl_code = result.get("implementation_code", "")
        self._register_dynamic_implementation(block.id, impl_code)

        # Add to registry
        self.registry.register(block)
        logger.info("Builder created block: %s", block.id)
        return block

    async def create_missing_blocks(self, missing_specs: list[dict[str, Any]]) -> list[BlockDefinition]:
        """Create all missing blocks from a list of specs."""
        created = []
        for spec in missing_specs:
            block = await self.create_block(spec)
            created.append(block)
        return created

    def _register_dynamic_implementation(self, block_id: str, code: str) -> None:
        """Register a dynamically generated block implementation."""
        if not code.strip():
            raise ValueError(f"No implementation_code provided for block '{block_id}'")

        scope: dict[str, Any] = {}
        try:
            exec(code, scope, scope)
        except Exception as e:
            logger.error("Failed to compile implementation for %s: %s", block_id, e)
            raise

        impl = scope.get(block_id)
        if impl is None:
            raise ValueError(f"implementation_code did not define '{block_id}'")
        if not inspect.iscoroutinefunction(impl):
            raise TypeError(f"implementation_code for '{block_id}' must define an async function")

        register_implementation(block_id)(impl)
