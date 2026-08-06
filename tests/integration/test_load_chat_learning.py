"""Load test: múltiplas mensagens de chat geram Execution Contexts e o sistema aprende.

Cenário (SDD §6, §13):
1. N mensagens de chat (tópicos kubernetes/database/monitoring) geram Execution
   Context via StrategyRouter e persistem ReasoningTrace sanitizados (INV-001).
2. Pipeline de aprendizado roda sobre os traces: ReflectionScheduler (Reflector
   heurístico, LLM mockado) -> Lessons; KnowledgeDistiller -> Strategies
   EXPERIMENTAL + SUPPORTED_BY (KM-002) + embedding; reforço de métricas;
   Curator promove para ACTIVE.
3. Verificação do aprendizado: novo recall vetorial retorna as Strategies do
   tópico certo por similaridade; integrity checks sem violação.

O embedder é determinístico e baseado em tópicos (1536-d, sem provider externo),
permitindo verificar o vector recall real de ponta a ponta. Requer Neo4j vivo.
Volume configurável via LOAD_TEST_MESSAGES (default 30).
"""

import asyncio
import math
import os
import random
import sys
import time
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

import pytest

from mi_dream.agents.tools import save_reasoning_trace
from mi_dream.cli.repl import build_system_prompt, recall_context
from mi_dream.config import settings
from mi_dream.knowledge.curator import Curator
from mi_dream.knowledge.distiller import KnowledgeDistiller
from mi_dream.knowledge.models import StrategyState
from mi_dream.knowledge.repository import StrategyRepository
from mi_dream.knowledge.router import ExecutionContext
from mi_dream.knowledge.vector import StrategyVectorRetriever
from mi_dream.learning.scheduler import ReflectionScheduler
from mi_dream.memory.connection import get_driver

DIM = 1536
TOPICS = ["kubernetes", "database", "monitoring"]
LOAD_MESSAGES = int(os.getenv("LOAD_TEST_MESSAGES", "30"))
CONCURRENCY = int(os.getenv("LOAD_TEST_CONCURRENCY", "5"))


class TopicEmbedder:
    """Embedder determinístico 1536-d: vetor por tópico (unitário), sem provider.

    Textos que mencionam o mesmo tópico ficam próximos em cosseno; tópicos
    diferentes ficam ortogonais (embeddings aleatórios com seed fixa).
    """

    def __init__(self) -> None:
        rng = random.Random(42)
        self._topic_vecs = {t: self._unit(rng) for t in TOPICS}
        self._base = self._unit(random.Random(7))

    @staticmethod
    def _unit(rng) -> list[float]:
        vec = [rng.uniform(-1.0, 1.0) for _ in range(DIM)]
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_query(self, text: str) -> list[float]:
        low = text.lower()
        vec = [0.0] * DIM
        for topic, tvec in self._topic_vecs.items():
            if topic in low:
                for i in range(DIM):
                    vec[i] += tvec[i]
        if all(x == 0.0 for x in vec):
            vec = list(self._base)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


def _canned_assistant(text: str) -> str:
    return (
        "Understood. I analyzed the request and prepared an execution plan with "
        "diagnosis steps, validation gates and a rollback strategy. Executing: "
        f"{text[:60]}..."
    )


@pytest.fixture
async def live_neo4j():
    try:
        async with get_driver().session(database=settings.neo4j_database) as session:
            await session.run("RETURN 1")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Neo4j unreachable: {e}")
    return True


def _chat_messages(n: int) -> list[tuple[str, str, str]]:
    out = []
    for i in range(n):
        topic = TOPICS[i % len(TOPICS)]
        outcome = "success" if i % 3 else "failure"
        text = (
            f"{topic} production incident {i}: nodes degraded, need to diagnose "
            f"the root cause and apply the runbook fix for cluster {i % 4} while "
            "keeping the service available"
        )
        out.append((text, outcome, topic))
    return out


