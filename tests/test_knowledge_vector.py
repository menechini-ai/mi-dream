import os
import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from neo4j_graphrag.types import RetrieverResult, RetrieverResultItem

from mi_dream.knowledge.models import Strategy
from mi_dream.knowledge.vector import RETRIEVAL_QUERY, StrategyVectorRetriever


def _strategy_dict(**overrides):
    data = dict(
        id="s1", title="K8s debug", description="d", domain="kubernetes",
        content="Check pods first", state="ACTIVE",
        support_count=3, success_rate=0.7,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        tenant_id="default", superseded_by=None,
    )
    data.update(overrides)
    return data


def test_retrieval_query_projects_strategy_without_embedding():
    assert "node {.id, .title" in RETRIEVAL_QUERY
    assert "succ.id" in RETRIEVAL_QUERY
    assert "embedding" not in RETRIEVAL_QUERY


@pytest.mark.asyncio
async def test_search_builds_strategies_and_passes_filters():
    fake = MagicMock()

    def fake_search(query_text, top_k, filters):
        return RetrieverResult(
            items=[RetrieverResultItem(content="", metadata=_strategy_dict())]
        )

    fake.search.side_effect = fake_search
    vr = StrategyVectorRetriever(retriever=fake)

    results = await vr.search("diagnose k8s", "default", "kubernetes")

    assert len(results) == 1
    assert isinstance(results[0], Strategy)
    assert results[0].title == "K8s debug"
    fake.search.assert_called_once()
    kwargs = fake.search.call_args.kwargs
    assert kwargs["query_text"] == "diagnose k8s"
    assert kwargs["filters"] == {
        "tenant_id": "default",
        "state": "ACTIVE",
        "domain": "kubernetes",
    }


@pytest.mark.asyncio
async def test_search_returns_empty_on_no_items():
    fake = MagicMock()
    fake.search.return_value = RetrieverResult(items=[])
    vr = StrategyVectorRetriever(retriever=fake)
    assert await vr.search("x", "default", "kubernetes") == []


def test_result_formatter_includes_score_and_strategy():
    from mi_dream.knowledge.vector import _result_formatter

    record = MagicMock()
    record.get.side_effect = lambda k: _strategy_dict() if k == "strategy" else 0.87
    item = _result_formatter(record)
    assert item.metadata["score"] == 0.87
    assert item.metadata["title"] == "K8s debug"


def test_build_creates_cypher_retriever_with_index_and_query():
    with patch("mi_dream.knowledge.vector.VectorCypherRetriever") as VCR:
        vr = StrategyVectorRetriever()
        vr._build()
    assert VCR.call_count == 1
    _, kwargs = VCR.call_args
    assert kwargs["index_name"] == "strategy_embedding"
    assert kwargs["retrieval_query"] == RETRIEVAL_QUERY
    assert kwargs["result_formatter"] is not None
