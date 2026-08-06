import asyncio
from pathlib import Path
from uuid import uuid4

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from mi_dream.agents.tools import save_reasoning_trace
from mi_dream.cli.commands import COMMANDS, dispatch
from mi_dream.cli.completer import SlashCompleter
from mi_dream.cli.renderer import (
    console,
    render_agents,
    render_commands,
    render_error,
    render_health,
    render_help,
    render_message,
    render_skills,
    render_status,
)
from mi_dream.cli.session import SessionManager, new_session_id
from mi_dream.config import settings
from mi_dream.health import check_all
from mi_dream.knowledge.repository import StrategyRepository
from mi_dream.knowledge.router import ExecutionContext, StrategyRouter
from mi_dream.llm.client import ask_llm
from mi_dream.memory.connection import get_driver

HISTORY_PATH = str(Path.home() / ".mi-dream" / "history")


def build_system_prompt(context: ExecutionContext) -> str:
    """Compose the assistant system prompt from the Execution Context contract (SDD §6)."""
    base = "You are a helpful assistant."
    if not context.strategies:
        return base
    lines = [base, "", "Relevant knowledge strategies:"]
    for s in context.strategies:
        lines.append(f"- [{s.title}] ({s.domain}): {s.description}")
    return "\n".join(lines)


async def recall_context(goal: str) -> ExecutionContext:
    """Retrieve the Execution Context via the Strategy Router.

    Graceful degradation (SDD §13): any Router/Neo4j failure yields an empty
    context — planning continues from scratch, never blocked.
    """
    try:
        async with get_driver().session(database=settings.neo4j_database) as session:
            router = StrategyRouter(StrategyRepository(session))
            return await router.retrieve(goal, {"domain": "general"}, settings.tenant_id)
    except Exception:
        return ExecutionContext(goal=goal)


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

    async def run(self) -> None:
        try:
            from mi_dream.memory.bootstrap import ensure_schema

            await ensure_schema()
        except Exception:
            pass

        prompt_session = PromptSession(
            history=FileHistory(HISTORY_PATH),
            completer=self._completer,
            complete_while_typing=True,
            key_bindings=self._bindings,
            multiline=False,
        )
        console.print("[bold cyan]mi-dream[/bold cyan] — Multi-Agent Learning System")
        sess = self._session_mgr.create(new_session_id())
        console.print(f"[dim]Session {sess.name}[/dim] — retomar depois com /session {sess.name}")
        console.print("[dim]Type /help for commands, Ctrl+C to exit[/dim]\n")

        while self._running:
            try:
                user_input = await prompt_session.prompt_async("\n> ")
                if not user_input.strip():
                    continue

                if user_input.startswith("/"):
                    parts = user_input[1:].split(" ", 1)
                    cmd = parts[0]
                    args = parts[1] if len(parts) > 1 else ""

                    if cmd == "exit":
                        break
                    elif cmd == "status":
                        results = await check_all()
                        render_health(results)
                    elif cmd == "skills":
                        skills = [{"name": "brainstorming", "desc": "Design exploration"}]
                        render_skills(skills)
                    elif cmd == "agents":
                        agents = [{"name": "Research", "desc": "Codebase exploration"}]
                        render_agents(agents)
                    elif cmd == "commands":
                        render_commands(COMMANDS)
                    elif cmd == "help":
                        render_help()
                    elif cmd == "session":
                        name = args.strip()
                        if name:
                            sess = self._session_mgr.resume(name)
                            console.print(
                                f"[cyan]Session {sess.name} resumed"
                                f" ({len(sess.context)} messages).[/cyan]"
                            )
                        else:
                            sess = self._session_mgr.create(new_session_id())
                            console.print(
                                f"[cyan]Started new session {sess.name}.[/cyan]"
                            )
                    elif cmd == "clear":
                        self._session_mgr.clear_context()
                        console.print("[cyan]Context cleared.[/cyan]")
                    else:
                        console.print(dispatch(cmd, args))
                    continue

                # Regular input → agent loop
                self._session_mgr.add_message("user", user_input)

                # Execution Context: recall strategies before planning (graceful degradation)
                context = await recall_context(user_input)
                system_prompt = build_system_prompt(context)

                with console.status("[bold cyan]Thinking...", spinner="dots"):
                    assistant_msg = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: ask_llm(
                            system=system_prompt,
                            user_message=user_input,
                            max_tokens=1024,
                        ),
                    )

                self._session_mgr.add_message("assistant", assistant_msg)
                render_message("assistant", assistant_msg)
                render_status(settings.llm_model, 0, "—")

                # Persist a PII-sanitized reasoning trace (SDD §18.2); never block chat on failure
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
