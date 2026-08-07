import os

from mi_dream.config import settings
from mi_dream.knowledge.curator import Curator
from mi_dream.knowledge.distiller import KnowledgeDistiller
from mi_dream.learning.evaluator import Evaluator
from mi_dream.learning.failure_analyzer import run_failure_analysis
from mi_dream.learning.reflector import Reflector
from mi_dream.memory.connection import get_driver
from mi_dream.memory.embeddings import build_embedder
from mi_dream.observability import get_logger, get_metrics
from mi_dream.resilience import migrate_claim_schema
from mi_dream.security.tenant import TenantContext

logger = get_logger("scheduler")


def _tenant_context(tenant_id: str | None = None) -> TenantContext:
    return TenantContext(id=tenant_id or settings.tenant_id)


CLAIM_TRACES_CYPHER = """
MATCH (t:ReasoningTrace {tenant_id: $tenant_id})
WHERE t.processing_status = "PENDING"
  AND (t.next_attempt_at IS NULL OR t.next_attempt_at <= datetime())
WITH t
ORDER BY t.created_at ASC
LIMIT $batch_size
SET t.processing_status = "CLAIMED",
    t.claimed_by = $worker_id,
    t.claimed_at = datetime(),
    t.attempt_count = COALESCE(t.attempt_count, 0) + 1
RETURN t {.*} AS trace
"""

MARK_PROCESSED_CYPHER = """
MATCH (t:ReasoningTrace {id: $trace_id})
SET t.processing_status = "PROCESSED"
"""

RETRY_TRACE_CYPHER = """
MATCH (t:ReasoningTrace {id: $trace_id})
SET t.processing_status = "PENDING",
    t.next_attempt_at = datetime() + duration({hours: 1})
"""

WORKER_ID = os.getenv("MI_DREAM_WORKER_ID", f"worker-{os.pid}")


class ReflectionScheduler:
    def __init__(self):
        self._evaluator = Evaluator()
        self._reflector = Reflector()

    async def run_cycle(self) -> dict:
        from mi_dream.memory.bootstrap import ensure_schema

        await ensure_schema()
        await migrate_claim_schema()
        driver = get_driver()
        metrics = get_metrics()
        tenant = _tenant_context()

        async with driver.session(database=settings.neo4j_database) as session:
            result = await session.run(
                CLAIM_TRACES_CYPHER,
                tenant_id=tenant.id,
                batch_size=50,
                worker_id=WORKER_ID,
            )
            traces = [r["trace"] async for r in result]

        if not traces:
            return {"traces_processed": 0, "lessons_created": 0}

        try:
            evaluated = self._evaluator.evaluate(traces)
            lessons = await self._reflector.reflect(evaluated, tenant_id=tenant.id)

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

            # Mark all claimed traces as processed
            async with driver.session(database=settings.neo4j_database) as session:
                for trace in traces:
                    await session.run(MARK_PROCESSED_CYPHER, trace_id=trace["id"])

            metrics.increment("learning_traces_processed", len(traces))
            metrics.increment("lessons_created", len(lessons))
            logger.info(
                "learning_cycle_completed",
                extra={"traces": len(traces), "lessons": len(lessons), "worker": WORKER_ID},
            )
            return {"traces_processed": len(traces), "lessons_created": len(lessons)}

        except Exception as e:
            logger.exception(
                "learning_cycle_failed",
                extra={"traces": len(traces), "worker": WORKER_ID},
            )
            metrics.increment("learning_cycle_failures")
            # Retry claimed traces
            async with driver.session(database=settings.neo4j_database) as session:
                for trace in traces:
                    await session.run(RETRY_TRACE_CYPHER, trace_id=trace["id"])
            raise


async def run_learning_cycle(tenant_id: str | None = None) -> dict:
    """Ciclo completo de aprendizado (SDD §20): reflect → distill → curator.

    Cada etapa é isolada em ``try/except``: falha em qualquer fase nunca bloqueia
    as demais nem a execução (degradação graciosa).
    """
    tenant = _tenant_context(tenant_id)
    metrics = get_metrics()
    report: dict = {
        "failure_analysis": None,
        "reflection": None,
        "distill": None,
        "curator": None,
    }

    try:
        report["failure_analysis"] = await run_failure_analysis(tenant.id)
    except Exception as e:
        metrics.increment("learning_cycle_failures")
        logger.exception("learning_cycle_failure_analysis_failed", extra={"tenant": tenant.id})
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
            lessons = await distiller.pending_lessons(tenant.id)
            strategies = await distiller.distill(lessons, tenant.id)
            curator = Curator(session)
            violations = await curator.run_integrity_checks(tenant.id)
            transitions = await curator.run_state_machine(tenant.id)
            duplicates = await curator.deduplicate(tenant.id)
            promoted = await curator.process_experimental_candidates(tenant.id)
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
        metrics.increment("strategies_promoted", len(promoted))
    except Exception as e:
        metrics.increment("learning_cycle_failures")
        logger.exception("learning_cycle_distill_curator_failed", extra={"tenant": tenant.id})
        report["distill"] = {"error": str(e)}

    return report
