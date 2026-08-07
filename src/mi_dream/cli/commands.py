from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class SlashCommand:
    name: str
    description: str
    handler: Callable[[str], str]


def _handle_skills(args: str) -> list[dict]:
    return [
        {"name": "brainstorming", "desc": "Design exploration"},
        {"name": "systematic-debugging", "desc": "Bug investigation"},
        {"name": "test-driven-development", "desc": "TDD workflow"},
        {"name": "writing-plans", "desc": "Implementation planning"},
    ]


def _handle_agents(args: str) -> list[dict]:
    return [
        {"name": "Research", "desc": "Codebase exploration and research"},
        {"name": "Implementation", "desc": "Code writing and refactoring"},
        {"name": "Review", "desc": "Code review and quality checks"},
    ]


def _handle_commands(args: str) -> list[dict]:
    return [{"name": cmd.name, "desc": cmd.description} for cmd in COMMANDS.values()]


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


def _handle_model(args: str) -> str:
    from mi_dream.config import settings
    return f"Model: {settings.llm_model}"


def _handle_cost(args: str) -> str:
    return "Use /cost in REPL for session cost estimate."


def _handle_learn(args: str) -> str:
    return "Run /learn in REPL (or `mi-dream learn`) for a learning cycle."


def _handle_review(args: str) -> str:
    return "Run /review in REPL (or `mi-dream review`) for the daily review."


def _handle_cron(args: str) -> str:
    """Manage cron jobs: /cron [list | rm <id>]"""
    from mi_dream.cli.cron import CronManager

    mgr = CronManager()
    parts = args.strip().split(" ", 1)
    if not parts or parts[0] == "list":
        jobs = mgr.list_jobs()
        if not jobs:
            return "No active cron jobs.\nUsage: /cron add 1h \"busque sobre SRE\""
        lines = ["Active cron jobs:", ""]
        for j in jobs:
            mode = f"script={j.script}" if j.script else "agent"
            lines.append(
                f"  [{j.id}] {j.prompt[:40] or j.script}... — every {j.interval} "
                f"({mode}) (last: {j.last_run or 'never'})"
            )
        return "\n".join(lines)
    if parts[0] == "rm" and len(parts) > 1:
        if mgr.deactivate(parts[1].strip()):
            return f"Cron job {parts[1]} removed."
        return f"Cron job {parts[1]} not found."
    return "Usage: /cron [list | rm <id>] | /cron add <interval> \"<prompt>\""


COMMANDS: dict[str, SlashCommand] = {
    "skills": SlashCommand("skills", "List available skills", _handle_skills),
    "agents": SlashCommand("agents", "List available agents", _handle_agents),
    "commands": SlashCommand("commands", "List all slash commands", _handle_commands),
    "help": SlashCommand("help", "Show help", _handle_help),
    "session": SlashCommand("session", "Create or resume session", _handle_session),
    "clear": SlashCommand("clear", "Clear session context", _handle_clear),
    "exit": SlashCommand("exit", "Exit the CLI", _handle_exit),
    "cron": SlashCommand("cron", "Manage learning cron jobs", _handle_cron),
    "model": SlashCommand("model", "Show current model", _handle_model),
    "cost": SlashCommand("cost", "Session cost estimate", _handle_cost),
    "learn": SlashCommand("learn", "Run a learning cycle", _handle_learn),
    "review": SlashCommand("review", "Run the daily review", _handle_review),
}


def dispatch(command: str, args: str = "") -> str | list[dict]:
    cmd = COMMANDS.get(command)
    if cmd:
        return cmd.handler(args)
    return f"Unknown command: /{command}. Type /help for available commands."
