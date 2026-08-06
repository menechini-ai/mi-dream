import os
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest

from mi_dream.knowledge.distiller import KnowledgeDistiller
from mi_dream.knowledge.models import CuratorDecision, Lesson, Strategy, StrategyState


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


def make_lesson(decision=CuratorDecision.CREATE, **kw):
    defaults = dict(
        id="l1",
        summary="Debug K8s pods first",
        decision=decision,
        source_trace_ids=["t1"],
        confidence=0.8,
        tenant_id="default",
    )
    defaults.update(kw)
    return Lesson(**defaults)


def make_strategy(**kw):
    defaults = dict(
        id="s1", title="Debug K8s", description="d", domain="general", content="c",
        state=StrategyState.EXPERIMENTAL, support_count=0, success_rate=0.0,
        created_at="2024-01-01T00:00:00Z", updated_at="2024-01-01T00:00:00Z",
        tenant_id="default", superseded_by=None,
    )
    defaults.update(kw)
    return Strategy(**defaults)


@pytest.mark.asyncio
async def test_distill_create_creates_strategy_and_links():
    session = AsyncMock()
    created = make_strategy()
    session.run.return_value.single.return_value = {"s": created.model_dump(mode="json")}
    distiller = KnowledgeDistiller(session)

    strategies = await distiller.distill([make_lesson(CuratorDecision.CREATE)], "default")

    assert len(strategies) == 1
    queries = [c.args[0] for c in session.run.call_args_list]
    assert any("CREATE (s:Strategy" in q for q in queries)
    assert any("SUPPORTED_BY" in q for q in queries)


@pytest.mark.asyncio
async def test_distill_reinforce_links_existing_strategy():
    session = AsyncMock()
    existing = make_strategy(support_count=2, success_rate=0.7)

    async def mock_run(query, **kwargs):
        if "MATCH (s:Strategy {domain:" in query:
            return FakeAsyncIter([{"s": existing.model_dump(mode="json")}])
        r = AsyncMock()
        r.single.return_value = {"s": existing.model_dump(mode="json")}
        return r

    session.run.side_effect = mock_run
    distiller = KnowledgeDistiller(session)

    strategies = await distiller.distill(
        [make_lesson(CuratorDecision.REINFORCE, summary="Debug K8s pods first")], "default"
    )

    assert len(strategies) == 1
    queries = [c.args[0] for c in session.run.call_args_list]
    assert not any("CREATE (s:Strategy" in q for q in queries)
    assert any("support_count = s.support_count" in q for q in queries)
    assert any("SUPPORTED_BY" in q for q in queries)


@pytest.mark.asyncio
async def test_distill_reinforce_creates_when_no_match():
    session = AsyncMock()
    created = make_strategy()

    async def mock_run(query, **kwargs):
        if "MATCH (s:Strategy {domain:" in query:
            return FakeAsyncIter([])
        r = AsyncMock()
        r.single.return_value = {"s": created.model_dump(mode="json")}
        return r

    session.run.side_effect = mock_run
    distiller = KnowledgeDistiller(session)

    strategies = await distiller.distill(
        [make_lesson(CuratorDecision.REINFORCE, summary="Something brand new")], "default"
    )

    assert len(strategies) == 1
    queries = [c.args[0] for c in session.run.call_args_list]
    assert any("CREATE (s:Strategy" in q for q in queries)


@pytest.mark.asyncio
async def test_distill_skips_contradict():
    session = AsyncMock()
    distiller = KnowledgeDistiller(session)

    strategies = await distiller.distill([make_lesson(CuratorDecision.CONTRADICT)], "default")

    assert strategies == []
    queries = [c.args[0] for c in session.run.call_args_list]
    assert not any("CREATE (s:Strategy" in q for q in queries)
    assert not any("SUPPORTED_BY" in q for q in queries)


@pytest.mark.asyncio
async def test_pending_lessons_fetches_unlinked():
    session = AsyncMock()
    lesson = make_lesson(CuratorDecision.CREATE)
    session.run.return_value = FakeAsyncIter([{"lesson": lesson.model_dump(mode="json")}])
    distiller = KnowledgeDistiller(session)

    lessons = await distiller.pending_lessons("default")

    assert len(lessons) == 1
    query = session.run.call_args.args[0]
    assert "SUPPORTED_BY" in query
    assert "NOT EXISTS" in query


@pytest.mark.asyncio
async def test_distill_create_embeds_strategy_when_embedder_available():
    session = AsyncMock()
    created = make_strategy()
    embedder = AsyncMock()
    embedder.embed_query.return_value = [0.1, 0.2, 0.3]

    async def mock_run(query, **kwargs):
        if "CREATE (s:Strategy" in query:
            r = AsyncMock()
            r.single.return_value = {"s": created.model_dump(mode="json")}
            return r
        if "s.embedding = $embedding" in query:
            r = AsyncMock()
            r.single.return_value = {"count": 1}
            return r
        r = AsyncMock()
        r.single.return_value = None
        return r

    session.run.side_effect = mock_run
    distiller = KnowledgeDistiller(session, embedder=embedder)

    await distiller.distill([make_lesson(CuratorDecision.CREATE)], "default")

    embedder.embed_query.assert_called_once_with("Debug K8s pods first")
    queries = [c.args[0] for c in session.run.call_args_list]
    assert any("s.embedding = $embedding" in q for q in queries)
    assert any("SUPPORTED_BY" in q for q in queries)


@pytest.mark.asyncio
async def test_distill_create_skips_embedding_on_failure():
    session = AsyncMock()
    created = make_strategy()
    embedder = AsyncMock()
    embedder.embed_query.side_effect = RuntimeError("proxy down")

    async def mock_run(query, **kwargs):
        if "CREATE (s:Strategy" in query:
            r = AsyncMock()
            r.single.return_value = {"s": created.model_dump(mode="json")}
            return r
        r = AsyncMock()
        r.single.return_value = None
        return r

    session.run.side_effect = mock_run
    distiller = KnowledgeDistiller(session, embedder=embedder)

    strategies = await distiller.distill(
        [make_lesson(CuratorDecision.CREATE)], "default"
    )

    assert len(strategies) == 1
    queries = [c.args[0] for c in session.run.call_args_list]
    assert not any("s.embedding" in q for q in queries)
    assert any("SUPPORTED_BY" in q for q in queries)
