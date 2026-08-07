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


def _trace(**overrides):
    data = {
        "id": "t1",
        "outcome": "failure",
        "error_type": "api_error",
        "metadata": '{"error_message": "boom", "source": "skill"}',
        "created_at": "2026-08-07T10:00:00Z",
    }
    data.update(overrides)
    return FakeRecord({"trace": data})


def _fp_record(**overrides):
    data = {
        "fp": {
            "id": "fp1",
            "error_type": "rate_limit_error",
            "domain": "general",
            "pattern": "Too Many Requests",
            "failure_count": 3,
            "last_seen": "2026-08-07T10:00:00Z",
            "created_at": "2026-08-07T09:00:00Z",
            "signature": "abc123",
            "tenant_id": "default",
        }
    }
    data.update(overrides)
    return FakeRecord(data)


@pytest.mark.asyncio
async def test_get_failure_patterns_lists_recent():
    from mi_dream.learning.failure_analyzer import get_failure_patterns

    session = _session_for([_fp_record()])
    driver = make_driver_mock(session)
    patterns = await get_failure_patterns("default", driver=driver)
    assert patterns[0]["error_type"] == "rate_limit_error"
    assert patterns[0]["failure_count"] == 3
    assert "ORDER BY p.last_seen DESC" in session.run.call_args.args[0]


@pytest.mark.asyncio
async def test_get_failure_patterns_filters_by_error_type():
    from mi_dream.learning.failure_analyzer import get_failure_patterns

    session = _session_for([_fp_record()])
    driver = make_driver_mock(session)
    patterns = await get_failure_patterns("default", error_type="rate_limit_error", driver=driver)
    assert len(patterns) == 1
    assert "error_type: $error_type" in session.run.call_args.args[0]


@pytest.mark.asyncio
async def test_get_failure_patterns_filters_by_domain():
    from mi_dream.learning.failure_analyzer import get_failure_patterns

    session = _session_for([_fp_record()])
    driver = make_driver_mock(session)
    patterns = await get_failure_patterns("default", domain="general", driver=driver)
    assert len(patterns) == 1
    assert "domain: $domain" in session.run.call_args.args[0]


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


def test_failure_signature_normalizes():
    from mi_dream.learning.failure_analyzer import failure_signature

    sig1 = failure_signature("rate_limit_error", "general", "Too Many Requests 429")
    sig2 = failure_signature("rate_limit_error", "general", "too many requests")
    assert sig1 == sig2


def test_failure_signature_differs_by_error_type():
    from mi_dream.learning.failure_analyzer import failure_signature

    assert failure_signature("api_error", "general", "boom") != failure_signature(
        "connection_error", "general", "boom"
    )


@pytest.mark.asyncio
async def test_run_failure_analysis_groups_and_links():
    from unittest.mock import AsyncMock, MagicMock

    from mi_dream.learning.failure_analyzer import run_failure_analysis

    session = _session_for(
        [
            _trace(
                id="t1",
                error_type="rate_limit_error",
                metadata='{"error_message": "Too Many Requests 429"}',
            ),
            _trace(
                id="t2",
                error_type="rate_limit_error",
                metadata='{"error_message": "too many requests"}',
            ),
        ]
    )
    driver = make_driver_mock(session)
    repo = MagicMock()
    repo.find_by_signature = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=MagicMock(id="fp-new"))
    repo.increment = AsyncMock()
    repo.link_trace = AsyncMock()

    report = await run_failure_analysis("default", driver=driver, repo=repo)

    assert report["failures_processed"] == 2
    assert report["patterns_created"] == 1
    assert report["patterns_updated"] == 0
    assert repo.link_trace.call_count == 2
    sig = repo.create.call_args.kwargs["signature"]
    assert isinstance(sig, str) and len(sig) == 16


@pytest.mark.asyncio
async def test_run_failure_analysis_increments_existing():
    from unittest.mock import AsyncMock, MagicMock

    from mi_dream.learning.failure_analyzer import run_failure_analysis

    session = _session_for([_trace(id="t1", error_type="api_error")])
    driver = make_driver_mock(session)
    repo = MagicMock()
    repo.find_by_signature = AsyncMock(return_value=MagicMock(id="fp1"))
    repo.increment = AsyncMock()
    repo.link_trace = AsyncMock()

    report = await run_failure_analysis("default", driver=driver, repo=repo)

    assert report["patterns_updated"] == 1
    assert report["patterns_created"] == 0
    repo.increment.assert_awaited_once_with("fp1")
    repo.link_trace.assert_awaited_once()
