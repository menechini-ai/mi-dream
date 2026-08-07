import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.commands import COMMANDS, dispatch
from mi_dream.cli.renderer import render_agents, render_commands, render_skills


def test_dispatch_skills_returns_list():
    result = dispatch("skills")
    assert isinstance(result, list)
    names = [s["name"] for s in result]
    assert "brainstorming" in names


def test_dispatch_agents_returns_list():
    result = dispatch("agents")
    assert isinstance(result, list)
    names = [a["name"] for a in result]
    assert "Research" in names


def test_dispatch_commands_returns_list():
    result = dispatch("commands")
    assert isinstance(result, list)
    assert any(c["name"] == "skills" for c in result)


def test_dispatch_help_returns_string():
    result = dispatch("help")
    assert isinstance(result, str)
    assert "mi-dream CLI" in result


def test_dispatch_unknown_returns_error():
    result = dispatch("foobar")
    assert "Unknown command" in result


def test_all_commands_have_dispatch_entry():
    for name, cmd in COMMANDS.items():
        if name == "exit":
            continue  # /exit intencionalmente levanta SystemExit
        result = dispatch(name, "")
        assert result is not None, f"Command /{name} returned None"


def test_render_skills_with_yaml_format():
    skills = [{"name": "brainstorming", "description": "Design exploration"}]
    render_skills(skills)  # should not raise


def test_render_agents_with_yaml_format():
    agents = [{"name": "Research", "description": "Codebase exploration"}]
    render_agents(agents)  # should not raise


def test_render_commands_with_list_format():
    cmds = [{"name": "skills", "desc": "List skills"}]
    render_commands(cmds)  # should not raise
