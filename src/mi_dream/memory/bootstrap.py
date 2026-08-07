from mi_dream.config import settings
from mi_dream.memory.connection import get_driver

_bootstrapped = False


def _schema_cypher() -> str:
    """Constraints + vector indexes, dimensions sourced from settings."""
    dims = settings.embedding_dimensions
    return f"""
CREATE CONSTRAINT strategy_id IF NOT EXISTS
FOR (s:Strategy) REQUIRE s.id IS UNIQUE;

CREATE CONSTRAINT lesson_id IF NOT EXISTS
FOR (l:Lesson) REQUIRE l.id IS UNIQUE;

CREATE CONSTRAINT episode_id IF NOT EXISTS
FOR (e:Episode) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT trace_id IF NOT EXISTS
FOR (t:ReasoningTrace) REQUIRE t.id IS UNIQUE;

CREATE CONSTRAINT daily_review_date IF NOT EXISTS
FOR (r:DailyReview) REQUIRE (r.tenant_id, r.date) IS UNIQUE;

CREATE VECTOR INDEX strategy_embedding IF NOT EXISTS
FOR (s:Strategy) ON (s.embedding)
OPTIONS {{indexConfig: {{`vector.dimensions`: {dims}, `vector.similarity_function`: 'cosine'}}}};

CREATE VECTOR INDEX episode_embedding IF NOT EXISTS
FOR (e:Episode) ON (e.embedding)
OPTIONS {{indexConfig: {{`vector.dimensions`: {dims}, `vector.similarity_function`: 'cosine'}}}};
"""


async def bootstrap_schema() -> None:
    driver = get_driver()
    async with driver.session(database=settings.neo4j_database) as session:
        for stmt in _schema_cypher().strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await session.run(stmt)


async def ensure_schema() -> None:
    """Idempotent, lazily-cached schema bootstrap.

    Runs constraints + vector indexes automatically once per process; retries
    on failure so a later call succeeds once Neo4j is reachable.
    """
    global _bootstrapped
    if _bootstrapped:
        return
    await bootstrap_schema()
    _bootstrapped = True
