import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.renderer import (
    render_agents,
    render_commands,
    render_error,
    render_help,
    render_message,
    render_skills,
    render_status,
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
        cmd_mock = MagicMock()
        cmd_mock.name = "skills"
        cmd_mock.description = "List skills"
        render_commands({"skills": cmd_mock})
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
