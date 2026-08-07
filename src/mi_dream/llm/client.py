"""LLM client wrapper — uses OpenAI SDK for OpenAI-compatible proxies."""

import time
from dataclasses import dataclass

from openai import OpenAI

from mi_dream.config import settings

_client: OpenAI | None = None


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


def ask_llm_full(system: str, user_message: str, max_tokens: int = 1024, history: list[dict] | None = None) -> LLMResponse:
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
        messages=messages,
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


def chat(system: str, user_message: str, max_tokens: int = 1024) -> str:
    """Alias for `ask_llm` — OpenAI-compatible chat helper."""
    return ask_llm(system=system, user_message=user_message, max_tokens=max_tokens)
