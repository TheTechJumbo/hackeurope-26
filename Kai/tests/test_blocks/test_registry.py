import pytest

from app.blocks.registry import BlockRegistry
from app.models.block import BlockCategory, BlockDefinition


@pytest.fixture()
def empty_registry():
    return BlockRegistry()


@pytest.fixture()
def loaded_registry():
    reg = BlockRegistry()
    reg.load_from_directory()
    return reg


class TestBlockRegistry:
    def test_load_all_definitions(self, loaded_registry):
        """All 35 Tier 1 block definitions should load."""
        assert loaded_registry.count == 35

    def test_load_returns_count(self, empty_registry):
        count = empty_registry.load_from_directory()
        assert count == 35

    def test_get_existing_block(self, loaded_registry):
        block = loaded_registry.get("trigger_cron")
        assert block is not None
        assert block.name == "Scheduled Trigger (Cron)"
        assert block.category == "trigger"

    def test_get_nonexistent_block(self, loaded_registry):
        assert loaded_registry.get("nonexistent_block") is None

    def test_register_new_block(self, loaded_registry):
        new_block = BlockDefinition(
            id="custom_block",
            name="Custom Block",
            description="A dynamically created block",
            category="think",
            organ="openai",
        )
        loaded_registry.register(new_block)
        assert loaded_registry.get("custom_block") is not None
        assert loaded_registry.count == 36

    def test_list_by_category(self, loaded_registry):
        triggers = loaded_registry.list_by_category(BlockCategory.TRIGGER)
        assert len(triggers) == 4
        assert all(b.category == "trigger" for b in triggers)

        think_blocks = loaded_registry.list_by_category(BlockCategory.THINK)
        assert len(think_blocks) == 5

        perceive_blocks = loaded_registry.list_by_category(BlockCategory.PERCEIVE)
        assert len(perceive_blocks) == 8

        act_blocks = loaded_registry.list_by_category(BlockCategory.ACT)
        assert len(act_blocks) == 4

        communicate_blocks = loaded_registry.list_by_category(BlockCategory.COMMUNICATE)
        assert len(communicate_blocks) == 4

        remember_blocks = loaded_registry.list_by_category(BlockCategory.REMEMBER)
        assert len(remember_blocks) == 5

        control_blocks = loaded_registry.list_by_category(BlockCategory.CONTROL)
        assert len(control_blocks) == 5

    def test_list_by_tier(self, loaded_registry):
        tier1 = loaded_registry.list_by_tier(1)
        assert len(tier1) == 35  # All blocks are Tier 1

    def test_search_by_keyword(self, loaded_registry):
        results = loaded_registry.search("payment stripe")
        assert len(results) > 0
        assert results[0].id == "stripe_pay"

    def test_search_by_description(self, loaded_registry):
        results = loaded_registry.search("summarize content")
        assert any(b.id == "claude_summarize" for b in results)

    def test_search_no_results(self, loaded_registry):
        results = loaded_registry.search("xyznonexistent")
        assert results == []

    def test_search_image_analysis(self, loaded_registry):
        results = loaded_registry.search("analyze image")
        assert any(b.id == "gemini_analyze_image" for b in results)

    def test_search_memory(self, loaded_registry):
        results = loaded_registry.search("read memory key")
        assert any(b.id == "memory_read" for b in results)

    def test_all_blocks_have_required_fields(self, loaded_registry):
        """Every block should have id, name, description, category, organ."""
        for block in loaded_registry.list_all():
            assert block.id
            assert block.name
            assert block.description
            assert block.category
            assert block.organ

    def test_all_block_ids_unique(self, loaded_registry):
        ids = [b.id for b in loaded_registry.list_all()]
        assert len(ids) == len(set(ids)), "Duplicate block IDs found"

    def test_all_blocks_have_examples(self, loaded_registry):
        """Every block should have at least one example."""
        for block in loaded_registry.list_all():
            assert len(block.examples) > 0, f"Block {block.id} has no examples"
