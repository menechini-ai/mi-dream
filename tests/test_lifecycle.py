"""Tests for mi_dream.resilience.lifecycle."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mi_dream.resilience.lifecycle import DriverLifecycle, Neo4jHealth


@pytest.mark.asyncio
async def test_start_creates_driver():
    lifecycle = DriverLifecycle()
    mock_driver = AsyncMock()
    mock_driver.verify_connectivity = AsyncMock()

    with patch("mi_dream.resilience.lifecycle.AsyncGraphDatabase.driver", return_value=mock_driver):
        await lifecycle.start()

    assert lifecycle._driver is mock_driver


@pytest.mark.asyncio
async def test_start_idempotent():
    lifecycle = DriverLifecycle()
    mock_driver = AsyncMock()
    mock_driver.verify_connectivity = AsyncMock()

    with patch("mi_dream.resilience.lifecycle.AsyncGraphDatabase.driver", return_value=mock_driver):
        await lifecycle.start()
        await lifecycle.start()  # second call should not recreate

    assert lifecycle._driver is mock_driver


@pytest.mark.asyncio
async def test_close_clears_driver():
    lifecycle = DriverLifecycle()
    mock_driver = AsyncMock()
    mock_driver.verify_connectivity = AsyncMock()
    lifecycle._driver = mock_driver

    with patch("mi_dream.resilience.lifecycle.AsyncGraphDatabase.driver", return_value=mock_driver):
        await lifecycle.start()

    await lifecycle.close()
    assert lifecycle._driver is None


@pytest.mark.asyncio
async def test_get_driver_before_start_raises():
    lifecycle = DriverLifecycle()
    with pytest.raises(RuntimeError, match="not started"):
        lifecycle.get_driver()


@pytest.mark.asyncio
async def test_health_connected():
    lifecycle = DriverLifecycle()
    mock_driver = AsyncMock()
    mock_driver.verify_connectivity = AsyncMock()
    lifecycle._driver = mock_driver

    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=AsyncMock(single=AsyncMock(return_value={"1": 1})))
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    health = await lifecycle.health()
    assert health.connected is True
    assert health.error is None


@pytest.mark.asyncio
async def test_health_not_started():
    lifecycle = DriverLifecycle()
    health = await lifecycle.health()
    assert health.connected is False
    assert "not started" not in str(health.error)  # just returns database name


def _mock_async_cm(result):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=result)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm
