from neo4j import AsyncSession

from mi_dream.knowledge.models import Strategy, StrategyCreate, StrategyState


class StrategyRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, data: StrategyCreate) -> Strategy:
        result = await self._session.run(
            """
            CREATE (s:Strategy {
                id: randomUUID(),
                title: $title,
                description: $description,
                domain: $domain,
                content: $content,
                state: 'EXPERIMENTAL',
                support_count: 0,
                success_rate: 0.0,
                created_at: datetime(),
                updated_at: datetime(),
                tenant_id: $tenant_id,
                superseded_by: null
            })
            RETURN s {.*} AS s
            """,
            title=data.title,
            description=data.description,
            domain=data.domain,
            content=data.content,
            tenant_id=data.tenant_id,
        )
        record = await result.single()
        return Strategy(**record["s"])

    async def get(self, strategy_id: str) -> Strategy | None:
        result = await self._session.run(
            """
            MATCH (s:Strategy {id: $id})
            OPTIONAL MATCH (s)-[:SUPERSEDES]->(succ:Strategy)
            RETURN s {.*, superseded_by: succ.id} AS s
            """,
            id=strategy_id,
        )
        record = await result.single()
        return Strategy(**record["s"]) if record else None

    async def list_by_domain(
        self, domain: str, tenant_id: str, state: StrategyState | None = None
    ) -> list[Strategy]:
        if state:
            result = await self._session.run(
                "MATCH (s:Strategy {domain: $domain, tenant_id: $tenant_id, "
                "state: $state}) RETURN s {.*} AS s",
                domain=domain,
                tenant_id=tenant_id,
                state=state.value,
            )
        else:
            result = await self._session.run(
                "MATCH (s:Strategy {domain: $domain, tenant_id: $tenant_id}) RETURN s {.*} AS s",
                domain=domain,
                tenant_id=tenant_id,
            )
        return [Strategy(**r["s"]) async for r in result]

    async def transition_state(self, strategy_id: str, new_state: StrategyState) -> Strategy | None:
        result = await self._session.run(
            """
            MATCH (s:Strategy {id: $id})
            SET s.state = $new_state, s.updated_at = datetime()
            RETURN s {.*} AS s
            """,
            id=strategy_id,
            new_state=new_state.value,
        )
        record = await result.single()
        return Strategy(**record["s"]) if record else None

    async def add_supported_by(self, strategy_id: str, lesson_id: str) -> None:
        """Create the (l:Lesson)-[:SUPPORTED_BY]->(s:Strategy) link (KM-002)."""
        await self._session.run(
            """
            MATCH (s:Strategy {id: $strategy_id}), (l:Lesson {id: $lesson_id})
            MERGE (l)-[:SUPPORTED_BY]->(s)
            """,
            strategy_id=strategy_id,
            lesson_id=lesson_id,
        )

    async def set_embedding(self, strategy_id: str, embedding: list[float]) -> None:
        """Persist the strategy embedding vector for vector recall (SDD §6)."""
        await self._session.run(
            """
            MATCH (s:Strategy {id: $id})
            SET s.embedding = $embedding
            """,
            id=strategy_id,
            embedding=embedding,
        )

    async def mark_superseded(self, strategy_id: str, successor_id: str) -> Strategy | None:
        result = await self._session.run(
            """
            MATCH (s:Strategy {id: $id})
            OPTIONAL MATCH (s)-[old:SUPERSEDES]->(:Strategy)
            DELETE old
            WITH s
            MATCH (successor:Strategy {id: $successor_id})
            SET s.state = 'SUPERSEDED', s.updated_at = datetime()
            CREATE (s)-[:SUPERSEDES]->(successor)
            RETURN s {.*, superseded_by: $successor_id} AS s
            """,
            id=strategy_id,
            successor_id=successor_id,
        )
        record = await result.single()
        return Strategy(**record["s"]) if record else None

    async def update_metrics(
        self, strategy_id: str, support_delta: int, success_rate: float
    ) -> Strategy | None:
        result = await self._session.run(
            """
            MATCH (s:Strategy {id: $id})
            SET s.support_count = s.support_count
                    + CASE WHEN $delta < 0 THEN 0 ELSE $delta END,
                s.success_rate = $success_rate,
                s.updated_at = datetime()
            RETURN s {.*} AS s
            """,
            id=strategy_id,
            delta=support_delta,
            success_rate=success_rate,
        )
        record = await result.single()
        return Strategy(**record["s"]) if record else None
