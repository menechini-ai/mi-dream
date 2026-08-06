import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.knowledge.models import CuratorDecision
from mi_dream.learning.evaluator import Evaluator
from mi_dream.learning.reflector import Reflector


def test_evaluator_scores_high_for_detailed_failure():
    e = Evaluator()
    trace = {"content": "x" * 300, "outcome": "failure"}
    scored = e.evaluate([trace])
    assert scored[0]["reflection_score"] >= 0.7


def test_evaluator_scores_low_for_brief_trace():
    e = Evaluator()
    trace = {"content": "short", "outcome": "unknown"}
    scored = e.evaluate([trace])
    assert scored[0]["reflection_score"] < 0.5


async def test_reflector_filters_below_threshold():
    r = Reflector()
    traces = [{"id": "t1", "content": "short", "outcome": "unknown", "reflection_score": 0.3}]
    lessons = await r.reflect(traces)
    assert len(lessons) == 0


async def test_reflector_creates_lesson_for_success_heuristic_fallback():
    r = Reflector()
    traces = [{"id": "t1", "content": "x" * 300, "outcome": "success", "reflection_score": 0.8}]
    with patch("mi_dream.learning.reflector.ask_llm", side_effect=RuntimeError("no llm")):
        lessons = await r.reflect(traces)
    assert len(lessons) == 1
    assert lessons[0].decision == CuratorDecision.REINFORCE
    assert lessons[0].tenant_id == "default"


async def test_reflector_creates_lesson_for_failure_heuristic_fallback():
    r = Reflector()
    traces = [{"id": "t1", "content": "x" * 300, "outcome": "failure", "reflection_score": 0.8}]
    with patch("mi_dream.learning.reflector.ask_llm", side_effect=RuntimeError("no llm")):
        lessons = await r.reflect(traces)
    assert len(lessons) == 1
    assert lessons[0].decision == CuratorDecision.REFINE


async def test_reflector_uses_llm_decision_when_available():
    r = Reflector()
    traces = [{"id": "t1", "content": "x" * 300, "outcome": "success", "reflection_score": 0.8}]
    llm_output = '{"summary": "A useful lesson", "decision": "CONTRADICT", "confidence": 0.9}'
    with patch("mi_dream.learning.reflector.ask_llm", return_value=llm_output):
        lessons = await r.reflect(traces)
    assert len(lessons) == 1
    assert lessons[0].decision == CuratorDecision.CONTRADICT
    assert lessons[0].id == "lesson-t1"


async def test_reflector_falls_back_on_invalid_llm_json():
    r = Reflector()
    traces = [{"id": "t1", "content": "x" * 300, "outcome": "success", "reflection_score": 0.8}]
    with patch("mi_dream.learning.reflector.ask_llm", return_value="not json"):
        lessons = await r.reflect(traces)
    assert len(lessons) == 1
    assert lessons[0].decision == CuratorDecision.REFINE
