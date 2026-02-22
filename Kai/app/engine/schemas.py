"""Strict schemas for every stage of the Thinker pipeline.

Each stage has a well-defined input/output contract as a Pydantic model.
Use validate_stage_output() at each boundary to catch malformed data early.

Export all schemas as JSON with: python -m engine.schemas
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Stage 1: DECOMPOSE output
# ─────────────────────────────────────────────


class ExistingBlockRef(BaseModel):
    """Reference to a block that already exists in the registry."""
    block_id: str = Field(description="ID of an existing block in the registry")
    reason: str = Field(description="Why this block is needed for the user's intent")


class NewBlockSpec(BaseModel):
    """Description of a block that needs to be created."""
    suggested_id: str = Field(description="Proposed ID for the new block, e.g. 'scrape_hn'")
    description: str = Field(description="What this block should do")
    category: str = Field(
        default="process",
        description="Block category: 'input', 'process', 'action', or 'memory'",
    )
    execution_type: str = Field(
        default="python",
        description="How the block runs — always 'python'",
    )
    input_schema: dict[str, Any] = Field(
        description="JSON Schema for the block's inputs",
        examples=[{
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }],
    )
    output_schema: dict[str, Any] = Field(
        description="JSON Schema for the block's outputs",
        examples=[{
            "type": "object",
            "properties": {"data": {"type": "string"}},
        }],
    )
    prompt_template: str | None = Field(
        default=None,
        description="Deprecated — legacy LLM blocks only. New blocks use source_code.",
    )
    examples: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Sample input/output pairs showing how the block is used",
    )
    use_when: str | None = Field(
        default=None,
        description="Guidance on when this block is appropriate",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Semantic tags for discovery",
    )


class DecomposeOutput(BaseModel):
    """Output of the decompose stage — a list of required blocks."""
    required_blocks: list[ExistingBlockRef | NewBlockSpec] = Field(
        min_length=1,
        description="Ordered list of blocks needed to fulfill the user's intent",
    )


# ─────────────────────────────────────────────
# Stage 2: MATCH output
# ─────────────────────────────────────────────


class MatchOutput(BaseModel):
    """Output of the match stage — split into found and missing."""
    matched_blocks: list[dict] = Field(
        description="Full block definitions from registry for blocks that were found",
    )
    missing_blocks: list[NewBlockSpec | dict] = Field(
        description="Block specs that had no match — need to be created",
    )


# ─────────────────────────────────────────────
# Stage 3: CREATE BLOCK output
# ─────────────────────────────────────────────


class BlockDefinition(BaseModel):
    """A complete block definition, ready to register."""
    id: str = Field(description="Unique block ID, e.g. 'scrape_hn'")
    name: str = Field(description="Human-readable name")
    description: str
    category: str = Field(description="'input', 'process', 'action', or 'memory'")
    execution_type: str = Field(default="python", description="Always 'python'")
    input_schema: dict[str, Any] = Field(
        description="JSON Schema defining the block's inputs",
    )
    output_schema: dict[str, Any] = Field(
        description="JSON Schema defining the block's outputs",
    )
    prompt_template: str | None = Field(
        default=None,
        description="Deprecated — legacy LLM blocks only",
    )
    source_code: str | None = Field(
        default=None,
        description="Python source code with async execute(inputs, context) function",
    )
    metadata: dict[str, Any] = Field(
        default_factory=lambda: {"created_by": "thinker", "tier": 2},
    )
    examples: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Sample input/output pairs showing how the block is used",
    )
    use_when: str | None = Field(
        default=None,
        description="Guidance on when this block is appropriate",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Semantic tags for discovery",
    )


class CreateBlockOutput(BaseModel):
    """Output of the create_block stage — newly created block definitions."""
    created_blocks: list[BlockDefinition] = Field(
        min_length=1,
        description="Blocks that were created and registered",
    )


# ─────────────────────────────────────────────
# Stage 4: WIRE output — the Pipeline JSON
# ─────────────────────────────────────────────


class PipelineNode(BaseModel):
    """A single node in the pipeline DAG."""
    id: str = Field(description="Sequential ID: n1, n2, n3...")
    block_id: str = Field(description="Which block this node executes")
    inputs: dict[str, Any] = Field(
        description="Input values — literal values or {{n1.field}} template references",
    )


class PipelineEdge(BaseModel):
    """A directed edge in the pipeline DAG."""
    from_node: str = Field(alias="from", description="Source node ID")
    to_node: str = Field(alias="to", description="Target node ID")

    model_config = {"populate_by_name": True}


class PipelineJSON(BaseModel):
    """The complete Pipeline JSON — output of the Thinker, input to the Doer."""
    id: str = Field(description="Pipeline ID, e.g. 'pipeline_hn_summary'")
    name: str = Field(description="Human-readable pipeline name")
    user_prompt: str = Field(description="The original user request")
    nodes: list[PipelineNode] = Field(
        min_length=1,
        description="Ordered list of pipeline nodes",
    )
    edges: list[PipelineEdge] = Field(
        default_factory=list,
        description="DAG edges defining execution dependencies",
    )
    memory_keys: list[str] = Field(
        default_factory=list,
        description="Memory keys this pipeline reads/writes",
    )


class WireOutput(BaseModel):
    """Output of the wire stage — the complete pipeline."""
    pipeline_json: PipelineJSON


# ─────────────────────────────────────────────
# Validation helper
# ─────────────────────────────────────────────


STAGE_SCHEMAS = {
    "decompose": DecomposeOutput,
    "match": MatchOutput,
    "create_block": CreateBlockOutput,
    "wire": WireOutput,
}


def validate_stage_output(stage: str, data: dict) -> BaseModel:
    """Validate a stage's output against its schema. Raises ValidationError on failure."""
    schema_cls = STAGE_SCHEMAS.get(stage)
    if not schema_cls:
        raise ValueError(f"Unknown stage: {stage}. Valid: {list(STAGE_SCHEMAS.keys())}")
    return schema_cls.model_validate(data)


def export_schemas(output_dir: str = "schemas"):
    """Export all stage schemas as JSON Schema files."""
    out = Path(output_dir)
    out.mkdir(exist_ok=True)

    all_models = {
        "decompose_output": DecomposeOutput,
        "match_output": MatchOutput,
        "create_block_output": CreateBlockOutput,
        "wire_output": WireOutput,
        "pipeline_json": PipelineJSON,
        "block_definition": BlockDefinition,
        "new_block_spec": NewBlockSpec,
    }

    for name, model in all_models.items():
        schema = model.model_json_schema()
        path = out / f"{name}.json"
        with open(path, "w") as f:
            json.dump(schema, f, indent=2)
        print(f"  {path}")

    print(f"\nExported {len(all_models)} schemas to {out}/")


if __name__ == "__main__":
    export_schemas()
