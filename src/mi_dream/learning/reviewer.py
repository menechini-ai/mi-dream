import asyncio
import json
from datetime import date

from mi_dream.config import settings
from mi_dream.knowledge.curator import Curator
from mi_dream.llm.client import ask_llm_full
from mi_dream.memory.connection import get_driver

REVIEW_SYSTEM_PROMPT = """\
You are a daily review agent for a learning system. Given today's production
stats and any integrity violations, write a concise 2-3 sentence narrative in
Portuguese summarizing the day: what was learned, whether the learning pipeline
is healthy, and any risks to flag. Be direct and factual.
"""


class DailyReviewer:
    """Revisão diária (SDD §22): stats de produção + integridade + resumo LLM.

    Os stats e health checks são coletados via Cypher parametrizado; o resumo
    narrativo é opcional (``use_llm``); o relatório é persistido de forma
    idempotente por dia em ``(:DailyReview {date, tenant_id})``.
    """

    def __init__(self, session, use_llm: bool = True):
        self._session = session
        self._use_llm = use_llm

    async def _count(self, cypher: str, **params) -> int:
        result = await self._session.run(cypher, **params)
        record = await result.single()
        return int(record["count"]) if record else 0

    async def collect_stats(self, tenant_id: str) -> dict:
        today = (
            "MATCH (n:ReasoningTrace {tenant_id: $tenant_id}) "
            "WHERE date(n.created_at) = date() RETURN count(*) AS count"
        )
        counts: dict[str, int] = {}
        queries = {
            "traces_today": (today, {}),
            "episodes_today": (today.replace("ReasoningTrace", "Episode"), {}),
            "lessons_today": (today.replace("ReasoningTrace", "Lesson"), {}),
            "strategies_total": (
                "MATCH (s:Strategy {tenant_id: $tenant_id}) RETURN count(*) AS count",
                {},
            ),
            "strategies_experimental": (
                "MATCH (s:Strategy {tenant_id: $tenant_id, state: $state}) "
                "RETURN count(*) AS count",
                {"state": "EXPERIMENTAL"},
            ),
            "strategies_active": (
                "MATCH (s:Strategy {tenant_id: $tenant_id, state: $state}) "
                "RETURN count(*) AS count",
                {"state": "ACTIVE"},
            ),
            "strategies_stale": (
                "MATCH (s:Strategy {tenant_id: $tenant_id, state: $state}) "
                "RETURN count(*) AS count",
                {"state": "STALE"},
            ),
            "strategies_archived": (
                "MATCH (s:Strategy {tenant_id: $tenant_id, state: $state}) "
                "RETURN count(*) AS count",
                {"state": "ARCHIVED"},
            ),
            "strategies_superseded": (
                "MATCH (s:Strategy {tenant_id: $tenant_id, state: $state}) "
                "RETURN count(*) AS count",
                {"state": "SUPERSEDED"},
            ),
            "promoted_today": (
                "MATCH (s:Strategy {tenant_id: $tenant_id, state: $state}) "
                "WHERE date(s.updated_at) = date() RETURN count(*) AS count",
                {"state": "ACTIVE"},
            ),
            "unprocessed_traces": (
                "MATCH (t:ReasoningTrace {tenant_id: $tenant_id}) "
                "WHERE NOT EXISTS { (:Lesson)-[:DERIVED_FROM]->(t) } "
                "RETURN count(*) AS count",
                {},
            ),
            "pending_lessons": (
                "MATCH (l:Lesson {tenant_id: $tenant_id}) "
                "WHERE NOT EXISTS { (l)-[:SUPPORTED_BY]->(:Strategy) } "
                "RETURN count(*) AS count",
                {},
            ),
            "promotion_candidates": (
                "MATCH (s:Strategy {tenant_id: $tenant_id, state: $state}) "
                "WHERE s.support_count >= 3 AND s.success_rate >= 0.6 "
                "RETURN count(*) AS count",
                {"state": "EXPERIMENTAL"},
            ),
        }
        for key, (cypher, params) in queries.items():
            counts[key] = await self._count(cypher, tenant_id=tenant_id, **params)
        return counts

    async def review(self, tenant_id: str | None = None) -> dict:
        tenant_id = tenant_id or settings.tenant_id
        stats = await self.collect_stats(tenant_id)
        curator = Curator(self._session)
        violations = await curator.run_integrity_checks(tenant_id)
        health = {
            "ok": len(violations) == 0,
            "unprocessed_traces": stats["unprocessed_traces"],
            "pending_lessons": stats["pending_lessons"],
            "promotion_candidates": stats["promotion_candidates"],
        }
        summary = ""
        if self._use_llm:
            summary = await self._summarize(stats, violations)
        report = {
            "date": date.today().isoformat(),
            "tenant_id": tenant_id,
            "stats": stats,
            "health": health,
            "integrity_violations": violations,
            "summary": summary,
        }
        await self._persist(report, tenant_id)
        return report

    async def _summarize(self, stats: dict, violations: list[dict]) -> str:
        try:
            payload = json.dumps(
                {"stats": stats, "violations": violations}, ensure_ascii=False
            )
            resp = await asyncio.to_thread(
                ask_llm_full,
                REVIEW_SYSTEM_PROMPT,
                f"Daily data:\n{payload}",
                max_tokens=300,
            )
            return resp.content
        except Exception:
            return ""

    async def _persist(self, report: dict, tenant_id: str) -> None:
        await self._session.run(
            """
            MERGE (r:DailyReview {tenant_id: $tenant_id, date: $date})
            SET r.report = $report, r.created_at = datetime()
            """,
            tenant_id=tenant_id,
            date=report["date"],
            report=json.dumps(report, ensure_ascii=False),
        )


async def run_daily_review(tenant_id: str | None = None) -> dict:
    tenant_id = tenant_id or settings.tenant_id
    async with get_driver().session(database=settings.neo4j_database) as session:
        reviewer = DailyReviewer(session)
        return await reviewer.review(tenant_id)


async def reviewed_dates(tenant_id: str | None = None) -> set[str]:
    tenant_id = tenant_id or settings.tenant_id
    dates: set[str] = set()
    async with get_driver().session(database=settings.neo4j_database) as session:
        result = await session.run(
            "MATCH (r:DailyReview {tenant_id: $tenant_id}) RETURN r.date AS date",
            tenant_id=tenant_id,
        )
        async for rec in result:
            if rec["date"]:
                dates.add(rec["date"])
    return dates


def daily_review_due(now_hour: int, reviewed_dates: set[str], today: str) -> bool:
    return now_hour >= settings.daily_review_hour and today not in reviewed_dates
