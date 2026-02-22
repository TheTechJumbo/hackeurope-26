from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.blocks.executor import register_implementation
from app.config import settings

logger = logging.getLogger("agentflow.blocks.claude_summarize")


@register_implementation("claude_summarize")
async def claude_summarize(inputs: dict[str, Any]) -> dict[str, Any]:
    """Use OpenAI to condense content into a concise summary."""
    content = inputs["content"]
    max_length = inputs.get("max_length", "paragraph")
    focus = inputs.get("focus", "")

    length_instructions = {
        "one_sentence": "Respond with exactly ONE sentence.",
        "paragraph": "Respond with a short paragraph (3-5 sentences).",
        "bullet_points": "Respond with 3-7 bullet points.",
    }

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured — add it to .env")

    prompt = f"""Summarize the following content.
{length_instructions.get(max_length, length_instructions["paragraph"])}
{f"Focus on: {focus}" if focus else ""}

Content:
{content}

Respond with ONLY valid JSON:
{{"summary": "<your summary>", "key_points": ["point1", "point2", ...]}}"""

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.default_model or "gpt-4o-mini",
            max_tokens=800,
            temperature=settings.llm_temperature,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise ValueError(f"OpenAI API error: {e}") from e

    response_text = (response.choices[0].message.content or "").strip()

    # Strip markdown code fences if present
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)```", response_text, re.DOTALL)
    if md_match:
        response_text = md_match.group(1).strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {
            "summary": response_text,
            "key_points": [],
        }
