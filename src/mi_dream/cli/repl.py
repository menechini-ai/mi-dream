import asyncio
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from mi_dream.agents.loop import run_tool_loop
from mi_dream.agents.toolbox import build_chat_toolbox
from mi_dream.agents.tools import save_reasoning_trace
from mi_dream.cli.commands import COMMANDS, dispatch
from mi_dream.cli.completer import SlashCompleter
from mi_dream.cli.cron import CronManager
from mi_dream.cli.loader import load_agents, load_skills
from mi_dream.cli.renderer import (
    console,
    render_agents,
    render_commands,
    render_error,
    render_failure_patterns,
    render_failures,
    render_health,
    render_message,
    render_skills,
    render_status,
)
from mi_dream.cli.session import SessionManager, new_session_id
from mi_dream.config import settings
from mi_dream.health import check_all
from mi_dream.knowledge.failure_patterns import FailurePatternRepository
from mi_dream.knowledge.repository import StrategyRepository
from mi_dream.knowledge.router import ExecutionContext, StrategyRouter
from mi_dream.knowledge.vector import StrategyVectorRetriever
from mi_dream.learning.compactor import ConversationCompactor
from mi_dream.learning.failure_analyzer import get_failure_patterns, get_failures
from mi_dream.learning.reviewer import (
    daily_review_due,
    reviewed_dates,
    run_daily_review,
)
from mi_dream.learning.scheduler import run_learning_cycle
from mi_dream.llm.client import ask_llm_full, extract_llm_error
from mi_dream.memory.connection import get_driver

HISTORY_PATH = str(Path.cwd() / ".midream" / "history")

TOOL_USE_GUIDANCE = (
    "\n\nAvailable functions: web_search(query, count=5) to search the web; "
    "web_fetch(url, max_chars) to read a page; read_file/list_dir/edit_file to "
    "work with project files; exec(command, timeout) to run a shell command if "
    "enabled. Always call functions through the function-calling API — never "
    "emit raw <web_search> or <tool_call> tags as text. When web_search returns "
    "no results, try a different query or web_fetch a likely URL. Answer in the "
    "user's language once you have enough information."
)


def build_system_prompt(context: ExecutionContext) -> str:
    base = "You are a helpful assistant."
    lines = [base]
    if context.strategies:
        lines.append("")
        lines.append("Relevant knowledge strategies:")
        for s in context.strategies:
            lines.append(f"- [{s.title}] ({s.domain}): {s.description}")
    if context.previous_failures:
        lines.append("")
        lines.append("Known failure patterns:")
        for f in context.previous_failures[-5:]:
            count = f.get("failure_count", 0)
            lines.append(
                f"- [{f.get('error_type', 'unknown')} x{count}] {(f.get('pattern') or '')[:200]}"
            )
    if context.recent_traces:
        lines.append("")
        lines.append("Recent conversation history:")
        for t in context.recent_traces[-10:]:
            lines.append(f"- {(t.get('content') or '')[:400]}")
    if context.episodes:
        lines.append("")
        lines.append("Prior session summaries:")
        for e in context.episodes[-5:]:
            lines.append(f"- {(e.get('summary') or '')[:400]}")
    return "\n".join(lines)


async def _recent_traces(session, tenant_id: str, limit: int = 20) -> list[dict]:
    try:
        result = await session.run(
            """
            MATCH (t:ReasoningTrace {tenant_id: $tenant_id})
            RETURN t {.*} AS trace
            ORDER BY t.created_at DESC
            LIMIT $limit
            """,
            tenant_id=tenant_id,
            limit=limit,
        )
        return [rec["trace"] async for rec in result]
    except Exception:
        return []


async def _recent_episodes(session, tenant_id: str, limit: int = 5) -> list[dict]:
    try:
        result = await session.run(
            """
            MATCH (e:Episode {tenant_id: $tenant_id})
            RETURN e {.*} AS episode
            ORDER BY e.created_at DESC
            LIMIT $limit
            """,
            tenant_id=tenant_id,
            limit=limit,
        )
        return [rec["episode"] async for rec in result]
    except Exception:
        return []


