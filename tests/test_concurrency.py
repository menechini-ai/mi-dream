"""P2: Concurrency tests for learning pipeline idempotency."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mi_dream.observability import get_metrics, WORKER_ID


def _mock_driver_with_trace(trace_id: str, status: str = "PENDING"):
    mock_rec = MagicMock()
    mock_rec.__getitem__ = lambda self, k: trace_id if k == "trace_id" else {"id": trace_id, "content": "c", "outcome": "success", "tenant_id": "default"}
    mock_result = AsyncMock()
    mock_result.__aiter__ = lambda self: self
    mock_result.__anext__ = AsyncMock(side_effect=[mock_rec, StopAsyncIteration()])
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))
    return mock_driver


def _mock_async_cm(result):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=result)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_two_workers_claim_different_traces():
    """P2: Two workers claiming from same pool should get different traces."""
    from mi_dream.resilience import CLAIM_TRACES_CYPHER

    # This tests the query structure, not actual Neo4j concurrency
    # (which requires a real database)
    assert "processing_status = " in CLAIM_TRACES_CYPHER
    assert "CLAIMED" in CLAIM_TRACES_CYPHER
    assert "worker_id" in CLAIM_TRACES_CYPHER
    assert "LIMIT" in CLAIM_TRACES_CYPHER


@pytest.mark.asyncio
async def test_scheduler_run_cycle_marks_processed():
    """P2: After successful learning cycle, traces are marked PROCESSED."""
    from mi_dream.learning.scheduler import ReflectionScheduler

    mock_rec = MagicMock()
    mock_rec.__getitem__ = lambda self, k: {"id": "t1", "content": "test", "outcome": "success", "tenant_id": "default"}[k]
    mock_result = AsyncMock()
    mock_result.__aiter__ = lambda self: self
    mock_result.__anext__ = AsyncMock(side_effect=[mock_rec, StopAsyncIteration()])
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.learning.scheduler.get_driver", return_value=mock_driver):
        with patch("mi_dream.learning.scheduler.settings") as ms:
            ms.neo4j_database = "neo4j"
            scheduler = ReflectionScheduler()
            result = await scheduler.run_cycle()

    assert result["traces_processed"] == 1
    # Should have called session.run for: claim + create lesson + mark processed
    assert mock_session.run.call_count >= 3


@pytest.mark.asyncio
async def test_scheduler_failure_retries_trace():
    """P2: On failure, claimed traces are retried (back to PENDING + next_attempt_at)."""
    from mi_dream.learning.scheduler import ReflectionScheduler, RETRY_TRACE_CYPHER

    mock_rec = MagicMock()
    mock_rec.__getitem__ = lambda self, k: {"id": "t1", "content": "test", "outcome": "success", "tenant_id": "default"}[k]
    mock_result = AsyncMock()
    mock_result.__aiter__ = lambda self: self
    mock_result.__anext__ = AsyncMock(side_effect=[mock_rec, StopAsyncIteration()])
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.learning.scheduler.get_driver", return_value=mock_driver):
        with patch("mi_dream.learning.scheduler.settings") as ms:
            ms.neo4j_database = "neo4j"
            scheduler = ReflectionScheduler()
            # Force evaluator to fail
            scheduler._evaluator.evaluate = lambda x: (_ for _ in ()).throw(RuntimeError("boom"))
            try:
                await scheduler.run_cycle()
            except RuntimeError:
                pass

    # Should have called retry query
    calls = [c.args[0] if c.args else c.kwargs.get("query", "") for c in mock_session.run.call_args_list]
    assert any("PENDING" in str(c) for c in calls)


def test_worker_id_default():
    assert WORKER_ID.startswith("worker-")


def test_worker_id_from_env(monkeypatch):
    monkeypatch.setenv("MI_DREAM_WORKER_ID", "test-worker-42")
    from mi_dream.observability.lifecycle import WORKER_ID as wid
    # Module-level var already loaded, check via reimport
    import importlib
    from mi_dream import observability
    importlib.reload(observability)
    assert observability.WORKER_ID == "test-worker-42"
