import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest

from mi_dream.health import HealthResult, check_all, check_llm_provider, check_neo4j


@pytest.mark.asyncio
async def test_check_neo4j_ok():
    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.single.return_value = {"n": 1}
    mock_session.run.return_value = mock_result

    from conftest import make_driver_mock

    mock_driver = make_driver_mock(mock_session)

    with patch("mi_dream.health.get_driver", return_value=mock_driver):
        with patch("mi_dream.health.settings.neo4j_database", "neo4j"):
            result = await check_neo4j()

    assert result.name == "neo4j"
    assert result.status == "ok"
    assert result.latency_ms > 0


@pytest.mark.asyncio
async def test_check_neo4j_error():
    with patch("mi_dream.health.get_driver", side_effect=Exception("connection refused")):
        result = await check_neo4j()

    assert result.name == "neo4j"
    assert result.status == "error"
    assert "connection refused" in result.detail


@pytest.mark.asyncio
async def test_check_llm_provider_no_key():
    with patch("mi_dream.health.settings.llm_api_key", ""):
        result = await check_llm_provider()

    assert result.name == "llm_provider"
    assert result.status == "warning"
    assert "not configured" in result.detail


@pytest.mark.asyncio
async def test_check_llm_provider_ok():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = "pong"
    mock_response.choices = [MagicMock(message=mock_msg)]
    mock_client.chat.completions.create.return_value = mock_response

    with patch("mi_dream.health.settings.llm_api_key", "sk-test"):
        with patch("mi_dream.health.settings.llm_model", "claude-sonnet-4-6"):
            with patch("mi_dream.health.settings.llm_base_url", "http://localhost:20128/v1"):
                with patch("mi_dream.health.settings.llm_provider", "anthropic"):
                    with patch("mi_dream.llm.client.get_client", return_value=mock_client):
                        result = await check_llm_provider()

    assert result.name == "llm_provider"
    assert result.status == "ok"
    assert "anthropic" in result.detail


@pytest.mark.asyncio
async def test_check_all_returns_two_results():
    with patch("mi_dream.health.check_neo4j") as mock_neo4j, \
         patch("mi_dream.health.check_llm_provider") as mock_llm:
        mock_neo4j.return_value = HealthResult(
            name="neo4j", status="ok", detail="ok", latency_ms=10
        )
        mock_llm.return_value = HealthResult(
            name="llm_provider", status="ok", detail="ok", latency_ms=20
        )
        results = await check_all()

    assert len(results) == 2
    assert results[0].name == "neo4j"
    assert results[1].name == "llm_provider"
