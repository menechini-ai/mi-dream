import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.loader import invalidate_cache, load_agents, load_skills

FIXTURE_SKILLS = "/home/access/AI/mi-dream/.midream/skills"
FIXTURE_AGENTS = "/home/access/AI/mi-dream/.midream/agents"


def test_load_skills_returns_list():
    with patch("mi_dream.cli.loader.settings") as mock_settings:
        mock_settings.skills_dir = FIXTURE_SKILLS
        invalidate_cache()
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
        invalidate_cache()
        agents = load_agents()
    assert isinstance(agents, list)
    assert len(agents) > 0
    assert "name" in agents[0]
    assert "prompt" in agents[0]


def test_load_skills_empty_dir():
    with patch("mi_dream.cli.loader.settings") as mock_settings:
        mock_settings.skills_dir = "/nonexistent/dir"
        invalidate_cache()
        skills = load_skills()
    assert skills == []


def test_load_caches_results():
    with patch("mi_dream.cli.loader.settings") as mock_settings:
        mock_settings.skills_dir = FIXTURE_SKILLS
        invalidate_cache()
        s1 = load_skills()
        s2 = load_skills()
    assert s1 is s2  # cached, same object


def test_invalidate_cache_clears():
    with patch("mi_dream.cli.loader.settings") as mock_settings:
        mock_settings.skills_dir = FIXTURE_SKILLS
        invalidate_cache()
        load_skills()
        invalidate_cache()
        skills = load_skills()
    assert isinstance(skills, list)
