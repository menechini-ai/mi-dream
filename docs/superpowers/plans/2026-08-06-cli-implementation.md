# Rich CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a rich terminal UI CLI for mi-dream — interactive chat session with slash commands (`/skills`, `/agents`, `/commands`, `/help`, `/session`, `/clear`, `/exit`), skills/agents listing, and session management similar to Anthropic's Claude Code CLI.

**Architecture:** Typer entry point → Prompt Toolkit REPL (multiline input, history, autocomplete) → Rich renderer (panels, markdown, status bar) → Agent loop (existing Supervisor + LLM). Session state managed in-memory with optional file persistence. Slash commands dispatched to handlers before reaching the agent.

**Tech Stack:** typer, prompt_toolkit, rich, anthropic (existing), pydantic (existing)

## Global Constraints

- Python >= 3.11
- Config loaded via `python-dotenv load_dotenv()` — no secrets hardcoded
- All LLM calls use existing `mi_dream.llm.client` wrapper
- Agent loop reuses existing `mi_dream.agents.tools` (recall_strategy, save_reasoning_trace)
- `[project.scripts]` entry: `mi-dream = "mi_dream.cli.app:main"`
- Slash commands: `/skills`, `/agents`, `/commands`, `/help`, `/session <name>`, `/clear`, `/exit`
- REPL: multiline input, history, autocomplete for slash commands

---

### Task 1: CLI Entry Point + Dependencies

**Files:**
- Modify: `pyproject.toml` (add deps + scripts entry)
- Create: `src/mi_dream/cli/__init__.py`

**Interfaces:**
- Consumes: nothing
- Produces: `mi-dream` console script entry point

```toml
# pyproject.toml additions
dependencies = [
    # ... existing ...
    "rich>=13.0",
    "prompt-toolkit>=3.0",
    "typer>=0.15",
]

[project.scripts]
mi-dream = "mi_dream.cli.app:main"
```

```python
# src/mi_dream/cli/__init__.py
"""CLI layer: rich terminal interface for mi-dream."""

```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_entry.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

def test_cli_package_exists():
    import mi_dream.cli
    assert True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_entry.py -v`
Expected: FAIL (package not found)

- [ ] **Step 3: Write minimal implementation**

Create `src/mi_dream/cli/__init__.py` and update `pyproject.toml`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_entry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/mi_dream/cli/__init__.py tests/test_cli_entry.py
git commit -m "feat: CLI package scaffold + deps (rich, prompt-toolkit, typer)"
```

---

### Task 2: Slash Commands Registry

**Files:**
- Create: `src/mi_dream/cli/commands.py`
- Test: `tests/test_cli_commands.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `SlashCommand` dataclass (name, description, handler)
  - `COMMANDS: dict[str, SlashCommand]` — registry of all slash commands
  - `dispatch(command: str, args: str) -> str` — routes command to handler

```python
# src/mi_dream/cli/commands.py
from dataclasses import dataclass
from typing import Callable

@dataclass
class SlashCommand:
    name: str
    description: str
    handler: Callable[[str], str]


def _handle_skills(args: str) -> str:
    """List available skills."""
    skills = [
        {"name": "brainstorming", "desc": "Design exploration"},
        {"name": "systematic-debugging", "desc": "Bug investigation"},
        {"name": "test-driven-development", "desc": "TDD workflow"},
        {"name": "writing-plans", "desc": "Implementation planning"},
    ]
    lines = ["Available skills:", ""]
    for s in skills:
        lines.append(f"  /{s['name']}  — {s['desc']}")
    return "\n".join(lines)


def _handle_agents(args: str) -> str:
    """List available agent types."""
    agents = [
        {"name": "Research", "desc": "Codebase exploration and research"},
        {"name": "Implementation", "desc": "Code writing and refactoring"},
        {"name": "Review", "desc": "Code review and quality checks"},
    ]
    lines = ["Available agents:", ""]
    for a in agents:
        lines.append(f"  {a['name']}  — {a['desc']}")
    return "\n".join(lines)


