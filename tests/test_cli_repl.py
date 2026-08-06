import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from mi_dream.cli.commands import dispatch
from mi_dream.cli.completer import SlashCompleter
from mi_dream.cli.repl import build_system_prompt, recall_context
from mi_dream.cli.session import SessionManager, new_session_id
from mi_dream.knowledge.models import Strategy, StrategyState
from mi_dream.knowledge.router import ExecutionContext


def _strategy(**kwargs):
    defaults = dict(
        id="s1", title="K8s debug", description="Check pods first", domain="kubernetes",
        content="c", state=StrategyState.ACTIVE, support_count=3, success_rate=0.7,
        created_at="2024-01-01T00:00:00Z", updated_at="2024-06-01T00:00:00Z",
        tenant_id="default",
    )
    defaults.update(kwargs)
    return Strategy(**defaults)


def test_build_system_prompt_empty_context():
    prompt = build_system_prompt(ExecutionContext(goal="x"))
    assert "Relevant knowledge strategies" not in prompt


def test_build_system_prompt_includes_strategies():
    ctx = ExecutionContext(goal="x", strategies=[_strategy()])
    prompt = build_system_prompt(ctx)
    assert "K8s debug" in prompt
    assert "Check pods first" in prompt


async def test_recall_context_degrades_gracefully():
    with patch("mi_dream.cli.repl.get_driver", side_effect=RuntimeError("neo4j down")):
        ctx = await recall_context("any goal")
    assert ctx.goal == "any goal"
    assert ctx.strategies == []


def test_slash_completer_completes_skills():
    completer = SlashCompleter()
    doc = Document("/sk", 2)
    event = CompleteEvent()
    completions = list(completer.get_completions(doc, event))
    assert len(completions) > 0
    assert any(c.text == "skills" for c in completions)


def test_slash_completer_partial_match():
    completer = SlashCompleter()
    doc = Document("/hel", 3)
    event = CompleteEvent()
    completions = list(completer.get_completions(doc, event))
    assert len(completions) == 1
    assert completions[0].text == "help"


def test_slash_completer_no_match():
    completer = SlashCompleter()
    doc = Document("/nonexistent", 11)
    event = CompleteEvent()
    completions = list(completer.get_completions(doc, event))
    assert len(completions) == 0


def test_repl_dispatches_slash_command():
    result = dispatch("help")
    assert "mi-dream CLI" in result


def test_repl_running_flag():
    with patch("mi_dream.cli.repl.console"):
        tmpdir = Path(tempfile.mkdtemp())
        mgr = SessionManager(session_dir=tmpdir)
        from mi_dream.cli.repl import REPL
        repl = REPL(mgr)
        assert repl._running is True


@pytest.mark.asyncio
async def test_repl_bootstraps_schema_automatically():
    from unittest.mock import AsyncMock, MagicMock

    from mi_dream.cli.repl import REPL

    async def fake_prompt(*args, **kwargs):
        raise SystemExit

    with patch("mi_dream.memory.bootstrap.ensure_schema", new=AsyncMock()) as mock_ensure, \
         patch("mi_dream.cli.repl.PromptSession") as MockPS:
        MockPS.return_value = MagicMock()
        MockPS.return_value.prompt_async = fake_prompt
        tmpdir = Path(tempfile.mkdtemp())
        mgr = SessionManager(session_dir=tmpdir)
        await REPL(mgr).run()

    mock_ensure.assert_awaited_once()


def test_new_session_id_is_random_and_resumable():
    ids = {new_session_id() for _ in range(50)}
    assert len(ids) == 50  # colisões essencialmente impossíveis
    sid = next(iter(ids))
    assert len(sid) > 4
    assert "-" in sid


def test_format_latency():
    from mi_dream.cli.repl import format_latency

    assert format_latency(340) == "340ms"
    assert format_latency(0) == "0ms"
    assert format_latency(1250) == "1.2s"


@pytest.mark.asyncio
async def test_repl_creates_random_session_on_start(tmp_path):
    from unittest.mock import MagicMock

    from mi_dream.cli.repl import REPL

    async def fake_prompt(*args, **kwargs):
        raise SystemExit

    with patch("mi_dream.cli.repl.PromptSession") as MockPS:
        MockPS.return_value = MagicMock()
        MockPS.return_value.prompt_async = fake_prompt
        mgr = SessionManager(session_dir=tmp_path)
        await REPL(mgr).run()

    session = mgr.current()
    assert session.name != "default"
    assert "-" in session.name
    assert (tmp_path / f"{session.name}.json").exists()  # salva com o ID aleatório
