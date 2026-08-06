"""LLM client wrapper — uses OpenAI SDK for OpenAI-compatible proxies."""

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


def ask_llm(system: str, user_message: str, max_tokens: int = 1024) -> str:
    """Send a chat message and return the response text (runs in executor)."""
    client = get_client()
    response = client.chat.completions.create(
        model=settings.llm_model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        return "[empty response from provider]"
    return content


def chat(system: str, user_message: str, max_tokens: int = 1024) -> str:
    """Alias for `ask_llm` — OpenAI-compatible chat helper."""
    return ask_llm(system=system, user_message=user_message, max_tokens=max_tokens)
