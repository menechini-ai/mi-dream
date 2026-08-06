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
