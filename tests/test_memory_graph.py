"""Tests for memory graph linking: trace embeddings, semantic recall, domain filter removal."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mi_dream.cli.repl import recall_context, _semantic_traces, _recent_traces
from mi_dream.knowledge.router import ExecutionContext


# --- recall_context: semantic traces are searched ---


@pytest.mark.asyncio
async def test_recall_context_searches_semantic_traces():
    """recall_context must call vector search for traces, not just recent_traces."""
    mock_rec = MagicMock()
    mock_rec.__getitem__ = lambda self, k: {
        "id": "t1", "content": "hello", "outcome": "success", "tenant_id": "default",
        "created_at": "2026-01-01", "goal": "test",
    }[k]
    mock_result = AsyncMock()
    mock_result.__aiter__ = lambda self: self
    mock_result.__anext__ = AsyncMock(side_effect=[mock_rec, StopAsyncIteration()])
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.cli.repl.get_driver", return_value=mock_driver):
        with patch("mi_dream.cli.repl.StrategyRouter") as MockRouter:
            mock_ctx = ExecutionContext(goal="test")
            MockRouter.return_value.retrieve = AsyncMock(return_value=mock_ctx)
            ctx = await recall_context("Qual meu nome?")

    # _semantic_traces must have been called (vector query on trace_embedding index)
    calls = [str(c) for c in mock_session.run.call_args_list]
    assert any("trace_embedding" in c for c in calls), (
        "recall_context did not search trace_embedding index"
    )
    assert len(ctx.recent_traces) == 1


@pytest.mark.asyncio
async def test_recall_context_merges_semantic_and_recent():
    """recall_context merges semantic + recent traces, dedupes by id."""
    # semantic returns t1, recent returns t2
    t1 = {"id": "t1", "content": "semantic match"}
    t2 = {"id": "t2", "content": "recent"}

    def session_run_side_effect(query, *args, **kwargs):
        if "trace_embedding" in query:
            # semantic
            rec = MagicMock()
            rec.__getitem__ = lambda self, k: t1[k]
            result = AsyncMock()
            result.__aiter__ = lambda self: self
            result.__anext__ = AsyncMock(side_effect=[rec, StopAsyncIteration()])
            return result
        else:
            # recent_traces
            rec = MagicMock()
            rec.__getitem__ = lambda self, k: t2[k]
            result = AsyncMock()
            result.__aiter__ = lambda self: self
            result.__anext__ = AsyncMock(side_effect=[rec, StopAsyncIteration()])
            return result

    mock_session = AsyncMock()
    mock_session.run = AsyncMock(side_effect=session_run_side_effect)
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.cli.repl.get_driver", return_value=mock_driver):
        with patch("mi_dream.cli.repl.StrategyRouter") as MockRouter:
            mock_ctx = ExecutionContext(goal="test")
            MockRouter.return_value.retrieve = AsyncMock(return_value=mock_ctx)
            ctx = await recall_context("test")

    ids = [t["id"] for t in ctx.recent_traces]
    assert ids == ["t1", "t2"], f"Expected merged order [t1, t2], got {ids}"


@pytest.mark.asyncio
async def test_recall_context_dedupes_duplicate_traces():
    """If same trace appears in both semantic and recent, it appears only once."""
    t = {"id": "t1", "content": "same trace"}

    def session_run_side_effect(query, *args, **kwargs):
        rec = MagicMock()
        rec.__getitem__ = lambda self, k: t[k]
        result = AsyncMock()
        result.__aiter__ = lambda self: self
        result.__anext__ = AsyncMock(side_effect=[rec, StopAsyncIteration()])
        return result

    mock_session = AsyncMock()
    mock_session.run = AsyncMock(side_effect=session_run_side_effect)
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.cli.repl.get_driver", return_value=mock_driver):
        with patch("mi_dream.cli.repl.StrategyRouter") as MockRouter:
            mock_ctx = ExecutionContext(goal="test")
            MockRouter.return_value.retrieve = AsyncMock(return_value=mock_ctx)
            ctx = await recall_context("test")

    assert len(ctx.recent_traces) == 1


@pytest.mark.asyncio
async def test_recall_context_graceful_on_trace_vector_failure():
    """If vector search fails for traces, recall still works with recent only."""
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(side_effect=RuntimeError("vector index missing"))
    mock_driver = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.cli.repl.get_driver", return_value=mock_driver):
        with patch("mi_dream.cli.repl.StrategyRouter") as MockRouter:
            mock_ctx = ExecutionContext(goal="test")
            MockRouter.return_value.retrieve = AsyncMock(return_value=mock_ctx)
            ctx = await recall_context("test")

    assert ctx.goal == "test"
    assert ctx.recent_traces == []


# --- trace_embedding index in bootstrap ---


def test_bootstrap_creates_trace_embedding_index():
    """bootstrap.py must CREATE VECTOR INDEX trace_embedding."""
    with open("src/mi_dream/memory/bootstrap.py") as f:
        content = f.read()

    assert "CREATE VECTOR INDEX trace_embedding" in content
    assert "ReasoningTrace" in content
    assert "embedding" in content


# --- save_reasoning_trace stores embedding ---


@pytest.mark.asyncio
async def test_save_reasoning_trace_stores_embedding():
    """save_reasoning_trace must persist embedding on the node."""
    from mi_dream.agents.tools import save_reasoning_trace

    mock_driver = AsyncMock()
    mock_session = AsyncMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.agents.tools.get_driver", return_value=mock_driver):
        with patch("mi_dream.agents.tools._embed") as mock_embed:
            mock_embed.return_value = [0.1, 0.2, 0.3]
            await save_reasoning_trace(
                "trace-1", "Qual meu nome?", {"outcome": "success"}, mock_driver,
                tenant_id="default",
            )

    # The Cypher must include embedding parameter and setNodeVectorProperty
    calls = [str(c) for c in mock_session.run.call_args_list]
    assert any("embedding" in c for c in calls), "embedding not passed to Cypher"
    assert any("setNodeVectorProperty" in c for c in calls), (
        "setNodeVectorProperty not in Cypher — embedding not persisted"
    )


# --- domain filter removed from vector search ---


def test_vector_search_no_domain_filter():
    """StrategyVectorRetriever must not filter by domain — domain filter kills relevant results."""
    import ast

    with open("src/mi_dream/knowledge/vector.py") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Find calls to retriever.search with filters
            if isinstance(func := node.func, ast.Attribute):
                if func.attr == "search":
                    for kw in node.keywords:
                        if kw.arg == "filters":
                            if isinstance(kw.value, ast.Dict):
                                keys = [k.value for k in kw.value.keys if isinstance(k, ast.Constant)]
                                assert "domain" not in [str(k) for k in keys], (
                                    "domain filter in vector search — removes relevant strategies"
                                )


def _mock_async_cm(result):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=result)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm
