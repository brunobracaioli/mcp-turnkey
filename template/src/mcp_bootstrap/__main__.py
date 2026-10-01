"""Entry point.

python -m mcp_bootstrap          # stdio transport (Claude Code / Desktop)
python -m mcp_bootstrap --http   # streamable-http on 127.0.0.1:8000 (Inspector)
"""

from __future__ import annotations

import sys

from .config import get_settings
from .observability.logging import configure_logging
from .server import mcp


def main() -> None:
    configure_logging(get_settings().log_level)
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
