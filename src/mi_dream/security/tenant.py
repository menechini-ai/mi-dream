"""Tenant isolation — TenantContext replaces bare tenant_id strings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    """Immutable tenant identity for domain operations."""

    id: str
    is_admin: bool = False


def tenant_from_str(tenant_id: str) -> TenantContext:
    """Transitional adapter: convert a bare string to TenantContext."""
    return TenantContext(id=tenant_id)