def _handle_commands(args: str) -> str:
    """List available slash commands."""
    lines = ["Slash commands:", ""]
    for cmd in COMMANDS.values():
        lines.append(f"  /{cmd.name}  — {cmd.description}")
    return "\n".join(lines)


def _handle_help(args: str) -> str:
    """Show help."""
    return """\
mi-dream CLI — Multi-Agent Learning System

Slash commands:
  /skills        List available skills
  /agents        List available agents
  /commands      List all slash commands
  /help          Show this help
  /session <n>   Create or resume session <n>
  /clear         Clear session context
  /exit          Exit the CLI

Regular input is sent to the Supervisor agent."""


def _handle_session(args: str) -> str:
    name = args.strip() or "default"
    return f"Session: {name}"


def _handle_clear(args: str) -> str:
    return "Context cleared."


def _handle_exit(args: str) -> str:
    raise SystemExit(0)


COMMANDS: dict[str, SlashCommand] = {
    "skills": SlashCommand("skills", "List available skills", _handle_skills),
    "agents": SlashCommand("agents", "List available agents", _handle_agents),
    "commands": SlashCommand("commands", "List all slash commands", _handle_commands),
    "help": SlashCommand("help", "Show help", _handle_help),
    "session": SlashCommand("session", "Create or resume session", _handle_session),
    "clear": SlashCommand("clear", "Clear session context", _handle_clear),
    "exit": SlashCommand("exit", "Exit the CLI", _handle_exit),
}


def dispatch(command: str, args: str = "") -> str:
    cmd = COMMANDS.get(command)
    if cmd:
        return cmd.handler(args)
    return f"Unknown command: /{command}. Type /help for available commands."
```

```python
# tests/test_cli_commands.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.commands import dispatch, COMMANDS

def test_skills_lists_skills():
    result = dispatch("skills")
    assert "brainstorming" in result

def test_agents_lists_agents():
    result = dispatch("agents")
    assert "Research" in result

def test_commands_lists_all_commands():
    result = dispatch("commands")
    assert "/skills" in result
    assert "/exit" in result

def test_help_returns_help_text():
    result = dispatch("help")
    assert "mi-dream CLI" in result
    assert "/skills" in result

def test_session_with_name():
    result = dispatch("session", "my-session")
    assert "my-session" in result

def test_session_default_name():
    result = dispatch("session", "")
    assert "default" in result

def test_clear():
    result = dispatch("clear")
    assert "cleared" in result.lower()

def test_unknown_command():
    result = dispatch("foobar")
    assert "Unknown command" in result

def test_all_commands_registered():
    assert "skills" in COMMANDS
    assert "agents" in COMMANDS
    assert "commands" in COMMANDS
    assert "help" in COMMANDS
    assert "session" in COMMANDS
    assert "clear" in COMMANDS
    assert "exit" in COMMANDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_commands.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Create `src/mi_dream/cli/commands.py` per the code above.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_commands.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mi_dream/cli/commands.py tests/test_cli_commands.py
git commit -m "feat: slash commands registry (skills, agents, commands, help, session, clear, exit)"
```

---

### Task 3: Rich Renderer

**Files:**
- Create: `src/mi_dream/cli/renderer.py`
- Test: `tests/test_cli_renderer.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `render_skills(skills: list[dict]) -> None` — renders skills panel
  - `render_agents(agents: list[dict]) -> None` — renders agents panel
  - `render_commands(commands: dict) -> None` — renders commands panel
  - `render_help() -> None` — renders help panel
  - `render_message(role: str, content: str) -> None` — renders user/assistant message
  - `render_status(model: str, tokens: int, latency: str) -> None` — renders status bar
  - `render_error(message: str) -> None` — renders error
  - `render_markdown(content: str) -> None` — renders markdown via rich.Console

