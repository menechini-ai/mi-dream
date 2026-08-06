import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from conftest import make_driver_mock


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
    assert "[:DERIVED_FROM]" in queries[-1]
    assert "REFLECTED_IN" not in queries[-1]
    assert "DERIVED_FROM" in queries[0]
