"""Embedding helpers — OpenAI text-embedding-3-small for block/pipeline search."""

import asyncio
from functools import lru_cache

from pydantic_settings import BaseSettings


class EmbeddingSettings(BaseSettings):
    openai_api_key: str = ""
    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def _get_openai():
    from openai import OpenAI
    settings = EmbeddingSettings()
    return OpenAI(api_key=settings.openai_api_key)


def generate_embedding_sync(text: str) -> list[float]:
    """Generate an embedding vector for the given text (synchronous)."""
    client = _get_openai()
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return response.data[0].embedding


async def generate_embedding(text: str) -> list[float]:
    """Generate an embedding vector for the given text (async wrapper)."""
    return await asyncio.to_thread(generate_embedding_sync, text)


def _schema_type_to_natural(prop: dict) -> str:
    """Convert a JSON Schema type to a descriptive natural language type."""
    t = prop.get("type", "any")
    desc = prop.get("description", "")
    if t == "string":
        return "text string"
    elif t == "number":
        return "floating point number"
    elif t == "integer":
        return "whole number"
    elif t == "boolean":
        return "true or false flag"
    elif t == "array":
        items = prop.get("items", {})
        item_type = _schema_type_to_natural(items) if items else "items"
        return f"list of {item_type}"
    elif t == "object":
        return "structured object"
    return t


def block_to_search_text(block: dict) -> str:
    """Build a plain-text embedding of a block focused on what it does.

    Only includes functional description, use_when, and tags — no I/O schemas.
    This keeps the embedding in the same semantic space as requirement descriptions,
    so cosine similarity directly compares desired vs existing functionality.
    """
    parts = []
    if block.get("description"):
        parts.append(block["description"].rstrip(".") + ".")
    if block.get("use_when"):
        parts.append(f"Use when {block['use_when'].rstrip('.')}.")
    if block.get("tags"):
        parts.append(f"Related to: {', '.join(block['tags'])}.")
    return " ".join(parts)