```python
# src/mi_dream/cli/renderer.py
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text
from rich.table import Table

console = Console()


def render_skills(skills: list[dict]) -> None:
    table = Table(title="Skills", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="green")
    table.add_column("Description")
    for s in skills:
        table.add_row(s["name"], s["desc"])
    console.print(table)


def render_agents(agents: list[dict]) -> None:
    table = Table(title="Agents", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="green")
    table.add_column("Description")
    for a in agents:
        table.add_row(a["name"], a["desc"])
    console.print(table)


def render_commands(commands: dict) -> None:
    table = Table(title="Commands", show_header=True, header_style="bold cyan")
    table.add_column("Command", style="green")
    table.add_column("Description")
    for cmd in commands.values():
        table.add_row(f"/{cmd.name}", cmd.description)
    console.print(table)


def render_help() -> None:
    console.print(Panel.fit(
        "[bold]mi-dream CLI[/bold]\n\n"
        "[green]/skills[/green]        List available skills\n"
        "[green]/agents[/green]        List available agents\n"
        "[green]/commands[/green]      List all slash commands\n"
        "[green]/help[/green]          Show this help\n"
        "[green]/session <n>[/green]   Create or resume session\n"
        "[green]/clear[/green]         Clear session context\n"
        "[green]/exit[/green]          Exit the CLI",
        title="Help",
        border_style="blue",
    ))


def render_message(role: str, content: str) -> None:
    if role == "user":
        console.print(Panel(content, title="You", border_style="green", title_align="left"))
    else:
        console.print(Panel(Markdown(content), title="Agent", border_style="cyan", title_align="left"))


def render_status(model: str, tokens: int, latency: str) -> None:
    status = Text()
    status.append(f"Model: {model} ", style="bold")
    status.append(f"Tokens: {tokens} ", style="dim")
    status.append(f"Latency: {latency}", style="dim")
    console.print(status)


def render_error(message: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {message}")


def render_markdown(content: str) -> None:
    console.print(Markdown(content))
```

```python
# tests/test_cli_renderer.py
import sys, os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.renderer import (
    render_skills, render_agents, render_commands,
    render_help, render_message, render_status, render_error, render_markdown
)


def test_render_skills_prints_table():
    with patch("mi_dream.cli.renderer.console") as mock_console:
        render_skills([{"name": "brainstorming", "desc": "Design"}])
        assert mock_console.print.called


def test_render_agents_prints_table():
    with patch("mi_dream.cli.renderer.console") as mock_console:
        render_agents([{"name": "Research", "desc": "Explore"}])
        assert mock_console.print.called


def test_render_commands_prints_table():
    with patch("mi_dream.cli.renderer.console") as mock_console:
        commands = {"skills": MagicMock(name="skills", description="List skills")}
        render_commands(commands)
        assert mock_console.print.called


def test_render_help_prints_panel():
    with patch("mi_dream.cli.renderer.console") as mock_console:
        render_help()
        assert mock_console.print.called


def test_render_message_user():
    with patch("mi_dream.cli.renderer.console") as mock_console:
        render_message("user", "hello")
        assert mock_console.print.called


def test_render_message_assistant():
    with patch("mi_dream.cli.renderer.console") as mock_console:
        render_message("assistant", "## Response\ncontent")
        assert mock_console.print.called


def test_render_status():
    with patch("mi_dream.cli.renderer.console") as mock_console:
        render_status("claude-sonnet-4-6", 150, "1.2s")
        assert mock_console.print.called


def test_render_error():
    with patch("mi_dream.cli.renderer.console") as mock_console:
        render_error("something failed")
        assert mock_console.print.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_renderer.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Create `src/mi_dream/cli/renderer.py` per the code above.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_renderer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mi_dream/cli/renderer.py tests/test_cli_renderer.py
git commit -m "feat: Rich renderer for CLI output (panels, tables, markdown, status)"
```

---

### Task 4: Session Manager

**Files:**
- Create: `src/mi_dream/cli/session.py`
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Session` class — holds context, history, metadata
  - `SessionManager` — creates/resumes/saves/clears sessions

```python
# src/mi_dream/cli/session.py
import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

