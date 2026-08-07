"""Tests for mi_dream.resilience schema migration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mi_dream.resilience import migrate_claim_schema


@pytest.mark.asyncio
async def test_migrate_claim_schema_migrates_traces():
    mock_rec = MagicMock()
    mock_rec.__getitem__ = lambda self, k: 42 if k == "migrated" else None
    mock_result = AsyncMock()
    mock_result.single = AsyncMock(return_value=mock_rec)
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.resilience.migrate_claim_schema.get_driver", return_value=mock_driver):
        with patch("mi_dream.resilience.migrate_claim_schema.settings") as mock_settings:
            mock_settings.neo4j_database = "neo4j"
            count = await migrate_claim_schema()

    assert count == 42


@pytest.mark.asyncio
async def test_migrate_claim_schema_creates_index():
    mock_rec = MagicMock()
    mock_rec.__getitem__ = lambda self, k: 0 if k == "migrated" else None
    mock_result = AsyncMock()
    mock_result.single = AsyncMock(return_value=mock_rec)
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.resilience.migrate_claim_schema.get_driver", return_value=mock_driver):
        with patch("mi_dream.resilience.migrate_claim_schema.settings") as mock_settings:
            mock_settings.neo4j_database = "neo4j"
            await migrate_claim_schema()

    # Should call run at least twice: once for migration, once for index
    assert mock_session.run.call_count >= 2


def _mock_async_cm(result):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=result)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm
