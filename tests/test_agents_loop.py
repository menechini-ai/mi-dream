from mi_dream.agents.loop import AgentResult, Tool, Toolbox, run_tool_loop
from mi_dream.llm.client import ChatTurn, ToolCall


class EchoTool(Tool):
    def __init__(self):
        super().__init__(
            name="echo",
            description="echo back the message",
            parameters={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        )

    def run(self, message):
        return f"echo:{message}"


def _echo_toolbox():
    return Toolbox([EchoTool()])


def test_toolbox_schemas_lists_function_schemas():
    schemas = _echo_toolbox().schemas()
    assert schemas == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "echo back the message",
                "parameters": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            },
        }
    ]


def test_toolbox_execute_runs_tool():
    assert _echo_toolbox().execute("echo", '{"message": "hi"}') == "echo:hi"


def test_toolbox_execute_unknown_tool_returns_error():
    result = _echo_toolbox().execute("nope", "{}")
    assert result.startswith("Error:")
    assert "unknown tool" in result


def test_toolbox_execute_invalid_json_returns_error():
    result = _echo_toolbox().execute("echo", "not json")
    assert result.startswith("Error:")


async def test_run_tool_loop_single_turn_without_tools(monkeypatch):
    def fake_chat_turn(messages, tools, max_tokens):
        assert tools is None
        return ChatTurn(content="hi", tool_calls=[])

    monkeypatch.setattr("mi_dream.agents.loop.chat_turn", fake_chat_turn)
    result = await run_tool_loop("sys", "hello")
    assert result.content == "hi"
    assert result.iterations == 1
    assert result.tool_calls == 0
    assert not result.limit_reached


async def test_run_tool_loop_executes_tool_then_finishes(monkeypatch):
    seen = []

    def fake_chat_turn(messages, tools, max_tokens):
        seen.append(messages)
        if len(seen) == 1:
            return ChatTurn(
                content="",
                tool_calls=[ToolCall("c1", "echo", '{"message": "hi"}')],
            )
        return ChatTurn(content="done", tool_calls=[])

    monkeypatch.setattr("mi_dream.agents.loop.chat_turn", fake_chat_turn)
    result = await run_tool_loop("sys", "hello", toolbox=_echo_toolbox())
    assert result.content == "done"
    assert result.iterations == 2
    assert result.tool_calls == 1

    tool_msg = seen[1][-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "c1"
    assert tool_msg["content"] == "echo:hi"

    assistant_msg = seen[1][-2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "echo"


async def test_run_tool_loop_max_iterations_guard(monkeypatch):
    def fake_chat_turn(messages, tools, max_tokens):
        return ChatTurn(
            content="",
            tool_calls=[ToolCall("c", "echo", '{"message": "x"}')],
        )

    monkeypatch.setattr("mi_dream.agents.loop.chat_turn", fake_chat_turn)
    result = await run_tool_loop("sys", "hello", toolbox=_echo_toolbox(), max_iterations=3)
    assert result.limit_reached
    assert result.iterations == 3
    assert result.tool_calls == 3
    assert result.content == "[tool loop limit reached]"


async def test_run_tool_loop_accumulates_usage(monkeypatch):
    def fake_chat_turn(messages, tools, max_tokens):
        return ChatTurn(
            content="done",
            tool_calls=[],
            total_tokens=10,
            prompt_tokens=4,
            completion_tokens=6,
            latency_ms=1.5,
        )

    monkeypatch.setattr("mi_dream.agents.loop.chat_turn", fake_chat_turn)
    result = await run_tool_loop("sys", "hello", toolbox=_echo_toolbox())
    assert isinstance(result, AgentResult)
    assert result.total_tokens == 10
    assert result.prompt_tokens == 4
    assert result.completion_tokens == 6
    assert result.latency_ms >= 0