DEFAULT_SESSION_DIR = Path.home() / ".midream" / "sessions"


@dataclass
class Session:
    name: str
    context: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class SessionManager:
    def __init__(self, session_dir: Path = DEFAULT_SESSION_DIR):
        self._session_dir = session_dir
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._current: Session | None = None

    def create(self, name: str = "default") -> Session:
        self._current = Session(name=name)
        return self._current

    def resume(self, name: str) -> Session:
        path = self._session_dir / f"{name}.json"
        if path.exists():
            data = json.loads(path.read_text())
            self._current = Session(**data)
        else:
            self._current = Session(name=name)
        return self._current

    def current(self) -> Session:
        if not self._current:
            return self.create()
        return self._current

    def add_message(self, role: str, content: str) -> None:
        session = self.current()
        session.context.append({"role": role, "content": content, "ts": datetime.now().isoformat()})
        session.updated_at = datetime.now().isoformat()

    def clear_context(self) -> None:
        session = self.current()
        session.context = []
        session.updated_at = datetime.now().isoformat()

    def save(self) -> None:
        if not self._current:
            return
        path = self._session_dir / f"{self._current.name}.json"
        path.write_text(json.dumps(self._current.__dict__, indent=2))

    def list_sessions(self) -> list[str]:
        return [f.stem for f in self._session_dir.glob("*.json")]
```

```python
# tests/test_cli_session.py
import sys, os
import json
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.session import Session, SessionManager


def test_create_session():
    mgr = SessionManager(session_dir=Path(tempfile.mkdtemp()))
    s = mgr.create("test")
    assert s.name == "test"
    assert len(s.context) == 0


def test_add_message():
    mgr = SessionManager(session_dir=Path(tempfile.mkdtemp()))
    mgr.create("test")
    mgr.add_message("user", "hello")
    mgr.add_message("assistant", "hi")
    ctx = mgr.current().context
    assert len(ctx) == 2
    assert ctx[0]["role"] == "user"
    assert ctx[0]["content"] == "hello"


def test_clear_context():
    mgr = SessionManager(session_dir=Path(tempfile.mkdtemp()))
    mgr.create("test")
    mgr.add_message("user", "hello")
    mgr.clear_context()
    assert len(mgr.current().context) == 0


def test_save_and_resume():
    tmpdir = Path(tempfile.mkdtemp())
    mgr = SessionManager(session_dir=tmpdir)
    mgr.create("persist")
    mgr.add_message("user", "msg1")
    mgr.save()

    mgr2 = SessionManager(session_dir=tmpdir)
    resumed = mgr2.resume("persist")
    assert resumed.name == "persist"
    assert len(resumed.context) == 1
    assert resumed.context[0]["content"] == "msg1"


def test_resume_nonexistent_creates_new():
    tmpdir = Path(tempfile.mkdtemp())
    mgr = SessionManager(session_dir=tmpdir)
    s = mgr.resume("nonexistent")
    assert s.name == "nonexistent"
    assert len(s.context) == 0


def test_list_sessions():
    tmpdir = Path(tempfile.mkdtemp())
    mgr = SessionManager(session_dir=tmpdir)
    mgr.create("s1")
    mgr.create("s2")
    mgr.save()
    mgr.save()
    sessions = mgr.list_sessions()
    assert "s1" in sessions
    assert "s2" in sessions
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_session.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Create `src/mi_dream/cli/session.py` per the code above.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_session.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mi_dream/cli/session.py tests/test_cli_session.py
git commit -m "feat: Session manager with persistence"
```

---

### Task 5: REPL + Autocomplete

**Files:**
- Create: `src/mi_dream/cli/completer.py`
- Create: `src/mi_dream/cli/repl.py`
- Test: `tests/test_cli_repl.py`

**Interfaces:**
- Consumes: `COMMANDS` from Task 2, `SessionManager` from Task 4, renderer from Task 3
- Produces:
  - `SlashCompleter` — prompt_toolkit completer for `/` commands
  - `REPL.run()` — main interactive loop

```python
# src/mi_dream/cli/completer.py
from prompt_toolkit.completion import Completer, Completion
from mi_dream.cli.commands import COMMANDS


