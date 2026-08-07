import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from unittest.mock import AsyncMock, patch

from mi_dream.memory.connection import get_driver


@pytest.mark.asyncio
async def test_get_driver_returns_singleton():
    with patch("mi_dream.memory.connection.AsyncGraphDatabase") as MockDriver:
        mock_driver = AsyncMock()
        MockDriver.driver.return_value = mock_driver
        d1 = get_driver()
        d2 = get_driver()
        assert d1 is d2
        MockDriver.driver.assert_called_once()


@pytest.mark.asyncio
async def test_get_driver_suppresses_unrecognized_notifications():
    with patch("mi_dream.memory.connection.AsyncGraphDatabase") as MockDriver:
        mock_driver = AsyncMock()
        MockDriver.driver.return_value = mock_driver
        get_driver()
    kwargs = MockDriver.driver.call_args.kwargs
    assert kwargs.get("notifications_disabled_classifications") == ["UNRECOGNIZED"]


@pytest.mark.asyncio
async def test_bootstrap_schema_runs_cypher():
    from conftest import make_driver_mock

    from mi_dream.memory.bootstrap import bootstrap_schema

    mock_session = AsyncMock()
    mock_run_result = AsyncMock()
    mock_run_result.single.return_value = None
    mock_session.run.return_value = mock_run_result

    mock_driver = make_driver_mock(mock_session)

    with patch("mi_dream.memory.bootstrap.get_driver", return_value=mock_driver):
        await bootstrap_schema()

    # Should have called run at least once (for constraints/indexes)
    assert mock_session.run.call_count >= 1


def test_schema_cypher_includes_daily_review_constraint():
    from mi_dream.memory.bootstrap import _schema_cypher

    cypher = _schema_cypher()
    assert "DailyReview" in cypher
    assert "(r.tenant_id, r.date) IS UNIQUE" in cypher


@pytest.mark.asyncio
async def test_ensure_schema_is_idempotent():
    from conftest import make_driver_mock

    from mi_dream.memory.bootstrap import ensure_schema

    mock_session = AsyncMock()
    mock_run_result = AsyncMock()
    mock_run_result.single.return_value = None
    mock_session.run.return_value = mock_run_result
    mock_driver = make_driver_mock(mock_session)

    with patch("mi_dream.memory.bootstrap.get_driver", return_value=mock_driver):
        await ensure_schema()
        first_call_count = mock_session.run.call_count
        await ensure_schema()

    # Second call must be a no-op: no additional Cypher executed
    assert mock_session.run.call_count == first_call_count
    assert first_call_count >= 1


@pytest.mark.asyncio
async def test_ensure_schema_retries_after_failure():
    from conftest import make_driver_mock

    from mi_dream.memory.bootstrap import ensure_schema

    mock_session = AsyncMock()
    mock_run_result = AsyncMock()
    mock_run_result.single.return_value = None
    mock_session.run.return_value = mock_run_result
    mock_driver = make_driver_mock(mock_session)

    with patch(
        "mi_dream.memory.bootstrap.bootstrap_schema",
        side_effect=[RuntimeError("neo4j down"), None],
    ):
        with patch("mi_dream.memory.bootstrap.get_driver", return_value=mock_driver):
            try:
                await ensure_schema()
                raised = False
            except RuntimeError:
                raised = True
            assert raised
            await ensure_schema()

    # Retry succeeded -> flag set, no exception
    import mi_dream.memory.bootstrap as bootstrap

    assert bootstrap._bootstrapped is True
