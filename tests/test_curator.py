import os
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from conftest import FakeAsyncIter

from mi_dream.knowledge.curator import Curator
from mi_dream.knowledge.models import StrategyState


def _mock_strategy(state, **kwargs):
    from mi_dream.knowledge.models import Strategy
    defaults = dict(
        id="s1", title="t", description="d", domain="dev", content="c",
        support_count=3, success_rate=0.7,
        created_at="2024-01-01T00:00:00Z", updated_at="2024-06-01T00:00:00Z",
        tenant_id="default", superseded_by=None,
    )
    defaults.update(kwargs)
    defaults["state"] = state
    return Strategy(**defaults)


@pytest.mark.asyncio
async def test_state_machine_promotes_stale_to_active():
    session = AsyncMock()
    calls = [
        {"count": 2},  # STALE -> ACTIVE
        {"count": 0},  # STALE -> ARCHIVED
        {"count": 0},  # SUPERSEDED -> ARCHIVED
    ]
    session.run.return_value.single.side_effect = calls
    curator = Curator(session)
    result = await curator.run_state_machine("default")
    assert result["promoted"] == 2
    assert result["demoted"] == 0


@pytest.mark.asyncio
async def test_state_machine_demotes_stale_to_archived():
    session = AsyncMock()
    calls = [
        {"count": 0},  # STALE -> ACTIVE
        {"count": 3},  # STALE -> ARCHIVED
        {"count": 1},  # SUPERSEDED -> ARCHIVED
    ]
    session.run.return_value.single.side_effect = calls
    curator = Curator(session)
    result = await curator.run_state_machine("default")
    assert result["promoted"] == 0
    assert result["demoted"] == 4


@pytest.mark.asyncio
async def test_integrity_check_detects_orphaned_active():
    session = AsyncMock()
    record = {"orphaned_strategy": "s1", "reason": "ACTIVE without SUPPORTED_BY"}
    mock_rec = MagicMock()
    mock_rec.data.return_value = record
    session.run.return_value = FakeAsyncIter([mock_rec])
    curator = Curator(session)
    violations = await curator.run_integrity_checks("default")
    assert len(violations) > 0


def test_integrity_check_superseded_orphan_uses_relationship():
    from mi_dream.knowledge.curator import INTEGRITY_CHECKS

    orphan = [c for c in INTEGRITY_CHECKS if "SUPERSEDED without successor" in c][0]
    assert "[:SUPERSEDES]" in orphan
    assert "superseded_by IS NULL" not in orphan


def test_integrity_check_cycle_detection_uses_relationship():
    from mi_dream.knowledge.curator import INTEGRITY_CHECKS

    cycle = [c for c in INTEGRITY_CHECKS if "SUPERSEDES*1..10" in c][0]
    assert "[:SUPERSEDES*1..10]" in cycle


@pytest.mark.asyncio
async def test_process_experimental_promotes_eligible():
    session = AsyncMock()
    promoted_state = _mock_strategy(StrategyState.ACTIVE, support_count=3, success_rate=0.7)
    items = [{"s": promoted_state.model_dump(mode="json")}]
    session.run.return_value = FakeAsyncIter(items)
    curator = Curator(session)
    promoted = await curator.process_experimental_candidates("default")
    assert len(promoted) == 1
    assert promoted[0].state == StrategyState.ACTIVE
    query = session.run.call_args.args[0]
    assert "SET s.state = 'ACTIVE'" in query
    assert "support_count >= 3 AND s.success_rate >= 0.6" in query
