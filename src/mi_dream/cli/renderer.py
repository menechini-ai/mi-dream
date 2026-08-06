from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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
    console.print(
        Panel.fit(
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
        )
    )


def render_message(role: str, content: str) -> None:
    if role == "user":
        console.print(Panel(content, title="You", border_style="green", title_align="left"))
    else:
        console.print(
            Panel(Markdown(content), title="Agent", border_style="cyan", title_align="left")
        )


def render_status(model: str, tokens: int, latency: str) -> None:
    status = Text()
    status.append(f"Model: {model} ", style="bold")
    status.append(f"Tokens: {tokens} ", style="dim")
    status.append(f"Latency: {latency}", style="dim")
    console.print(status)


def render_error(message: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {message}")


def render_health(results: list) -> None:
    table = Table(title="Health Check", show_header=True, header_style="bold cyan")
    table.add_column("Service", style="green")
    table.add_column("Status", justify="center")
    table.add_column("Detail")
    table.add_column("Latency", justify="right")
    for r in results:
        status_style = "green" if r.status == "ok" else "red" if r.status == "error" else "yellow"
        status_icon = "OK" if r.status == "ok" else "ERR" if r.status == "error" else "WARN"
        table.add_row(
            r.name,
            f"[{status_style}]{status_icon}[/{status_style}]",
            r.detail,
            f"{r.latency_ms} ms",
        )
    console.print(table)


def render_markdown(content: str) -> None:
    console.print(Markdown(content))