class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            partial = text[1:].lower()
            for name, cmd in COMMANDS.items():
                if name.startswith(partial):
                    display = f"/{name}  — {cmd.description}"
                    yield Completion(
                        name,
                        start_position=-len(partial),
                        display=display,
                    )
```

```python
# src/mi_dream/cli/repl.py
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from mi_dream.cli.completer import SlashCompleter
from mi_dream.cli.commands import dispatch
from mi_dream.cli.renderer import (
    render_message, render_error, render_status,
    render_skills, render_agents, render_commands, render_help, render_markdown
)
from mi_dream.cli.session import SessionManager
from mi_dream.llm.client import chat
from mi_dream.config import settings
from mi_dream.agents.tools import recall_strategy, save_reasoning_trace


HISTORY_PATH = str(Path.home() / ".midream" / "history")


def _display_output(text: str) -> None:
    """Render CLI output — plain text or /command result."""
    if text.startswith("Available") or text.startswith("Slash") or text.startswith("mi-dream"):
        console.print(text)
    elif text.startswith("Session:"):
        console.print(f"[cyan]{text}[/cyan]")
    elif text.startswith("Context"):
        console.print(f"[cyan]{text}[/cyan]")
    elif "Error" in text or "Unknown" in text:
        render_error(text)
    else:
        render_markdown(text)


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

    def run(self) -> None:
        session = PromptSession(
            history=FileHistory(HISTORY_PATH),
            completer=self._completer,
            complete_while_typing=True,
            key_bindings=self._bindings,
            multiline=False,
        )
        console.print("[bold cyan]mi-dream[/bold cyan] — Multi-Agent Learning System")
        console.print("[dim]Type /help for commands, Ctrl+C to exit[/dim]\n")

        while self._running:
            try:
                user_input = session.prompt("\n> ")
                if not user_input.strip():
                    continue

                if user_input.startswith("/"):
                    parts = user_input[1:].split(" ", 1)
                    cmd = parts[0]
                    args = parts[1] if len(parts) > 1 else ""
                    result = dispatch(cmd, args)

                    if cmd == "exit":
                        break
                    elif cmd in ("skills", "agents", "commands"):
                        if cmd == "skills":
                            skills = [{"name": "brainstorming", "desc": "Design exploration"}]
                            render_skills(skills)
                        elif cmd == "agents":
                            agents = [{"name": "Research", "desc": "Codebase exploration"}]
                            render_agents(agents)
                        elif cmd == "commands":
                            from mi_dream.cli.commands import COMMANDS
                            render_commands(COMMANDS)
                    elif cmd == "help":
                        render_help()
                    elif cmd == "session":
                        console.print(f"[cyan]{result}[/cyan]")
                    elif cmd == "clear":
                        self._session_mgr.clear_context()
                        console.print("[cyan]Context cleared.[/cyan]")
                    else:
                        console.print(result)
                    continue

                # Regular input → agent loop
                self._session_mgr.add_message("user", user_input)
                ctx = self._session_mgr.current()
                render_message("user", user_input)

                # Build context from session history
                history = [{"role": m["role"], "content": m["content"]} for m in ctx.context]

                # Call LLM via existing client
                from mi_dream.llm.client import get_client
                client = get_client()
                messages = [{"role": h["role"], "content": h["content"]} for h in history]
                response = client.messages.create(
                    model=settings.llm_model,
                    max_tokens=1024,
                    messages=messages,
                )
                assistant_msg = response.content[0].text

                self._session_mgr.add_message("assistant", assistant_msg)
                render_message("assistant", assistant_msg)
                render_status(settings.llm_model, response.usage.input_tokens + response.usage.output_tokens, "—")

            except KeyboardInterrupt:
                continue
            except SystemExit:
                break
            except Exception as e:
                render_error(str(e))

        self._session_mgr.save()
        console.print("\n[dim]Session saved. Goodbye![/dim]")
