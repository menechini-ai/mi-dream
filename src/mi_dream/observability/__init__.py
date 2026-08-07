"""Observability: structured logging and metrics for mi-dream."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any


def get_logger(name: str) -> logging.Logger:
    """Return a structured JSON logger for the given module."""
    logger = logging.getLogger(f"mi_dream.{name}")
    if not logger.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


@dataclass
class Metrics:
    """In-memory counters for learning pipeline observability."""

    learning_cycle_failures: int = 0
    learning_traces_processed: int = 0
    lessons_created: int = 0
    strategies_created: int = 0
    strategies_promoted: int = 0
    learning_lag_seconds: float = 0.0

    def increment(self, name: str, amount: int = 1) -> None:
        setattr(self, name, getattr(self, name) + amount)

    def to_dict(self) -> dict[str, Any]:
        return {
            "learning_cycle_failures": self.learning_cycle_failures,
            "learning_traces_processed": self.learning_traces_processed,
            "lessons_created": self.lessons_created,
            "strategies_created": self.strategies_created,
            "strategies_promoted": self.strategies_promoted,
            "learning_lag_seconds": self.learning_lag_seconds,
        }


# Singleton — no external deps, safe to import at module level.
_metrics = Metrics()


def get_metrics() -> Metrics:
    return _metrics


WORKER_ID = os.getenv("MI_DREAM_WORKER_ID", f"worker-{os.getpid()}")
