"""Per-request tenant scope, carried in a context variable.

The transport middleware validates the MCP credential, builds a tenant-bound
upstream client and sets this scope for the duration of the request. Tools read it
through the container and never take a ``tenant_id`` argument. Context variables are
task-local and inherited by child tasks, so concurrent requests stay isolated.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from .domain.ports import UpstreamClient


@dataclass(frozen=True, slots=True)
class RequestScope:
    """Everything tenant-specific resolved for the current request."""

    tenant_id: str
    api: UpstreamClient


current_scope: ContextVar[RequestScope | None] = ContextVar("current_scope", default=None)


def get_scope() -> RequestScope | None:
    """The current request scope, or ``None`` outside a tenant request."""
    return current_scope.get()
