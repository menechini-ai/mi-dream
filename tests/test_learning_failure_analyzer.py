import os
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from conftest import FakeAsyncIter, make_driver_mock


class FakeRecord:
    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]


def _session_for(records):
    session = AsyncMock()
    session.run.return_value = FakeAsyncIter(records)
    return session


def _record(**overrides):
    data = {
        "id": "t1",
        "content": "Q: x\nA: [ERROR: boom]",
        "outcome": "failure",
        "error_type": "api_error",
        "error_source": "skill",
        "metadata": '{"error_message": "boom", "tokens": 9, "source": "skill"}',
        "created_at": "2026-08-07T10:00:00Z",
    }
    data.update(overrides)
    return FakeRecord(data)


@pytest.mark.asyncio
async def test_get_failures_filters_and_parses():
    from mi_dream.learning.failure_analyzer import get_failures

    session = _session_for([_record()])
    driver = make_driver_mock(session)
    rows = await get_failures(
        "default", limit=20, error_type="api_error", source="skill", driver=driver
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "t1"
    assert row["error_type"] == "api_error"
    assert row["source"] == "skill"
    assert row["error_message"] == "boom"
    assert row["tokens"] == 9

    query = session.run.call_args.args[0]
    assert "t.outcome = 'failure'" in query
    assert "t.error_type = $error_type" in query
    assert "t.error_source = $source" in query
    assert "ORDER BY t.created_at DESC LIMIT $limit" in query
    assert session.run.call_args.kwargs["limit"] == 20


@pytest.mark.asyncio
async def test_get_failures_fallback_for_missing_props():
    from mi_dream.learning.failure_analyzer import get_failures

    session = _session_for(
        [
            _record(
                error_type=None,
                error_source=None,
                metadata='{"outcome": "failure", "error_message": "x"}',
            )
        ]
    )
    driver = make_driver_mock(session)
    rows = await get_failures("default", driver=driver)

    assert rows[0]["error_type"] == "unknown"
    assert rows[0]["source"] == "unknown"
    assert rows[0]["error_message"] == "x"


@pytest.mark.asyncio
async def test_get_failures_empty_when_no_matches():
    from mi_dream.learning.failure_analyzer import get_failures

    session = _session_for([])
    driver = make_driver_mock(session)
    rows = await get_failures("default", driver=driver)
    assert rows == []
