"""File-backed token store for local stdio development.

Persists the single local upstream token to a gitignored JSON file with ``0600``
permissions (like any OAuth CLI keeps its token). Production uses
``SupabaseTokenStore`` behind the same port.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from ..domain.models import StoredToken

DEFAULT_TOKEN_PATH = Path(".secrets") / "upstream_token.json"
_OWNER_RW = stat.S_IRUSR | stat.S_IWUSR  # 0600


class FileTokenStore:
    """Concrete :class:`~mcp_bootstrap.domain.ports.TokenStore` adapter."""

    def __init__(self, path: Path | str = DEFAULT_TOKEN_PATH) -> None:
        self._path = Path(path)

    async def get(self) -> StoredToken | None:
        if not self._path.exists():
            return None
        try:
            return StoredToken.model_validate_json(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    async def save(self, token: StoredToken) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _OWNER_RW)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(token.model_dump(), fh)
        # Re-assert perms in case the file pre-existed with looser bits.
        os.chmod(self._path, _OWNER_RW)

    async def clear(self) -> None:
        self._path.unlink(missing_ok=True)
