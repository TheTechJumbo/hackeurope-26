import pytest

from app.blocks.executor import BlockExecutor, resolve_templates
from app.models.block import BlockDefinition
from app.models.execution import ExecutionStatus


class TestResolveTemplates:
    def test_resolve_node_reference(self):
        inputs = {"query": "{{n1.title}}"}
        context = {"n1": {"title": "Hello World"}}
        resolved = resolve_templates(inputs, context)
        assert resolved["query"] == "Hello World"

    def test_resolve_memory_reference(self):
        inputs = {"history": "{{memory.past_orders}}"}
        context = {}
        memory = {"past_orders": ["Pizza", "Sushi"]}
        resolved = resolve_templates(inputs, context, memory)
        assert resolved["history"] == ["Pizza", "Sushi"]

    def test_resolve_preserves_type(self):
        inputs = {"data": "{{n1.results}}"}
        context = {"n1": {"results": [1, 2, 3]}}
        resolved = resolve_templates(inputs, context)
        assert resolved["data"] == [1, 2, 3]
        assert isinstance(resolved["data"], list)

    def test_resolve_string_interpolation(self):
        inputs = {"text": "Price is {{n1.price}} euros"}
        context = {"n1": {"price": 399}}
        resolved = resolve_templates(inputs, context)
        assert resolved["text"] == "Price is 399 euros"

    def test_resolve_no_templates(self):
        inputs = {"query": "plain text", "count": 5}
        resolved = resolve_templates(inputs, {})
        assert resolved == {"query": "plain text", "count": 5}

    def test_resolve_missing_reference(self):
        inputs = {"x": "{{missing.field}}"}
        resolved = resolve_templates(inputs, {})
        # Pure template returns raw lookup value (None when missing)
        assert resolved["x"] is None

    def test_resolve_missing_in_string(self):
        inputs = {"x": "hello {{missing.field}} world"}
        resolved = resolve_templates(inputs, {})
        # String interpolation replaces missing with empty string
        assert resolved["x"] == "hello  world"


class TestBlockExecutor:
    @pytest.fixture()
    def executor(self):
        return BlockExecutor()

    @pytest.fixture()
    def dummy_block(self):
        return BlockDefinition(
            id="nonexistent_block",
            name="Nonexistent",
            description="No implementation",
            category="think",
            organ="openai",
        )

    @pytest.mark.asyncio
    async def test_missing_implementation(self, executor, dummy_block):
        result = await executor.execute(dummy_block, {})
        assert result.status == ExecutionStatus.FAILED
        assert "No implementation" in result.error

    @pytest.mark.asyncio
    async def test_execute_records_duration(self, executor, dummy_block):
        result = await executor.execute(dummy_block, {})
        assert result.duration_ms is not None
        assert result.duration_ms >= 0
