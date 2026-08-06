import asyncio

import typer

from mi_dream.cli.repl import REPL
from mi_dream.cli.session import SessionManager
from mi_dream.config import settings

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
