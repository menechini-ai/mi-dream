import os
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from conftest import FakeAsyncIter

from mi_dream.knowledge.models import FailurePatternCreate


class FakeRecord:
    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]


def _fp(**overrides):
    data = {
        "id": "fp1",
        "error_type": "rate_limit_error",
        "domain": "general",
        "pattern": "Rate limit no provider",
        "tenant_id": "default",
        "failure_count": 3,
        "last_seen": "2026-08-07T00:00:00Z",
        "created_at": "2026-08-07T00:00:00Z",
        "signature": "sig1",
    }
    data.update(overrides)
    return data


def _single_session(record):
    session = AsyncMock()
    result = AsyncMock()
    result.single.return_value = record
    session.run.return_value = result
    return session


def _iter_session(records):
    session = AsyncMock()
    session.run.return_value = FakeAsyncIter(records)
    return session


def _repo(session):
    from mi_dream.knowledge.failure_patterns import FailurePatternRepository

    return FailurePatternRepository(session)


@pytest.mark.asyncio
async def test_create_persists_and_returns_model():
    session = _single_session(FakeRecord({"fp": _fp()}))
    repo = _repo(session)
    fp = await repo.create(
        FailurePatternCreate(
            error_type="rate_limit_error", domain="general",
            pattern="Rate limit no provider", tenant_id="default",
        )
    )
    assert fp.id == "fp1"
    assert fp.failure_count == 3
    query = session.run.call_args.args[0]
    assert "CREATE (p:FailurePattern" in query
    assert session.run.call_args.kwargs["tenant_id"] == "default"


@pytest.mark.asyncio
async def test_get_returns_model():
    session = _single_session(FakeRecord({"fp": _fp()}))
    repo = _repo(session)
    fp = await repo.get("fp1")
    assert fp is not None
    assert fp.error_type == "rate_limit_error"
    assert "MATCH (p:FailurePattern {id: $id})" in session.run.call_args.args[0]


@pytest.mark.asyncio
async def test_get_returns_none_when_missing():
    session = _single_session(None)
    repo = _repo(session)
    assert await repo.get("nope") is None


@pytest.mark.asyncio
async def test_list_by_domain_filters_tenant():
    session = _iter_session([FakeRecord({"fp": _fp()})])
    repo = _repo(session)
    rows = await repo.list_by_domain("general", "default")
    assert len(rows) == 1
    query = session.run.call_args.args[0]
    assert "{domain: $domain, tenant_id: $tenant_id}" in query
    assert session.run.call_args.kwargs["tenant_id"] == "default"


@pytest.mark.asyncio
async def test_list_by_error_type_filters():
    session = _iter_session([FakeRecord({"fp": _fp()})])
    repo = _repo(session)
    rows = await repo.list_by_error_type("rate_limit_error", "default")
    assert len(rows) == 1
    assert "error_type: $error_type" in session.run.call_args.args[0]


@pytest.mark.asyncio
async def test_increment_updates_count_and_last_seen():
    session = _single_session(FakeRecord({"fp": _fp(failure_count=4)}))
    repo = _repo(session)
    fp = await repo.increment("fp1")
    assert fp.failure_count == 4
    kwargs = session.run.call_args.kwargs
    assert kwargs["id"] == "fp1"


@pytest.mark.asyncio
async def test_link_trace_merges_relationship():
    session = AsyncMock()
    repo = _repo(session)
    await repo.link_trace("t1", "fp1")
    query = session.run.call_args.args[0]
    assert "ATTRIBUTED_TO" in query
    assert "MERGE" in query
    assert session.run.call_args.kwargs["trace_id"] == "t1"
    assert session.run.call_args.kwargs["pattern_id"] == "fp1"


@pytest.mark.asyncio
async def test_attributed_trace_ids_returns_set():
    session = _iter_session(
        [
            FakeRecord({"trace_id": "t1"}),
            FakeRecord({"trace_id": "t2"}),
            FakeRecord({"trace_id": "t1"}),
        ]
    )
    repo = _repo(session)
    ids = await repo.attributed_trace_ids("default")
    assert ids == {"t1", "t2"}
    assert "ATTRIBUTED_TO" in session.run.call_args.args[0]


@pytest.mark.asyncio
async def test_find_by_signature_matches_tenant():
    session = _single_session(FakeRecord({"fp": _fp()}))
    repo = _repo(session)
    fp = await repo.find_by_signature("sig1", "default")
    assert fp is not None
    kwargs = session.run.call_args.kwargs
    assert kwargs["signature"] == "sig1"
    assert kwargs["tenant_id"] == "default"
