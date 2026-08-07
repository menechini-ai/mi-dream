import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from conftest import FakeAsyncIter
from typer.testing import CliRunner

from mi_dream.cli.app import app

runner = CliRunner()


def _noop_coroutine():
    async def _noop():
        return None

    return _noop()


def test_chat_invokes_repl():
    with patch("mi_dream.cli.app.REPL") as MockREPL, \
         patch("mi_dream.cli.app.SessionManager") as MockSM:
        mock_mgr = MagicMock()
        MockSM.return_value = mock_mgr
        mock_repl = MagicMock()
        mock_repl.run.return_value = _noop_coroutine()
        MockREPL.return_value = mock_repl

        result = runner.invoke(app, ["chat", "--session", "test"])
        assert result.exit_code == 0
        mock_repl.run.assert_called_once()


def test_chat_default_session():
    with patch("mi_dream.cli.app.REPL") as MockREPL, \
         patch("mi_dream.cli.app.SessionManager") as MockSM:
        mock_mgr = MagicMock()
        MockSM.return_value = mock_mgr
        mock_repl = MagicMock()
        mock_repl.run.return_value = _noop_coroutine()
        MockREPL.return_value = mock_repl

        result = runner.invoke(app, ["chat"])
        assert result.exit_code == 0
        mock_mgr.resume.assert_called_once_with("default")


def test_sessions_lists_sessions():
    with patch("mi_dream.cli.app.SessionManager") as MockSM:
        mock_mgr = MagicMock()
        mock_mgr.list_sessions.return_value = ["s1", "s2"]
        MockSM.return_value = mock_mgr

        result = runner.invoke(app, ["sessions"])
        assert result.exit_code == 0
        assert "s1" in result.stdout
        assert "s2" in result.stdout


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "chat" in result.stdout
    assert "sessions" in result.stdout
    assert "init" in result.stdout
    assert "reflect" in result.stdout
    assert "distill" in result.stdout
    assert "curator" in result.stdout
    assert "learn" in result.stdout
    assert "review" in result.stdout


def test_init_bootstraps_schema():
    from unittest.mock import AsyncMock

    with patch("mi_dream.memory.bootstrap.bootstrap_schema") as mock_bs:
        mock_bs.return_value = AsyncMock()
        result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "Schema bootstrapped" in result.stdout
    mock_bs.assert_called_once()


def test_reflect_runs_cycle():
    async def fake_run():
        return {"traces_processed": 3, "lessons_created": 1}

    with patch(
        "mi_dream.learning.scheduler.ReflectionScheduler",
        return_value=MagicMock(run_cycle=fake_run),
    ):
        result = runner.invoke(app, ["reflect"])
    assert result.exit_code == 0
    assert "traces_processed" in result.stdout
    assert "lessons_created" in result.stdout


def test_distill_runs_pipeline():
    from unittest.mock import AsyncMock

    from conftest import make_driver_mock

    mock_session = AsyncMock()
    mock_session.run.return_value = FakeAsyncIter([])
    mock_distiller = MagicMock()
    mock_distiller.pending_lessons = AsyncMock(return_value=[])
    mock_distiller.distill = AsyncMock(return_value=[])

    with patch(
        "mi_dream.knowledge.distiller.KnowledgeDistiller", return_value=mock_distiller
    ), patch(
        "mi_dream.memory.connection.get_driver", return_value=make_driver_mock(mock_session)
    ):
        result = runner.invoke(app, ["distill"])
    assert result.exit_code == 0
    assert "Distill:" in result.stdout
    mock_distiller.pending_lessons.assert_awaited_once()
    mock_distiller.distill.assert_awaited_once()


def test_curator_reports():
    from unittest.mock import AsyncMock

    from conftest import make_driver_mock

    mock_session = AsyncMock()

    async def mock_run(query, **kwargs):
        if "RETURN count" in query or query.strip().startswith("MATCH (s:Strategy {id:"):
            r = AsyncMock()
            r.single.return_value = {"count": 0}
            return r
        return FakeAsyncIter([])

    mock_session.run.side_effect = mock_run

    with patch(
        "mi_dream.memory.connection.get_driver", return_value=make_driver_mock(mock_session)
    ):
        result = runner.invoke(app, ["curator", "--tenant", "default"])
    assert result.exit_code == 0
    assert "Integrity violations: 0" in result.stdout
    assert "State machine" in result.stdout


def test_learn_runs_cycle_once():
    from unittest.mock import AsyncMock

    with patch(
        "mi_dream.cli.app.run_learning_cycle",
        new=AsyncMock(return_value={"reflection": {}, "distill": {}, "curator": {}}),
    ) as mock_cycle:
        result = runner.invoke(app, ["learn", "--once"])

    assert result.exit_code == 0
    assert "Learn:" in result.stdout
    mock_cycle.assert_awaited_once()


def test_review_runs_once():
    from unittest.mock import AsyncMock

    with patch(
        "mi_dream.cli.app.run_daily_review",
        new=AsyncMock(return_value={"date": "2026-08-07", "health": {"ok": True}}),
    ) as mock_review:
        result = runner.invoke(app, ["review", "--once"])

    assert result.exit_code == 0
    assert "Daily review" in result.stdout
    mock_review.assert_awaited_once()


