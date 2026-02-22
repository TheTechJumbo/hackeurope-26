"""Tests for all 10 Phase 2 block implementations."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.blocks.executor import BlockExecutor, get_implementation
from app.blocks.loader import load_all_implementations
from app.blocks.registry import BlockRegistry
from app.database import init_db, get_db
from app.memory.store import MemoryStore
from app.models.execution import ExecutionStatus


@pytest.fixture(scope="module", autouse=True)
def setup():
    init_db()
    load_all_implementations()


@pytest.fixture()
def executor():
    return BlockExecutor()


@pytest.fixture()
def registry():
    reg = BlockRegistry()
    reg.load_from_directory()
    return reg


@pytest.fixture()
def mem():
    store = MemoryStore()
    store.clear_namespace("test")
    yield store
    store.clear_namespace("test")


# ── Trigger Blocks ───────────────────────────────────────────────────

class TestTriggerManual:
    @pytest.mark.asyncio
    async def test_basic_trigger(self, executor, registry):
        block = registry.get("trigger_manual")
        result = await executor.execute(block, {"user_input": "find flights"})
        assert result.status == ExecutionStatus.COMPLETED
        assert "triggered_at" in result.output
        assert result.output["user_input"] == "find flights"

    @pytest.mark.asyncio
    async def test_no_user_input(self, executor, registry):
        block = registry.get("trigger_manual")
        result = await executor.execute(block, {})
        assert result.status == ExecutionStatus.COMPLETED
        assert result.output["user_input"] == ""


class TestTriggerCron:
    @pytest.mark.asyncio
    async def test_cron_trigger(self, executor, registry):
        block = registry.get("trigger_cron")
        result = await executor.execute(
            block, {"schedule": "0 8 * * 2", "timezone": "Europe/Dublin"}
        )
        assert result.status == ExecutionStatus.COMPLETED
        assert result.output["schedule"] == "0 8 * * 2"
        assert "triggered_at" in result.output


# ── Perceive Blocks ──────────────────────────────────────────────────

class TestWebSearch:
    @pytest.mark.asyncio
    async def test_no_api_key_raises(self, executor, registry):
        """Without API key, raises a clear error."""
        block = registry.get("web_search")
        with patch("app.blocks.implementations.perceive.web_search.settings") as mock_settings:
            mock_settings.serper_api_key = ""
            result = await executor.execute(
                block, {"query": "best protein powder", "num_results": 3}
            )
            assert result.status == ExecutionStatus.FAILED
            assert "SERPER_API_KEY" in result.error

    @pytest.mark.asyncio
    async def test_search_with_mocked_api(self, executor, registry):
        """With mocked Serper API, returns real-shaped results."""
        block = registry.get("web_search")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic": [
                {"title": "Result 1", "link": "https://example.com/1", "snippet": "Snippet 1"},
                {"title": "Result 2", "link": "https://example.com/2", "snippet": "Snippet 2"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.blocks.implementations.perceive.web_search.settings") as mock_settings, \
             patch("app.blocks.implementations.perceive.web_search.httpx.AsyncClient", return_value=mock_client):
            mock_settings.serper_api_key = "test-key"
            result = await executor.execute(
                block, {"query": "best protein powder", "num_results": 2}
            )

        assert result.status == ExecutionStatus.COMPLETED
        assert len(result.output["results"]) == 2
        assert result.output["results"][0]["title"] == "Result 1"


class TestWebScrape:
    @pytest.mark.asyncio
    async def test_scrape_returns_text(self, executor, registry):
        block = registry.get("web_scrape")
        result = await executor.execute(
            block, {"url": "https://httpbin.org/html"}
        )
        assert result.status == ExecutionStatus.COMPLETED
        assert len(result.output["text"]) > 0
        assert result.output["url"] == "https://httpbin.org/html"


# ── Think Blocks ─────────────────────────────────────────────────────

class TestClaudeDecide:
    @pytest.mark.asyncio
    async def test_no_api_key_raises(self, executor, registry):
        """Without API key, raises a clear error."""
        block = registry.get("claude_decide")
        with patch("app.blocks.implementations.think.claude_decide.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            result = await executor.execute(
                block,
                {
                    "options": [{"name": "A", "price": 10}, {"name": "B", "price": 5}],
                    "criteria": "cheapest",
                },
            )
            assert result.status == ExecutionStatus.FAILED
            assert "OPENAI_API_KEY" in result.error

    @pytest.mark.asyncio
    async def test_decide_with_mocked_api(self, executor, registry):
        """With mocked Claude API, returns decision."""
        block = registry.get("claude_decide")

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"chosen": {"name": "B", "price": 5}, "reasoning": "Cheapest option", "confidence": 0.9}'))
        ]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.blocks.implementations.think.claude_decide.settings") as mock_settings, \
             patch("app.blocks.implementations.think.claude_decide.AsyncOpenAI", return_value=mock_client):
            mock_settings.openai_api_key = "test-key"
            result = await executor.execute(
                block,
                {
                    "options": [{"name": "A", "price": 10}, {"name": "B", "price": 5}],
                    "criteria": "cheapest",
                },
            )

        assert result.status == ExecutionStatus.COMPLETED
        assert "chosen" in result.output
        assert "reasoning" in result.output


class TestClaudeSummarize:
    @pytest.mark.asyncio
    async def test_no_api_key_raises(self, executor, registry):
        """Without API key, raises a clear error."""
        block = registry.get("claude_summarize")
        with patch("app.blocks.implementations.think.claude_summarize.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            result = await executor.execute(
                block, {"content": "This is a long article about AI regulation."}
            )
            assert result.status == ExecutionStatus.FAILED
            assert "OPENAI_API_KEY" in result.error

    @pytest.mark.asyncio
    async def test_summarize_with_mocked_api(self, executor, registry):
        """With mocked Claude API, returns summary."""
        block = registry.get("claude_summarize")

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"summary": "AI regulation is evolving.", "key_points": ["Point 1", "Point 2"]}'))
        ]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.blocks.implementations.think.claude_summarize.settings") as mock_settings, \
             patch("app.blocks.implementations.think.claude_summarize.AsyncOpenAI", return_value=mock_client):
            mock_settings.openai_api_key = "test-key"
            result = await executor.execute(
                block, {"content": "This is a long article about AI regulation in Europe."}
            )

        assert result.status == ExecutionStatus.COMPLETED
        assert "summary" in result.output
        assert "key_points" in result.output


# ── Remember Blocks ──────────────────────────────────────────────────

class TestMemoryOps:
    @pytest.mark.asyncio
    async def test_write_and_read(self, executor, registry, mem):
        write_block = registry.get("memory_write")
        read_block = registry.get("memory_read")

        # Write
        w_result = await executor.execute(
            write_block, {"key": "test_key", "value": 42, "namespace": "test"}
        )
        assert w_result.status == ExecutionStatus.COMPLETED
        assert w_result.output["success"] is True

        # Read
        r_result = await executor.execute(
            read_block, {"key": "test_key", "namespace": "test"}
        )
        assert r_result.status == ExecutionStatus.COMPLETED
        assert r_result.output["value"] == 42
        assert r_result.output["found"] is True

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, executor, registry):
        block = registry.get("memory_read")
        result = await executor.execute(
            block, {"key": "nonexistent_key_xyz", "namespace": "test"}
        )
        assert result.status == ExecutionStatus.COMPLETED
        assert result.output["found"] is False
        assert result.output["value"] is None

    @pytest.mark.asyncio
    async def test_append(self, executor, registry, mem):
        block = registry.get("memory_append")

        r1 = await executor.execute(
            block, {"key": "my_list", "value": "item1", "namespace": "test"}
        )
        assert r1.output["list_length"] == 1

        r2 = await executor.execute(
            block, {"key": "my_list", "value": "item2", "namespace": "test"}
        )
        assert r2.output["list_length"] == 2

        # Verify the full list
        read_block = registry.get("memory_read")
        r3 = await executor.execute(
            read_block, {"key": "my_list", "namespace": "test"}
        )
        assert r3.output["value"] == ["item1", "item2"]


# ── Communicate Blocks ───────────────────────────────────────────────

class TestNotifyInApp:
    @pytest.mark.asyncio
    async def test_notification(self, executor, registry):
        block = registry.get("notify_in_app")
        result = await executor.execute(
            block,
            {"title": "Price Alert", "message": "PS5 dropped!", "level": "success"},
        )
        assert result.status == ExecutionStatus.COMPLETED
        assert result.output["delivered"] is True
        assert isinstance(result.output["notification_id"], int)

    @pytest.mark.asyncio
    async def test_notification_persists_to_db(self, executor, registry):
        """notify_in_app should write to the notifications table."""
        block = registry.get("notify_in_app")
        await executor.execute(
            block,
            {"title": "DB Test", "message": "Should persist", "level": "info"},
        )

        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM notifications WHERE title = 'DB Test'"
            ).fetchone()
            assert row is not None
            assert row["message"] == "Should persist"
            assert row["level"] == "info"
            assert row["category"] == "notification"


class TestAskUserConfirm:
    @pytest.mark.asyncio
    async def test_auto_confirms(self, executor, registry):
        block = registry.get("ask_user_confirm")
        result = await executor.execute(
            block,
            {"question": "Proceed with order?", "details": {"total": 99.99}},
        )
        assert result.status == ExecutionStatus.COMPLETED
        assert result.output["confirmed"] is True

    @pytest.mark.asyncio
    async def test_confirmation_persists_to_db(self, executor, registry):
        """ask_user_confirm should write a confirmation notification."""
        block = registry.get("ask_user_confirm")
        await executor.execute(
            block,
            {"question": "Buy this item?", "details": {"price": 50}},
        )

        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM notifications WHERE category = 'confirmation' AND message = 'Buy this item?'"
            ).fetchone()
            assert row is not None
            assert row["title"] == "Confirmation Requested"
            assert row["level"] == "warning"


# ── Control Flow Blocks ──────────────────────────────────────────────

class TestConditionalBranch:
    @pytest.mark.asyncio
    async def test_less_than_true(self, executor, registry):
        block = registry.get("conditional_branch")
        result = await executor.execute(
            block, {"condition": "price < 400", "value": 399}
        )
        assert result.output["branch"] == "true"

    @pytest.mark.asyncio
    async def test_less_than_false(self, executor, registry):
        block = registry.get("conditional_branch")
        result = await executor.execute(
            block, {"condition": "price < 400", "value": 450}
        )
        assert result.output["branch"] == "false"

    @pytest.mark.asyncio
    async def test_greater_than(self, executor, registry):
        block = registry.get("conditional_branch")
        result = await executor.execute(
            block, {"condition": "score > 100", "value": 150}
        )
        assert result.output["branch"] == "true"

    @pytest.mark.asyncio
    async def test_boolean_value(self, executor, registry):
        block = registry.get("conditional_branch")
        result = await executor.execute(
            block, {"condition": "", "value": True}
        )
        assert result.output["branch"] == "true"

    @pytest.mark.asyncio
    async def test_equality(self, executor, registry):
        block = registry.get("conditional_branch")
        result = await executor.execute(
            block, {"condition": "x == 42", "value": 42}
        )
        assert result.output["branch"] == "true"
