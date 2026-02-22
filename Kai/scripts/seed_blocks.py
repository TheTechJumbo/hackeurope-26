"""Seed block definitions into Supabase from local JSON definitions.

Usage:
  python3 Kai/scripts/seed_blocks.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.storage.supabase_client import get_supabase
from app.storage.embeddings import generate_embedding_sync, block_to_search_text

DEFINITIONS_DIR = Path(__file__).resolve().parent.parent / "app" / "blocks" / "definitions"


def load_definitions() -> list[dict]:
    blocks: list[dict] = []
    for path in sorted(DEFINITIONS_DIR.glob("*.json")):
        data = json.load(path.open("r", encoding="utf-8"))
        entries = data if isinstance(data, list) else data.get("blocks", [])
        blocks.extend(entries)
    return blocks


def normalize_block(block: dict) -> dict:
    block = dict(block)
    block.setdefault("name", block["id"].replace("_", " ").title())
    block.setdefault("description", "")
    block.setdefault("category", "process")
    block.setdefault("execution_type", "python")
    block.setdefault("input_schema", {})
    block.setdefault("output_schema", {})
    block.setdefault("use_when", None)
    block.setdefault("tags", [])
    block.setdefault("examples", [])
    block.setdefault("metadata", {"created_by": "seed", "tier": 1})
    return block


def main() -> None:
    sb = get_supabase()
    blocks = load_definitions()
    for block in blocks:
        block = normalize_block(block)
        search_text = block_to_search_text(block)
        embedding = generate_embedding_sync(search_text)
        row = {
            "id": block["id"],
            "name": block.get("name"),
            "description": block.get("description", ""),
            "category": block.get("category", "process"),
            "execution_type": block.get("execution_type", "python"),
            "input_schema": block.get("input_schema", {}),
            "output_schema": block.get("output_schema", {}),
            "prompt_template": block.get("prompt_template"),
            "source_code": block.get("source_code"),
            "use_when": block.get("use_when"),
            "tags": block.get("tags", []),
            "examples": block.get("examples", []),
            "metadata": block.get("metadata", {}),
            "embedding": embedding,
        }
        sb.table("blocks").upsert(row).execute()
        print(f"Seeded {row['id']}")


if __name__ == "__main__":
    main()
