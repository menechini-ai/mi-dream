import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from conftest import FakeAsyncIter, make_driver_mock


@pytest.mark.asyncio
async def test_run_cycle_bootstraps_schema_automatically():
    from mi_dream.learning.scheduler import ReflectionScheduler

    mock_session = AsyncMock()
    mock_session.run.return_value = FakeAsyncIter([])
    mock_driver = make_driver_mock(mock_session)

    with patch("mi_dream.learning.scheduler.get_driver", return_value=mock_driver), patch(
        "mi_dream.memory.bootstrap.ensure_schema", new=AsyncMock()
    ) as mock_ensure:
        result = await ReflectionScheduler().run_cycle()

    mock_ensure.assert_awaited_once()
    assert result == {"traces_processed": 0, "lessons_created": 0}


@pytest.mark.asyncio
async def test_run_cycle_creates_lessons_and_links():
    from mi_dream.learning.scheduler import ReflectionScheduler

    trace = {
        "id": "t-load",
        "content": "x" * 300,
        "outcome": "success",
        "tenant_id": "default",
    }
    mock_session = AsyncMock()

    async def mock_run(query, **kwargs):
        if "RETURN t {.*} AS trace" in query:
            return FakeAsyncIter([{"trace": trace}])
        return FakeAsyncIter([])

    mock_session.run.side_effect = mock_run
    mock_driver = make_driver_mock(mock_session)

    with patch("mi_dream.learning.scheduler.get_driver", return_value=mock_driver), patch(
        "mi_dream.memory.bootstrap.ensure_schema", new=AsyncMock()
    ):
        result = await ReflectionScheduler().run_cycle()

    assert result["traces_processed"] == 1
    assert result["lessons_created"] == 1


@pytest.mark.asyncio
async def test_run_cycle_links_lesson_via_derived_from():
    from mi_dream.learning.scheduler import ReflectionScheduler

    trace = {
        "id": "t-df",
        "content": "x" * 300,
        "outcome": "success",
        "tenant_id": "default",
    }
    mock_session = AsyncMock()

    async def mock_run(query, **kwargs):
        if "RETURN t {.*} AS trace" in query:
            return FakeAsyncIter([{"trace": trace}])
        return FakeAsyncIter([])

    mock_session.run.side_effect = mock_run
    mock_driver = make_driver_mock(mock_session)

    with patch("mi_dream.learning.scheduler.get_driver", return_value=mock_driver), patch(
        "mi_dream.memory.bootstrap.ensure_schema", new=AsyncMock()
    ):
        await ReflectionScheduler().run_cycle()

    queries = [c.args[0] for c in mock_session.run.call_args_list]
    create_queries = [q for q in queries if "CREATE (l:Lesson" in q]
    assert len(create_queries) == 1
    assert "[:DERIVED_FROM]" in create_queries[0]
    assert "REFLECTED_IN" not in create_queries[0]


@pytest.mark.asyncio
async def test_run_learning_cycle_orchestrates_all_stages():
    from unittest.mock import AsyncMock

    from mi_dream.learning.scheduler import run_learning_cycle

    mock_session = AsyncMock()
    mock_driver = make_driver_mock(mock_session)

    sched = MagicMock()
    sched.run_cycle = AsyncMock(return_value={"traces_processed": 1, "lessons_created": 1})
    dist = MagicMock()
    dist.pending_lessons = AsyncMock(return_value=[])
    dist.distill = AsyncMock(return_value=[])
    cur = MagicMock()
    cur.run_integrity_checks = AsyncMock(return_value=[])
    cur.run_state_machine = AsyncMock(return_value={"promoted": 0, "demoted": 0})
    cur.deduplicate = AsyncMock(return_value=[])
    cur.process_experimental_candidates = AsyncMock(return_value=[])

    with patch("mi_dream.learning.scheduler.ReflectionScheduler", return_value=sched), \
         patch("mi_dream.learning.scheduler.KnowledgeDistiller", return_value=dist), \
         patch("mi_dream.learning.scheduler.Curator", return_value=cur), \
         patch("mi_dream.learning.scheduler.get_driver", return_value=mock_driver), \
         patch("mi_dream.learning.scheduler.run_failure_analysis", new=AsyncMock(
             return_value={"failures_processed": 2, "patterns_created": 1, "patterns_updated": 0}
         )) as mock_fa, \
         patch("mi_dream.learning.scheduler.build_embedder", return_value=None):
        report = await run_learning_cycle("default")

    sched.run_cycle.assert_awaited_once()
    dist.pending_lessons.assert_awaited_once_with("default")
    dist.distill.assert_awaited_once()
    cur.run_integrity_checks.assert_awaited_once_with("default")
    cur.process_experimental_candidates.assert_awaited_once_with("default")
    mock_fa.assert_awaited_once_with("default")
    assert report["reflection"]["lessons_created"] == 1
    assert report["failure_analysis"]["patterns_created"] == 1
    assert "distill" in report
    assert "curator" in report


