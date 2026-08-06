import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from unittest.mock import AsyncMock

import pytest

from mi_dream.knowledge.models import StrategyCreate, StrategyState
from mi_dream.knowledge.repository import StrategyRepository
from mi_dream.knowledge.service import StrategyService


def make_strategy(**overrides):
    defaults = dict(
        id="s1", title="t", description="d", domain="dev", content="c",
        state=StrategyState.EXPERIMENTAL, support_count=0, success_rate=0.0,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        tenant_id="default", superseded_by=None,
    )
    defaults.update(overrides)
    from mi_dream.knowledge.models import Strategy
    return Strategy(**defaults)


@pytest.mark.asyncio
async def test_create_strategy():
    session = AsyncMock()
    s = make_strategy()
    session.run.return_value.single.return_value = {"s": s.model_dump(mode="json")}
    repo = StrategyRepository(session)
    service = StrategyService(repo)
    result = await service.create(
        StrategyCreate(title="t", description="d", domain="dev", content="c")
    )
    assert result.id == "s1"
    assert result.state == StrategyState.EXPERIMENTAL


@pytest.mark.asyncio
async def test_promote_to_active_succeeds_when_eligible():
    session = AsyncMock()
    eligible = make_strategy(support_count=3, success_rate=0.7)
    session.run.return_value.single.return_value = {"s": eligible.model_dump(mode="json")}
    repo = StrategyRepository(session)
    service = StrategyService(repo)
    result = await service.promote_to_active("s1")
    assert result is not None


@pytest.mark.asyncio
async def test_promote_to_active_fails_when_insufficient_support():
    session = AsyncMock()
    ineligible = make_strategy(support_count=2, success_rate=0.7)
    session.run.return_value.single.return_value = {"s": ineligible.model_dump(mode="json")}
    repo = StrategyRepository(session)
    service = StrategyService(repo)
    result = await service.promote_to_active("s1")
    assert result is None


@pytest.mark.asyncio
async def test_invalid_transition_raises():
    session = AsyncMock()
    s = make_strategy(state=StrategyState.ARCHIVED)
    session.run.return_value.single.return_value = {"s": s.model_dump(mode="json")}
    repo = StrategyRepository(session)
    service = StrategyService(repo)
    with pytest.raises(ValueError, match="Invalid transition"):
        await service.transition("s1", StrategyState.ACTIVE)


@pytest.mark.asyncio
async def test_supersede_marks_superseded_via_relationship():
    session = AsyncMock()
    active = make_strategy(state=StrategyState.ACTIVE)
    session.run.return_value.single.return_value = {"s": active.model_dump(mode="json")}
    repo = StrategyRepository(session)
    service = StrategyService(repo)

    result = await service.supersede("s1", "s2")

    assert result is not None
    query = session.run.call_args.args[0]
    assert "[:SUPERSEDES]" in query


@pytest.mark.asyncio
async def test_list_by_domain_filters_tenant():
    from unittest.mock import MagicMock
    session = AsyncMock()
    strategies = [make_strategy(domain="kubernetes"), make_strategy(domain="kubernetes")]
    items = [{"s": s.model_dump(mode="json")} for s in strategies]

    class FakeAsyncIter:
        def __init__(self, items):
            self._items = items
            self._i = 0
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self._i >= len(self._items):
                raise StopAsyncIteration
            item = self._items[self._i]
            self._i += 1
            return item

    session.run.return_value = MagicMock(__aiter__=lambda self: FakeAsyncIter(items))
    repo = StrategyRepository(session)
    result = await repo.list_by_domain("kubernetes", "default")
    assert len(result) == 2
