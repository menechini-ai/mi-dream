import os
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

import pytest
from conftest import FakeAsyncIter

from mi_dream.knowledge.curator import Curator
from mi_dream.knowledge.models import CuratorDecision, Strategy, StrategyCreate, StrategyState
from mi_dream.knowledge.repository import StrategyRepository
from mi_dream.knowledge.router import StrategyRouter
from mi_dream.learning.reflector import Reflector
from mi_dream.security.sanitizer import sanitize


def _strategy(**kwargs):
    defaults = dict(
        id="s1", title="K8s debug", description="d", domain="kubernetes",
        content="Check pods first", state=StrategyState.EXPERIMENTAL,
        support_count=3, success_rate=0.7,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        tenant_id="default", superseded_by=None,
    )
    defaults.update(kwargs)
    return Strategy(**defaults)


@pytest.mark.asyncio
async def test_full_phase1_flow():
    session = AsyncMock()
    s = _strategy()
    promoted = _strategy(state=StrategyState.ACTIVE)

    # Setup side_effect for different query types
    async def mock_run(*args, **kwargs):
        query = args[0] if args else ""
        if "CREATE (s:Strategy" in query:
            # create returns single
            r = AsyncMock()
            r.single.return_value = {"s": s.model_dump(mode="json")}
            return r
        elif "MATCH (s:Strategy {domain:" in query:
            # list_by_domain returns iter
            return FakeAsyncIter([{"s": promoted.model_dump(mode="json")}])
        elif "MATCH (s:Strategy {id:" in query:
            # get/transition returns single
            r = AsyncMock()
            r.single.return_value = {"s": promoted.model_dump(mode="json")}
            return r
        elif "MATCH (s:Strategy {state: 'EXPERIMENTAL'" in query:
            # process_experimental_candidates returns iter
            return FakeAsyncIter([{"s": promoted.model_dump(mode="json")}])
        elif "MATCH (s:Strategy {state: 'STALE'" in query or (
            "MATCH (s:Strategy {state: 'SUPERSEDED'" in query
        ):
            r = AsyncMock()
            r.single.return_value = {"count": 0}
            return r
        else:
            r = AsyncMock()
            r.single.return_value = {"count": 0}
            return r

    session.run.side_effect = mock_run

    # 1. Strategy CRUD: create
    repo = StrategyRepository(session)
    created = await repo.create(
        StrategyCreate(title="K8s debug", description="d", domain="kubernetes", content="c")
    )
    assert created.state == StrategyState.EXPERIMENTAL

    # 2. Curator: promote to ACTIVE
    curator = Curator(session)
    candidates = await curator.process_experimental_candidates("default")
    assert len(candidates) == 1
    assert candidates[0].state == StrategyState.ACTIVE

    # 3. Router: retrieve ACTIVE strategies
    router = StrategyRouter(repo)
    ctx = await router.retrieve("diagnose k8s", {"domain": "kubernetes"}, "default")
    assert len(ctx.strategies) == 1
    assert ctx.strategies[0].state == StrategyState.ACTIVE

    # 4. Reflector: synthesize lesson (heuristic fallback, deterministic)
    from unittest.mock import patch

    reflector = Reflector()
    traces = [{"id": "t1", "content": "x" * 300, "outcome": "success", "reflection_score": 0.9}]
    with patch("mi_dream.learning.reflector.ask_llm", side_effect=RuntimeError("no llm")):
        lessons = await reflector.reflect(traces)
    assert len(lessons) == 1
    assert lessons[0].decision == CuratorDecision.REINFORCE

    # 5. PII sanitization
    dirty = "email me at test@example.com with api_key=secret123"
    clean = sanitize(dirty)
    assert "test@example.com" not in clean
    assert "secret123" not in clean
    assert "[REDACTED]" in clean
