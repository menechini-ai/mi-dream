from mi_dream.config import settings
from mi_dream.knowledge.curator import Curator
from mi_dream.knowledge.distiller import KnowledgeDistiller
from mi_dream.learning.evaluator import Evaluator
from mi_dream.learning.failure_analyzer import run_failure_analysis
from mi_dream.learning.reflector import Reflector
from mi_dream.memory.connection import get_driver
from mi_dream.memory.embeddings import build_embedder


class ReflectionScheduler:
    def __init__(self):
        self._evaluator = Evaluator()
        self._reflector = Reflector()

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


async def run_learning_cycle(tenant_id: str | None = None) -> dict:
    """Ciclo completo de aprendizado (SDD §20): reflect → distill → curator.

    Cada etapa é isolada em ``try/except``: falha em qualquer fase nunca bloqueia
    as demais nem a execução (degradação graciosa).
    """
    tenant_id = tenant_id or settings.tenant_id
    report: dict = {
        "failure_analysis": None,
        "reflection": None,
        "distill": None,
        "curator": None,
    }

    try:
        report["failure_analysis"] = await run_failure_analysis(tenant_id)
    except Exception as e:
        report["failure_analysis"] = {"error": str(e)}

    try:
        scheduler = ReflectionScheduler()
        report["reflection"] = await scheduler.run_cycle()
    except Exception as e:
        report["reflection"] = {"error": str(e)}

    try:
        embedder = None
        try:
            embedder = build_embedder()
        except Exception:
            embedder = None
        async with get_driver().session(database=settings.neo4j_database) as session:
            distiller = KnowledgeDistiller(session, embedder=embedder)
            lessons = await distiller.pending_lessons(tenant_id)
            strategies = await distiller.distill(lessons, tenant_id)
            curator = Curator(session)
            violations = await curator.run_integrity_checks(tenant_id)
            transitions = await curator.run_state_machine(tenant_id)
            duplicates = await curator.deduplicate(tenant_id)
            promoted = await curator.process_experimental_candidates(tenant_id)
        report["distill"] = {
            "lessons_processed": len(lessons),
            "strategies_touched": len(strategies),
        }
        report["curator"] = {
            "integrity_violations": len(violations),
            "state_machine": transitions,
            "duplicates": len(duplicates),
            "promoted": len(promoted),
        }
    except Exception as e:
        report["distill"] = {"error": str(e)}

    return report
