import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from datetime import UTC, datetime

import pytest
from conftest import FakeAsyncIter

from mi_dream.agents.tools import recall_strategy, save_reasoning_trace
from mi_dream.knowledge.models import Strategy, StrategyState
from mi_dream.knowledge.router import ExecutionContext


def _strategy(**kwargs):
    defaults = dict(
        id="s1", title="t", description="d", domain="dev", content="c",
        state=StrategyState.ACTIVE, support_count=3, success_rate=0.7,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        tenant_id="default",
    )
    defaults.update(kwargs)
    return Strategy(**defaults)


@pytest.mark.asyncio
async def test_recall_strategy_returns_execution_context():
    router = AsyncMock()
    ctx = ExecutionContext(goal="test goal", strategies=[])
    router.retrieve.return_value = ctx
    result = await recall_strategy("test goal", {"domain": "test"}, "default", router)
    assert result.goal == "test goal"
    router.retrieve.assert_called_once_with("test goal", {"domain": "test"}, "default")


@pytest.mark.asyncio
async def test_save_reasoning_trace_writes_to_neo4j():
    from conftest import make_driver_mock

    mock_session = AsyncMock()
    mock_run_result = AsyncMock()
    mock_session.run.return_value = mock_run_result
    driver = make_driver_mock(mock_session)
    meta = {"tenant_id": "default"}
    await save_reasoning_trace("t1", "trace content", meta, driver)
    mock_session.run.assert_called_once()
    call_args = mock_session.run.call_args
    assert "ReasoningTrace" in call_args[0][0]
    assert call_args[1]["trace_id"] == "t1"


@pytest.mark.asyncio
async def test_save_reasoning_trace_sanitizes_pii():
    from conftest import make_driver_mock

    mock_session = AsyncMock()
    mock_session.run.return_value = AsyncMock()
    driver = make_driver_mock(mock_session)
    dirty = "contact user@example.com with api_key=sk-secret"
    await save_reasoning_trace("t2", dirty, {"tenant_id": "default"}, driver)
    written = mock_session.run.call_args[1]["content"]
    assert "user@example.com" not in written
    assert "sk-secret" not in written
    assert "[REDACTED]" in written


@pytest.mark.asyncio
async def test_save_reasoning_trace_serializes_metadata():
    from conftest import make_driver_mock

    mock_session = AsyncMock()
    driver = make_driver_mock(mock_session)
    await save_reasoning_trace(
        "t1", "trace content", {"tenant_id": "default", "outcome": "success"}, driver
    )
    metadata = mock_session.run.call_args[1]["metadata"]
    assert isinstance(metadata, str)
    assert json.loads(metadata)["outcome"] == "success"


@pytest.mark.asyncio
async def test_save_reasoning_trace_persists_outcome_property():
    from conftest import make_driver_mock

    mock_session = AsyncMock()
    driver = make_driver_mock(mock_session)
    await save_reasoning_trace(
        "t1", "c", {"tenant_id": "default", "outcome": "failure"}, driver
    )
    kwargs = mock_session.run.call_args[1]
    assert kwargs["outcome"] == "failure"


@pytest.mark.asyncio
async def test_save_reasoning_trace_stores_error_props():
    from conftest import make_driver_mock

    mock_session = AsyncMock()
    driver = make_driver_mock(mock_session)
    await save_reasoning_trace(
        "t1",
        "c",
        {
            "tenant_id": "default",
            "outcome": "failure",
            "error_type": "rate_limit_error",
            "error_source": "skill",
        },
        driver,
    )
    kwargs = mock_session.run.call_args[1]
    assert kwargs["error_type"] == "rate_limit_error"
    assert kwargs["error_source"] == "skill"


async def test_make_recall_strategy_tool_returns_json_context():
    from conftest import make_driver_mock

    from mi_dream.agents.tools import make_recall_strategy_tool
    from mi_dream.knowledge.router import ExecutionContext

    mock_session = AsyncMock()
    driver = make_driver_mock(mock_session)
    ctx = ExecutionContext(goal="deploy k8s", strategies=[_strategy()])
    mock_session.run.return_value = FakeAsyncIter([])

    async def fake_retrieve(goal, context, tenant_id):
        return ctx

    tool_fn = make_recall_strategy_tool("default")
    with patch("mi_dream.agents.tools.get_driver", return_value=driver):
        with patch(
            "mi_dream.agents.tools.StrategyRouter",
            return_value=MagicMock(retrieve=fake_retrieve),
        ):
            result = await tool_fn.ainvoke({"goal": "deploy k8s", "context": "{}"})

    import json

    parsed = json.loads(result)
    assert parsed["goal"] == "deploy k8s"
    assert len(parsed["strategies"]) == 1
    assert parsed["strategies"][0]["title"] == "t"


async def test_make_recall_strategy_tool_degrades_gracefully():
    from mi_dream.agents.tools import make_recall_strategy_tool

    tool_fn = make_recall_strategy_tool("default")
    with patch(
        "mi_dream.agents.tools.get_driver", side_effect=RuntimeError("neo4j down")
    ):
        result = await tool_fn.ainvoke({"goal": "anything", "context": "{}"})

    import json

    parsed = json.loads(result)
    assert parsed["goal"] == "anything"
    assert parsed["strategies"] == []


async def test_make_save_reasoning_trace_tool_sanitizes():
    from conftest import make_driver_mock

    from mi_dream.agents.tools import make_save_reasoning_trace_tool

    mock_session = AsyncMock()
    mock_session.run.return_value = AsyncMock()
    driver = make_driver_mock(mock_session)
    tool_fn = make_save_reasoning_trace_tool("default")
    with patch("mi_dream.agents.tools.get_driver", return_value=driver):
        reply = await tool_fn.ainvoke(
            {
                "trace_id": "t9",
                "content": "mail a@b.com key=zz",
                "outcome": "success",
            }
        )
    assert "t9" in reply
    written = mock_session.run.call_args[1]["content"]
    assert "a@b.com" not in written
    assert "[REDACTED]" in written
    metadata = mock_session.run.call_args[1]["metadata"]
    assert isinstance(metadata, str)
    assert json.loads(metadata)["tenant_id"] == "default"
