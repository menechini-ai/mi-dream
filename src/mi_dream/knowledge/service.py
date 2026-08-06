from mi_dream.knowledge.models import VALID_TRANSITIONS, Strategy, StrategyState
from mi_dream.knowledge.repository import StrategyRepository


class StrategyService:
    def __init__(self, repo: StrategyRepository):
        self._repo = repo

    async def create(self, data) -> Strategy:
        return await self._repo.create(data)

    async def get(self, strategy_id: str) -> Strategy | None:
        return await self._repo.get(strategy_id)

    async def list_by_domain(self, domain: str, tenant_id: str) -> list[Strategy]:
        return await self._repo.list_by_domain(domain, tenant_id)

    async def promote_to_active(self, strategy_id: str) -> Strategy | None:
        s = await self._repo.get(strategy_id)
        if not s or s.state != StrategyState.EXPERIMENTAL:
            return None
        if s.support_count < 3 or s.success_rate < 0.6:
            return None
        return await self._repo.transition_state(strategy_id, StrategyState.ACTIVE)

    async def transition(self, strategy_id: str, new_state: StrategyState) -> Strategy | None:
        s = await self._repo.get(strategy_id)
        if not s:
            return None
        if new_state not in VALID_TRANSITIONS[s.state]:
            raise ValueError(f"Invalid transition: {s.state} -> {new_state}")
        return await self._repo.transition_state(strategy_id, new_state)

    async def supersede(self, strategy_id: str, successor_id: str) -> Strategy | None:
        s = await self._repo.get(strategy_id)
        if not s or s.state != StrategyState.ACTIVE:
            return None
        return await self._repo.mark_superseded(strategy_id, successor_id)
