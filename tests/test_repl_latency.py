"""Tests for non-blocking response flow in REPL (all 3 entry points)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mi_dream.cli.repl import REPL


def _make_repl():
    repl = REPL.__new__(REPL)
    repl._session_mgr = MagicMock()
    repl._session_mgr.current.return_value.context = []
    repl._session_mgr.add_message = MagicMock()
    repl._running = False
    repl._auto_learn_task = None
    repl._daily_review_task = None
    repl._traces_since_learn = 0
    repl._cron_mgr = MagicMock()
    return repl


class FakeResponse:
    content = "fake answer"
    total_tokens = 10
    prompt_tokens = 5
    completion_tokens = 5
    latency_ms = 100.0


# --- _run_prompt (agent/skill mode) ---


@pytest.mark.asyncio
async def test_run_prompt_success_schedules_background():
    repl = _make_repl()

    with patch.object(repl, "_ask_with_tools", return_value=FakeResponse()):
        with patch.object(repl, "_post_response") as mock_post:
            await repl._run_prompt("Agent", "name", "prompt", "hi")

    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_run_prompt_error_schedules_background():
    repl = _make_repl()

    with patch.object(repl, "_ask_with_tools", side_effect=RuntimeError("llm down")):
        with patch.object(repl, "_post_response") as mock_post:
            with patch("mi_dream.cli.repl.render_error"):
                await repl._run_prompt("Agent", "name", "prompt", "hi")

    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_post_response_trace_failure_does_not_block():
    call_order = []

    async def failing_trace(*args, **kwargs):
        call_order.append("trace")
        raise RuntimeError("neo4j down")

    async def fake_learn(*args, **kwargs):
        call_order.append("learn")

    async def fake_compact(*args, **kwargs):
        call_order.append("compact")

    repl = _make_repl()
    with patch.object(repl, "_trace_outcome", side_effect=failing_trace):
        with patch.object(repl, "_maybe_auto_learn", side_effect=fake_learn):
            with patch.object(repl, "_maybe_auto_compact", side_effect=fake_compact):
                await repl._post_response(
                    "agent", "name", "user", "assistant", "success"
                )

    assert "trace" in call_order
    assert "learn" in call_order
    assert "compact" in call_order


@pytest.mark.asyncio
async def test_post_response_returns_immediately():
    """_post_response itself returns quickly — it just schedules background work."""
    repl = _make_repl()

    with patch.object(repl, "_trace_outcome"):
        with patch.object(repl, "_maybe_auto_learn"):
            with patch.object(repl, "_maybe_auto_compact"):
                start = asyncio.get_event_loop().time()
                await repl._post_response(
                    "agent", "name", "user", "assistant", "success"
                )
                elapsed = asyncio.get_event_loop().time() - start

    assert elapsed < 1.0, f"_post_response took {elapsed}s, should be near-instant"


# --- Structural verification: all 3 call sites use create_task ---


def test_all_callers_use_create_task():
    """Verify _post_response is only called via asyncio.create_task, never awaited directly."""
    import ast

    with open("src/mi_dream/cli/repl.py") as f:
        tree = ast.parse(f.read())

    # Find all await self._post_response(...) calls — these are BAD
    bad_awaits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Await):
            # Check if the awaited call is _post_response
            func = node.value
            if isinstance(func, ast.Call):
                if (
                    isinstance(func.func, ast.Attribute)
                    and func.func.attr == "_post_response"
                ):
                    bad_awaits.append(node.lineno)

    # Find all asyncio.create_task(self._post_response(...)) — these are GOOD
    good_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(func := node.func, ast.Attribute):
                if (
                    func.attr == "create_task"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "asyncio"
                ):
                    if node.args and isinstance(node.args[0], ast.Call):
                        call = node.args[0]
                        if (
                            isinstance(call.func, ast.Attribute)
                            and call.func.attr == "_post_response"
                        ):
                            good_calls.append(node.lineno)

    assert bad_awaits == [], (
        f"Direct await _post_response found at lines {bad_awaits} — "
        "should use asyncio.create_task instead"
    )
    assert len(good_calls) >= 3, (
        f"Expected at least 3 asyncio.create_task(_post_response) calls, found {len(good_calls)} at lines {good_calls}"
    )
