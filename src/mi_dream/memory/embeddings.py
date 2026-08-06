from neo4j_graphrag.embeddings import OpenAIEmbeddings

from mi_dream.config import settings


def build_embedder() -> OpenAIEmbeddings:
    """Build the embedding provider used by the vector retriever and the
    Distiller (SDD §6 recall_strategy, §4.1.6).

    Reuses the OpenAI-compatible proxy endpoint configured for the LLM unless
    ``EMBEDDING_BASE_URL`` / ``EMBEDDING_API_KEY`` are set explicitly.
    """
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        base_url=settings.embedding_base_url or settings.llm_base_url,
        api_key=settings.embedding_api_key or settings.llm_api_key,
    )
