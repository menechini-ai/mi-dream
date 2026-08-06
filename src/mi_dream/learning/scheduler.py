import asyncio

from mi_dream.config import settings
from mi_dream.learning.evaluator import Evaluator
from mi_dream.learning.reflector import Reflector
from mi_dream.memory.connection import get_driver


class ReflectionScheduler:
    def __init__(self):
        self._evaluator = Evaluator()
        self._reflector = Reflector()
        self._running = False

    async def run_cycle(self) -> dict:
        from mi_dream.memory.bootstrap import ensure_schema

        await ensure_schema()
        driver = get_driver()
        async with driver.session(database=settings.neo4j_database) as session:
            result = await session.run(
                """
                MATCH (t:ReasoningTrace {tenant_id: $tenant_id})
                WHERE NOT EXISTS { (:Lesson)-[:DERIVED_FROM]->(t) }
                RETURN t {.*} AS trace
                LIMIT 50
                """,
                tenant_id=settings.tenant_id,
            )
            traces = [r["trace"] async for r in result]

        evaluated = self._evaluator.evaluate(traces)
        lessons = await self._reflector.reflect(evaluated, tenant_id=settings.tenant_id)

        async with driver.session(database=settings.neo4j_database) as session:
            for lesson in lessons:
                await session.run(
                    """
                    CREATE (l:Lesson {
                        id: $id, summary: $summary, decision: $decision,
                        source_trace_ids: $source_trace_ids, confidence: $confidence,
                        tenant_id: $tenant_id, created_at: datetime()
                    })
                    WITH l
                    MATCH (t:ReasoningTrace {id: $trace_id})
                    CREATE (l)-[:DERIVED_FROM]->(t)
                    """,
                    id=lesson.id,
                    summary=lesson.summary,
                    decision=lesson.decision.value,
                    source_trace_ids=lesson.source_trace_ids,
                    confidence=lesson.confidence,
                    tenant_id=lesson.tenant_id,
                    trace_id=lesson.source_trace_ids[0],
                )

        return {"traces_processed": len(traces), "lessons_created": len(lessons)}

    async def start(self, interval_hours: int = 6):
        self._running = True
        while self._running:
            try:
                result = await self.run_cycle()
                print(f"Reflection cycle: {result}")
            except Exception as e:
                print(f"Reflection cycle failed: {e}")
            await asyncio.sleep(interval_hours * 3600)

    def stop(self):
        self._running = False
