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


def _mock_tool_call_response(content=None, tool_calls=None, usage=None):
    mock_response = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    mock_response.choices = [MagicMock(message=msg)]
    mock_response.usage = usage
    return mock_response


def test_chat_turn_no_tools_sends_only_messages():
    from mi_dream.llm.client import chat_turn

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_tool_call_response("ok")

    with patch("mi_dream.llm.client.get_client", return_value=mock_client):
        turn = chat_turn([{"role": "user", "content": "hi"}])

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert "tools" not in kwargs
    assert turn.content == "ok"
    assert turn.tool_calls == []


def test_chat_turn_sends_tools_schema():
    from mi_dream.llm.client import chat_turn

    tools_schema = [
        {"type": "function", "function": {"name": "web_search", "parameters": {}}}
    ]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_tool_call_response("ok")

    with patch("mi_dream.llm.client.get_client", return_value=mock_client):
        turn = chat_turn([{"role": "user", "content": "hi"}], tools=tools_schema)

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["tools"] == tools_schema
    assert turn.content == "ok"


def test_chat_turn_parses_tool_calls():
    from mi_dream.llm.client import ToolCall, chat_turn

    tc = MagicMock()
    tc.id = "call_1"
    tc.function.name = "web_search"
    tc.function.arguments = '{"query": "x"}'
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_tool_call_response(
        None, [tc]
    )

    with patch("mi_dream.llm.client.get_client", return_value=mock_client):
        turn = chat_turn([{"role": "user", "content": "hi"}])

    assert len(turn.tool_calls) == 1
    assert isinstance(turn.tool_calls[0], ToolCall)
    assert turn.tool_calls[0].id == "call_1"
    assert turn.tool_calls[0].name == "web_search"
    assert turn.tool_calls[0].arguments == '{"query": "x"}'
    assert turn.content == "[empty response from provider]"


def test_chat_turn_reports_usage_and_latency():
    from mi_dream.llm.client import chat_turn

    usage = MagicMock()
    usage.total_tokens = 42
    usage.prompt_tokens = 20
    usage.completion_tokens = 22
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_tool_call_response(
        "ok", usage=usage
    )

    with patch("mi_dream.llm.client.get_client", return_value=mock_client):
        turn = chat_turn([{"role": "user", "content": "hi"}])

    assert turn.total_tokens == 42
    assert turn.prompt_tokens == 20
    assert turn.completion_tokens == 22
    assert turn.latency_ms >= 0


def test_chat_turn_sends_timeout_from_settings():
    from mi_dream.llm.client import chat_turn

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_tool_call_response("ok")

    with patch("mi_dream.llm.client.get_client", return_value=mock_client), patch(
        "mi_dream.llm.client.settings.llm_timeout_seconds", 45
    ):
        chat_turn([{"role": "user", "content": "hi"}])

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["timeout"] == 45


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
        with (
            patch("mi_dream.llm.client.settings.llm_api_key", "sk-test"),
            patch("mi_dream.llm.client.settings.llm_temperature", 0.2),
        ):
            ask_llm_full("system", "user")

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.2


def test_extract_llm_error_connection():
    from mi_dream.llm.client import extract_llm_error

    error_type, message = extract_llm_error(ConnectionError("provider unreachable"))
    assert error_type == "connection_error"
    assert "unreachable" in message


def test_extract_llm_error_openai_rate_limit():
    from openai import RateLimitError

    from mi_dream.llm.client import extract_llm_error

    exc = RateLimitError("429 too many requests", response=MagicMock(), body={})
    error_type, message = extract_llm_error(exc)
    assert error_type == "rate_limit_error"
    assert "429" in message


def test_extract_llm_error_openai_auth():
    from openai import AuthenticationError

    from mi_dream.llm.client import extract_llm_error

    exc = AuthenticationError("401 bad key", response=MagicMock(), body={})
    assert extract_llm_error(exc)[0] == "auth_error"


def test_extract_llm_error_config_value_error():
    from mi_dream.llm.client import extract_llm_error

    assert extract_llm_error(ValueError("LLM_API_KEY not set"))[0] == "config_error"


def test_extract_llm_error_unknown():
    from mi_dream.llm.client import extract_llm_error

    assert extract_llm_error(RuntimeError("weird"))[0] == "unknown_error"


def test_extract_llm_error_truncates_message():
    from mi_dream.llm.client import ERROR_TYPE_MESSAGE_MAX, extract_llm_error

    _, message = extract_llm_error(RuntimeError("x" * 1000))
    assert len(message) <= ERROR_TYPE_MESSAGE_MAX
