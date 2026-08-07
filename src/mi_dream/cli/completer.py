from prompt_toolkit.completion import Completer, Completion

from mi_dream.cli.commands import COMMANDS
from mi_dream.cli.loader import load_agents, load_skills


class SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            partial = text[1:].lower()
            for name, cmd in COMMANDS.items():
                if name.startswith(partial):
                    yield Completion(
                        name,
                        start_position=-len(partial),
                        display=f"/{name}  — {cmd.description}",
                    )
            for skill in load_skills():
                sname = skill.get("name", "")
                if sname.lower().startswith(partial):
                    yield Completion(
                        sname,
                        start_position=-len(partial),
                        display=f"/{sname}  — {skill.get('description', '')}",
                    )
        elif text.startswith("@"):
            partial = text[1:].lower()
            for agent in load_agents():
                aname = agent.get("name", "")
                if aname.lower().startswith(partial):
                    yield Completion(
                        aname,
                        start_position=-len(partial),
                        display=f"@{aname}  — {agent.get('description', '')}",
                    )
