import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.knowledge.models import (
    VALID_TRANSITIONS,
    CuratorDecision,
    Lesson,
    Strategy,
    StrategyCreate,
    StrategyState,
)


class _Neo4jDateTime:
    """Fake neo4j.time.DateTime: carries to_native(), not a datetime subclass."""

    def __init__(self, dt):
        self._dt = dt

    def to_native(self):
        return self._dt

    def __repr__(self):
        return repr(self._dt)


def test_strategy_state_values():
    assert StrategyState.EXPERIMENTAL.value == "EXPERIMENTAL"
    assert StrategyState.ACTIVE.value == "ACTIVE"


def test_strategy_accepts_neo4j_datetime():
    dt = datetime.now(UTC)
    s = Strategy(
        id="s1", title="t", description="d", domain="dev", content="c",
        created_at=_Neo4jDateTime(dt), updated_at=_Neo4jDateTime(dt),
        tenant_id="default",
    )
    assert s.created_at == dt
    assert s.updated_at == dt


def test_strategy_accepts_native_datetime():
    dt = datetime.now(UTC)
    s = Strategy(
        id="s1", title="t", description="d", domain="dev", content="c",
        created_at=dt, updated_at=dt, tenant_id="default",
    )
    assert s.created_at == dt


def test_valid_transitions_experimental_to_active():
    assert StrategyState.ACTIVE in VALID_TRANSITIONS[StrategyState.EXPERIMENTAL]


def test_valid_transitions_archived_is_terminal():
    assert VALID_TRANSITIONS[StrategyState.ARCHIVED] == []


def test_valid_transitions_superseded_to_archived():
    assert StrategyState.ARCHIVED in VALID_TRANSITIONS[StrategyState.SUPERSEDED]


def test_lesson_decision_required():
    lesson = Lesson(
        id="l1", summary="x", decision=CuratorDecision.CREATE,
        source_trace_ids=["t1"], confidence=0.8
    )
    assert lesson.decision == CuratorDecision.CREATE


def test_strategy_requires_tenant_id():
    s = StrategyCreate(title="t", description="d", domain="dev", content="c")
    assert s.tenant_id == "default"


def test_failure_pattern_model():
    from mi_dream.knowledge.models import FailurePattern

    dt = datetime.now(UTC)
    fp = FailurePattern(
        id="fp1",
        tenant_id="default",
        error_type="rate_limit_error",
        domain="general",
        pattern="Rate limit no provider",
        failure_count=3,
        last_seen=dt,
        created_at=dt,
        signature="abc123",
    )
    assert fp.failure_count == 3
    assert fp.error_type == "rate_limit_error"


def test_failure_pattern_accepts_neo4j_datetime():
    from mi_dream.knowledge.models import FailurePattern

    dt = datetime.now(UTC)
    fp = FailurePattern(
        id="fp1",
        error_type="api_error",
        domain="general",
        pattern="boom",
        last_seen=_Neo4jDateTime(dt),
        created_at=_Neo4jDateTime(dt),
    )
    assert fp.last_seen == dt
    assert fp.created_at == dt


def test_curator_decision_values():
    assert CuratorDecision.CREATE.value == "CREATE"
    assert CuratorDecision.REINFORCE.value == "REINFORCE"
    assert CuratorDecision.REFINE.value == "REFINE"
    assert CuratorDecision.CONTRADICT.value == "CONTRADICT"