@pytest.mark.asyncio
async def test_run_learning_cycle_isolates_stage_failures():
    from unittest.mock import AsyncMock

    from mi_dream.learning.scheduler import run_learning_cycle

    mock_session = AsyncMock()
    mock_driver = make_driver_mock(mock_session)

    sched = MagicMock()
    sched.run_cycle = AsyncMock(side_effect=RuntimeError("reflect down"))
    dist = MagicMock()
    dist.pending_lessons = AsyncMock(return_value=[])
    dist.distill = AsyncMock(return_value=[])
    cur = MagicMock()
    cur.run_integrity_checks = AsyncMock(return_value=[])
    cur.run_state_machine = AsyncMock(return_value={"promoted": 0, "demoted": 0})
    cur.deduplicate = AsyncMock(return_value=[])
    cur.process_experimental_candidates = AsyncMock(return_value=[])

    with patch("mi_dream.learning.scheduler.ReflectionScheduler", return_value=sched), \
         patch("mi_dream.learning.scheduler.KnowledgeDistiller", return_value=dist), \
         patch("mi_dream.learning.scheduler.Curator", return_value=cur), \
         patch("mi_dream.learning.scheduler.get_driver", return_value=mock_driver), \
         patch("mi_dream.learning.scheduler.build_embedder", return_value=None):
        report = await run_learning_cycle("default")

    assert "error" in report["reflection"]
    assert report["distill"] is not None


@pytest.mark.asyncio
async def test_run_learning_cycle_isolates_failure_analysis():
    from unittest.mock import AsyncMock

    from mi_dream.learning.scheduler import run_learning_cycle

    mock_session = AsyncMock()
    mock_driver = make_driver_mock(mock_session)

    sched = MagicMock()
    sched.run_cycle = AsyncMock(return_value={"traces_processed": 0, "lessons_created": 0})
    dist = MagicMock()
    dist.pending_lessons = AsyncMock(return_value=[])
    dist.distill = AsyncMock(return_value=[])
    cur = MagicMock()
    cur.run_integrity_checks = AsyncMock(return_value=[])
    cur.run_state_machine = AsyncMock(return_value={"promoted": 0, "demoted": 0})
    cur.deduplicate = AsyncMock(return_value=[])
    cur.process_experimental_candidates = AsyncMock(return_value=[])

    with patch("mi_dream.learning.scheduler.ReflectionScheduler", return_value=sched), \
         patch("mi_dream.learning.scheduler.KnowledgeDistiller", return_value=dist), \
         patch("mi_dream.learning.scheduler.Curator", return_value=cur), \
         patch("mi_dream.learning.scheduler.get_driver", return_value=mock_driver), \
         patch("mi_dream.learning.scheduler.run_failure_analysis", new=AsyncMock(
             side_effect=RuntimeError("neo4j down")
         )), \
         patch("mi_dream.learning.scheduler.build_embedder", return_value=None):
        report = await run_learning_cycle("default")

    assert "error" in report["failure_analysis"]
    assert report["reflection"] is not None
