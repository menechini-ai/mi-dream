import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.llm.client import ask_llm, ask_llm_full


def _mock_response(content="hello", usage=None):
    mock_response = MagicMock()
    msg = MagicMock()
    msg.content = content
    mock_response.choices = [MagicMock(message=msg)]
    mock_response.usage = usage
    return mock_response


def test_ask_llm_full_reports_usage_and_latency():
    usage = MagicMock()
    usage.total_tokens = 42
    usage.prompt_tokens = 20
    usage.completion_tokens = 22
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_response("hello", usage)

    with patch("mi_dream.llm.client.get_client", return_value=mock_client):
        with patch("mi_dream.llm.client.settings.llm_api_key", "sk-test"):
            resp = ask_llm_full("system", "user", max_tokens=256)

    assert resp.content == "hello"
    assert resp.total_tokens == 42
    assert resp.prompt_tokens == 20
    assert resp.completion_tokens == 22
    assert resp.latency_ms >= 0


def test_ask_llm_full_handles_missing_usage():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_response("hello", usage=None)

    with patch("mi_dream.llm.client.get_client", return_value=mock_client):
        with patch("mi_dream.llm.client.settings.llm_api_key", "sk-test"):
            resp = ask_llm_full("system", "user")

    assert resp.content == "hello"
    assert resp.total_tokens == 0
    assert resp.prompt_tokens == 0
    assert resp.completion_tokens == 0


def test_ask_llm_returns_content_only():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_response("hello", None)

    with patch("mi_dream.llm.client.get_client", return_value=mock_client):
        with patch("mi_dream.llm.client.settings.llm_api_key", "sk-test"):
            assert ask_llm("system", "user") == "hello"


def test_ask_llm_full_empty_content_placeholder():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_response(None, None)

    with patch("mi_dream.llm.client.get_client", return_value=mock_client):
        with patch("mi_dream.llm.client.settings.llm_api_key", "sk-test"):
            resp = ask_llm_full("system", "user")

    assert resp.content == "[empty response from provider]"


def test_ask_llm_full_sends_temperature():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_response("hello", None)

    with patch("mi_dream.llm.client.get_client", return_value=mock_client):
        with patch("mi_dream.llm.client.settings.llm_api_key", "sk-test"), patch(
            "mi_dream.llm.client.settings.llm_temperature", 0.2
        ):
            ask_llm_full("system", "user")

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.2
