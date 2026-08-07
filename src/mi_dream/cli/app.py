import asyncio

import typer

from mi_dream.cli.repl import REPL
from mi_dream.cli.session import SessionManager
from mi_dream.config import settings
from mi_dream.learning.failure_analyzer import get_failure_patterns, get_failures
from mi_dream.learning.reviewer import (
    daily_review_due,
    reviewed_dates,
    run_daily_review,
)
from mi_dream.learning.scheduler import run_learning_cycle

app = typer.Typer(name="mi-dream", add_completion=False, no_args_is_help=True)


@app.command()
def chat(session: str = typer.Option("default", "--session", "-s", help="Session name")):
    """Start interactive chat session."""
    mgr = SessionManager()
    mgr.resume(session)
    repl = REPL(mgr)
    asyncio.run(repl.run())


@app.command()
def sessions():
    """List saved sessions."""
    mgr = SessionManager()
    for name in mgr.list_sessions():
        typer.echo(f"  {name}")


@app.command()
def init():
    """Bootstrap the Neo4j schema (constraints + vector indexes)."""
    from mi_dream.memory.bootstrap import bootstrap_schema

    async def _run() -> None:
        await bootstrap_schema()

    asyncio.run(_run())
    typer.echo("Schema bootstrapped.")


@app.command()
def reflect():
    """Run one Reflection pipeline cycle (Evaluator -> Reflector -> Lesson)."""
    from mi_dream.learning.scheduler import ReflectionScheduler

    async def _run() -> dict:
        scheduler = ReflectionScheduler()
        return await scheduler.run_cycle()

    result = asyncio.run(_run())
    typer.echo(f"Reflection cycle: {result}")


@app.command()
def distill():
    """Run Knowledge Distiller: pending Lessons -> Experimental Strategies + SUPPORTED_BY."""
    from mi_dream.knowledge.distiller import KnowledgeDistiller
    from mi_dream.memory.connection import get_driver
    from mi_dream.memory.embeddings import build_embedder

    async def _run() -> dict:
        async with get_driver().session(database=settings.neo4j_database) as session:
            distiller = KnowledgeDistiller(session, embedder=build_embedder())
            lessons = await distiller.pending_lessons(settings.tenant_id)
            strategies = await distiller.distill(lessons, settings.tenant_id)
        return {"lessons_processed": len(lessons), "strategies_touched": len(strategies)}

    result = asyncio.run(_run())
    typer.echo(f"Distill: {result}")


@app.command()
def learn(
    once: bool = typer.Option(False, "--once", help="Run a single cycle and exit"),
    interval_minutes: int = typer.Option(
        settings.refl_interval_minutes, "--interval-minutes", "-i"
    ),
):
    """Run the automatic learning pipeline (reflect → distill → curator).

    Daemon loop by default; use --once for a single cycle.
    """

    async def _run() -> None:
        while True:
            report = await run_learning_cycle()
            processed = report.get("reflection", {}).get("traces_processed", 0)
            if processed == 0:
                typer.echo("Learn: nothing to process (no traces in queue)")
            else:
                typer.echo(f"Learn: {report}")
            if once:
                return
            typer.echo(f"Sleeping {interval_minutes}m... (Ctrl+C to stop)")
            await asyncio.sleep(interval_minutes * 60)

    asyncio.run(_run())


@app.command()
def review(
    once: bool = typer.Option(True, "--once/--daemon", help="Run once and exit (default) or loop as daemon"),
):
    """Run the daily review (stats + integrity + LLM summary).

    Default: single run and exit. Use --daemon for continuous loop.
    """
    from datetime import date, datetime

    async def _run() -> None:
        if once:
            today = date.today().isoformat()
            if daily_review_due(
                datetime.now().hour, await reviewed_dates(), today
            ):
                report = await run_daily_review()
                typer.echo(f"Daily review: {report}")
            else:
                typer.echo("Daily review: not due yet (already reviewed today)")
            return
        while True:
            today = date.today().isoformat()
            if daily_review_due(
                datetime.now().hour, await reviewed_dates(), today
            ):
                report = await run_daily_review()
                typer.echo(f"Daily review: {report}")
            typer.echo("Sleeping 1h... (Ctrl+C to stop)")
            await asyncio.sleep(3600)

    asyncio.run(_run())


@app.command()
def failures(
    limit: int = typer.Option(20, "--limit", "-n", help="Max failures to list"),
    error_type: str | None = typer.Option(None, "--type", help="Filter by error type"),
    source: str | None = typer.Option(
        None, "--source", help="Filter by source (chat|skill|agent|cron)"
    ),
):
    """List persisted LLM failures (ReasoningTrace outcome=failure)."""

    async def _run() -> list[dict]:
        return await get_failures(
            settings.tenant_id, limit=limit, error_type=error_type, source=source
        )

    rows = asyncio.run(_run())
    if not rows:
        typer.echo("No failures recorded.")
        return
    for row in rows:
        created = str(row.get("created_at") or "")[:19]
        typer.echo(
            f"[{created}] {row['error_type']} ({row['source']}): "
            f"{row['error_message'][:120]}"
        )


@app.command()
def failure_patterns(
    limit: int = typer.Option(20, "--limit", "-n", help="Max patterns to list"),
    error_type: str | None = typer.Option(None, "--type", help="Filter by error type"),
    domain: str | None = typer.Option(None, "--domain", help="Filter by domain"),
):
    """List aggregated FailurePattern (negative knowledge, SDD §23.7)."""

    async def _run() -> list[dict]:
        return await get_failure_patterns(
            settings.tenant_id,
            limit=limit,
            error_type=error_type,
            domain=domain,
        )

    rows = asyncio.run(_run())
    if not rows:
        typer.echo("No failure patterns recorded.")
        return
    for row in rows:
        last = str(row.get("last_seen") or "")[:19]
        typer.echo(
            f"[{row['error_type']} x{row.get('failure_count', 0)}] "
            f"({row.get('domain', 'general')}) {row.get('pattern', '')[:120]} "
            f"— last {last}"
        )


@app.command()
def curator(
    tenant: str = typer.Option(settings.tenant_id, "--tenant", help="Tenant scope"),
):
    """Run Curator governance: integrity checks, state machine, dedup."""
    from mi_dream.knowledge.curator import Curator
    from mi_dream.memory.connection import get_driver

    async def _run() -> dict:
        async with get_driver().session(database=settings.neo4j_database) as session:
            curator = Curator(session)
            violations = await curator.run_integrity_checks(tenant)
            transitions = await curator.run_state_machine(tenant)
            duplicates = await curator.deduplicate(tenant)
        return {
            "integrity_violations": violations,
            "state_machine": transitions,
            "duplicates": duplicates,
        }

    report = asyncio.run(_run())
    typer.echo(f"Integrity violations: {len(report['integrity_violations'])}")
    for v in report["integrity_violations"]:
        typer.echo(f"  - {v}")
    typer.echo(f"State machine: {report['state_machine']}")
    typer.echo(f"Duplicates merged: {len(report['duplicates'])}")


def main():
    app()
