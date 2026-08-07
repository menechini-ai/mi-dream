import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.loader import load_agents, load_skills

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_SKILLS = str(FIXTURES / "skills")
FIXTURE_AGENTS = str(FIXTURES / "agents")


def test_load_skills_returns_list():
    with patch("mi_dream.cli.loader.settings") as mock_settings:
        mock_settings.skills_dir = FIXTURE_SKILLS
        load_skills.cache_clear()
        skills = load_skills()
    assert isinstance(skills, list)
    assert len(skills) > 0
    assert "name" in skills[0]
    assert "description" in skills[0]
    assert "prompt" in skills[0]
    assert len(skills[0]["prompt"]) > 0


def test_load_agents_returns_list():
    with patch("mi_dream.cli.loader.settings") as mock_settings:
        mock_settings.agents_dir = FIXTURE_AGENTS
        load_agents.cache_clear()
        agents = load_agents()
    assert isinstance(agents, list)
    assert len(agents) > 0
    assert "name" in agents[0]
    assert "prompt" in agents[0]


def test_load_skills_empty_dir():
    with patch("mi_dream.cli.loader.settings") as mock_settings:
        mock_settings.skills_dir = "/nonexistent/dir"
        load_skills.cache_clear()
        skills = load_skills()
    assert skills == []


def test_load_caches_results():
    with patch("mi_dream.cli.loader.settings") as mock_settings:
        mock_settings.skills_dir = FIXTURE_SKILLS
        load_skills.cache_clear()
        s1 = load_skills()
        s2 = load_skills()
    assert s1 is s2  # cached, same object


def test_cache_clear_works():
    with patch("mi_dream.cli.loader.settings") as mock_settings:
        mock_settings.skills_dir = FIXTURE_SKILLS
        load_skills.cache_clear()
        load_skills()
        load_skills.cache_clear()
        skills = load_skills()
    assert isinstance(skills, list)
