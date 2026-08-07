import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.commands import COMMANDS, dispatch
from mi_dream.cli.loader import invalidate_cache, load_agents, load_skills


def test_skills_returns_list_of_dicts():
    result = dispatch("skills")
    assert isinstance(result, list)
    assert any(s["name"] == "brainstorming" for s in result)


def test_agents_returns_list_of_dicts():
    result = dispatch("agents")
    assert isinstance(result, list)
    assert any(a["name"] == "Research" for a in result)


def test_commands_returns_list_of_dicts():
    result = dispatch("commands")
    assert isinstance(result, list)
    assert any(c["name"] == "skills" for c in result)


def test_help_returns_string():
    result = dispatch("help")
    assert isinstance(result, str)
    assert "mi-dream CLI" in result


def test_session_with_name():
    result = dispatch("session", "my-session")
    assert "my-session" in result


def test_session_default_name():
    result = dispatch("session", "")
    assert "default" in result


def test_clear():
    result = dispatch("clear")
    assert "cleared" in result.lower()


def test_model_show_current():
    result = dispatch("model", "")
    assert "model" in result.lower()


def test_unknown_command():
    result = dispatch("foobar")
    assert "Unknown command" in result


def test_all_commands_registered():
    required = ["skills", "agents", "commands", "help", "session", "clear", "exit", "model", "cost"]
    for cmd in required:
        assert cmd in COMMANDS, f"Missing command: {cmd}"


def test_load_skills_from_yaml():
    invalidate_cache()
    skills = load_skills()
    assert isinstance(skills, list)
    assert len(skills) > 0
    assert "name" in skills[0]
    assert "description" in skills[0]


def test_load_agents_from_yaml():
    invalidate_cache()
    agents = load_agents()
    assert isinstance(agents, list)
    assert len(agents) > 0
    assert "name" in agents[0]
