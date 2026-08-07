"""LLM client wrapper — uses OpenAI SDK for OpenAI-compatible proxies."""

import time
from dataclasses import dataclass

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from mi_dream.config import settings

_client: OpenAI | None = None

ERROR_TYPE_MESSAGE_MAX = 300


def extract_llm_error(exc: Exception) -> tuple[str, str]:
    """Classify an LLM call failure into a short ``(error_type, message)`` (SDD §23)."""
    if isinstance(exc, APIConnectionError) or isinstance(exc, ConnectionError):
        error_type = "connection_error"
    elif isinstance(exc, APITimeoutError) or isinstance(exc, TimeoutError):
        error_type = "timeout_error"
    elif isinstance(exc, RateLimitError):
        error_type = "rate_limit_error"
    elif isinstance(exc, AuthenticationError):
        error_type = "auth_error"
    elif isinstance(exc, PermissionDeniedError):
        error_type = "permission_error"
    elif isinstance(exc, APIError):
        error_type = "api_error"
    elif isinstance(exc, ValueError):
        error_type = "config_error"
    else:
        error_type = "unknown_error"
    message = str(exc).strip() or exc.__class__.__name__
    if len(message) > ERROR_TYPE_MESSAGE_MAX:
        message = message[: ERROR_TYPE_MESSAGE_MAX - 1] + "…"
    return error_type, message


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.llm_api_key:
            raise ValueError("LLM_API_KEY not set in environment")
        _client = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
        )
    return _client


@dataclass
class LLMResponse:
    """Result of an LLM call: content plus observable usage/latency."""

    content: str
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


def ask_llm_full(
    system: str,
    user_message: str,
    max_tokens: int = 1024,
    history: list[dict] | None = None,
) -> LLMResponse:
    """Send a chat message and return content + token usage + latency.

    ``history`` is optional prior turns (list of {role, content}). When provided,
    they are sent before the current user message so the LLM has conversation memory.

    ``usage`` may be absent on some OpenAI-compatible proxies — both fields
    fall back to 0 in that case.
    """
    client = get_client()
    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    start = time.monotonic()
    response = client.chat.completions.create(
        model=settings.llm_model,
        max_tokens=max_tokens,
        temperature=settings.llm_temperature,
        messages=messages,
        timeout=settings.llm_timeout_seconds,
    )
    latency_ms = (time.monotonic() - start) * 1000
    content = response.choices[0].message.content
    if not content:
        content = "[empty response from provider]"
    usage = getattr(response, "usage", None)
    return LLMResponse(
        content=content,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        latency_ms=latency_ms,
    )


def ask_llm(system: str, user_message: str, max_tokens: int = 1024) -> str:
    """Send a chat message and return the response text (runs in executor)."""
    return ask_llm_full(system, user_message, max_tokens).content


@dataclass
class ToolCall:
    """A single tool call the model requested in a chat turn."""

    id: str
    name: str
    arguments: str


@dataclass
class ChatTurn:
    """Result of a raw chat turn: content plus any tool calls the model made."""

    content: str
    tool_calls: list[ToolCall]
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


def chat_turn(
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens: int = 1024,
) -> ChatTurn:
    """Send raw messages to the LLM, optionally advertising tool schemas.

    Returns content plus any ``tool_calls`` the model requested so callers can
    run them and feed the results back (``role: "tool"``) in a following turn.
    """
    client = get_client()
    kwargs: dict = {
        "model": settings.llm_model,
        "max_tokens": max_tokens,
        "temperature": settings.llm_temperature,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
    kwargs["timeout"] = settings.llm_timeout_seconds
    start = time.monotonic()
    response = client.chat.completions.create(**kwargs)
    latency_ms = (time.monotonic() - start) * 1000
    msg = response.choices[0].message
    content = msg.content or "[empty response from provider]"
    tool_calls = [
        ToolCall(
            id=tc.id,
            name=tc.function.name,
            arguments=tc.function.arguments,
        )
        for tc in (msg.tool_calls or [])
    ]
    usage = getattr(response, "usage", None)
    return ChatTurn(
        content=content,
        tool_calls=tool_calls,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        latency_ms=latency_ms,
    )
