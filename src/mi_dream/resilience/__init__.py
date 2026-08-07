"""Schema migration for claim/lease (idempotency) on ReasoningTrace."""

from __future__ import annotations

CLAIM_PROPERTIES_CYPHER = """
MATCH (t:ReasoningTrace)
WHERE t.processing_status IS NULL
SET t.processing_status = "PENDING",
    t.attempt_count = 0
RETURN count(t) AS migrated
"""

CLAIM_INDEX_CYPHER = """
CREATE INDEX trace_claim_status IF NOT EXISTS
FOR (t:ReasoningTrace) ON (t.processing_status)
"""


async def migrate_claim_schema() -> int:
    from mi_dream.config import settings
    from mi_dream.memory.connection import get_driver

    driver = get_driver()
    migrated = 0
    async with driver.session(database=settings.neo4j_database) as session:
        result = await session.run(CLAIM_PROPERTIES_CYPHER)
        rec = await result.single()
        migrated = rec["migrated"] if rec else 0

        for stmt in CLAIM_INDEX_CYPHER.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await session.run(stmt)
    return migrated
