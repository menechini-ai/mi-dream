import asyncio
import json

from mi_dream.knowledge.models import CuratorDecision, Lesson
from mi_dream.llm.client import ask_llm

LESSON_SYSTEM_PROMPT = """\
You are a learning synthesizer. Analyze the reasoning trace and produce a lesson.

Output JSON with:
- summary: one sentence describing the key learning
- decision: one of CREATE, REINFORCE, REFINE, CONTRADICT
- confidence: float 0.0-1.0

Rules:
- CREATE: new strategy needed
- REINFORCE: existing approach worked, reinforce it
- REFINE: approach needs improvement
- CONTRADICT: contradicts existing knowledge

Output ONLY valid JSON, no markdown.
"""


class Reflector:
    """Synthesizes Lessons from high-scored ReasoningTraces using LLM."""

    async def reflect(self, traces: list[dict], tenant_id: str = "default") -> list[Lesson]:
        lessons = []
        for trace in traces:
            if trace.get("reflection_score", 0) < 0.5:
                continue
            lesson = await self._synthesize(trace, tenant_id)
            lessons.append(lesson)
        return lessons

    async def _synthesize(self, trace: dict, tenant_id: str) -> Lesson:
        try:
            raw = await asyncio.to_thread(
                ask_llm,
                LESSON_SYSTEM_PROMPT,
                "Trace: "
                f"{trace.get('content', '')[:2000]}\nOutcome: "
                f"{trace.get('outcome', 'unknown')}",
                max_tokens=256,
            )
        except Exception:
            return self._synthesize_heuristic(trace, tenant_id)
        try:
            data = json.loads(raw)
            decision = CuratorDecision(data.get("decision", "REFINE"))
        except (ValueError, json.JSONDecodeError):
            decision = CuratorDecision.REFINE
        return self._build_lesson(trace, tenant_id, decision, raw)

    def _synthesize_heuristic(self, trace: dict, tenant_id: str) -> Lesson:
        outcome = trace.get("outcome", "unknown")
        decision = (
            CuratorDecision.REINFORCE if outcome == "success" else CuratorDecision.REFINE
        )
        return self._build_lesson(trace, tenant_id, decision, None)

    def _build_lesson(
        self, trace: dict, tenant_id: str, decision: CuratorDecision, raw: str | None
    ) -> Lesson:
        return Lesson(
            id=f"lesson-{trace['id']}",
            summary=(raw or trace.get("content", ""))[:200],
            decision=decision,
            source_trace_ids=[trace["id"]],
            confidence=min(trace.get("reflection_score", 0.5), 1.0),
            tenant_id=tenant_id,
        )
