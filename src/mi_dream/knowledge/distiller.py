import inspect

from mi_dream.knowledge.models import CuratorDecision, Lesson, Strategy, StrategyCreate
from mi_dream.knowledge.repository import StrategyRepository


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace()).strip()


class KnowledgeDistiller:
    """Consolida Lessons em Strategies EXPERIMENTAL com link SUPPORTED_BY (SDD §4.1.6).

    Fase 1 (determinístico): a decisão CREATE/REINFORCE/REFINE/CONTRADICT vem do
    Reflector; o Distiller materializa a Strategy e cria o link de suporte (KM-002).
    Authoring de conteúdo via LLM é Phase 2.
    """

    def __init__(self, session, repo=None, embedder=None):
        self._session = session
        self._repo = repo or StrategyRepository(session)
        self._embedder = embedder

    async def pending_lessons(self, tenant_id: str) -> list[Lesson]:
        """Lessons ainda sem Strategy de suporte (ainda não distiladas)."""
        result = await self._session.run(
            """
            MATCH (l:Lesson {tenant_id: $tenant_id})
            WHERE NOT EXISTS { (l)-[:SUPPORTED_BY]->(:Strategy) }
            RETURN l {.*} AS lesson
            LIMIT 100
            """,
            tenant_id=tenant_id,
        )
        return [Lesson(**r["lesson"]) async for r in result]

    async def distill(self, lessons: list[Lesson], tenant_id: str) -> list[Strategy]:
        touched = []
        for lesson in lessons:
            strategy = await self._apply(lesson, tenant_id)
            if strategy is not None:
                touched.append(strategy)
        return touched

    async def _apply(self, lesson: Lesson, tenant_id: str) -> Strategy | None:
        if lesson.decision == CuratorDecision.CREATE:
            return await self._create(lesson, tenant_id)
        if lesson.decision in (CuratorDecision.REINFORCE, CuratorDecision.REFINE):
            return await self._reinforce(lesson, tenant_id)
        # CONTRADICT: registrado na Lesson; sem mutação de Strategy (Phase 2: FailurePattern)
        return None

    async def _create(self, lesson: Lesson, tenant_id: str) -> Strategy:
        strategy = await self._repo.create(
            StrategyCreate(
                title=lesson.summary[:200],
                description=lesson.summary,
                domain="general",
                content=lesson.summary,
                tenant_id=tenant_id,
            )
        )
        if self._embedder is not None:
            await self._embed(strategy, lesson)
        await self._repo.add_supported_by(strategy.id, lesson.id)
        return strategy

    async def _embed(self, strategy: Strategy, lesson: Lesson) -> None:
        """Populate s.embedding for vector recall; graceful on provider failure."""
        try:
            vector = self._embedder.embed_query(lesson.summary)
            if inspect.isawaitable(vector):
                vector = await vector
            if vector:
                await self._repo.set_embedding(strategy.id, vector)
        except Exception:
            pass

    async def _reinforce(self, lesson: Lesson, tenant_id: str) -> Strategy:
        existing = await self._repo.list_by_domain("general", tenant_id)
        target = self._match(lesson, existing)
        if target is None:
            return await self._create(lesson, tenant_id)
        await self._repo.update_metrics(target.id, 1, target.success_rate)
        await self._repo.add_supported_by(target.id, lesson.id)
        return target

    @staticmethod
    def _match(lesson: Lesson, strategies: list[Strategy]) -> Strategy | None:
        key = _normalize(lesson.summary)
        for s in strategies:
            title = _normalize(s.title)
            if title and title in key:
                return s
        return None
