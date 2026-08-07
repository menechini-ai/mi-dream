"""Tests for mi_dream.security.tenant."""

import pytest

from mi_dream.security.tenant import TenantContext


def test_tenant_context_id():
    ctx = TenantContext(id="tenant-a")
    assert ctx.id == "tenant-a"


def test_tenant_context_default_admin_false():
    ctx = TenantContext(id="t1")
    assert ctx.is_admin is False


def test_tenant_context_is_admin():
    ctx = TenantContext(id="t1", is_admin=True)
    assert ctx.is_admin is True


def test_tenant_context_frozen():
    ctx = TenantContext(id="t1")
    with pytest.raises(AttributeError):
        ctx.id = "t2"  # type: ignore[misc]


def test_tenant_context_equal():
    a = TenantContext(id="t1")
    b = TenantContext(id="t1")
    assert a == b
