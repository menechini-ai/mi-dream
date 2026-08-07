import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.cli.completer import SlashCompleter
from mi_dream.cli.repl import build_system_prompt, recall_context
from mi_dream.knowledge.models import Strategy
from mi_dream.knowledge.router import ExecutionContext


def test_build_system_prompt_empty_context():
    ctx = ExecutionContext(goal="test")
    result = build_system_prompt(ctx)
    assert result == "You are a helpful assistant."


def test_build_system_prompt_with_strategies():
    s = Strategy(
        id="s1", title="K8s debug", description="Check pods", domain="kubernetes",
        content="Check pods first",
        created_at="2024-01-01T00:00:00Z", updated_at="2024-01-01T00:00:00Z",
    )
    ctx = ExecutionContext(goal="debug", strategies=[s])
    result = build_system_prompt(ctx)
    assert "Relevant knowledge strategies:" in result
    assert "[K8s debug]" in result
    assert "kubernetes" in result


def test_build_system_prompt_multiple_strategies():
    strategies = [
        Strategy(id="s1", title="S1", description="d1", domain="d", content="c1",
                 created_at="2024-01-01T00:00:00Z", updated_at="2024-01-01T00:00:00Z"),
        Strategy(id="s2", title="S2", description="d2", domain="d", content="c2",
                 created_at="2024-01-01T00:00:00Z", updated_at="2024-01-01T00:00:00Z"),
    ]
    ctx = ExecutionContext(goal="test", strategies=strategies)
    result = build_system_prompt(ctx)
    assert "[S1]" in result
    assert "[S2]" in result


@pytest.mark.asyncio
async def test_recall_context_success():
    mock_router = MagicMock()
    mock_router.retrieve = MagicMock(return_value=ExecutionContext(goal="test", strategies=[]))

    with patch("mi_dream.cli.repl.StrategyRouter", return_value=mock_router), \
         patch("mi_dream.cli.repl.StrategyRepository") as MockRepo, \
         patch("mi_dream.cli.repl.get_driver") as mock_get_driver:
        mock_session = MagicMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__aenter__ = MagicMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = MagicMock(return_value=False)
        mock_get_driver.return_value = mock_driver
        MockRepo.return_value = MagicMock()

        result = await recall_context("test goal")

    assert isinstance(result, ExecutionContext)
    assert result.goal == "test goal"


@pytest.mark.asyncio
async def test_recall_context_fallback_on_error():
    with patch("mi_dream.cli.repl.get_driver", side_effect=Exception("DB down")):
        result = await recall_context("test")

    assert isinstance(result, ExecutionContext)
    assert result.goal == "test"
    assert result.strategies == []


@pytest.mark.asyncio
async def test_recall_context_includes_recent_memory():
    from unittest.mock import AsyncMock, MagicMock

    from conftest import FakeAsyncIter, make_driver_mock

    traces = [{"trace": {"id": "t1", "content": "Q: meu nome é Adilson\nA: Prazer"}}]
    episodes = [{"episode": {"id": "e1", "summary": "Usuário se chama Adilson"}}]

    async def fake_run(query, **kwargs):
        if "ReasoningTrace" in query:
            return FakeAsyncIter(traces)
        return FakeAsyncIter(episodes)

    session = AsyncMock()
    session.run.side_effect = fake_run
    driver = make_driver_mock(session)

    mock_router = MagicMock()
    mock_router.retrieve = AsyncMock(
        return_value=ExecutionContext(goal="qual o meu nome", strategies=[])
    )

    with patch("mi_dream.cli.repl.StrategyRouter", return_value=mock_router), \
         patch("mi_dream.cli.repl.StrategyRepository"), \
         patch("mi_dream.cli.repl.get_driver", return_value=driver):
        ctx = await recall_context("qual o meu nome")

    assert len(ctx.recent_traces) == 1
    assert len(ctx.episodes) == 1
    assert "Adilson" in ctx.recent_traces[0]["content"]


def test_completer_includes_commands():
    completer = SlashCompleter()
    doc = MagicMock()
    doc.text_before_cursor = "/sk"
    completions = list(completer.get_completions(doc, None))
    assert any(c.text == "skills" for c in completions)


def test_completer_includes_skills():
    completer = SlashCompleter()
    doc = MagicMock()
    doc.text_before_cursor = "/brain"
    completions = list(completer.get_completions(doc, None))
    assert any(c.text == "brainstorming" for c in completions)


def test_completer_includes_agents():
    completer = SlashCompleter()
    doc = MagicMock()
    doc.text_before_cursor = "@Res"
    completions = list(completer.get_completions(doc, None))
    assert any(c.text == "Research" for c in completions)


def test_completer_no_prefix_returns_empty():
    completer = SlashCompleter()
    doc = MagicMock()
    doc.text_before_cursor = "hello"
    completions = list(completer.get_completions(doc, None))
    assert completions == []


def test_completer_empty_prefix_returns_all():
    completer = SlashCompleter()
    doc = MagicMock()
    doc.text_before_cursor = "/"
    completions = list(completer.get_completions(doc, None))
    assert any(c.text == "skills" for c in completions)
    assert any(c.text == "agents" for c in completions)


@pytest.mark.asyncio
async def test_run_with_skill_injects_prompt():
    from mi_dream.cli.loader import load_skills
    from mi_dream.cli.repl import REPL
    from mi_dream.cli.session import SessionManager

    mgr = SessionManager()
    repl = REPL(mgr)

    skills = load_skills()
    brainstorming = next(s for s in skills if s["name"] == "brainstorming")

    with patch("mi_dream.cli.repl.ask_llm_full") as mock_llm, \
         patch.object(mgr, "add_message"):
        mock_llm.return_value = MagicMock(
            content="brainstorm result", total_tokens=10, latency_ms=5.0
        )
        await repl._run_with_skill(brainstorming, "design a logo")

    mock_llm.assert_called_once()
    call_kwargs = mock_llm.call_args.kwargs
    assert "brainstorming facilitator" in call_kwargs["system"]
    assert call_kwargs["user_message"] == "design a logo"


@pytest.mark.asyncio
async def test_run_with_agent_injects_prompt():
    from mi_dream.cli.loader import load_agents
    from mi_dream.cli.repl import REPL
    from mi_dream.cli.session import SessionManager

    mgr = SessionManager()
    repl = REPL(mgr)

    agents = load_agents()
    research = next(a for a in agents if a["name"] == "Research")

    with patch("mi_dream.cli.repl.ask_llm_full") as mock_llm, \
         patch.object(mgr, "add_message"):
        mock_llm.return_value = MagicMock(
            content="research result", total_tokens=10, latency_ms=5.0
        )
        await repl._run_with_agent(research, "find auth code")

    mock_llm.assert_called_once()
    call_kwargs = mock_llm.call_args.kwargs
    assert "research agent" in call_kwargs["system"]
    assert call_kwargs["user_message"] == "find auth code"


def test_completer_agents_use_at_prefix():
    completer = SlashCompleter()
    doc = MagicMock()
    doc.text_before_cursor = "@Res"
    completions = list(completer.get_completions(doc, None))
    assert any("Research" in c.text for c in completions)
    assert any("@Research" in str(c.display) for c in completions)
