import pytest
from pydantic import ValidationError

from app.models.block import BlockCategory, BlockDefinition, BlockOrgan
from app.models.pipeline import (
    Pipeline,
    PipelineEdge,
    PipelineNode,
    PipelineStatus,
    TriggerConfig,
    TriggerType,
)
from app.models.execution import ExecutionState, ExecutionStatus, NodeResult
from app.models.memory import MemoryEntry, MemoryQuery


# ── BlockDefinition ──────────────────────────────────────────────────

class TestBlockDefinition:
    def test_valid_block(self):
        block = BlockDefinition(
            id="test_block",
            name="Test Block",
            description="A test block",
            category=BlockCategory.THINK,
            organ=BlockOrgan.OPENAI,
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        )
        assert block.id == "test_block"
        assert block.category == "think"
        assert block.organ == "openai"
        assert block.tier == 1
        assert block.api_type == "real"

    def test_block_missing_required_fields(self):
        with pytest.raises(ValidationError):
            BlockDefinition(id="test", name="Test")

    def test_block_invalid_category(self):
        with pytest.raises(ValidationError):
            BlockDefinition(
                id="test",
                name="Test",
                description="desc",
                category="invalid",
                organ="system",
            )

    def test_block_defaults(self):
        block = BlockDefinition(
            id="b",
            name="B",
            description="d",
            category="trigger",
            organ="system",
        )
        assert block.tier == 1
        assert block.api_type == "real"
        assert block.examples == []
        assert block.input_schema == {}
        assert block.output_schema == {}


# ── Pipeline ─────────────────────────────────────────────────────────

class TestPipeline:
    def test_valid_pipeline(self):
        pipeline = Pipeline(
            id="pipe_001",
            user_intent="Buy milk every Tuesday",
            trigger=TriggerConfig(type=TriggerType.CRON, schedule="0 8 * * 2"),
            nodes=[
                PipelineNode(id="n1", block_id="trigger_cron"),
                PipelineNode(id="n2", block_id="web_search", inputs={"query": "milk delivery"}),
            ],
            edges=[PipelineEdge(from_node="n1", to_node="n2")],
            memory_keys=["past_orders"],
        )
        assert pipeline.status == PipelineStatus.CREATED
        assert len(pipeline.nodes) == 2
        assert len(pipeline.edges) == 1
        assert pipeline.trigger.schedule == "0 8 * * 2"

    def test_pipeline_missing_intent(self):
        with pytest.raises(ValidationError):
            Pipeline(
                id="pipe",
                trigger=TriggerConfig(type=TriggerType.MANUAL),
                nodes=[],
                edges=[],
            )

    def test_pipeline_edge_with_condition(self):
        edge = PipelineEdge(from_node="a", to_node="b", condition="price < 400")
        assert edge.condition == "price < 400"

    def test_pipeline_node_with_inputs(self):
        node = PipelineNode(
            id="n1",
            block_id="claude_decide",
            inputs={"options": "{{n0.results}}", "criteria": "cheapest"},
        )
        assert "{{n0.results}}" in node.inputs["options"]


# ── ExecutionState ───────────────────────────────────────────────────

class TestExecutionState:
    def test_valid_execution_state(self):
        state = ExecutionState(pipeline_id="p1", run_id="r1")
        assert state.status == ExecutionStatus.PENDING
        assert state.shared_context == {}
        assert state.node_results == []

    def test_node_result(self):
        result = NodeResult(
            node_id="n1",
            block_id="web_search",
            status=ExecutionStatus.COMPLETED,
            output={"results": [{"title": "Test"}]},
            duration_ms=150.5,
        )
        assert result.error is None
        assert result.duration_ms == 150.5


# ── Memory ───────────────────────────────────────────────────────────

class TestMemory:
    def test_memory_entry(self):
        entry = MemoryEntry(key="price_history", value=[100, 200, 300])
        assert entry.namespace == "default"
        assert entry.value == [100, 200, 300]

    def test_memory_query(self):
        query = MemoryQuery(key="test")
        assert query.namespace == "default"
        assert query.search_text is None
