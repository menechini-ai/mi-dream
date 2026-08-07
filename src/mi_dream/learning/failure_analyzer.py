import json

from mi_dream.config import settings
from mi_dream.memory.connection import get_driver


def _parse_metadata(metadata_json) -> dict:
    try:
        data = json.loads(metadata_json)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


async def get_failures(
    tenant_id: str,
    limit: int = 20,
    error_type: str | None = None,
    source: str | None = None,
    driver=None,
) -> list[dict]:
    """List persisted ReasoningTrace failures, newest first (SDD §23).

    ``error_type`` and ``source`` (chat|skill|agent|cron) are optional filters
    over node properties; nodes created before v2.5 fall back to metadata.
    """
    driver = driver or get_driver()
    where = ["t.outcome = 'failure'"]
    params: dict = {"tenant_id": tenant_id, "limit": limit}
    if error_type:
        where.append("t.error_type = $error_type")
        params["error_type"] = error_type
    if source:
        where.append("t.error_source = $source")
        params["source"] = source
    cypher = (
        "MATCH (t:ReasoningTrace {tenant_id: $tenant_id}) "
        f"WHERE {' AND '.join(where)} "
        "RETURN t.id AS id, t.content AS content, t.outcome AS outcome, "
        "t.error_type AS error_type, t.error_source AS error_source, "
        "t.metadata AS metadata, t.created_at AS created_at "
        "ORDER BY t.created_at DESC LIMIT $limit"
    )
    failures: list[dict] = []
    async with driver.session(database=settings.neo4j_database) as session:
        result = await session.run(cypher, **params)
        async for rec in result:
            meta = _parse_metadata(rec["metadata"])
            failures.append(
                {
                    "id": rec["id"],
                    "content": rec["content"],
                    "error_type": rec["error_type"] or meta.get("error_type") or "unknown",
                    "source": rec["error_source"] or meta.get("source") or "unknown",
                    "error_message": meta.get("error_message", ""),
                    "tokens": meta.get("tokens", 0),
                    "latency_ms": meta.get("latency_ms", 0.0),
                    "created_at": rec["created_at"],
                }
            )
    return failures
