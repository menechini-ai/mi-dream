import asyncio
from pathlib import Path
from uuid import uuid4

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

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
    render_health,
    render_message,
    render_skills,
    render_status,
)
from mi_dream.cli.session import SessionManager, new_session_id
from mi_dream.config import settings
from mi_dream.health import check_all
from mi_dream.knowledge.repository import StrategyRepository
from mi_dream.knowledge.router import ExecutionContext, StrategyRouter
from mi_dream.llm.client import ask_llm_full
from mi_dream.memory.connection import get_driver

HISTORY_PATH = str(Path.cwd() / ".midream" / "history")


def build_system_prompt(context: ExecutionContext) -> str:
    base = "You are a helpful assistant."
    if not context.strategies:
        return base
    lines = [base, "", "Relevant knowledge strategies:"]
    for s in context.strategies:
        lines.append(f"- [{s.title}] ({s.domain}): {s.description}")
    return "\n".join(lines)


async def recall_context(goal: str) -> ExecutionContext:
    try:
        async with get_driver().session(database=settings.neo4j_database) as session:
            router = StrategyRouter(StrategyRepository(session))
            return await router.retrieve(goal, {"domain": "general"}, settings.tenant_id)
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
        self._setup_bindings()

    def _setup_bindings(self) -> None:
        @self._bindings.add("c-c")
        def _(event):
            if event.app.current_buffer.text.strip():
                event.app.current_buffer.reset()
            else:
                self._running = False
                event.app.exit()

    async def _run_with_skill(self, skill: dict, user_input: str) -> None:
        system_prompt = skill["prompt"]
        self._session_mgr.add_message("user", user_input)

        with console.status(f"[bold cyan]Skill: {skill['name']}...", spinner="dots"):
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ask_llm_full(
                    system=system_prompt,
                    user_message=user_input,
                    max_tokens=1024,
                    history=[{"role": m["role"], "content": m["content"]} for m in self._session_mgr.current().context],
                ),
            )
        assistant_msg = resp.content
        self._session_mgr.add_message("assistant", assistant_msg)
        render_message("assistant", assistant_msg)
        render_status(settings.llm_model, resp.total_tokens, format_latency(resp.latency_ms))

    async def _run_with_agent(self, agent: dict, user_input: str) -> None:
        system_prompt = agent["prompt"]
        self._session_mgr.add_message("user", user_input)

        with console.status(f"[bold cyan]Agent: {agent['name']}...", spinner="dots"):
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ask_llm_full(
                    system=system_prompt,
                    user_message=user_input,
                    max_tokens=1024,
                    history=[{"role": m["role"], "content": m["content"]} for m in self._session_mgr.current().context],
                ),
            )
        assistant_msg = resp.content
        self._session_mgr.add_message("assistant", assistant_msg)
        render_message("assistant", assistant_msg)
        render_status(settings.llm_model, resp.total_tokens, format_latency(resp.latency_ms))

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
        sess = self._session_mgr.create(new_session_id())
        console.print(f"[dim]Session {sess.name}[/dim] — retomar depois com /session {sess.name}")
        console.print("[dim]Type /help for commands, Ctrl+C to exit[/dim]\n")

        cron_mgr = CronManager()

        while self._running:
            try:
                for job in cron_mgr.due_jobs():
                    if job.script:
                        output = cron_mgr.run_script(job.script)
                        console.print(f"[dim][cron] Script: {job.script} — {output[:100] or '(silent)'}[/dim]")
                    else:
                        console.print(f"[dim][cron] Running: {job.prompt[:60]}...[/dim]")
                        with console.status(f"[bold cyan]Cron: {job.id}...", spinner="dots"):
                            resp = await asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda: ask_llm_full(system="You are a learning agent. Execute the task.", user_message=job.prompt, max_tokens=1024, history=[]),
                            )
                        console.print(f"[dim][cron] Done: {job.id} ({resp.total_tokens} tokens)[/dim]")
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
                        user_chars = sum(
                            len(m["content"]) for m in msgs if m["role"] == "user"
                        )
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
                    elif cmd in COMMANDS:
                        if cmd == "cron" and args.startswith("add "):
                            cron_mgr = CronManager()
                            parsed = cron_mgr.parse_chat(f"/cron {args}")
                            if parsed:
                                interval, prompt, script = parsed
                                job = cron_mgr.add(interval, prompt, script=script)
                                mode = f"script={script}" if script else "agent"
                                console.print(f"[green]Cron job scheduled:[/green] [{job.id}] every {interval} ({mode}) — \"{job.prompt[:50]}...\"")
                            else:
                                console.print("[red]Usage:[/red] /cron add <interval> \"<prompt>\"\n  /cron add <interval> --no-agent --script <file.sh>\nExample: /cron add 1h \"busque sobre SRE\"")
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

                with console.status("[bold cyan]Thinking...", spinner="dots"):
                    resp = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: ask_llm_full(
                            system=system_prompt,
                            user_message=user_input,
                            max_tokens=1024,
                            history=history,
                        ),
                    )
                assistant_msg = resp.content

                self._session_mgr.add_message("assistant", assistant_msg)
                render_message("assistant", assistant_msg)
                render_status(
                    settings.llm_model, resp.total_tokens, format_latency(resp.latency_ms)
                )

                try:
                    await save_reasoning_trace(
                        trace_id=f"cli-{uuid4().hex}",
                        content=f"Q: {user_input}\nA: {assistant_msg}",
                        metadata={"tenant_id": settings.tenant_id, "outcome": "success"},
                        driver=get_driver(),
                    )
                except Exception:
                    pass

            except KeyboardInterrupt:
                continue
            except SystemExit:
                break
            except Exception as e:
                render_error(str(e))

        self._session_mgr.save()
        sess = self._session_mgr.current()
        console.print(f"\n[bold]Session {sess.name} saved. Goodbye![/bold]")
