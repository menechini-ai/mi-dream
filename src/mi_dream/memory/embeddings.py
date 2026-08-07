from mi_dream.config import settings


def build_embedder():
    """Build the embedding provider used by the vector retriever and the
    Distiller (SDD §6 recall_strategy, §4.1.6).

    Priority: SentenceTransformers (local, no server) → Ollama (local server)
    → OpenAI-compatible (needs creds). Falls back gracefully if provider fails.
    """
    base_url = settings.embedding_base_url or settings.llm_base_url or ""

    # 1. SentenceTransformers — local inference, no server, no API key
    try:
        from neo4j_graphrag.embeddings import SentenceTransformerEmbeddings
        return SentenceTransformerEmbeddings(model=settings.embedding_model)
    except ImportError:
        pass

    # 2. Ollama — local server, no API key
    if "ollama" in base_url.lower() or ":11434" in base_url:
        try:
            from neo4j_graphrag.embeddings import OllamaEmbeddings
            return OllamaEmbeddings(model=settings.embedding_model, base_url=base_url)
        except ImportError:
            pass

    # 3. OpenAI-compatible — needs base_url + API key
    if base_url and (settings.embedding_api_key or settings.llm_api_key):
        from neo4j_graphrag.embeddings import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model=settings.embedding_model,
            base_url=base_url,
            api_key=settings.embedding_api_key or settings.llm_api_key,
        )

    raise ImportError(
        "No embedding provider available. "
        "Install: pip install sentence-transformers torch, "
        "or configure EMBEDDING_BASE_URL + EMBEDDING_API_KEY."
    )