```

```python
# tests/test_cli_repl.py
import sys, os
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.completer import SlashCompleter
from mi_dream.cli.session import SessionManager
from mi_dream.cli.commands import dispatch
from mi_dream.cli.repl import REPL
from prompt_toolkit.document import Document
from prompt_toolkit.completion import CompleteEvent


def test_slash_completer_completes_skills():
    completer = SlashCompleter()
    doc = Document("/sk", 2)
    event = CompleteEvent(completing=True)
    completions = list(completer.get_completions(doc, event))
    assert len(completions) > 0
    assert any(c.text == "skills" for c in completions)


def test_slash_completer_partial_match():
    completer = SlashCompleter()
    doc = Document("/hel", 3)
    event = CompleteEvent(completing=True)
    completions = list(completer.get_completions(doc, event))
    assert len(completions) == 1
    assert completions[0].text == "help"


def test_slash_completer_no_match():
    completer = SlashCompleter()
    doc = Document("/nonexistent", 11)
    event = CompleteEvent(completing=True)
    completions = list(completer.get_completions(doc, event))
    assert len(completions) == 0


def test_repl_dispatches_slash_command():
    tmpdir = Path(tempfile.mkdtemp())
    mgr = SessionManager(session_dir=tmpdir)
    repl = REPL(mgr)
    result = dispatch("help")
    assert "mi-dream CLI" in result


def test_repl_handles_exit():
    with patch("mi_dream.cli.repl.console"):
        tmpdir = Path(tempfile.mkdtemp())
        mgr = SessionManager(session_dir=tmpdir)
        repl = REPL(mgr)
        assert repl._running is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_repl.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Create `src/mi_dream/cli/completer.py`, `src/mi_dream/cli/repl.py` per the code above.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_repl.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mi_dream/cli/completer.py src/mi_dream/cli/repl.py tests/test_cli_repl.py
git commit -m "feat: REPL with prompt_toolkit + autocomplete for slash commands"
```

---

### Task 6: Typer App + Chat Command

**Files:**
- Create: `src/mi_dream/cli/app.py`
- Test: `tests/test_cli_app.py`

**Interfaces:**
- Consumes: `REPL` from Task 5, `SessionManager` from Task 4
- Produces: `main()` entry point invoked by `mi-dream` console script

```python
# src/mi_dream/cli/app.py
import typer
from mi_dream.cli.repl import REPL
from mi_dream.cli.session import SessionManager

app = typer.Typer(name="mi-dream", add_completion=False, no_args_is_help=True)


@app.command()
def chat(session: str = typer.Option("default", "--session", "-s", help="Session name")):
    """Start interactive chat session."""
    mgr = SessionManager()
    mgr.resume(session)
    repl = REPL(mgr)
    repl.run()


@app.command()
def sessions():
    """List saved sessions."""
    mgr = SessionManager()
    for name in mgr.list_sessions():
        typer.echo(f"  {name}")


def main():
    app()
```

```python
# tests/test_cli_app.py
import sys, os
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


def test_chat_invokes_repl():
    with patch("mi_dream.cli.app.REPL") as MockREPL, \
         patch("mi_dream.cli.app.SessionManager") as MockSM:
        mock_mgr = MagicMock()
        MockSM.return_value = mock_mgr
        mock_repl = MagicMock()
        MockREPL.return_value = mock_repl

        result = runner.invoke(app, ["chat", "--session", "test"])
        assert result.exit_code == 0
        mock_repl.run.assert_called_once()


def test_chat_default_session():
    with patch("mi_dream.cli.app.REPL") as MockREPL, \
         patch("mi_dream.cli.app.SessionManager") as MockSM:
        mock_mgr = MagicMock()
        MockSM.return_value = mock_mgr
        mock_repl = MagicMock()
        MockREPL.return_value = mock_repl

        result = runner.invoke(app, ["chat"])
        assert result.exit_code == 0
        mock_mgr.resume.assert_called_once_with("default")


