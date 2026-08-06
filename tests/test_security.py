import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mi_dream.security.sanitizer import contains_pii, sanitize


def test_sanitize_redacts_email():
    text = "Contact me at user@example.com for details"
    result = sanitize(text)
    assert "@" not in result
    assert "[REDACTED]" in result


def test_sanitize_redacts_api_key():
    text = "api_key=sk-12345abcdef"
    result = sanitize(text)
    assert "sk-12345abcdef" not in result


def test_contains_pii_detects_email():
    assert contains_pii("user@example.com") is True


def test_contains_pii_false_for_clean_text():
    assert contains_pii("just a normal string") is False


def test_sanitize_idempotent():
    text = "no pii here"
    assert sanitize(text) == text


def test_sanitize_redacts_phone():
    text = "Call me at 555-123-4567"
    result = sanitize(text)
    assert "555-123-4567" not in result


def test_sanitize_redacts_ssn():
    text = "SSN: 123-45-6789"
    result = sanitize(text)
    assert "123-45-6789" not in result


def test_sanitize_redacts_bearer_token():
    text = "Authorization: Bearer abc123token"
    result = sanitize(text)
    assert "abc123token" not in result
