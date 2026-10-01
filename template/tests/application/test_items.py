"""Example slice: reads, preview-first writes, confirm-gated deletes."""

from __future__ import annotations

import pytest

from fakes import FakeUpstream
from mcp_bootstrap.application import items
from mcp_bootstrap.domain.errors import ValidationError


async def test_list_items_maps_rows_to_models() -> None:
    api = FakeUpstream({("GET", "items"): {"items": [{"id": "i1", "name": "First"}]}})
    result = await items.list_items(api, limit=5)
    assert [i.id for i in result] == ["i1"]
    assert api.calls == [("GET", "items", {"limit": 5})]


@pytest.mark.parametrize("limit", [0, items.MAX_LIST_LIMIT + 1])
async def test_list_items_rejects_out_of_range_limits(limit: int) -> None:
    with pytest.raises(ValidationError):
        await items.list_items(FakeUpstream(), limit=limit)


async def test_create_preview_does_not_call_the_upstream() -> None:
    api = FakeUpstream()
    result = await items.create_item(api, name="  New  ", preview=True)
    assert result.executed is False
    assert result.payload == {"name": "New"}
    assert api.calls == []


async def test_create_executes_when_not_previewing() -> None:
    api = FakeUpstream({("POST", "items"): {"id": "i9"}})
    result = await items.create_item(api, name="New", preview=False)
    assert result.executed is True
    assert result.result == {"id": "i9"}


async def test_blank_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        await items.create_item(FakeUpstream(), name="   ", preview=True)


async def test_delete_without_confirm_is_a_no_op() -> None:
    api = FakeUpstream()
    result = await items.delete_item(api, "i1", confirm=False)
    assert result.executed is False
    assert api.calls == []


async def test_ids_are_path_quoted() -> None:
    api = FakeUpstream()
    await items.delete_item(api, "../admin", confirm=True)
    assert api.calls[0][1] == "items/..%2Fadmin"
