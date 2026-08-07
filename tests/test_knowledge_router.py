import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from unittest.mock import AsyncMock

import pytest

from mi_dream.knowledge.models import Strategy, StrategyState
from mi_dream.knowledge.repository import StrategyRepository
from mi_dream.knowledge.router import ExecutionContext, StrategyRouter


def _strategy(**kwargs):
    defaults = dict(
        id="s1", title="K8s debug", description="d", domain="kubernetes",
        content="Check pods first", state=StrategyState.ACTIVE,
        support_count=3, success_rate=0.7,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        tenant_id="default",
    )
    defaults.update(kwargs)
    return Strategy(**defaults)


@pytest.mark.asyncio
async def test_retrieve_returns_context_with_strategies():
    repo = AsyncMock(spec=StrategyRepository)
    strategy = _strategy()
    repo.list_by_domain.return_value = [strategy]
    router = StrategyRouter(repo)
    ctx = await router.retrieve("diagnose k8s", {"domain": "kubernetes"}, "default")
    assert len(ctx.strategies) == 1
    assert ctx.strategies[0].title == "K8s debug"
    assert ctx.goal == "diagnose k8s"


@pytest.mark.asyncio
async def test_retrieve_graceful_degradation_when_no_strategies():
    repo = AsyncMock(spec=StrategyRepository)
    repo.list_by_domain.return_value = []
    router = StrategyRouter(repo)
    ctx = await router.retrieve("unknown task", {"domain": "nonexistent"}, "default")
    assert ctx.strategies == []
    assert ctx.goal == "unknown task"


@pytest.mark.asyncio
async def test_retrieve_uses_default_domain():
    repo = AsyncMock(spec=StrategyRepository)
    repo.list_by_domain.return_value = []
    router = StrategyRouter(repo)
    await router.retrieve("task", {}, "default")
    repo.list_by_domain.assert_called_once_with(
        domain="general", tenant_id="default", state=StrategyState.ACTIVE
    )


@pytest.mark.asyncio
async def test_retrieve_uses_vector_when_available():
    repo = AsyncMock(spec=StrategyRepository)
    vector = AsyncMock()
    strategy = _strategy()
    vector.search.return_value = [strategy]
    router = StrategyRouter(repo, vector_retriever=vector)

    ctx = await router.retrieve("diagnose k8s", {"domain": "kubernetes"}, "default")

    vector.search.assert_awaited_once_with("diagnose k8s", "default", "kubernetes", 5)
    assert ctx.strategies == [strategy]
    repo.list_by_domain.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_falls_back_to_domain_on_vector_failure():
    repo = AsyncMock(spec=StrategyRepository)
    vector = AsyncMock()
    vector.search.side_effect = RuntimeError("index down")
    strategy = _strategy()
    repo.list_by_domain.return_value = [strategy]
    router = StrategyRouter(repo, vector_retriever=vector)

    ctx = await router.retrieve("x", {"domain": "kubernetes"}, "default")

    assert ctx.strategies == [strategy]
    repo.list_by_domain.assert_called_once()


@pytest.mark.asyncio
async def test_retrieve_falls_back_to_domain_when_vector_empty():
    repo = AsyncMock(spec=StrategyRepository)
    vector = AsyncMock()
    vector.search.return_value = []
    repo.list_by_domain.return_value = []
    router = StrategyRouter(repo, vector_retriever=vector)

    ctx = await router.retrieve("x", {"domain": "kubernetes"}, "default")

    assert ctx.strategies == []
    repo.list_by_domain.assert_called_once()


def test_execution_context_defaults_recent_memory():
    ctx = ExecutionContext(goal="x")
    assert ctx.recent_traces == []
    assert ctx.episodes == []
    data = ctx.to_dict()
    assert "recent_traces" in data
    assert "episodes" in data


@pytest.mark.asyncio
async def test_retrieve_fills_previous_failures_from_failure_repo():
    from mi_dream.knowledge.models import FailurePattern

    repo = AsyncMock(spec=StrategyRepository)
    repo.list_by_domain.return_value = []
    failure_repo = AsyncMock()
    fp = FailurePattern(
        id="fp1",
        error_type="rate_limit_error",
        domain="kubernetes",
        pattern="Too Many Requests",
        failure_count=3,
        last_seen=datetime.now(UTC),
        created_at=datetime.now(UTC),
        signature="ab" * 8,
        tenant_id="default",
    )
    failure_repo.list_by_domain.return_value = [fp]

    router = StrategyRouter(repo, failure_repo=failure_repo)
    ctx = await router.retrieve("x", {"domain": "kubernetes"}, "default")

    assert len(ctx.previous_failures) == 1
    assert ctx.previous_failures[0]["error_type"] == "rate_limit_error"
    assert ctx.previous_failures[0]["failure_count"] == 3
    failure_repo.list_by_domain.assert_awaited_once_with("kubernetes", "default")


@pytest.mark.asyncio
async def test_retrieve_without_failure_repo_leaves_previous_failures_empty():
    repo = AsyncMock(spec=StrategyRepository)
    repo.list_by_domain.return_value = []
    router = StrategyRouter(repo)
    ctx = await router.retrieve("x", {"domain": "kubernetes"}, "default")
    assert ctx.previous_failures == []
