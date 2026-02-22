"""LLM service — OpenAI SDK wrapped with Paid.ai for cost tracing (optional)."""

from __future__ import annotations

import asyncio
import json
import re

from app.config import settings


def get_client():
    """Return a Paid.ai-wrapped OpenAI client."""
    from openai import OpenAI

    raw_client = OpenAI(api_key=settings.openai_api_key)
    if settings.paid_api_key:
        try:
            from paid.tracing.wrappers import PaidOpenAI

            return PaidOpenAI(raw_client)
        except ImportError:
            pass
    return raw_client


async def call_llm(
    system: str,
    user: str,
    model: str | None = None,
) -> str:
    """Call an LLM and return the text response.

    Uses OpenAI SDK, wrapped with Paid.ai for cost tracking when available.
    """
    m = model or settings.default_model
    client = get_client()

    def _call_openai():
        return client.chat.completions.create(
            model=m,
            temperature=settings.llm_temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

    response = await asyncio.to_thread(_call_openai)
    return response.choices[0].message.content or ""


async def call_llm_messages(
    messages: list[dict],
    model: str | None = None,
) -> str:
    """Call an LLM with a full messages array for multi-turn conversation."""
    m = model or settings.default_model
    client = get_client()

    def _call_openai():
        return client.chat.completions.create(
            model=m,
            temperature=settings.llm_temperature,
            messages=messages,
        )

    response = await asyncio.to_thread(_call_openai)
    return response.choices[0].message.content or ""


def parse_json_output(text: str, schema: dict | None = None) -> dict:
    """Extract the first JSON object from LLM text output."""
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return {"raw": text}
