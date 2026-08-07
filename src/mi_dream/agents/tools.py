import json
import logging

from langchain_core.tools import tool

from mi_dream.config import settings
from mi_dream.knowledge.repository import StrategyRepository
from mi_dream.knowledge.router import ExecutionContext, StrategyRouter
from mi_dream.knowledge.vector import StrategyVectorRetriever
from mi_dream.memory.connection import get_driver
from mi_dream.memory.reasoning import trace_fingerprint
from mi_dream.observability import get_logger, get_metrics
from mi_dream.security.sanitizer import sanitize

logger = get_logger("agents.tools")


async def recall_strategy(
    goal: str, context: dict, tenant_id: str, router: StrategyRouter
) -> ExecutionContext:
    """Tool: consulta Strategy Router antes de planejar."""
    return await router.retrieve(goal, context, tenant_id)


async def save_reasoning_trace(trace_id: str, content: str, metadata: dict, driver) -> None:
    """Tool: grava ReasoningTrace via memory.reasoning (PII-sanitized, SDD §18.2)."""
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {"raw": metadata}
    tenant_id = metadata.get("tenant_id", "default")
    outcome = metadata.get("outcome", "unknown")
    error_type = metadata.get("error_type")
    error_source = metadata.get("error_source")
    content = sanitize(content)
    metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    async with driver.session() as session:
        await session.run(
            """
            CREATE (t:ReasoningTrace {
                id: $trace_id,
                content: $content,
                metadata: $metadata,
                outcome: $outcome,
                error_type: $error_type,
                error_source: $error_source,
                content_hash: $content_hash,
                created_at: datetime(),
                tenant_id: $tenant_id
            })
            """,
            trace_id=trace_id,
            content=content,
            metadata=metadata_json,
            outcome=outcome,
            error_type=error_type,
            error_source=error_source,
            content_hash=trace_fingerprint(content, outcome, metadata_json),
            tenant_id=tenant_id,
        )


def make_recall_strategy_tool(tenant_id: str = "default"):
    """Build a langchain tool that retrieves Strategy knowledge (SDD §6 recall_strategy).

    Uses semantic vector recall via neo4j-graphrag (StrategyVectorRetriever),
    falling back to domain-based listing when vectors are unavailable.
    """
    vector = StrategyVectorRetriever(top_k=settings.vector_top_k)

    @tool
    async def recall_strategy(goal: str, context: str = "{}") -> str:
        """Retrieve relevant Strategy knowledge for a goal before planning.

        Args:
            goal: the task objective to plan for.
            context: optional JSON string with domain, constraints, capabilities.

        Returns:
            JSON ExecutionContext with retrieved ACTIVE strategies (may be empty).
        """
        try:
            ctx = json.loads(context or "{}")
        except json.JSONDecodeError:
            ctx = {}
        ctx.setdefault("domain", "general")
        try:
            async with get_driver().session(database=settings.neo4j_database) as session:
                router = StrategyRouter(
                    StrategyRepository(session),
                    vector_retriever=vector,
                    top_k=settings.vector_top_k,
                )
                result = await router.retrieve(goal, ctx, tenant_id)
            return result.to_json()
        except Exception:
            return ExecutionContext(goal=goal).to_json()

    return recall_strategy


def make_save_reasoning_trace_tool(tenant_id: str = "default"):
    """Build a langchain tool that persists a PII-sanitized reasoning trace (SDD §6)."""

    @tool
    async def save_reasoning_trace(trace_id: str, content: str, outcome: str = "unknown") -> str:
        """Persist a PII-sanitized reasoning trace after task execution.

        Args:
            trace_id: unique identifier for this trace.
            content: the reasoning/action content to record.
            outcome: success, failure or unknown.

        Returns:
            confirmation string.
        """
        metadata = {"tenant_id": tenant_id, "outcome": outcome}
        content = sanitize(content)
        metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        async with get_driver().session() as session:
            await session.run(
                """
                CREATE (t:ReasoningTrace {
                    id: $trace_id,
                    content: $content,
                    metadata: $metadata,
                    outcome: $outcome,
                    content_hash: $content_hash,
                    created_at: datetime(),
                    tenant_id: $tenant_id
                })
                """,
                trace_id=trace_id,
                content=content,
                metadata=metadata_json,
                outcome=outcome,
                content_hash=trace_fingerprint(content, outcome, metadata_json),
                tenant_id=tenant_id,
            )
        return f"trace {trace_id} saved"

    return save_reasoning_trace
