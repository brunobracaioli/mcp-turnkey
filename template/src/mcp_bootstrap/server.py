"""MCP presentation layer.

Thin FastMCP wrappers over the application use cases. Tools validate input through
Pydantic-typed signatures, translate domain errors into model-safe ``ToolError``
messages and never leak tokens or raw upstream payloads. The tenant (in prod) is
always derived from the MCP credential, never passed as an argument.

Conventions: reads carry ``readOnlyHint``; writes take ``preview`` (validate and
return the payload without calling the upstream); irreversible actions carry
``destructiveHint`` and do nothing unless ``confirm=true``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import Icon, ToolAnnotations
from pydantic import BaseModel, Field

from . import application as app
from ._icon import ICON_DATA_URI
from .application.items import MAX_LIST_LIMIT
from .config import SERVICE_DISPLAY_NAME, SERVICE_SLUG
from .container import Container, ToolHost
from .domain.errors import DomainError
from .domain.models import ResourceId
from .observability.logging import get_logger

logger = get_logger(__name__)

# SCAFFOLD: what the server does and the rules the model must follow (shown to the
# client as server instructions). Keep it about behavior, not marketing.
INSTRUCTIONS = f"""{SERVICE_DISPLAY_NAME} connector.

READS are safe and return compact models. WRITES accept `preview=true`, which validates
the input and returns the payload without changing anything; show it to the user first.
Destructive tools do nothing unless called with `confirm=true`.

AUTH: in hosted mode the tenant comes from the connection itself — never ask the user
for an account or tenant id. If a tool says the account is not connected, ask the user
to reconnect this server. `{SERVICE_SLUG}_token_status` checks the connection.
"""

mcp = FastMCP(
    SERVICE_DISPLAY_NAME,
    instructions=INSTRUCTIONS,
    icons=[Icon(src=ICON_DATA_URI, mimeType="image/png", sizes=["256x256"])],
)

# Active composition root. The serverless transport swaps in a ProdContainer.
_active: dict[str, ToolHost] = {"host": Container()}


def set_container(host: ToolHost) -> None:
    """Replace the active composition root (used by the serverless transport)."""
    _active["host"] = host


def _host() -> ToolHost:
    return _active["host"]


_READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
_DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)


def _fail(exc: Exception) -> ToolError:
    """Convert an exception into a model-safe ToolError (domain messages are safe)."""
    if isinstance(exc, DomainError):
        return ToolError(exc.message)
    logger.exception("unexpected_tool_error")
    return ToolError(f"An unexpected error occurred in {SERVICE_DISPLAY_NAME}.")


def _dump(items: Sequence[BaseModel]) -> list[dict[str, Any]]:
    return [item.model_dump(exclude_none=True) for item in items]


# ── auth ───────────────────────────────────────────────────────────────────────


@mcp.tool(name=f"{SERVICE_SLUG}_login")
async def login() -> dict[str, Any]:
    """Start connecting the upstream account (step 1 of 2, local mode).

    Local mode: returns an `authorize_url`; approve it, then pass the FULL URL the
    browser was redirected to into the submit-callback tool. Hosted mode: the login
    happens while connecting this server; this only reports whether it is connected.
    """
    try:
        return await _host().auth_login()
    except Exception as exc:
        raise _fail(exc) from exc


@mcp.tool(name=f"{SERVICE_SLUG}_submit_callback")
async def submit_callback(
    callback_url: Annotated[
        str,
        Field(
            min_length=1,
            max_length=4096,
            description="The full URL the browser was redirected to (has ?code=…&state=…).",
        ),
    ],
) -> dict[str, Any]:
    """Finish the local login (step 2 of 2): exchange the code and store the token."""
    try:
        return await _host().auth_submit_callback(callback_url)
    except Exception as exc:
        raise _fail(exc) from exc


@mcp.tool(name=f"{SERVICE_SLUG}_token_status", annotations=_READ_ONLY)
async def token_status() -> dict[str, Any]:
    """Report whether the upstream connection works, its account and scopes."""
    try:
        return await _host().auth_status()
    except Exception as exc:
        raise _fail(exc) from exc


@mcp.tool(name=f"{SERVICE_SLUG}_refresh_token")
async def refresh_token() -> dict[str, Any]:
    """Renew the upstream access token now (also proves the connection works)."""
    try:
        return await _host().auth_refresh()
    except Exception as exc:
        raise _fail(exc) from exc


# ── example slice: items ─────────────────────────────────────────────────────────
# SCAFFOLD: replace these tools with the upstream's real resources.


@mcp.tool(annotations=_READ_ONLY)
async def list_items(
    limit: Annotated[int, Field(ge=1, le=MAX_LIST_LIMIT, description="Max items")] = 20,
) -> list[dict[str, Any]]:
    """List items, newest first."""
    try:
        return _dump(await app.items.list_items(_host().api, limit=limit))
    except Exception as exc:
        raise _fail(exc) from exc


@mcp.tool(annotations=_READ_ONLY)
async def get_item(item_id: Annotated[ResourceId, Field(description="Item id")]) -> dict[str, Any]:
    """Get one item by id."""
    try:
        return (await app.items.get_item(_host().api, item_id)).model_dump(exclude_none=True)
    except Exception as exc:
        raise _fail(exc) from exc


@mcp.tool(annotations=_WRITE)
async def create_item(
    name: Annotated[str, Field(min_length=1, max_length=200, description="Item name")],
    preview: Annotated[bool, Field(description="Validate only; create nothing")] = False,
) -> dict[str, Any]:
    """Create an item (use preview=true first to show the payload)."""
    try:
        result = await app.items.create_item(_host().api, name=name, preview=preview)
        return result.model_dump(exclude_none=True)
    except Exception as exc:
        raise _fail(exc) from exc


@mcp.tool(annotations=_DESTRUCTIVE)
async def delete_item(
    item_id: Annotated[ResourceId, Field(description="Item id")],
    confirm: Annotated[bool, Field(description="Must be true to delete (irreversible)")] = False,
) -> dict[str, Any]:
    """Delete an item — irreversible; a preview unless confirm=true."""
    try:
        result = await app.items.delete_item(_host().api, item_id, confirm=confirm)
        return result.model_dump(exclude_none=True)
    except Exception as exc:
        raise _fail(exc) from exc
