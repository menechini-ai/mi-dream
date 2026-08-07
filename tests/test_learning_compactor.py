import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from conftest import make_driver_mock


@pytest.mark.asyncio
async def test_compact_truncates_and_preserves_recent():
    from mi_dream.learning.compactor import ConversationCompactor

    messages = [
        {"role": "user", "content": m} for m in ("a" * 50, "b" * 50, "c" * 50, "d" * 50, "e" * 50)
    ]
    compactor = ConversationCompactor()
    with patch(
        "mi_dream.learning.compactor.ask_llm_full",
        return_value=MagicMock(content="RESUMO"),
    ):
        result = await compactor.compact(messages, threshold_chars=100, keep_recent=2)

    assert len(result) == 3
    assert result[0]["role"] == "system"
    assert "RESUMO" in result[0]["content"]
    assert result[-1] == messages[-1]


@pytest.mark.asyncio
async def test_compact_no_op_below_threshold():
    from mi_dream.learning.compactor import ConversationCompactor

    messages = [{"role": "user", "content": "oi"}]
    compactor = ConversationCompactor()
    result = await compactor.compact(messages, threshold_chars=100, keep_recent=2)
    assert result == messages


@pytest.mark.asyncio
async def test_persist_episode_creates_episode_and_trace():
    from mi_dream.learning.compactor import ConversationCompactor

    session = AsyncMock()
    driver = make_driver_mock(session)
    compactor = ConversationCompactor()
    with patch("mi_dream.learning.compactor.get_driver", return_value=driver):
        eid = await compactor.persist_episode("Usuário se chama Adilson", "sess-1", "default")

    queries = [c.args[0] for c in session.run.call_args_list]
    assert any("CREATE (e:Episode" in q for q in queries)
    assert any("CREATE (t:ReasoningTrace" in q for q in queries)
    assert eid.startswith("ep-")


@pytest.mark.asyncio
async def test_persist_episode_embeds_when_embedder_available():
    from mi_dream.learning.compactor import ConversationCompactor

    session = AsyncMock()
    driver = make_driver_mock(session)
    embedder = AsyncMock()
    embedder.embed_query.return_value = [0.1, 0.2]
    compactor = ConversationCompactor(embedder=embedder)
    with patch("mi_dream.learning.compactor.get_driver", return_value=driver):
        await compactor.persist_episode("resumo", "sess-1", "default")

    queries = [c.args[0] for c in session.run.call_args_list]
    assert any("e.embedding = $embedding" in q for q in queries)


@pytest.mark.asyncio
async def test_persist_episode_sanitizes_summary():
    from mi_dream.learning.compactor import ConversationCompactor

    session = AsyncMock()
    driver = make_driver_mock(session)
    compactor = ConversationCompactor()
    with patch("mi_dream.learning.compactor.get_driver", return_value=driver):
        await compactor.persist_episode(
            "meu email é a@b.com e tenho 123-45-6789", "sess-1", "default"
        )

    calls = session.run.call_args_list
    trace_calls = [c for c in calls if "CREATE (t:ReasoningTrace" in c.args[0]]
    assert len(trace_calls) == 1
    assert "[REDACTED]" in trace_calls[0].kwargs["content"]
