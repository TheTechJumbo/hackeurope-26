from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class BlockCategory(str, Enum):
    TRIGGER = "trigger"
    PERCEIVE = "perceive"
    THINK = "think"
    ACT = "act"
    COMMUNICATE = "communicate"
    REMEMBER = "remember"
    CONTROL = "control"


class BlockOrgan(str, Enum):
    GEMINI = "gemini"
    CLAUDE = "claude"
    OPENAI = "openai"
    ELEVENLABS = "elevenlabs"
    STRIPE = "stripe"
    MIRO = "miro"
    SYSTEM = "system"
    WEB = "web"
    EMAIL = "email"


class BlockExample(BaseModel):
    input: dict[str, Any]
    output: dict[str, Any]


class BlockDefinition(BaseModel):
    id: str = Field(..., description="Unique snake_case block identifier")
    name: str = Field(..., description="Human-readable block name")
    description: str = Field(..., description="What this block does and when to use it")
    category: BlockCategory
    organ: BlockOrgan

    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for block inputs",
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for block outputs",
    )

    api_type: str = Field(
        default="real",
        description="'real' or 'mock' — whether the block calls a real API",
    )
    tier: int = Field(default=1, description="Priority tier (1=MVP, 2=impressive, 3=full)")

    examples: list[BlockExample] = Field(default_factory=list)

    model_config = {"use_enum_values": True}


class BlockReference(BaseModel):
    """Lightweight reference to a block used in pipeline nodes."""

    block_id: str
    block_name: str | None = None
