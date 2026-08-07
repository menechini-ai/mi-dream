import asyncio
import inspect
import json
from uuid import uuid4

from mi_dream.config import settings
from mi_dream.llm.client import ask_llm_full
from mi_dream.memory.connection import get_driver
from mi_dream.memory.reasoning import trace_fingerprint
from mi_dream.security.sanitizer import sanitize

COMPACT_SYSTEM_PROMPT = """\
You are a conversation summarizer. Condense the conversation into a concise
summary that preserves key facts: names, preferences, decisions, code snippets,
and objective facts. Discard filler and pleasantries. Keep it under 250 words.
"""


class ConversationCompactor:
    """Compacta conversas longas num resumo e o persiste como Episode (SDD §19).

    O resumo é mantido no contexto como uma mensagem de role ``system``, com os
    turnos mais recentes verbatim. A persistência grava ``(:Episode)`` (com
    embedding no índice ``episode_embedding``) e um ``ReasoningTrace`` derivado,
    permitindo que o resumo entre no Learning Pipeline.
    """

    def __init__(self, embedder=None):
        self._embedder = embedder

    async def summarize(self, messages: list[dict]) -> str:
        transcript = "\n".join(
            f"{m.get('role', '?')}: {m.get('content', '')}" for m in messages
        )
        resp = await asyncio.to_thread(
            ask_llm_full,
            COMPACT_SYSTEM_PROMPT,
            f"Conversation:\n{transcript}",
            max_tokens=512,
        )
        return resp.content

    @staticmethod
    def _size(messages: list[dict]) -> int:
        return sum(len(m.get("content", "")) for m in messages)

    async def compact(
        self,
        messages: list[dict],
        threshold_chars: int | None = None,
        keep_recent: int | None = None,
    ) -> list[dict]:
        threshold = (
            threshold_chars
            if threshold_chars is not None
            else settings.compact_threshold_chars
        )
        keep = keep_recent if keep_recent is not None else settings.compact_keep_recent
        if self._size(messages) <= threshold:
            return list(messages)
        keep = max(1, min(keep, len(messages)))
        older = messages[:-keep]
        summary = await self.summarize(older)
        return [{"role": "system", "content": f"[Resumo] {summary}"}, *messages[-keep:]]

    async def persist_episode(
        self, summary: str, session_id: str, tenant_id: str | None = None
    ) -> str:
        tenant_id = tenant_id or settings.tenant_id
        summary = sanitize(summary)
        episode_id = f"ep-{uuid4().hex}"
        embedding = await self._embed(summary)
        async with get_driver().session(database=settings.neo4j_database) as session:
            await session.run(
                """
                CREATE (e:Episode {
                    id: $id, summary: $summary, content: $summary,
                    session_id: $session_id, tenant_id: $tenant_id,
                    created_at: datetime()
                })
                """,
                id=episode_id,
                summary=summary,
                session_id=session_id,
                tenant_id=tenant_id,
            )
            if embedding:
                await session.run(
                    "MATCH (e:Episode {id: $id}) SET e.embedding = $embedding",
                    id=episode_id,
                    embedding=embedding,
                )
            metadata = json.dumps(
                {
                    "tenant_id": tenant_id,
                    "outcome": "success",
                    "source": "episode",
                    "episode_id": episode_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            await session.run(
                """
                CREATE (t:ReasoningTrace {
                    id: $trace_id, content: $content, metadata: $metadata,
                    outcome: $outcome, content_hash: $content_hash,
                    created_at: datetime(), tenant_id: $tenant_id
                })
                """,
                trace_id=f"cli-{uuid4().hex}",
                content=summary,
                metadata=metadata,
                outcome="success",
                content_hash=trace_fingerprint(summary, "success", metadata),
                tenant_id=tenant_id,
            )
        return episode_id

    async def _embed(self, summary: str) -> list[float] | None:
        if self._embedder is None:
            return None
        try:
            vector = self._embedder.embed_query(summary)
            if inspect.isawaitable(vector):
                vector = await vector
            return vector
        except Exception:
            return None
