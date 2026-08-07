import hashlib
import json
import re

from mi_dream.config import settings
from mi_dream.knowledge.failure_patterns import FailurePatternRepository
from mi_dream.knowledge.models import FailurePatternCreate
from mi_dream.memory.connection import get_driver

_STOPWORDS = {
    "a", "an", "and", "are", "for", "in", "is", "not", "of", "on",
    "or", "the", "this", "to", "was", "were", "with",
}


def _parse_metadata(metadata_json) -> dict:
    try:
        data = json.loads(metadata_json)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def failure_signature(error_type: str, domain: str, message: str) -> str:
    """Deterministic signature of a failure (SDD §23.7, Phase 2a).

    Normalizes the error message (lowercase, word tokens, stopwords removed)
    so similar messages group into the same FailurePattern, regardless of
    case/punctuation.
    """
    words = [
        w
        for w in re.findall(r"[a-z0-9]+", message.lower())
        if len(w) > 3 and w not in _STOPWORDS
    ]
    key = " ".join(sorted(set(words))[:5])
    raw = f"{error_type}:{domain}:{key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _extract_failure_meta(trace: dict) -> tuple[str, str, str]:
    metadata = _parse_metadata(trace.get("metadata"))
    error_type = trace.get("error_type") or metadata.get("error_type") or "unknown_error"
    domain = trace.get("domain") or metadata.get("domain") or "general"
    message = metadata.get("error_message") or trace.get("content") or ""
    return error_type, domain, message


def _representative_message(group: list[dict]) -> str:
    messages = []
    for trace in group:
        _, _, message = _extract_failure_meta(trace)
        if message:
            messages.append(message)
    if not messages:
        return "unknown failure"
    return max(set(messages), key=messages.count)[:200]


async def _unattributed_failure_traces(
    session, tenant_id: str, limit: int
) -> list[dict]:
    result = await session.run(
        """
        MATCH (t:ReasoningTrace {tenant_id: $tenant_id, outcome: 'failure'})
        WHERE NOT EXISTS { (t)-[:ATTRIBUTED_TO]->(:FailurePattern) }
        RETURN t {.*} AS trace
        ORDER BY t.created_at ASC
        LIMIT $limit
        """,
        tenant_id=tenant_id,
        limit=limit,
    )
    return [rec["trace"] async for rec in result]


async def run_failure_analysis(
    tenant_id: str | None = None,
    limit: int = 50,
    driver=None,
    repo=None,
) -> dict:
    """Agrega failure traces em FailurePattern (SDD §23.7, Phase 2a).

    Idempotente via ``ATTRIBUTED_TO``: cada trace é processado uma única vez.
    Determinístico: agrupamento por ``failure_signature``.
    """
    tenant_id = tenant_id or settings.tenant_id
    driver = driver or get_driver()
    async with driver.session(database=settings.neo4j_database) as session:
        repo = repo or FailurePatternRepository(session)
        traces = await _unattributed_failure_traces(session, tenant_id, limit)

        groups: dict[tuple[str, str, str], list[dict]] = {}
        for trace in traces:
            error_type, domain, message = _extract_failure_meta(trace)
            sig = failure_signature(error_type, domain, message)
            groups.setdefault((error_type, domain, sig), []).append(trace)

        created = 0
        updated = 0
        for (error_type, domain, sig), group in groups.items():
            existing = await repo.find_by_signature(sig, tenant_id)
            if existing:
                await repo.increment(existing.id)
                pattern_id = existing.id
                updated += 1
            else:
                pattern = await repo.create(
                    FailurePatternCreate(
                        error_type=error_type,
                        domain=domain,
                        pattern=_representative_message(group),
                        tenant_id=tenant_id,
                    ),
                    signature=sig,
                )
                pattern_id = pattern.id
                created += 1
            for trace in group:
                await repo.link_trace(trace["id"], pattern_id)

        return {
            "failures_processed": len(traces),
            "patterns_created": created,
            "patterns_updated": updated,
        }


async def get_failure_patterns(
    tenant_id: str,
    limit: int = 20,
    error_type: str | None = None,
    domain: str | None = None,
    driver=None,
) -> list[dict]:
    """Lista FailurePattern (conhecimento negativo), mais recentes/recorrentes."""
    driver = driver or get_driver()
    patterns: list[dict] = []
    async with driver.session(database=settings.neo4j_database) as session:
        repo = FailurePatternRepository(session)
        if error_type:
            rows = await repo.list_by_error_type(error_type, tenant_id)
        elif domain:
            rows = await repo.list_by_domain(domain, tenant_id)
        else:
            rows = await repo.list_recent(tenant_id, limit)
        patterns = [p.model_dump(mode="json") for p in rows]
    return patterns


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
