class Evaluator:
    """Scores reasoning traces for reflection worthiness."""

    def evaluate(self, traces: list[dict]) -> list[dict]:
        scored = []
        for trace in traces:
            score = self._score_trace(trace)
            scored.append({**trace, "reflection_score": score})
        return scored

    def _score_trace(self, trace: dict) -> float:
        length = len(trace.get("content", ""))
        has_outcome = bool(trace.get("outcome"))
        has_failure = trace.get("outcome") == "failure"
        score = 0.0
        if length > 200:
            score += 0.3
        if has_outcome:
            score += 0.4
        if has_failure:
            score += 0.3
        if trace.get("outcome") == "success":
            score += 0.1
        return min(score, 1.0)
