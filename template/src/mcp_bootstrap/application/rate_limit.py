"""Fixed-window rate limiting over the :class:`Cache` port."""

from __future__ import annotations

from ..config import SERVICE_SLUG
from ..domain.ports import Cache
from ..observability.logging import get_logger

logger = get_logger(__name__)


async def allow(cache: Cache | None, key: str, *, limit: int, window_seconds: int) -> bool:
    """Count one hit on ``key``; ``False`` once ``limit`` is exceeded in the window.

    Fail-open by design: without a cache, or when it errors, the request passes.
    Blocking every login on an Upstash blip is worse than a short unthrottled window;
    authentication remains the real gate.
    """
    if cache is None:
        return True
    try:
        count = await cache.incr(key, ttl_seconds=window_seconds)
    except Exception:
        logger.warning("rate_limit_unavailable")
        return True
    return count <= limit


def ip_key(bucket: str, client_ip: str) -> str:
    """Per-IP counter key for a public endpoint bucket."""
    return f"{SERVICE_SLUG}:rl:{bucket}:{client_ip}"
