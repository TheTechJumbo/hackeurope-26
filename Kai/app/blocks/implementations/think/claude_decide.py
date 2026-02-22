from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.blocks.executor import register_implementation
from app.config import settings

logger = logging.getLogger("agentflow.blocks.claude_decide")


@register_implementation("claude_decide")
async def claude_decide(inputs: dict[str, Any]) -> dict[str, Any]:
    """Use OpenAI to pick the best option from a set based on criteria."""
    options = inputs["options"]
    criteria = inputs["criteria"]
    context = inputs.get("context", "")

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured — add it to .env")

    prompt = f"""You are a decision-making assistant. Pick the BEST option from the list below.

Criteria: {criteria}
{f"Context: {context}" if context else ""}

Options:
{json.dumps(options, indent=2)}

Respond with ONLY valid JSON in this exact format:
{{"chosen": <the selected option object>, "reasoning": "<why you chose it>", "confidence": <0.0-1.0>}}"""

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.default_model or "gpt-4o-mini",
            max_tokens=500,
            temperature=settings.llm_temperature,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise ValueError(f"OpenAI API error: {e}") from e

    response_text = (response.choices[0].message.content or "").strip()
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)```", response_text, re.DOTALL)
    if md_match:
        response_text = md_match.group(1).strip()
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {
            "chosen": options[0] if options else {},
            "reasoning": response_text,
            "confidence": 0.5,
        }