@pytest.mark.asyncio
async def test_load_chat_contexts_and_learning(live_neo4j, monkeypatch):
    tenant = f"load-{uuid4().hex[:12]}"
    monkeypatch.setattr(settings, "tenant_id", tenant)

    from mi_dream.cli import repl as repl_mod
    from mi_dream.learning import reflector as reflector_mod

    monkeypatch.setattr(repl_mod, "ask_llm", _canned_assistant)
    monkeypatch.setattr(reflector_mod, "ask_llm", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("llm mocked off for load test")
    ))

    driver = get_driver()
    try:
        # ---- Fase 1: carga de chat — mensagens geram contextos + traces ----
        messages = _chat_messages(LOAD_MESSAGES)

        async def send_one(i: int, text: str, outcome: str) -> tuple[ExecutionContext, str]:
            ctx = await recall_context(text)
            assert isinstance(ctx, ExecutionContext)
            assert ctx.goal == text
            prompt = build_system_prompt(ctx)
            assert isinstance(prompt, str) and "assistant" in prompt
            trace_id = f"cli-load-{i}-{uuid4().hex[:8]}"
            await save_reasoning_trace(
                trace_id=trace_id,
                content=f"Q: {text}\nA: {_canned_assistant(text)}",
                metadata={"tenant_id": tenant, "outcome": outcome},
                driver=driver,
            )
            return ctx, trace_id

        sem = asyncio.Semaphore(CONCURRENCY)

        async def throttled(i: int, text: str, outcome: str):
            async with sem:
                return await send_one(i, text, outcome)

        t0 = time.perf_counter()
        results = await asyncio.gather(
            *(throttled(i, t, o) for i, (t, o, _) in enumerate(messages))
        )
        wall = time.perf_counter() - t0
        trace_ids = [tid for _, tid in results]
        assert len(trace_ids) == LOAD_MESSAGES

        async with driver.session(database=settings.neo4j_database) as session:
            row = await (await session.run(
                "MATCH (t:ReasoningTrace {tenant_id: $t}) RETURN count(t) AS c",
                t=tenant,
            )).single()
            assert row["c"] == LOAD_MESSAGES, "nem todos os traces foram persistidos"

        # ---- Fase 2: aprendizado — reflect -> lessons -> strategies -> ACTIVE ---
        processed_total = 0
        lessons_total = 0
        for _ in range(10):  # scheduler processa em lotes de 50 (LIMIT)
            cycle = await ReflectionScheduler().run_cycle()
            if cycle["traces_processed"] == 0:
                break
            processed_total += cycle["traces_processed"]
            lessons_total += cycle["lessons_created"]
        assert processed_total == LOAD_MESSAGES
        assert lessons_total >= 1

        async with driver.session(database=settings.neo4j_database) as session:
            distiller = KnowledgeDistiller(session, embedder=TopicEmbedder())
            lessons = await distiller.pending_lessons(tenant)
            strategies = await distiller.distill(lessons, tenant)
            assert len(strategies) == len(lessons) > 0

            emb = await (await session.run(
                "MATCH (s:Strategy {tenant_id: $t}) "
                "WHERE size(s.embedding) = $d RETURN count(s) AS c",
                t=tenant, d=DIM,
            )).single()
            assert emb["c"] == len(strategies), "embeddings não persistidos (1536-d)"

            repo = StrategyRepository(session)
            for s in strategies:
                await repo.update_metrics(s.id, 3, 0.8)
            curator = Curator(session)
            promoted = await curator.process_experimental_candidates(tenant)
            assert len(promoted) == len(strategies)
            assert all(p.state == StrategyState.ACTIVE for p in promoted)

        # ---- Fase 3: checagem do aprendizado ----
        # 3a. Novo chat: o contexto agora traz as Strategies aprendidas
        ctx = await recall_context(messages[0][0])
        assert ctx.strategies, "contexto vazio após aprendizado"
        assert "Relevant knowledge strategies" in build_system_prompt(ctx)

        # 3b. Recall vetorial: query de um tópico retorna strategy do mesmo tópico
        vr = StrategyVectorRetriever(embedder=TopicEmbedder())
        try:
            for topic in TOPICS:
                hits = await vr.search(f"{topic} incident diagnosis", tenant, "general", 5)
                assert hits, f"recall vetorial vazio para {topic}"
                assert hits[0].score is not None
                assert topic in hits[0].content.lower(), (
                    f"top-1 de '{topic}' não é do tópico ({hits[0].content[:60]})"
                )
        finally:
            await vr.close()

        # 3c. Integridade: INV-001 (traces imutáveis) e KM-002 (ACTIVE suportada)
        async with driver.session(database=settings.neo4j_database) as session:
            violations = await Curator(session).run_integrity_checks(tenant)
        assert violations == []

        print(
            f"\n[load] messages={LOAD_MESSAGES} concurrency={CONCURRENCY} "
            f"wall={wall:.2f}s traces={len(trace_ids)} "
            f"lessons={lessons_total} strategies={len(strategies)} "
            f"active={len(promoted)}"
        )
    finally:
        async with driver.session(database=settings.neo4j_database) as session:
            await session.run(
                "MATCH (n {tenant_id: $t}) DETACH DELETE n", t=tenant
            )
