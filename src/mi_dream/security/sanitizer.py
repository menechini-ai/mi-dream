import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PIIPatterns:
    email: re.Pattern = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    phone_us: re.Pattern = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")
    ssn: re.Pattern = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    api_key: re.Pattern = re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+")
    bearer: re.Pattern = re.compile(r"(?i)bearer\s+[a-zA-Z0-9\-_.]+")


PATTERNS = PIIPatterns()
REDACTION = "[REDACTED]"


def sanitize(text: str) -> str:
    for name, pattern in PATTERNS.__dict__.items():
        if isinstance(pattern, re.Pattern):
            text = pattern.sub(REDACTION, text)
    return text


def contains_pii(text: str) -> bool:
    for name, pattern in PATTERNS.__dict__.items():
        if isinstance(pattern, re.Pattern):
            if pattern.search(text):
                return True
    return False
