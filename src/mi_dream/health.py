"""Health checks for Neo4j and LLM provider."""

from __future__ import annotations

import time
from dataclasses import dataclass

from mi_dream.config import settings
from mi_dream.memory.connection import get_driver


@dataclass
class HealthResult:
    name: str
    status: str  # ok | error | warning
    detail: str = ""
    latency_ms: float = 0.0


async def check_neo4j() -> HealthResult:
    start = time.monotonic()
    try:
        driver = get_driver()
        async with driver.session(database=settings.neo4j_database) as session:
            result = await session.run("RETURN 1 AS n")
            record = await result.single()
            assert record["n"] == 1
        latency = (time.monotonic() - start) * 1000
        return HealthResult(
            name="neo4j",
            status="ok",
            detail=f"{settings.neo4j_uri} ({settings.neo4j_database})",
            latency_ms=round(latency, 1),
        )
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return HealthResult(
            name="neo4j",
            status="error",
            detail=str(e),
            latency_ms=round(latency, 1),
        )


async def check_llm_provider() -> HealthResult:
    start = time.monotonic()
    if not settings.llm_api_key:
        return HealthResult(
            name="llm_provider",
            status="warning",
            detail="LLM_API_KEY not configured",
        )
    try:
        from mi_dream.llm.client import get_client

        client = get_client()
        client.chat.completions.create(
            model=settings.llm_model,
            max_tokens=5,
            messages=[{"role": "user", "content": "ping"}],
        )
        latency = (time.monotonic() - start) * 1000
        return HealthResult(
            name="llm_provider",
            status="ok",
            detail=f"{settings.llm_provider} / {settings.llm_model} @ {settings.llm_base_url}",
            latency_ms=round(latency, 1),
        )
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return HealthResult(
            name="llm_provider",
            status="error",
            detail=str(e),
            latency_ms=round(latency, 1),
        )


async def check_all() -> list[HealthResult]:
    return [await check_neo4j(), await check_llm_provider()]
