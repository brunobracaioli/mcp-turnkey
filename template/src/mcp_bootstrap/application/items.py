"""Example vertical slice: items.

SCAFFOLD: replace this slice with the upstream's real resources, keeping the shape —
reads return domain models; writes take ``preview`` (validate and show the payload
without calling the upstream); destructive actions require ``confirm=True``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..domain.errors import ValidationError
from ..domain.models import Item, WriteResult
from ..domain.ports import UpstreamClient

_ITEMS_PATH = "items"
MAX_LIST_LIMIT = 100


def _item_path(item_id: str) -> str:
    # Ids are already pattern-checked at the tool boundary; quoting is the second
    # barrier against path smuggling (defense in depth).
    return f"{_ITEMS_PATH}/{quote(item_id, safe='')}"


async def list_items(api: UpstreamClient, *, limit: int) -> list[Item]:
    """List items, newest first."""
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise ValidationError(f"limit must be between 1 and {MAX_LIST_LIMIT}.")
    body = await api.get(_ITEMS_PATH, params={"limit": limit})
    rows = body.get("items") or body.get("data") or []
    return [Item.model_validate(row) for row in rows if isinstance(row, dict)]


async def get_item(api: UpstreamClient, item_id: str) -> Item:
    """Fetch one item."""
    return Item.model_validate(await api.get(_item_path(item_id)))


async def create_item(api: UpstreamClient, *, name: str, preview: bool) -> WriteResult:
    """Create an item; with ``preview`` only the payload is returned."""
    payload: dict[str, Any] = {"name": name.strip()}
    if not payload["name"]:
        raise ValidationError("name must not be blank.")
    if preview:
        return WriteResult(
            executed=False, detail="Preview only; nothing was created.", payload=payload
        )
    created = await api.post(_ITEMS_PATH, payload)
    return WriteResult(executed=True, detail="Item created.", payload=payload, result=created)


async def delete_item(api: UpstreamClient, item_id: str, *, confirm: bool) -> WriteResult:
    """Delete an item. Irreversible, so it is a no-op preview unless ``confirm``."""
    if not confirm:
        return WriteResult(
            executed=False,
            detail="Deleting is irreversible. Re-run with confirm=true to delete.",
            payload={"item_id": item_id},
        )
    await api.delete(_item_path(item_id))
    return WriteResult(executed=True, detail="Item deleted.", payload={"item_id": item_id})