async def recall_context(goal: str) -> ExecutionContext:
    try:
        async with get_driver().session(database=settings.neo4j_database) as session:
            router = StrategyRouter(
                StrategyRepository(session),
                vector_retriever=StrategyVectorRetriever(top_k=settings.vector_top_k),
                top_k=settings.vector_top_k,
                failure_repo=FailurePatternRepository(session),
            )
            context = await router.retrieve(goal, {"domain": "general"}, settings.tenant_id)
            context.recent_traces = await _recent_traces(session, settings.tenant_id)
            context.episodes = await _recent_episodes(session, settings.tenant_id)
            return context
    except Exception:
        return ExecutionContext(goal=goal)


def format_latency(latency_ms: float) -> str:
    """Human-readable latency, e.g. ``1.2s`` or ``340ms``."""
    if latency_ms >= 1000:
        return f"{latency_ms / 1000:.1f}s"
    return f"{latency_ms:.0f}ms"


class REPL:
    def __init__(self, session_mgr: SessionManager):
        self._session_mgr = session_mgr
        self._completer = SlashCompleter()
        self._running = True
        self._bindings = KeyBindings()
        self._traces_since_learn = 0
        self._reviewed_dates: set[str] = set()
        self._toolbox = build_chat_toolbox()
        self._setup_bindings()

    def _setup_bindings(self) -> None:
        @self._bindings.add("c-c")
        def _(event):
            if event.app.current_buffer.text.strip():
                event.app.current_buffer.reset()
            else:
                self._running = False
                event.app.exit()

    async def _ask_llm(self, system: str, user: str, history: list[dict]):
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: ask_llm_full(
                system=system,
                user_message=user,
                max_tokens=settings.llm_max_tokens,
                history=history,
            ),
        )

    async def _ask_with_tools(self, system: str, user: str, history: list[dict]):
        return await run_tool_loop(
            system + TOOL_USE_GUIDANCE,
            user,
            history,
            toolbox=self._toolbox,
            max_iterations=settings.agent_max_iterations,
            max_tokens=settings.llm_max_tokens,
        )

    async def _trace_outcome(
        self,
        source: str,
        name: str,
        content: str,
        outcome: str,
        error_type: str | None = None,
        error_message: str | None = None,
        tokens: int = 0,
        latency_ms: float = 0.0,
    ) -> None:
        """Persist a ReasoningTrace with real outcome (SDD §23); never raises."""
        try:
            metadata = {
                "tenant_id": settings.tenant_id,
                "outcome": outcome,
                "source": source,
                "name": name,
                "error_type": error_type,
                "error_message": error_message,
                "tokens": tokens,
                "latency_ms": round(latency_ms, 1),
            }
            await save_reasoning_trace(
                trace_id=f"cli-{uuid4().hex}",
                content=content,
                metadata=metadata,
                driver=get_driver(),
            )
            self._traces_since_learn += 1
        except Exception:
            pass

    async def _run_prompt(self, label: str, name: str, system_prompt: str, user_input: str) -> None:
        self._session_mgr.add_message("user", user_input)
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in self._session_mgr.current().context[:-1]
        ]
        try:
            with console.status(f"[bold cyan]{label}: {name}...", spinner="dots"):
                resp = await self._ask_llm(system_prompt, user_input, history)
            assistant_msg = resp.content
            self._session_mgr.add_message("assistant", assistant_msg)
            render_message("assistant", assistant_msg)
            render_status(settings.llm_model, resp.total_tokens, format_latency(resp.latency_ms))
            await self._trace_outcome(
                label.lower(),
                name,
                f"Q: {user_input}\nA: {assistant_msg}",
                "success",
                tokens=resp.total_tokens,
                latency_ms=resp.latency_ms,
            )
        except Exception as e:
            error_type, error_message = extract_llm_error(e)
            render_error(f"{error_message} ({error_type})")
            await self._trace_outcome(
                label.lower(),
                name,
                f"Q: {user_input}\nA: [ERROR: {error_message}]",
                "failure",
                error_type=error_type,
                error_message=error_message,
            )

    async def _run_with_skill(self, skill: dict, user_input: str) -> None:
        await self._run_prompt("Skill", skill["name"], skill["prompt"], user_input)

    async def _run_with_agent(self, agent: dict, user_input: str) -> None:
        await self._run_prompt("Agent", agent["name"], agent["prompt"], user_input)

    async def _handle_session_command(self, args: str) -> None:
        name = args.strip() or "default"
        self._session_mgr.resume(name)
        console.print(f"[green]Session: {name}[/green]")

    async def _handle_compact(self) -> None:
        sess = self._session_mgr.current()
        if not sess.context:
            console.print("[dim]Nothing to compact.[/dim]")
            return
        compactor = ConversationCompactor()
        compacted = await compactor.compact(sess.context)
        if compacted == sess.context:
            console.print("[dim]Context under threshold; nothing compacted.[/dim]")
            return
        summary = compacted[0]["content"]
        sess.context = compacted
        try:
            episode_id = await compactor.persist_episode(summary, sess.name)
            console.print(f"[green]Compacted → Episode {episode_id}[/green]")
        except Exception as e:
            console.print(f"[yellow]Episode persist failed (graceful): {e}[/yellow]")

    async def _handle_learn(self) -> None:
        with console.status("[bold cyan]Learning cycle...", spinner="dots"):
            report = await run_learning_cycle()
        console.print(f"[green]Learn: {report}[/green]")

    async def _run_learning_cycle_safe(self) -> None:
        try:
            await run_learning_cycle()
        except Exception:
            pass

    async def _maybe_auto_learn(self) -> None:
        """Disparo por contexto (SDD §20.2): aprende a cada N traces."""
        if self._traces_since_learn >= settings.learn_trace_threshold:
            self._traces_since_learn = 0
            await self._run_learning_cycle_safe()

    async def _maybe_auto_compact(self) -> None:
        """Auto-compactação (SDD §20.5): contexto >= threshold → compacta e aprende."""
        sess = self._session_mgr.current()
        size = sum(len(m.get("content", "")) for m in sess.context)
        if size < settings.compact_threshold_chars:
            return
        compactor = ConversationCompactor()
        compacted = await compactor.compact(sess.context)
        if compacted == sess.context:
            return
        summary = compacted[0]["content"]
        sess.context = compacted
        try:
            await compactor.persist_episode(summary, sess.name)
        except Exception:
            pass
        self._traces_since_learn = 0
        await self._run_learning_cycle_safe()

    async def _handle_review(self) -> None:
        with console.status("[bold cyan]Daily review...", spinner="dots"):
            report = await run_daily_review()
        console.print(f"[green]Daily review:[/green] {report}")
        self._reviewed_dates.add(date.today().isoformat())

    async def _handle_failures(self, args: str) -> None:
        error_type = args.strip() or None
        try:
            failures = await get_failures(settings.tenant_id, limit=20, error_type=error_type)
        except Exception as e:
            render_error(str(e))
            return
        if not failures:
            console.print("[dim]No failures recorded.[/dim]")
            return
        render_failures(failures)

    async def _handle_patterns(self, args: str) -> None:
        error_type = args.strip() or None
        try:
            patterns = await get_failure_patterns(
                settings.tenant_id, limit=20, error_type=error_type
            )
        except Exception as e:
            render_error(str(e))
            return
        if not patterns:
            console.print("[dim]No failure patterns recorded.[/dim]")
            return
        render_failure_patterns(patterns)

    async def _daily_review(self) -> None:
        """Hora fixa + catch-up (SDD §22.4): revisa se já passou da hora e o dia
        ainda não foi revisado; depois checa a cada 60 min."""
        while self._running:
            try:
                self._reviewed_dates = await reviewed_dates()
                today = date.today().isoformat()
                if daily_review_due(datetime.now().hour, self._reviewed_dates, today):
                    await self._handle_review()
            except Exception:
                pass
            await asyncio.sleep(3600)

    async def _auto_learn(self) -> None:
        while self._running:
            await asyncio.sleep(settings.refl_interval_minutes * 60)
            try:
                await run_learning_cycle()
            except Exception:
                pass

    async def run(self) -> None:
        try:
            from mi_dream.memory.bootstrap import ensure_schema

            await ensure_schema()
        except Exception:
            pass

        Path(HISTORY_PATH).parent.mkdir(parents=True, exist_ok=True)
        prompt_session = PromptSession(
            history=FileHistory(HISTORY_PATH),
            completer=self._completer,
            complete_while_typing=True,
            key_bindings=self._bindings,
            multiline=False,
        )
        console.print(f"[bold cyan]mi-dream[/bold cyan] — Model: {settings.llm_model}")
        sess = self._session_mgr.current()
        if sess.name == "default" and not sess.context:
            saved = self._session_mgr.list_sessions()
            if saved:
                sess = self._session_mgr.resume(saved[-1])
                console.print(
                    f"[dim]Session {sess.name} resumed ({len(sess.context)} messages)[/dim]"
                )
            else:
                sess = self._session_mgr.create(new_session_id())
                console.print(
                    f"[dim]Session {sess.name}[/dim] — retomar depois com /session {sess.name}"
                )
        else:
            console.print(f"[dim]Session {sess.name} resumed ({len(sess.context)} messages)[/dim]")
        console.print("[dim]Type /help for commands, Ctrl+C to exit[/dim]\n")

        cron_mgr = CronManager()
        self._traces_since_learn = 0
        self._auto_learn_task = asyncio.create_task(self._auto_learn())
        self._daily_review_task = asyncio.create_task(self._daily_review())

        while self._running:
            try:
                for job in cron_mgr.due_jobs():
                    if job.script:
                        output = cron_mgr.run_script(job.script)
                        console.print(
                            f"[dim][cron] Script: {job.script} — {output[:100] or '(silent)'}[/dim]"
                        )
                    else:
                        console.print(f"[dim][cron] Running: {job.prompt[:60]}...[/dim]")
                        try:
                            with console.status(f"[bold cyan]Cron: {job.id}...", spinner="dots"):
                                resp = await self._ask_llm(
                                    "You are a learning agent. Execute the task.",
                                    job.prompt,
                                    [],
                                )
                            console.print(
                                f"[dim][cron] Done: {job.id} ({resp.total_tokens} tokens)[/dim]"
                            )
                            await self._trace_outcome(
                                "cron",
                                job.id,
                                f"Task: {job.prompt}\nA: {resp.content[:2000]}",
                                "success",
                                tokens=resp.total_tokens,
                                latency_ms=resp.latency_ms,
                            )
                        except Exception as e:
                            error_type, error_message = extract_llm_error(e)
                            console.print(f"[dim][cron] Failed: {job.id} ({error_type})[/dim]")
                            await self._trace_outcome(
                                "cron",
                                job.id,
                                f"Task: {job.prompt}\nA: [ERROR: {error_message}]",
                                "failure",
                                error_type=error_type,
                                error_message=error_message,
                            )
                    cron_mgr.mark_run(job.id)

                user_input = await prompt_session.prompt_async("\n❯ ")
                if not user_input.strip():
                    continue

                if user_input.startswith("/"):
                    parts = user_input[1:].split(" ", 1)
                    cmd = parts[0]
                    args = parts[1] if len(parts) > 1 else ""

                    if cmd == "status":
                        results = await check_all()
                        render_health(results)
                    elif cmd == "cost":
                        msgs = self._session_mgr.current().context
                        user_chars = sum(len(m["content"]) for m in msgs if m["role"] == "user")
                        assistant_chars = sum(
                            len(m["content"]) for m in msgs if m["role"] == "assistant"
                        )
                        console.print(
                            f"[bold]Session cost estimate:[/bold]\n"
                            f"  Messages: {len(msgs)}\n"
                            f"  Input tokens (est.): {user_chars // 4}\n"
                            f"  Output tokens (est.): {assistant_chars // 4}\n"
                            f"  Model: {settings.llm_model}"
                        )
                    elif cmd == "session":
                        await self._handle_session_command(args)
                    elif cmd == "clear":
                        self._session_mgr.clear_context()
                        console.print("[green]Context cleared.[/green]")
                    elif cmd == "compact":
                        await self._handle_compact()
                    elif cmd == "learn":
                        await self._handle_learn()
                    elif cmd == "review":
                        await self._handle_review()
                    elif cmd == "failures":
                        await self._handle_failures(args)
                    elif cmd == "patterns":
                        await self._handle_patterns(args)
                    elif cmd in COMMANDS:
                        if cmd == "cron" and args.startswith("add "):
                            cron_mgr = CronManager()
                            parsed = cron_mgr.parse_chat(f"/cron {args}")
                            if parsed:
                                interval, prompt, script = parsed
                                job = cron_mgr.add(interval, prompt, script=script)
                                mode = f"script={script}" if script else "agent"
                                console.print(
                                    f"[green]Cron job scheduled:[/green] [{job.id}] every "
                                    f'{interval} ({mode}) — "{job.prompt[:50]}..."'
                                )
                            else:
                                console.print(
                                    '[red]Usage:[/red] /cron add <interval> "<prompt>"\n'
                                    "  /cron add <interval> --no-agent --script <file.sh>\n"
                                    'Example: /cron add 1h "busque sobre SRE"'
                                )
                        else:
                            result = dispatch(cmd, args)
                            if isinstance(result, list):
                                if cmd == "skills":
                                    render_skills(result)
                                elif cmd == "agents":
                                    render_agents(result)
                                elif cmd == "commands":
                                    render_commands(result)
                            else:
                                console.print(result)
                    else:
                        skill = next((s for s in load_skills() if s["name"] == cmd), None)
                        if skill:
                            await self._run_with_skill(skill, args)
                        else:
                            console.print(
                                f"[red]Unknown: /{cmd}[/red] — Type /help for available commands."
                            )
                    continue

                if user_input.startswith("@"):
                    parts = user_input[1:].split(" ", 1)
                    agent_name = parts[0]
                    agent_args = parts[1] if len(parts) > 1 else ""
                    agent = next((a for a in load_agents() if a["name"] == agent_name), None)
                    if agent:
                        await self._run_with_agent(agent, agent_args)
                    else:
                        console.print(
                            f"[red]Unknown agent: @{agent_name}[/red]"
                            " — Type /agents to list available agents."
                        )
                    continue

                # Regular input → agent loop
                self._session_mgr.add_message("user", user_input)

                context = await recall_context(user_input)
                system_prompt = build_system_prompt(context)

                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in self._session_mgr.current().context[:-1]
                ]

                try:
                    with console.status("[bold cyan]Thinking...", spinner="dots"):
                        resp = await self._ask_with_tools(system_prompt, user_input, history)
                    assistant_msg = resp.content

                    self._session_mgr.add_message("assistant", assistant_msg)
                    render_message("assistant", assistant_msg)
                    render_status(
                        settings.llm_model,
                        resp.total_tokens,
                        format_latency(resp.latency_ms),
                    )
                    await self._trace_outcome(
                        "chat",
                        "",
                        f"Q: {user_input}\nA: {assistant_msg}",
                        "success",
                        tokens=resp.total_tokens,
                        latency_ms=resp.latency_ms,
                    )
                except Exception as e:
                    error_type, error_message = extract_llm_error(e)
                    render_error(f"{error_message} ({error_type})")
                    await self._trace_outcome(
                        "chat",
                        "",
                        f"Q: {user_input}\nA: [ERROR: {error_message}]",
                        "failure",
                        error_type=error_type,
                        error_message=error_message,
                    )
                await self._maybe_auto_learn()
                await self._maybe_auto_compact()

            except KeyboardInterrupt:
                continue
            except SystemExit:
                break
            except Exception as e:
                render_error(str(e))

        self._auto_learn_task.cancel()
        self._daily_review_task.cancel()
        if self._traces_since_learn:
            try:
                await run_learning_cycle()
            except Exception:
                pass
        self._session_mgr.save()
        sess = self._session_mgr.current()
        console.print(f"\n[bold]Session {sess.name} saved. Goodbye![/bold]")
