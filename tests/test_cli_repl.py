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
        id="s1",
        title="K8s debug",
        description="Check pods first",
        domain="kubernetes",
        content="c",
        state=StrategyState.ACTIVE,
        support_count=3,
        success_rate=0.7,
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-06-01T00:00:00Z",
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


def test_build_system_prompt_includes_recent_traces():
    ctx = ExecutionContext(
        goal="x",
        recent_traces=[{"content": "Q: meu nome é Adilson\nA: Prazer, Adilson"}],
    )
    prompt = build_system_prompt(ctx)
    assert "Recent conversation history" in prompt
    assert "Adilson" in prompt


def test_build_system_prompt_includes_episodes():
    ctx = ExecutionContext(goal="x", episodes=[{"summary": "Usuário se chama Adilson"}])
    prompt = build_system_prompt(ctx)
    assert "Prior session summaries" in prompt
    assert "Adilson" in prompt


def test_build_system_prompt_includes_failure_patterns():
    ctx = ExecutionContext(
        goal="x",
        previous_failures=[
            {
                "error_type": "rate_limit_error",
                "pattern": "Too Many Requests",
                "failure_count": 5,
            }
        ],
    )
    prompt = build_system_prompt(ctx)
    assert "Known failure patterns" in prompt
    assert "Too Many Requests" in prompt
    assert "5" in prompt


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

    with (
        patch("mi_dream.memory.bootstrap.ensure_schema", new=AsyncMock()) as mock_ensure,
        patch("mi_dream.cli.repl.PromptSession") as MockPS,
    ):
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


@pytest.mark.asyncio
async def test_repl_preserves_resumed_session(tmp_path):
    from unittest.mock import MagicMock

    from mi_dream.cli.repl import REPL

    async def fake_prompt(*args, **kwargs):
        raise SystemExit

    with patch("mi_dream.cli.repl.PromptSession") as MockPS:
        MockPS.return_value = MagicMock()
        MockPS.return_value.prompt_async = fake_prompt
        mgr = SessionManager(session_dir=tmp_path)
        mgr.resume("mysess")
        mgr.add_message("user", "oi")
        await REPL(mgr).run()

    assert mgr.current().name == "mysess"
    assert (tmp_path / "mysess.json").exists()


@pytest.mark.asyncio
async def test_repl_session_command_resumes(tmp_path):

    from mi_dream.cli.repl import REPL

    mgr = SessionManager(session_dir=tmp_path)
    repl = REPL(mgr)
    with patch("mi_dream.cli.repl.console"):
        await repl._handle_session_command("mysess")
    assert mgr.current().name == "mysess"


@pytest.mark.asyncio
async def test_repl_clear_command_clears_context(tmp_path):
    from unittest.mock import MagicMock

    from mi_dream.cli.repl import REPL

    inputs = iter(["/clear"])

    async def fake_prompt(*args, **kwargs):
        try:
            return next(inputs)
        except StopIteration:
            raise SystemExit

    with patch("mi_dream.cli.repl.PromptSession") as MockPS, patch("mi_dream.cli.repl.console"):
        MockPS.return_value = MagicMock()
        MockPS.return_value.prompt_async = fake_prompt
        mgr = SessionManager(session_dir=tmp_path)
        mgr.resume("s1")
        mgr.add_message("user", "hello")
        mgr.add_message("assistant", "world")
        await REPL(mgr).run()

    assert mgr.current().context == []


