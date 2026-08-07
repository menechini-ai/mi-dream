from neo4j import AsyncSession

from mi_dream.knowledge.models import FailurePattern, FailurePatternCreate


class FailurePatternRepository:
    """Persistência de conhecimento negativo (SDD §23.7, Phase 2a).

    ``failure_count`` cresce apenas via ``increment`` (monotônico, espelha
    INV-002a). ``ATTRIBUTED_TO`` liga cada failure trace ao padrão que o
    absorveu, garantindo idempotência da análise.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self, data: FailurePatternCreate, signature: str = ""
    ) -> FailurePattern:
        result = await self._session.run(
            """
            CREATE (p:FailurePattern {
                id: randomUUID(),
                error_type: $error_type,
                domain: $domain,
                pattern: $pattern,
                failure_count: 0,
                last_seen: datetime(),
                created_at: datetime(),
                signature: $signature,
                tenant_id: $tenant_id
            })
            RETURN p {.*} AS fp
            """,
            error_type=data.error_type,
            domain=data.domain,
            pattern=data.pattern,
            signature=signature,
            tenant_id=data.tenant_id,
        )
        record = await result.single()
        return FailurePattern(**record["fp"])

    async def find_by_signature(
        self, signature: str, tenant_id: str
    ) -> FailurePattern | None:
        result = await self._session.run(
            "MATCH (p:FailurePattern {signature: $signature, "
            "tenant_id: $tenant_id}) RETURN p {.*} AS fp LIMIT 1",
            signature=signature,
            tenant_id=tenant_id,
        )
        record = await result.single()
        return FailurePattern(**record["fp"]) if record else None

    async def get(self, pattern_id: str) -> FailurePattern | None:
        result = await self._session.run(
            """
            MATCH (p:FailurePattern {id: $id})
            RETURN p {.*} AS fp
            """,
            id=pattern_id,
        )
        record = await result.single()
        return FailurePattern(**record["fp"]) if record else None

    async def list_by_domain(
        self, domain: str, tenant_id: str
    ) -> list[FailurePattern]:
        result = await self._session.run(
            "MATCH (p:FailurePattern {domain: $domain, tenant_id: $tenant_id}) "
            "RETURN p {.*} AS fp ORDER BY p.failure_count DESC",
            domain=domain,
            tenant_id=tenant_id,
        )
        return [FailurePattern(**r["fp"]) async for r in result]

    async def list_by_error_type(
        self, error_type: str, tenant_id: str
    ) -> list[FailurePattern]:
        result = await self._session.run(
            "MATCH (p:FailurePattern {error_type: $error_type, "
            "tenant_id: $tenant_id}) "
            "RETURN p {.*} AS fp ORDER BY p.failure_count DESC",
            error_type=error_type,
            tenant_id=tenant_id,
        )
        return [FailurePattern(**r["fp"]) async for r in result]

    async def list_recent(self, tenant_id: str, limit: int = 20) -> list[FailurePattern]:
        result = await self._session.run(
            "MATCH (p:FailurePattern {tenant_id: $tenant_id}) "
            "RETURN p {.*} AS fp ORDER BY p.last_seen DESC LIMIT $limit",
            tenant_id=tenant_id,
            limit=limit,
        )
        return [FailurePattern(**r["fp"]) async for r in result]

    async def increment(self, pattern_id: str) -> FailurePattern | None:
        result = await self._session.run(
            """
            MATCH (p:FailurePattern {id: $id})
            SET p.failure_count = p.failure_count + 1,
                p.last_seen = datetime()
            RETURN p {.*} AS fp
            """,
            id=pattern_id,
        )
        record = await result.single()
        return FailurePattern(**record["fp"]) if record else None

    async def link_trace(self, trace_id: str, pattern_id: str) -> None:
        """Create (t:ReasoningTrace)-[:ATTRIBUTED_TO]->(p:FailurePattern)."""
        await self._session.run(
            """
            MATCH (t:ReasoningTrace {id: $trace_id})
            MATCH (p:FailurePattern {id: $pattern_id})
            MERGE (t)-[:ATTRIBUTED_TO]->(p)
            """,
            trace_id=trace_id,
            pattern_id=pattern_id,
        )

    async def attributed_trace_ids(self, tenant_id: str) -> set[str]:
        result = await self._session.run(
            "MATCH (t:ReasoningTrace {tenant_id: $tenant_id}) "
            "WHERE EXISTS { (t)-[:ATTRIBUTED_TO]->(:FailurePattern) } "
            "RETURN t.id AS trace_id",
            tenant_id=tenant_id,
        )
        return {rec["trace_id"] async for rec in result}
