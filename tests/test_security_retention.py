"""Tests for mi_dream.security.retention."""

import os

import pytest

from mi_dream.security.retention import (
    RetentionPolicy,
    TraceSensitivity,
    classify_sensitivity,
    get_retention_policy,
)


def test_classify_open_clean():
    assert classify_sensitivity("how do I deploy k8s?") == TraceSensitivity.OPEN


def test_classify_sensitive_email():
    assert classify_sensitivity("contact user@example.com") == TraceSensitivity.SENSITIVE


def test_classify_sensitive_api_key():
    assert classify_sensitivity("use api_key=sk-secret123") == TraceSensitivity.SENSITIVE


def test_classify_sensitive_bearer():
    assert classify_sensitivity("Authorization: Bearer abc123") == TraceSensitivity.SENSITIVE


def test_get_retention_policy_defaults():
    policy = get_retention_policy()
    assert policy.open_ttl_days == 90
    assert policy.internal_ttl_days == 30
    assert policy.sensitive_ttl_days == 7


def test_retention_policy_from_env(monkeypatch):
    monkeypatch.setenv("RETENTION_OPEN_DAYS", "60")
    monkeypatch.setenv("RETENTION_INTERNAL_DAYS", "15")
    monkeypatch.setenv("RETENTION_SENSITIVE_DAYS", "3")
    # Reload module to pick up env
    import importlib
    from mi_dream.security import retention
    importlib.reload(retention)
    p = retention.get_retention_policy()
    assert p.open_ttl_days == 60
    assert p.internal_ttl_days == 15
    assert p.sensitive_ttl_days == 3
