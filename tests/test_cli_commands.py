import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.commands import COMMANDS, dispatch


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
