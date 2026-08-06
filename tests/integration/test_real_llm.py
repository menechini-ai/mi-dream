import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

import pytest

from mi_dream.config import settings
from mi_dream.knowledge.models import CuratorDecision
from mi_dream.learning.reflector import Reflector
from mi_dream.llm.client import chat, get_client


@pytest.fixture(scope="module")
def llm_available():
    if not settings.llm_api_key:
        pytest.skip("LLM_API_KEY not set in environment")
    try:
        response = get_client().chat.completions.create(
            model=settings.llm_model,
            max_tokens=3,
            messages=[{"role": "user", "content": "ping"}],
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            pytest.skip("LLM provider returned empty response")
    except Exception:
        pytest.skip("LLM provider unreachable")


def test_llm_client_real_call(llm_available):
    """Real LLM call — verifies provider connectivity."""
    response = chat(
        system="You are a test assistant. Reply with exactly: OK",
        user_message="Say OK",
        max_tokens=10,
    )
    assert "OK" in response.upper()
    assert len(response) > 0


async def test_reflector_real_llm_synthesis(llm_available):
    """Real Reflector: LLM synthesizes a Lesson from a trace."""
    reflector = Reflector()
    traces = [
        {
            "id": "t-real-1",
            "content": "Tried to deploy to Kubernetes but the pod was in CrashLoopBackOff. "
                       "Checked logs with kubectl logs, found OOMKilled. Increased memory limit.",
            "outcome": "success",
            "reflection_score": 0.9,
        }
    ]
    lessons = await reflector.reflect(traces, tenant_id="default")
    assert len(lessons) == 1
    lesson = lessons[0]
    assert lesson.id == "lesson-t-real-1"
    assert lesson.decision in CuratorDecision
    assert 0.0 <= lesson.confidence <= 1.0
    assert len(lesson.summary) > 0
    assert lesson.source_trace_ids == ["t-real-1"]


async def test_reflector_real_llm_failure_trace(llm_available):
    """Real Reflector: LLM synthesizes lesson from failure trace."""
    reflector = Reflector()
    traces = [
        {
            "id": "t-real-2",
            "content": "Attempted to connect to database without retry logic. "
                       "Connection failed transiently, no retry = task failed.",
            "outcome": "failure",
            "reflection_score": 0.8,
        }
    ]
    lessons = await reflector.reflect(traces, tenant_id="default")
    assert len(lessons) == 1
    assert lessons[0].decision in (
        CuratorDecision.REFINE,
        CuratorDecision.CREATE,
        CuratorDecision.CONTRADICT,
    )


async def test_reflector_real_llm_multiple_traces(llm_available):
    """Real Reflector: processes multiple traces, filters below threshold."""
    reflector = Reflector()
    traces = [
        {"id": "t-a", "content": "x" * 300, "outcome": "success", "reflection_score": 0.9},
        {"id": "t-b", "content": "short", "outcome": "unknown", "reflection_score": 0.2},
        {"id": "t-c", "content": "y" * 300, "outcome": "failure", "reflection_score": 0.85},
    ]
    lessons = await reflector.reflect(traces, tenant_id="default")
    assert len(lessons) == 2
    ids = {lesson.id for lesson in lessons}
    assert "lesson-t-a" in ids
    assert "lesson-t-b" not in ids
    assert "lesson-t-c" in ids
