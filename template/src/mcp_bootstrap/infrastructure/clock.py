"""Real wall-clock adapter for the :class:`Clock` port."""

from __future__ import annotations

import asyncio
import time


class SystemClock:
    """Production clock backed by ``time`` and ``asyncio.sleep``."""

    def now(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
