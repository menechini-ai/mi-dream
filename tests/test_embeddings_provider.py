"""Tests for embedding provider selection (SentenceTransformers → Ollama → OpenAI)."""

import importlib
from unittest.mock import MagicMock, patch

import pytest


# --- build_embedder provider priority ---


def test_build_embedder_uses_sentence_transformers_when_available():
    """SentenceTransformers is tried first."""
    mock_st = MagicMock()
    mock_st.return_value = mock_st

    with patch.dict("sys.modules", {"neo4j_graphrag.embeddings.sentence_transformers": MagicMock()}):
        import mi_dream.memory.embeddings as emb
        importlib.reload(emb)
        with patch.object(emb, "SentenceTransformerEmbeddings", return_value=mock_st) as mock_cls:
            with patch.object(emb, "settings") as ms:
                ms.embedding_model = "all-MiniLM-L6-v2"
                result = emb.build_embedder()
                mock_cls.assert_called_once_with(model="all-MiniLM-L6-v2")


def test_build_embedder_falls_back_to_ollama():
    """When SentenceTransformers is not installed, falls back to Ollama if base_url matches."""
    mock_ollama = MagicMock()
    mock_ollama.return_value = mock_ollama

    # Simulate SentenceTransformers not available (ImportError)
    fake_modules = {
        "neo4j_graphrag.embeddings": MagicMock(),
        "neo4j_graphrag.embeddings.sentence_transformers": None,
    }

    with patch.dict("sys.modules", fake_modules):
        import mi_dream.memory.embeddings as emb
        importlib.reload(emb)
        with patch.object(emb, "OllamaEmbeddings", return_value=mock_ollama) as mock_cls:
            with patch.object(emb, "settings") as ms:
                ms.embedding_model = "nomic-embed-text"
                ms.embedding_base_url = "http://localhost:11434"
                ms.embedding_api_key = None
                ms.llm_api_key = None
                result = emb.build_embedder()
                mock_cls.assert_called_once_with(
                    model="nomic-embed-text",
                    base_url="http://localhost:11434",
                )


def test_build_embedder_falls_back_to_openai_compatible():
    """When local providers unavailable, uses OpenAI-compatible with base_url + key."""
    mock_openai = MagicMock()
    mock_openai.return_value = mock_openai

    fake_modules = {
        "neo4j_graphrag.embeddings": MagicMock(),
        "neo4j_graphrag.embeddings.sentence_transformers": None,
        "neo4j_graphrag.embeddings.ollama": None,
    }

    with patch.dict("sys.modules", fake_modules):
        import mi_dream.memory.embeddings as emb
        importlib.reload(emb)
        with patch.object(emb, "OpenAIEmbeddings", return_value=mock_openai) as mock_cls:
            with patch.object(emb, "settings") as ms:
                ms.embedding_model = "text-embedding-3-small"
                ms.embedding_base_url = "http://localhost:20128/v1"
                ms.embedding_api_key = "sk-test"
                ms.llm_api_key = None
                result = emb.build_embedder()
                mock_cls.assert_called_once_with(
                    model="text-embedding-3-small",
                    base_url="http://localhost:20128/v1",
                    api_key="sk-test",
                )


def test_build_embedder_raises_when_no_provider():
    """Raises ImportError when no provider is available."""
    fake_modules = {
        "neo4j_graphrag.embeddings": MagicMock(),
        "neo4j_graphrag.embeddings.sentence_transformers": None,
        "neo4j_graphrag.embeddings.ollama": None,
        "neo4j_graphrag.embeddings.openai": None,
    }

    with patch.dict("sys.modules", fake_modules):
        import mi_dream.memory.embeddings as emb
        importlib.reload(emb)
        with patch.object(emb, "settings") as ms:
            ms.embedding_model = "any"
            ms.embedding_base_url = None
            ms.llm_base_url = None
            ms.embedding_api_key = None
            ms.llm_api_key = None
            with pytest.raises(ImportError, match="No embedding provider available"):
                emb.build_embedder()


# --- _embed graceful degradation ---


def test_embed_returns_none_on_failure():
    """_embed returns None when build_embedder fails — trace still gets saved."""
    from mi_dream.agents.tools import _embed

    with patch("mi_dream.agents.tools.build_embedder", side_effect=ImportError("no provider")):
        result = _embed("hello world")
        assert result is None


@pytest.mark.asyncio
async def test_save_trace_without_embedding_still_persists():
    """save_reasoning_trace must persist the node even when _embed returns None."""
    from mi_dream.agents.tools import save_reasoning_trace

    mock_session = AsyncMock()
    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=_mock_async_cm(mock_session))

    with patch("mi_dream.agents.tools.get_driver", return_value=mock_driver):
        with patch("mi_dream.agents.tools._embed", return_value=None):
            await save_reasoning_trace(
                "t1", "test content", {"outcome": "success"}, mock_driver,
                tenant_id="default",
            )

    assert mock_session.run.called
    # Cypher should NOT contain setNodeVectorProperty when no embedding
    cypher = str(mock_session.run.call_args[0][0])
    assert "setNodeVectorProperty" not in cypher
    assert "embedding" not in cypher


def _mock_async_cm(result):
    from unittest.mock import AsyncMock
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=result)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm
