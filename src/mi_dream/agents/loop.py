"""Agent tool loop: LLM <-> tool calls with an iteration guard.

Mirrors the tool-call pattern from nanobot (HKUDS/nanobot) but with a bounded
loop so a model that keeps requesting tools cannot spin forever.
"""

import asyncio
import json
from dataclasses import dataclass, field

from mi_dream.llm.client import ChatTurn, chat_turn

TOOL_LOOP_LIMIT_MESSAGE = "[tool loop limit reached]"


class Tool:
    """Base class for a tool the agent can call."""

    def __init__(self, name: str, description: str, parameters: dict):
        self.name = name
        self.description = description
        self.parameters = parameters

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def run(self, **kwargs) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Tool {self.name}>"


class Toolbox:
    """Registry of tools: builds OpenAI tool schemas and executes by name."""

    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self._tools[tool.name] = tool

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments_json: str) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool {name!r}. Available: {', '.join(self.names())}"
        try:
            kwargs = json.loads(arguments_json) if arguments_json.strip() else {}
        except json.JSONDecodeError as exc:
            return f"Error: invalid JSON arguments for {name!r}: {exc}"
        try:
            result = tool.run(**kwargs)
        except Exception as exc:  # noqa: BLE001 - surface any tool failure to the model
            return f"Error: {name!r} failed: {exc}"
        if not isinstance(result, str):
            result = json.dumps(result)
        return result


@dataclass
class AgentResult:
    """Final result of a tool loop, shaped like ``LLMResponse`` for the REPL."""

    content: str
    iterations: int = 0
    tool_calls: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    limit_reached: bool = False
    tool_history: list[dict] = field(default_factory=list)


def _assistant_tool_call_message(turn: ChatTurn) -> dict:
    return {
        "role": "assistant",
        "content": turn.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in turn.tool_calls
        ],
    }


async def run_tool_loop(
    system: str,
    user: str,
    history: list[dict] | None = None,
    toolbox: Toolbox | None = None,
    max_iterations: int = 5,
    max_tokens: int = 1024,
) -> AgentResult:
    """Run the agent loop: chat -> tool calls -> results -> chat, bounded.

    Stops when the model replies without tool calls, or after ``max_iterations``
    turns (returning ``limit_reached=True`` so callers can surface the guard).
    """
    messages: list[dict] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user})
    tools = toolbox.schemas() if toolbox else None

    tool_calls_done = 0
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    latency_ms = 0.0
    tool_history: list[dict] = []

    for iteration in range(max_iterations):
        turn = await asyncio.to_thread(chat_turn, messages, tools, max_tokens)
        total_tokens += turn.total_tokens
        prompt_tokens += turn.prompt_tokens
        completion_tokens += turn.completion_tokens
        latency_ms += turn.latency_ms

        if not turn.tool_calls:
            return AgentResult(
                content=turn.content,
                iterations=iteration + 1,
                tool_calls=tool_calls_done,
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                tool_history=tool_history,
            )

        messages.append(_assistant_tool_call_message(turn))
        for tc in turn.tool_calls:
            if toolbox is None:
                result = f"Error: no tools are available to run {tc.name!r}"
            else:
                result = toolbox.execute(tc.name, tc.arguments)
            tool_calls_done += 1
            tool_history.append({"name": tc.name, "arguments": tc.arguments, "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return AgentResult(
        content=TOOL_LOOP_LIMIT_MESSAGE,
        iterations=max_iterations,
        tool_calls=tool_calls_done,
        total_tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        limit_reached=True,
        tool_history=tool_history,
    )
