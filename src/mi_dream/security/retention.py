"""Trace retention policy — classification + TTL management."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class TraceSensitivity(str, Enum):
    OPEN = "OPEN"
    INTERNAL = "INTERNAL"
    SENSITIVE = "SENSITIVE"


@dataclass(frozen=True)
class RetentionPolicy:
    open_ttl_days: int = 90
    internal_ttl_days: int = 30
    sensitive_ttl_days: int = 7


_DEFAULT_POLICY = RetentionPolicy(
    open_ttl_days=int(os.getenv("RETENTION_OPEN_DAYS", "90")),
    internal_ttl_days=int(os.getenv("RETENTION_INTERNAL_DAYS", "30")),
    sensitive_ttl_days=int(os.getenv("RETENTION_SENSITIVE_DAYS", "7")),
)


def classify_sensitivity(content: str) -> TraceSensitivity:
    """Classify content sensitivity. SENSITIVE if PII/secrets detected post-sanitization."""
    from mi_dream.security.sanitizer import sanitize

    redacted = sanitize(content)
    if redacted != content:
        return TraceSensitivity.SENSITIVE
    return TraceSensitivity.OPEN


def get_retention_policy() -> RetentionPolicy:
    return _DEFAULT_POLICY
