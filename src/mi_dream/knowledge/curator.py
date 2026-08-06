from neo4j import AsyncSession

from mi_dream.knowledge.models import Strategy

INTEGRITY_CHECKS = [
    # KM-002: Strategy ACTIVE must have at least one SUPPORTED_BY lesson
    """
    MATCH (s:Strategy {state: 'ACTIVE', tenant_id: $tenant_id})
    WHERE NOT EXISTS { MATCH (s)<-[:SUPPORTED_BY]-(:Lesson) }
    RETURN s.id AS orphaned_strategy, 'ACTIVE without SUPPORTED_BY' AS reason
    """,
    # SUPERSEDED without successor
    """
    MATCH (s:Strategy {state: 'SUPERSEDED', tenant_id: $tenant_id})
    WHERE NOT EXISTS { MATCH (s)-[:SUPERSEDES]->(:Strategy) }
    RETURN s.id AS orphaned_strategy, 'SUPERSEDED without successor' AS reason
    """,
    # SUPERSEDED cycle detection
    """
    MATCH path = (a:Strategy {tenant_id: $tenant_id})-[:SUPERSEDES*1..10]->(a)
    RETURN [n IN nodes(path) | n.id] AS cycle
    """,
]


DEDUP_CYPHER = """
MATCH (s1:Strategy {tenant_id: $tenant_id}), (s2:Strategy {tenant_id: $tenant_id})
WHERE s1.id < s2.id
  AND s1.domain = s2.domain
  AND s1.title = s2.title
  AND s1.state IN ['EXPERIMENTAL', 'ACTIVE']
RETURN s1.id AS keep_id, s2.id AS merge_id, s1.title AS title
"""


class Curator:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def run_integrity_checks(self, tenant_id: str) -> list[dict]:
        violations = []
        for cypher in INTEGRITY_CHECKS:
            result = await self._session.run(cypher, tenant_id=tenant_id)
            violations.extend([r.data() async for r in result])
        violations.extend(await self.check_trace_immutability(tenant_id))
        return violations

    async def check_trace_immutability(self, tenant_id: str) -> list[dict]:
        """INV-001: detect any mutation of a ReasoningTrace after creation.

        Compares the stored ``content_hash`` against a recomputed fingerprint
        of the current content/outcome/metadata. Also flags traces created
        before ``content_hash`` was introduced.
        """
        from mi_dream.memory.reasoning import trace_fingerprint

        result = await self._session.run(
            """
            MATCH (t:ReasoningTrace {tenant_id: $tenant_id})
            RETURN t.id AS trace_id, t.content AS content, t.outcome AS outcome,
                   t.metadata AS metadata, t.content_hash AS content_hash
            """,
            tenant_id=tenant_id,
        )
        violations = []
        async for rec in result:
            content_hash = rec["content_hash"]
            if content_hash is None:
                violations.append(
                    {
                        "trace_id": rec["trace_id"],
                        "reason": "ReasoningTrace without content_hash (INV-001 not enforced)",
                    }
                )
                continue
            fingerprint = trace_fingerprint(
                rec["content"], rec["outcome"], rec["metadata"]
            )
            if fingerprint != content_hash:
                violations.append(
                    {
                        "trace_id": rec["trace_id"],
                        "reason": "ReasoningTrace mutated (content_hash mismatch, INV-001)",
                    }
                )
        return violations

    async def run_state_machine(self, tenant_id: str) -> dict:
        promoted = 0
        demoted = 0

        # STALE -> ACTIVE: used within last 90 days
        result = await self._session.run(
            """
            MATCH (s:Strategy {state: 'STALE', tenant_id: $tenant_id})
            WHERE s.updated_at > datetime() - duration('P90D')
            SET s.state = 'ACTIVE', s.updated_at = datetime()
            RETURN count(s) AS count
            """,
            tenant_id=tenant_id,
        )
        rec = await result.single()
        promoted += rec["count"]

        # STALE -> ARCHIVED: no use > 90d, low support
        result = await self._session.run(
            """
            MATCH (s:Strategy {state: 'STALE', tenant_id: $tenant_id})
            WHERE s.updated_at <= datetime() - duration('P90D')
              AND s.support_count < 3
            SET s.state = 'ARCHIVED', s.updated_at = datetime()
            RETURN count(s) AS count
            """,
            tenant_id=tenant_id,
        )
        rec = await result.single()
        demoted += rec["count"]

        # SUPERSEDED -> ARCHIVED: > 90d since superseded
        result = await self._session.run(
            """
            MATCH (s:Strategy {state: 'SUPERSEDED', tenant_id: $tenant_id})
            WHERE s.updated_at <= datetime() - duration('P90D')
            SET s.state = 'ARCHIVED', s.updated_at = datetime()
            RETURN count(s) AS count
            """,
            tenant_id=tenant_id,
        )
        rec = await result.single()
        demoted += rec["count"]

        return {"promoted": promoted, "demoted": demoted}

    async def deduplicate(self, tenant_id: str) -> list[dict]:
        result = await self._session.run(DEDUP_CYPHER, tenant_id=tenant_id)
        duplicates = [r.data() async for r in result]
        for dup in duplicates:
            # Fase 1: SUPPORTED_BY is the only relationship type attached to
            # Strategy nodes. Dynamic rel-type redirection (arbitrary edges) is
            # handled by the Knowledge Librarian in Phase 2.
            await self._session.run(
                """
                MATCH (keep:Strategy {id: $keep_id}), (merge:Strategy {id: $merge_id})
                MATCH (merge)<-[:SUPPORTED_BY]-(l:Lesson)
                MERGE (keep)<-[:SUPPORTED_BY]-(l)
                WITH keep, merge
                DETACH DELETE merge
                """,
                keep_id=dup["keep_id"],
                merge_id=dup["merge_id"],
            )
        return duplicates

    async def process_experimental_candidates(self, tenant_id: str) -> list[Strategy]:
        """Promote EXPERIMENTAL -> ACTIVE if criteria met (INV-002).

        Returns the promoted strategies already in ACTIVE state.
        """
        result = await self._session.run(
            """
            MATCH (s:Strategy {state: 'EXPERIMENTAL', tenant_id: $tenant_id})
            WHERE s.support_count >= 3 AND s.success_rate >= 0.6
            SET s.state = 'ACTIVE', s.updated_at = datetime()
            RETURN s {.*} AS s
            """,
            tenant_id=tenant_id,
        )
        return [Strategy(**r["s"]) async for r in result]
