"""Tests for P1/P2 additions: validate_transitions, wilson_ci."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mi_dream.knowledge.curator import Curator
from mi_dream.knowledge.models import StrategyState, VALID_TRANSITIONS


def test_wilson_ci_high_confidence():
    low, high = Curator.wilson_ci(300, 500)
    assert low > 0.55
    assert high < 0.65


def test_wilson_ci_low_confidence():
    low, high = Curator.wilson_ci(3, 5)
    assert low < 0.15
    assert high > 0.9


def test_wilson_ci_zero_trials():
    low, high = Curator.wilson_ci(0, 0)
    assert low == 0.0
    assert high == 0.0


def test_wilson_ci_all_success():
    low, high = Curator.wilson_ci(10, 10)
    assert low > 0.7
    assert high == 1.0


def test_wilson_ci_ordered():
    low1, _ = Curator.wilson_ci(6, 10)
    low2, _ = Curator.wilson_ci(60, 100)
    assert abs(low2 - 0.5) < abs(low1 - 0.5)


def _mock_session(rows):
    mock_rec = MagicMock()
    mock_rec.data.return_value = rows
    mock_result = AsyncMock()
    mock_result.__aiter__ = lambda self: self
    mock_result.__anext__ = AsyncMock(side_effect=[MagicMock(data=lambda: r) for r in rows] + [StopAsyncIteration()])
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    return mock_session


@pytest.mark.asyncio
async def test_validate_transitions_detects_invalid():
    rows = [
        {"from_id": "s1", "from_state": "EXPERIMENTAL", "to_id": "s2", "to_state": "ARCHIVED"},
    ]
    mock_session = _mock_session(rows)
    curator = Curator(mock_session)
    violations = await curator.validate_transitions("default")
    assert len(violations) == 1
    assert "Invalid transition" in violations[0]["reason"]


@pytest.mark.asyncio
async def test_validate_transitions_allows_valid():
    rows = [
        {"from_id": "s1", "from_state": "EXPERIMENTAL", "to_id": "s2", "to_state": "ACTIVE"},
    ]
    mock_session = _mock_session(rows)
    curator = Curator(mock_session)
    violations = await curator.validate_transitions("default")
    assert violations == []


@pytest.mark.asyncio
async def test_validate_transitions_invalid_state_string_skipped():
    rows = [
        {"from_id": "s1", "from_state": "UNKNOWN", "to_id": "s2", "to_state": "ACTIVE"},
    ]
    mock_session = _mock_session(rows)
    curator = Curator(mock_session)
    violations = await curator.validate_transitions("default")
    assert violations == []
