from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.blocks.executor import register_implementation
from app.config import settings

logger = logging.getLogger("agentflow.blocks.claude_extra")


async def _call_openai(prompt: str, max_tokens: int = 800) -> str:
    """Shared OpenAI API call helper."""
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured — add it to .env")

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.default_model or "gpt-4o-mini",
            max_tokens=max_tokens,
            temperature=settings.llm_temperature,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise ValueError(f"OpenAI API error: {e}") from e

    text = (response.choices[0].message.content or "").strip()
    # Strip markdown code fences if present
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if md_match:
        text = md_match.group(1).strip()
    return text


@register_implementation("claude_analyze")
async def claude_analyze(inputs: dict[str, Any]) -> dict[str, Any]:
    """Use OpenAI to perform deep analysis on data."""
    data = inputs["data"]
    question = inputs["question"]
    context = inputs.get("context", "")

    prompt = f"""Analyze the following data and answer the question.

Question: {question}
{f"Context: {context}" if context else ""}

Data:
{json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)}

Respond with ONLY valid JSON:
{{"analysis": "...", "findings": ["..."], "recommendation": "..."}}"""

    response = await _call_openai(prompt)
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"analysis": response, "findings": [], "recommendation": ""}


@register_implementation("claude_recommend")
async def claude_recommend(inputs: dict[str, Any]) -> dict[str, Any]:
    """Use OpenAI to recommend the best option based on preferences and history."""
    options = inputs["options"]
    preferences = inputs.get("preferences", {})
    history = inputs.get("history", [])

    prompt = f"""Recommend the best option from the list below.

User preferences: {json.dumps(preferences)}
Past choices (avoid repeating): {json.dumps(history)}

Options:
{json.dumps(options, indent=2)}

Respond with ONLY valid JSON:
{{"recommendation": <chosen option object>, "reasoning": "...", "alternatives": [<other good options>]}}"""

    response = await _call_openai(prompt)
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {
            "recommendation": options[0] if options else {},
            "reasoning": response,
            "alternatives": [],
        }


@register_implementation("claude_categorize")
async def claude_categorize(inputs: dict[str, Any]) -> dict[str, Any]:
    """Use OpenAI to classify content into categories."""
    content = inputs["content"]
    categories = inputs.get("categories", [])

    cat_str = f"\nCategories to choose from: {json.dumps(categories)}" if categories else ""

    prompt = f"""Categorize the following content.{cat_str}

Content: {content}

Respond with ONLY valid JSON:
{{"category": "...", "confidence": 0.0-1.0, "reasoning": "..."}}"""

    response = await _call_openai(prompt)
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"category": "unknown", "confidence": 0.5, "reasoning": response}
