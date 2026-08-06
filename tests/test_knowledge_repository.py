import os
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest

from mi_dream.knowledge.models import Strategy, StrategyState
from mi_dream.knowledge.repository import StrategyRepository


def make_strategy(**overrides):
    defaults = dict(
        id="s1", title="t", description="d", domain="dev", content="c",
        state=StrategyState.EXPERIMENTAL, support_count=0, success_rate=0.0,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        tenant_id="default", superseded_by=None,
    )
    defaults.update(overrides)
    return Strategy(**defaults)


@pytest.mark.asyncio
async def test_mark_superseded_creates_supersedes_relationship():
    session = AsyncMock()
    s = make_strategy(state=StrategyState.SUPERSEDED)
    session.run.return_value.single.return_value = {"s": s.model_dump(mode="json")}
    repo = StrategyRepository(session)

    await repo.mark_superseded("s1", "s2")

    query = session.run.call_args.args[0]
    assert "[:SUPERSEDES]" in query
    assert "superseded_by = $successor_id" not in query


@pytest.mark.asyncio
async def test_mark_superseded_keeps_single_successor():
    session = AsyncMock()
    s = make_strategy(state=StrategyState.SUPERSEDED)
    session.run.return_value.single.return_value = {"s": s.model_dump(mode="json")}
    repo = StrategyRepository(session)

    await repo.mark_superseded("s1", "s3")

    query = session.run.call_args.args[0]
    assert "DELETE old" in query


@pytest.mark.asyncio
async def test_get_resolves_superseded_by_via_relationship():
    session = AsyncMock()
    s = make_strategy(state=StrategyState.SUPERSEDED)
    data = {**s.model_dump(mode="json"), "superseded_by": "s2"}
    session.run.return_value.single.return_value = {"s": data}
    repo = StrategyRepository(session)

    result = await repo.get("s1")

    assert result.superseded_by == "s2"
    query = session.run.call_args.args[0]
    assert "succ.id" in query


@pytest.mark.asyncio
async def test_update_metrics_clamps_negative_delta_invariant_002a():
    session = AsyncMock()
    s = make_strategy(support_count=3, success_rate=0.7)
    session.run.return_value.single.return_value = {"s": s.model_dump(mode="json")}
    repo = StrategyRepository(session)

    await repo.update_metrics("s1", -5, 0.7)

    query = session.run.call_args.args[0]
    assert "$delta < 0" in query
    assert "CASE WHEN $delta < 0 THEN 0 ELSE $delta END" in query


@pytest.mark.asyncio
async def test_update_metrics_positive_delta_accumulates():
    session = AsyncMock()
    s = make_strategy(support_count=5, success_rate=0.7)
    session.run.return_value.single.return_value = {"s": s.model_dump(mode="json")}
    repo = StrategyRepository(session)

    await repo.update_metrics("s1", 2, 0.7)

    query = session.run.call_args.args[0]
    assert "CASE WHEN $delta < 0 THEN 0 ELSE $delta END" in query


@pytest.mark.asyncio
async def test_set_embedding_sets_vector():
    session = AsyncMock()
    session.run.return_value.single.return_value = None
    repo = StrategyRepository(session)

    await repo.set_embedding("s1", [0.1, 0.2, 0.3])

    query = session.run.call_args.args[0]
    assert "s.embedding = $embedding" in query
    assert session.run.call_args.kwargs["embedding"] == [0.1, 0.2, 0.3]
