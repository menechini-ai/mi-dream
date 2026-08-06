import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest

from mi_dream.knowledge.curator import Curator
from mi_dream.memory.reasoning import trace_fingerprint


class FakeAsyncIter:
    def __init__(self, items):
        self._items = items
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._i]
        self._i += 1
        return item


def test_trace_fingerprint_is_deterministic():
    a = trace_fingerprint("content", "success", '{"tenant_id": "default"}')
    b = trace_fingerprint("content", "success", '{"tenant_id": "default"}')
    assert a == b
    assert len(a) == 64


def test_trace_fingerprint_accepts_dict_and_string_identically():
    d = trace_fingerprint("c", "success", {"outcome": "success", "tenant_id": "t1"})
    s = trace_fingerprint("c", "success", '{"outcome":"success","tenant_id":"t1"}')
    assert d == s


def test_trace_fingerprint_canonicalizes_key_order():
    a = trace_fingerprint("c", "s", {"tenant_id": "t1", "outcome": "success"})
    b = trace_fingerprint("c", "s", {"outcome": "success", "tenant_id": "t1"})
    assert a == b


def test_trace_fingerprint_changes_with_content():
    a = trace_fingerprint("original", "success", '{"tenant_id": "default"}')
    b = trace_fingerprint("mutated", "success", '{"tenant_id": "default"}')
    assert a != b


@pytest.mark.asyncio
async def test_save_reasoning_trace_stores_content_hash():
    from mi_dream.agents.tools import save_reasoning_trace

    driver = MagicMock()
    session = AsyncMock()
    session.__aenter__.return_value = session
    driver.session.return_value = session

    metadata = {"tenant_id": "t1", "outcome": "success"}
    await save_reasoning_trace("tr-1", "the reasoning", metadata, driver)

    query = session.run.call_args.args[0]
    assert "content_hash" in query
    stored = session.run.call_args.kwargs["content_hash"]
    meta = session.run.call_args.kwargs["metadata"]
    assert stored == trace_fingerprint("the reasoning", "success", meta)


@pytest.mark.asyncio
async def test_save_reasoning_trace_accepts_serialized_metadata():
    from mi_dream.agents.tools import save_reasoning_trace

    driver = MagicMock()
    session = AsyncMock()
    session.__aenter__.return_value = session
    driver.session.return_value = session

    await save_reasoning_trace(
        "tr-3", "the reasoning", '{"tenant_id": "t1", "outcome": "success"}', driver
    )

    kwargs = session.run.call_args.kwargs
    assert kwargs["metadata"] == '{"outcome":"success","tenant_id":"t1"}'
    expected = trace_fingerprint("the reasoning", "success", kwargs["metadata"])
    assert kwargs["content_hash"] == expected


@pytest.mark.asyncio
async def test_save_tool_stores_content_hash():
    from mi_dream.agents.tools import make_save_reasoning_trace_tool

    tool = make_save_reasoning_trace_tool(tenant_id="t1")

    session = AsyncMock()
    session.__aenter__.return_value = session
    driver = MagicMock()
    driver.session.return_value = session

    with patch("mi_dream.agents.tools.get_driver", return_value=driver):
        await tool.ainvoke(
            {"trace_id": "tr-2", "content": "tool reasoning", "outcome": "success"}
        )

    query = session.run.call_args.args[0]
    assert "content_hash" in query
    stored = session.run.call_args.kwargs["content_hash"]
    meta = session.run.call_args.kwargs["metadata"]
    assert stored == trace_fingerprint("tool reasoning", "success", meta)


def _trace_record(trace_id, content, outcome, metadata, content_hash):
    rec = MagicMock()
    rec.__getitem__.side_effect = lambda k: {
        "trace_id": trace_id,
        "content": content,
        "outcome": outcome,
        "metadata": metadata,
        "content_hash": content_hash,
    }[k]
    return rec


@pytest.mark.asyncio
async def test_curator_flags_mutated_trace_invariant_001():
    session = AsyncMock()
    original_hash = trace_fingerprint(
        "original", "success", '{"tenant_id": "default"}'
    )
    session.run.return_value = FakeAsyncIter(
        [
            _trace_record("t1", "MUTATED", "success", '{"tenant_id": "default"}', original_hash),
            _trace_record("t2", "original", "success", '{"tenant_id": "default"}', original_hash),
        ]
    )
    curator = Curator(session)
    violations = await curator.check_trace_immutability("default")
    assert len(violations) == 1
    assert violations[0]["trace_id"] == "t1"
    assert "mutated" in violations[0]["reason"].lower()


@pytest.mark.asyncio
async def test_curator_flags_trace_missing_content_hash():
    session = AsyncMock()
    session.run.return_value = FakeAsyncIter(
        [
            _trace_record("t3", "content", "success", '{"tenant_id": "default"}', None),
        ]
    )
    curator = Curator(session)
    violations = await curator.check_trace_immutability("default")
    assert len(violations) == 1
    assert violations[0]["trace_id"] == "t3"
    assert "content_hash" in violations[0]["reason"]


@pytest.mark.asyncio
async def test_integrity_checks_include_trace_immutability():
    session = AsyncMock()
    record = {"orphaned_strategy": "s1", "reason": "ACTIVE without SUPPORTED_BY"}
    mock_rec = MagicMock()
    mock_rec.data.return_value = record
    session.run.return_value = FakeAsyncIter([mock_rec])
    curator = Curator(session)

    violations = await curator.run_integrity_checks("default")

    # at least the strategy violation + the trace-immutability pass
    assert any("SUPPORTED_BY" in v.get("reason", "") for v in violations)
    trace_queries = [
        c.args[0]
        for c in session.run.call_args_list
        if ":ReasoningTrace" in c.args[0]
    ]
    assert len(trace_queries) == 1