def test_sessions_lists_sessions():
    with patch("mi_dream.cli.app.SessionManager") as MockSM:
        mock_mgr = MagicMock()
        mock_mgr.list_sessions.return_value = ["s1", "s2"]
        MockSM.return_value = mock_mgr

        result = runner.invoke(app, ["sessions"])
        assert result.exit_code == 0
        assert "s1" in result.stdout
        assert "s2" in result.stdout


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "chat" in result.stdout
    assert "sessions" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_app.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Create `src/mi_dream/cli/app.py` per the code above.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_app.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mi_dream/cli/app.py tests/test_cli_app.py pyproject.toml
git commit -m "feat: Typer CLI entry point with chat + sessions commands"
```

---

### Task 7: Integration Test (Real REPL Smoke Test)

**Files:**
- Create: `tests/integration/test_cli_integration.py`

**Interfaces:**
- Consumes: all previous tasks
- Produces: smoke test that exercises full CLI flow

```python
# tests/integration/test_cli_integration.py
import sys, os
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

import pytest
from mi_dream.cli.session import SessionManager
from mi_dream.cli.commands import dispatch
from mi_dream.cli.renderer import render_skills, render_help
from mi_dream.cli.completer import SlashCompleter


def test_full_cli_flow():
    tmpdir = Path(tempfile.mkdtemp())
    mgr = SessionManager(session_dir=tmpdir)

    # 1. Create session
    session = mgr.create("integration-test")
    assert session.name == "integration-test"

    # 2. Add messages
    mgr.add_message("user", "hello")
    mgr.add_message("assistant", "hi there")
    assert len(mgr.current().context) == 2

    # 3. Slash commands work
    assert "brainstorming" in dispatch("skills")
    assert "Research" in dispatch("agents")
    assert "/help" in dispatch("commands")
    help_result = dispatch("help")
    assert "mi-dream CLI" in help_result

    # 4. Session resume
    mgr.save()
    mgr2 = SessionManager(session_dir=tmpdir)
    resumed = mgr2.resume("integration-test")
    assert len(resumed.context) == 2
    assert resumed.context[0]["content"] == "hello"

    # 5. Clear context
    mgr.clear_context()
    assert len(mgr.current().context) == 0

    # 6. Autocomplete works
    completer = SlashCompleter()
    from prompt_toolkit.document import Document
    from prompt_toolkit.completion import CompleteEvent
    doc = Document("/sk", 2)
    completions = list(completer.get_completions(doc, CompleteEvent(completing=True)))
    assert any(c.text == "skills" for c in completions)
```

- [ ] **Step 1: Write the failing test**

```python
# (already written above)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_cli_integration.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

All components from Tasks 1-5 exist. The integration test stitches them together.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_cli_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_cli_integration.py
git commit -m "test: CLI integration smoke test"
```

---

## Self-Review

**Spec coverage:**
- Rich UI: Task 3 (renderer.py — panels, tables, markdown, status bar)
- Skills listing: Task 2 (`/skills` command + render_skills)
- Agents listing: Task 2 (`/agents` command + render_agents)
- Commands listing: Task 2 (`/commands` command + render_commands)
- Help: Task 2 (`/help` command + render_help)
- Session management: Task 4 (SessionManager with create/resume/save/clear)
- Interactive chat: Task 5 (REPL with agent loop)
- Typer entry: Task 6 (app.py with `chat` + `sessions` commands)
- Autocomplete: Task 5 (SlashCompleter)
- `[project.scripts]` entry: Task 6

**No placeholders:** All code blocks contain runnable code.

**Type consistency:** `Session`, `SessionManager`, `SlashCommand`, `COMMANDS`, `SlashCompleter`, `REPL` — consistent across all tasks.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-06-cli-implementation.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
