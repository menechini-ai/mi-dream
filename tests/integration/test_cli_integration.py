import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from mi_dream.cli.commands import dispatch
from mi_dream.cli.completer import SlashCompleter
from mi_dream.cli.session import SessionManager


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
    doc = Document("/sk", 2)
    completions = list(completer.get_completions(doc, CompleteEvent()))
    assert any(c.text == "skills" for c in completions)