@pytest.mark.asyncio
async def test_repl_compact_command_compacts_and_persists(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from mi_dream.cli.repl import REPL

    mgr = SessionManager(session_dir=tmp_path)
    mgr.create("s1")
    for msg in ("a" * 100, "b" * 100, "c" * 100):
        mgr.add_message("user", msg)
    repl = REPL(mgr)

    fake = MagicMock()
    fake.compact = AsyncMock(
        return_value=[
            {"role": "system", "content": "[Resumo] ABC"},
            {"role": "user", "content": "c" * 100},
        ]
    )
    fake.persist_episode = AsyncMock(return_value="ep-1")

    with (
        patch("mi_dream.cli.repl.ConversationCompactor", return_value=fake),
        patch("mi_dream.cli.repl.console"),
    ):
        await repl._handle_compact()

    fake.compact.assert_awaited_once()
    fake.persist_episode.assert_awaited_once()
    assert mgr.current().context[0]["role"] == "system"


@pytest.mark.asyncio
async def test_repl_learn_command_runs_cycle(tmp_path):
    from unittest.mock import AsyncMock

    from mi_dream.cli.repl import REPL

    mgr = SessionManager(session_dir=tmp_path)
    repl = REPL(mgr)

    with (
        patch("mi_dream.cli.repl.run_learning_cycle", new=AsyncMock(return_value={})) as mock_cycle,
        patch("mi_dream.cli.repl.console"),
    ):
        await repl._handle_learn()

    mock_cycle.assert_awaited_once()


@pytest.mark.asyncio
async def test_repl_auto_learn_after_trace_threshold(tmp_path):
    from unittest.mock import AsyncMock, patch

    from mi_dream.cli.repl import REPL
    from mi_dream.config import settings

    mgr = SessionManager(session_dir=tmp_path)
    repl = REPL(mgr)

    with (
        patch.object(settings, "learn_trace_threshold", 2),
        patch("mi_dream.cli.repl.run_learning_cycle", new=AsyncMock(return_value={})) as mock_cycle,
    ):
        repl._traces_since_learn = 1
        await repl._maybe_auto_learn()
        mock_cycle.assert_not_awaited()

        repl._traces_since_learn = 2
        await repl._maybe_auto_learn()
        mock_cycle.assert_awaited_once()
        assert repl._traces_since_learn == 0


@pytest.mark.asyncio
async def test_repl_auto_compact_on_context_threshold(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch

    from mi_dream.cli.repl import REPL
    from mi_dream.config import settings

    mgr = SessionManager(session_dir=tmp_path)
    mgr.create("s1")
    for msg in ("a" * 100, "b" * 100, "c" * 100, "d" * 100):
        mgr.add_message("user", msg)
    repl = REPL(mgr)

    fake = MagicMock()
    fake.compact = AsyncMock(
        return_value=[
            {"role": "system", "content": "[Resumo] ABC"},
            {"role": "user", "content": "d" * 100},
        ]
    )
    fake.persist_episode = AsyncMock(return_value="ep-1")

    with (
        patch.object(settings, "compact_threshold_chars", 250),
        patch("mi_dream.cli.repl.ConversationCompactor", return_value=fake),
        patch(
            "mi_dream.cli.repl.run_learning_cycle",
            new=AsyncMock(return_value={}),
        ) as mock_cycle,
    ):
        await repl._maybe_auto_compact()

    fake.compact.assert_awaited_once()
    fake.persist_episode.assert_awaited_once()
    mock_cycle.assert_awaited_once()
    assert mgr.current().context[0]["role"] == "system"


@pytest.mark.asyncio
async def test_repl_auto_compact_no_op_below_threshold(tmp_path):
    from unittest.mock import AsyncMock, patch

    from mi_dream.cli.repl import REPL
    from mi_dream.config import settings

    mgr = SessionManager(session_dir=tmp_path)
    mgr.add_message("user", "oi")
    repl = REPL(mgr)

    with (
        patch.object(settings, "compact_threshold_chars", 250),
        patch("mi_dream.cli.repl.ConversationCompactor") as MockCompactor,
        patch("mi_dream.cli.repl.run_learning_cycle", new=AsyncMock()) as mock_cycle,
    ):
        await repl._maybe_auto_compact()

    MockCompactor.assert_not_called()
    mock_cycle.assert_not_awaited()


@pytest.mark.asyncio
async def test_repl_review_command_runs_daily_review(tmp_path):
    from unittest.mock import AsyncMock

    from mi_dream.cli.repl import REPL

    mgr = SessionManager(session_dir=tmp_path)
    repl = REPL(mgr)

    with (
        patch(
            "mi_dream.cli.repl.run_daily_review", new=AsyncMock(return_value={"date": "2026-08-07"})
        ) as mock_review,
        patch("mi_dream.cli.repl.console"),
    ):
        await repl._handle_review()

    mock_review.assert_awaited_once()
    assert "2026-08-07" in repl._reviewed_dates


@pytest.mark.asyncio
async def test_repl_run_prompt_success_saves_success_trace(tmp_path):
    from mi_dream.cli.repl import REPL
    from mi_dream.llm.client import LLMResponse

    mgr = SessionManager(session_dir=tmp_path)
    mgr.create("s1")
    repl = REPL(mgr)
    captured = {}

    async def fake_save(trace_id, content, metadata, driver):
        captured["metadata"] = metadata
        captured["content"] = content

    with (
        patch(
            "mi_dream.cli.repl.ask_llm_full",
            return_value=LLMResponse("oi", total_tokens=10, latency_ms=50),
        ),
        patch("mi_dream.cli.repl.save_reasoning_trace", new=fake_save),
        patch("mi_dream.cli.repl.render_message"),
        patch("mi_dream.cli.repl.render_status"),
        patch("mi_dream.cli.repl.console"),
    ):
        await repl._run_prompt("Skill", "brainstorming", "sys", "hello")

    assert captured["metadata"]["outcome"] == "success"
    assert captured["metadata"]["source"] == "skill"
    assert captured["metadata"]["name"] == "brainstorming"
    assert captured["metadata"]["tokens"] == 10
    assert repl._traces_since_learn == 1
    assert mgr.current().context[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_repl_run_prompt_failure_saves_failure_trace(tmp_path):
    from mi_dream.cli.repl import REPL

    mgr = SessionManager(session_dir=tmp_path)
    mgr.create("s1")
    repl = REPL(mgr)
    captured = {}

    async def fake_save(trace_id, content, metadata, driver):
        captured["metadata"] = metadata
        captured["content"] = content

    with (
        patch(
            "mi_dream.cli.repl.ask_llm_full", side_effect=ConnectionError("provider unreachable")
        ),
        patch("mi_dream.cli.repl.save_reasoning_trace", new=fake_save),
        patch("mi_dream.cli.repl.render_error") as mock_render_error,
        patch("mi_dream.cli.repl.render_message"),
        patch("mi_dream.cli.repl.render_status"),
        patch("mi_dream.cli.repl.console"),
    ):
        await repl._run_prompt("Skill", "brainstorming", "sys", "hello")

    assert captured["metadata"]["outcome"] == "failure"
    assert captured["metadata"]["error_type"] == "connection_error"
    assert "provider unreachable" in captured["metadata"]["error_message"]
    assert repl._traces_since_learn == 1
    mock_render_error.assert_called_once()
    assert mgr.current().context[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_repl_chat_failure_persists_and_continues(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from mi_dream.cli.repl import REPL
    from mi_dream.knowledge.router import ExecutionContext

    inputs = iter(["oi", "tchau"])

    async def fake_prompt(*args, **kwargs):
        try:
            return next(inputs)
        except StopIteration:
            raise SystemExit

    captured = []

    async def fake_save(trace_id, content, metadata, driver):
        captured.append(metadata)

    with (
        patch("mi_dream.cli.repl.PromptSession") as MockPS,
        patch("mi_dream.cli.repl.run_tool_loop", side_effect=ConnectionError("boom")) as mock_loop,
        patch("mi_dream.cli.repl.save_reasoning_trace", new=fake_save),
        patch(
            "mi_dream.cli.repl.recall_context",
            new=AsyncMock(return_value=ExecutionContext(goal="oi")),
        ),
        patch("mi_dream.cli.repl.run_learning_cycle", new=AsyncMock(return_value={})),
        patch("mi_dream.cli.repl.reviewed_dates", new=AsyncMock(return_value=set())),
        patch("mi_dream.cli.repl.render_error"),
        patch("mi_dream.cli.repl.console"),
    ):
        MockPS.return_value = MagicMock()
        MockPS.return_value.prompt_async = fake_prompt
        mgr = SessionManager(session_dir=tmp_path)
        mgr.create("s1")
        await REPL(mgr).run()

    assert mock_loop.call_count == 2
    assert len(captured) == 2
    assert all(m["outcome"] == "failure" for m in captured)
    assert all(m["error_type"] == "connection_error" for m in captured)
    assert all(m["source"] == "chat" for m in captured)


@pytest.mark.asyncio
async def test_repl_chat_runs_tool_loop_and_saves_trace(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from mi_dream.agents.loop import AgentResult
    from mi_dream.cli.repl import REPL
    from mi_dream.knowledge.router import ExecutionContext

    inputs = iter(["oi"])

    async def fake_prompt(*args, **kwargs):
        try:
            return next(inputs)
        except StopIteration:
            raise SystemExit

    captured = []

    async def fake_save(trace_id, content, metadata, driver):
        captured.append(metadata)

    async def fake_loop(system, user, history, toolbox=None, **kwargs):
        assert toolbox is not None
        assert "web_search" in system
        return AgentResult(
            content="resposta com ferramentas",
            iterations=2,
            tool_calls=1,
            total_tokens=12,
            latency_ms=7.0,
        )

    with (
        patch("mi_dream.cli.repl.PromptSession") as MockPS,
        patch("mi_dream.cli.repl.run_tool_loop", new=fake_loop),
        patch("mi_dream.cli.repl.save_reasoning_trace", new=fake_save),
        patch(
            "mi_dream.cli.repl.recall_context",
            new=AsyncMock(return_value=ExecutionContext(goal="oi")),
        ),
        patch("mi_dream.cli.repl.run_learning_cycle", new=AsyncMock(return_value={})),
        patch("mi_dream.cli.repl.reviewed_dates", new=AsyncMock(return_value=set())),
        patch("mi_dream.cli.repl.render_message"),
        patch("mi_dream.cli.repl.render_status"),
        patch("mi_dream.cli.repl.console"),
    ):
        MockPS.return_value = MagicMock()
        MockPS.return_value.prompt_async = fake_prompt
        mgr = SessionManager(session_dir=tmp_path)
        mgr.create("s1")
        await REPL(mgr).run()

    last = mgr.current().context[-1]
    assert last["role"] == "assistant"
    assert last["content"] == "resposta com ferramentas"
    assert captured[0]["outcome"] == "success"
    assert captured[0]["source"] == "chat"
    assert captured[0]["tokens"] == 12


@pytest.mark.asyncio
async def test_repl_handle_failures_renders(tmp_path):
    from unittest.mock import AsyncMock

    from mi_dream.cli.repl import REPL
    from mi_dream.config import settings

    mgr = SessionManager(session_dir=tmp_path)
    repl = REPL(mgr)
    fake = [
        {
            "id": "t1",
            "error_type": "api_error",
            "source": "skill",
            "error_message": "boom",
            "tokens": 9,
            "created_at": "2026-08-07T10:00:00Z",
        }
    ]

    with (
        patch("mi_dream.cli.repl.get_failures", new=AsyncMock(return_value=fake)) as mock_get,
        patch("mi_dream.cli.repl.render_failures") as mock_render,
        patch("mi_dream.cli.repl.console"),
    ):
        await repl._handle_failures("api_error")

    mock_get.assert_awaited_once()
    assert mock_get.call_args.args[0] == settings.tenant_id
    assert mock_get.call_args.kwargs["error_type"] == "api_error"
    mock_render.assert_called_once_with(fake)


@pytest.mark.asyncio
async def test_repl_handle_failures_empty(tmp_path):
    from unittest.mock import AsyncMock

    from mi_dream.cli.repl import REPL

    mgr = SessionManager(session_dir=tmp_path)
    repl = REPL(mgr)

    with (
        patch("mi_dream.cli.repl.get_failures", new=AsyncMock(return_value=[])),
        patch("mi_dream.cli.repl.console") as mock_console,
    ):
        await repl._handle_failures("")

    assert "No failures" in mock_console.print.call_args.args[0]


@pytest.mark.asyncio
async def test_repl_handle_patterns_renders(tmp_path):
    from unittest.mock import AsyncMock

    from mi_dream.cli.repl import REPL
    from mi_dream.config import settings

    mgr = SessionManager(session_dir=tmp_path)
    repl = REPL(mgr)
    fake = [
        {
            "id": "fp1",
            "error_type": "rate_limit_error",
            "domain": "general",
            "pattern": "Too Many Requests",
            "failure_count": 5,
            "last_seen": "2026-08-07T10:00:00Z",
        }
    ]

    with (
        patch(
            "mi_dream.cli.repl.get_failure_patterns", new=AsyncMock(return_value=fake)
        ) as mock_get,
        patch("mi_dream.cli.repl.render_failure_patterns") as mock_render,
        patch("mi_dream.cli.repl.console"),
    ):
        await repl._handle_patterns("rate_limit_error")

    mock_get.assert_awaited_once()
    assert mock_get.call_args.args[0] == settings.tenant_id
    assert mock_get.call_args.kwargs["error_type"] == "rate_limit_error"
    mock_render.assert_called_once_with(fake)


@pytest.mark.asyncio
async def test_repl_handle_patterns_empty(tmp_path):
    from unittest.mock import AsyncMock

    from mi_dream.cli.repl import REPL

    mgr = SessionManager(session_dir=tmp_path)
    repl = REPL(mgr)

    with (
        patch("mi_dream.cli.repl.get_failure_patterns", new=AsyncMock(return_value=[])),
        patch("mi_dream.cli.repl.console") as mock_console,
    ):
        await repl._handle_patterns("")

    assert "No failure patterns" in mock_console.print.call_args.args[0]
