import asyncio

from neo4j import GraphDatabase
from neo4j_graphrag.retrievers import VectorCypherRetriever
from neo4j_graphrag.types import RetrieverResultItem

from mi_dream.config import settings
from mi_dream.knowledge.models import Strategy
from mi_dream.memory.embeddings import build_embedder

RETRIEVAL_QUERY = """
OPTIONAL MATCH (node)-[:SUPERSEDES]->(succ:Strategy)
RETURN node {.id, .title, .description, .domain, .content, .state,
             .support_count, .success_rate, .created_at, .updated_at,
             .tenant_id, superseded_by: succ.id} AS strategy, score
"""


def _result_formatter(record) -> RetrieverResultItem:
    data = dict(record.get("strategy"))
    data["score"] = record.get("score")
    return RetrieverResultItem(content="", metadata=data)


class StrategyVectorRetriever:
    """Async adapter over neo4j-graphrag VectorCypherRetriever (SDD §6 recall_strategy).

    The underlying retriever is synchronous, so it runs in a worker thread via
    ``asyncio.to_thread``. The sync driver is created lazily on first search to
    keep construction side-effect free for tests and tooling.
    """

    def __init__(
        self,
        index_name: str = "strategy_embedding",
        top_k: int = 5,
        embedder=None,
        driver=None,
        database: str | None = None,
        retriever=None,
    ) -> None:
        self._index_name = index_name
        self._top_k = top_k
        self._database = database or settings.neo4j_database
        self._embedder = embedder
        self._driver = driver
        self._retriever = retriever
        self._owns_driver = False

    def _build(self) -> VectorCypherRetriever:
        if self._retriever is not None:
            return self._retriever
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            self._owns_driver = True
        if self._embedder is None:
            self._embedder = build_embedder()
        self._retriever = VectorCypherRetriever(
            driver=self._driver,
            index_name=self._index_name,
            retrieval_query=RETRIEVAL_QUERY,
            embedder=self._embedder,
            result_formatter=_result_formatter,
            neo4j_database=self._database,
        )
        if getattr(self._retriever, "_node_embedding_property", None) is None:
            self._retriever._node_embedding_property = getattr(
                self._retriever, "_embedding_node_property", None
            )
        return self._retriever

    async def search(
        self,
        goal: str,
        tenant_id: str,
        domain: str,
        top_k: int | None = None,
    ) -> list[Strategy]:
        retriever = self._build()
        result = await asyncio.to_thread(
            retriever.search,
            query_text=goal,
            top_k=top_k or self._top_k,
            filters={"tenant_id": tenant_id, "state": "ACTIVE", "domain": domain},
        )
        strategies = []
        for item in result.items:
            data = dict(item.metadata)
            strategies.append(Strategy(**data))
        return strategies

    async def close(self) -> None:
        if self._owns_driver and self._driver is not None:
            self._driver.close()
            self._driver = None
            self._retriever = None
