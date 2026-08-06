from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class StrategyState(StrEnum):
    EXPERIMENTAL = "EXPERIMENTAL"
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    DEPRECATED = "DEPRECATED"


class CuratorDecision(StrEnum):
    CREATE = "CREATE"
    REINFORCE = "REINFORCE"
    REFINE = "REFINE"
    CONTRADICT = "CONTRADICT"


VALID_TRANSITIONS: dict[StrategyState, list[StrategyState]] = {
    StrategyState.EXPERIMENTAL: [StrategyState.ACTIVE, StrategyState.ARCHIVED],
    StrategyState.ACTIVE: [StrategyState.STALE, StrategyState.SUPERSEDED, StrategyState.DEPRECATED],
    StrategyState.STALE: [StrategyState.ACTIVE, StrategyState.ARCHIVED],
    StrategyState.SUPERSEDED: [StrategyState.ARCHIVED],
    StrategyState.ARCHIVED: [],
    StrategyState.DEPRECATED: [],
}


class StrategyCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: str
    domain: str = Field(..., max_length=100)
    content: str
    tenant_id: str = "default"


class Strategy(StrategyCreate):
    id: str
    state: StrategyState = StrategyState.EXPERIMENTAL
    support_count: int = 0
    success_rate: float = 0.0
    created_at: datetime
    updated_at: datetime
    superseded_by: str | None = None
    score: float | None = None  # preenchido pelo recall vetorial (cosine similarity)

    model_config = {"from_attributes": True}

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def coerce_neo4j_datetime(cls, v):
        """Coerce neo4j.time.DateTime (exposed by the Bolt driver) to datetime."""
        if hasattr(v, "to_native"):
            return v.to_native()
        return v


class Lesson(BaseModel):
    """Nó de primeira classe no grafo desde a Fase 1 (SDD §4.1.2).

    Criado pelo Reflector/scheduler com a relação
    (l:Lesson)-[:DERIVED_FROM]->(t:ReasoningTrace).
    """

    id: str
    summary: str
    decision: CuratorDecision
    source_trace_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    tenant_id: str = "default"


def now_utc() -> datetime:
    return datetime.now(UTC)
