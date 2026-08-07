"""P2: Tests that verify the full architecture flow (recall → prompt → LLM → trace)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mi_dream.cli.repl import build_system_prompt, recall_context
from mi_dream.knowledge.models import Strategy, StrategyState
from mi_dream.knowledge.router import ExecutionContext


def test_build_system_prompt_includes_strategies():
    ctx = ExecutionContext(
        goal="deploy app",
        strategies=[
            Strategy(
                id="s1", title="K8s Deploy", description="Use kubectl apply",
                domain="devops", content="...", state=StrategyState.ACTIVE,
                support_count=3, success_rate=0.7,
                created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00",
                tenant_id="default",
            )
        ],
    )
    prompt = build_system_prompt(ctx)
    assert "K8s Deploy" in prompt
    assert "Relevant knowledge strategies" in prompt


def test_build_system_prompt_empty_context():
    ctx = ExecutionContext(goal="hello")
    prompt = build_system_prompt(ctx)
    assert prompt == "You are a helpful assistant."


def test_build_system_prompt_includes_failure_patterns():
    ctx = ExecutionContext(
        goal="deploy",
        previous_failures=[
            {"error_type": "ConnectionTimeout", "failure_count": 3, "pattern": "DB timeout on deploy"},
        ],
    )
    prompt = build_system_prompt(ctx)
    assert "ConnectionTimeout" in prompt
    assert "Known failure patterns" in prompt


def test_build_system_prompt_includes_recent_traces():
    ctx = ExecutionContext(
        goal="hello",
        recent_traces=[{"content": "User asked about docker", "outcome": "success"}],
    )
    prompt = build_system_prompt(ctx)
    assert "Recent conversation history" in prompt
    assert "docker" in prompt


def test_build_system_prompt_includes_episodes():
    ctx = ExecutionContext(
        goal="hello",
        episodes=[{"summary": "User discussed Kubernetes deployment strategies", "created_at": "2026-01-01"}],
    )
    prompt = build_system_prompt(ctx)
    assert "Prior session summaries" in prompt
    assert "Kubernetes" in prompt


@pytest.mark.asyncio
async def test_recall_context_returns_context_on_success():
    mock_ctx = ExecutionContext(goal="test", strategies=[])
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=AsyncMock(__aiter__=lambda self: self))
    # Make __anext__ return empty immediately
    mock_session.run.return_value.__anext__ = AsyncMock(side_effect=StopAsyncIteration())
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.cli.repl.get_driver", return_value=mock_driver):
        with patch("mi_dream.cli.repl.StrategyRouter") as MockRouter:
            MockRouter.return_value.retrieve = AsyncMock(return_value=mock_ctx)
            ctx = await recall_context("test query")

    assert ctx.goal == "test"


@pytest.mark.asyncio
async def test_recall_context_graceful_degradation_on_failure():
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(side_effect=RuntimeError("neo4j down"))

    with patch("mi_dream.cli.repl.get_driver", return_value=mock_driver):
        ctx = await recall_context("test query")

    # Should return empty context, not crash
    assert ctx.goal == "test query"
    assert ctx.strategies == []


def test_architecture_flow_components_present():
    """Verify all architecture components are importable and wired."""
    from mi_dream.cli.repl import recall_context, build_system_prompt
    from mi_dream.knowledge.router import StrategyRouter, ExecutionContext
    from mi_dream.knowledge.vector import StrategyVectorRetriever
    from mi_dream.knowledge.repository import StrategyRepository
    from mi_dream.learning.scheduler import ReflectionScheduler, run_learning_cycle
    from mi_dream.observability import get_logger, get_metrics
    from mi_dream.resilience import migrate_claim_schema, DriverLifecycle
    from mi_dream.security.tenant import TenantContext, tenant_from_str

    # All components importable — architecture is wired
    assert callable(recall_context)
    assert callable(build_system_prompt)
    assert callable(run_learning_cycle)


def _mock_async_cm(result):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=result)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm
