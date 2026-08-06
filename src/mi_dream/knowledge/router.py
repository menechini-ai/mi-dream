from dataclasses import dataclass, field
from typing import Any

from mi_dream.knowledge.models import Strategy, StrategyState
from mi_dream.knowledge.repository import StrategyRepository


@dataclass
class ExecutionContext:
    goal: str
    entities: list[dict] = field(default_factory=list)
    strategies: list[Strategy] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    previous_failures: list[dict] = field(default_factory=list)
    best_practices: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "entities": self.entities,
            "strategies": [s.model_dump(mode="json") for s in self.strategies],
            "constraints": self.constraints,
            "capabilities": self.capabilities,
            "previous_failures": self.previous_failures,
            "best_practices": self.best_practices,
        }

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict())


class StrategyRouter:
    def __init__(self, repo: StrategyRepository, vector_retriever=None, top_k: int = 5):
        self._repo = repo
        self._vector = vector_retriever
        self._top_k = top_k

    async def retrieve(
        self, goal: str, context: dict[str, Any], tenant_id: str
    ) -> ExecutionContext:
        domain = context.get("domain", "general")

        strategies = []
        if self._vector is not None:
            try:
                strategies = await self._vector.search(goal, tenant_id, domain, self._top_k)
            except Exception:
                strategies = []

        if not strategies:
            strategies = await self._repo.list_by_domain(
                domain=domain, tenant_id=tenant_id, state=StrategyState.ACTIVE
            )

        if not strategies:
            return ExecutionContext(goal=goal)

        return ExecutionContext(
            goal=goal,
            entities=context.get("entities", []),
            strategies=strategies,
            constraints=context.get("constraints", []),
            capabilities=context.get("capabilities", []),
            previous_failures=context.get("previous_failures", []),
            best_practices=context.get("best_practices", []),
        )
