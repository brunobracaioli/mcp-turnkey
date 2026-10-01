# How to add a slice of tools

1. **Spec first:** add the tools to the contracts table in `docs/specs/` with inputs,
   outputs and edge cases.
2. **Domain:** model the responses in `domain/models.py` (Pydantic, `extra="ignore"`).
   Ids that come from the model use `ResourceId` (or an `Annotated` with its own pattern).
3. **Application:** create `application/<slice>.py` with `async` functions that take the
   `UpstreamClient` port. Writes accept `preview`; destructive operations require
   `confirm`. Validate business rules here (`ValidationError`). Export the module in
   `application/__init__.py`.
4. **Presentation:** in `server.py`, one thin tool per use case: annotations
   (`_READ_ONLY`, `_WRITE`, `_DESTRUCTIVE`), parameters as `Annotated[..., Field(...)]`
   with size limits, body `try: … except Exception as exc: raise _fail(exc) from exc`.
5. **Tests:** `tests/application/test_<slice>.py` with `FakeUpstream`; extend
   `test_server_tools.py` if you add a new annotation.
6. **Reference:** update `docs/reference/mcp-tools.md`.
7. Run `ruff check . && ruff format --check . && mypy src && pytest -q`.

> Gotcha: the post-edit hook runs `ruff check --fix`, which deletes imports that are not
> used yet. Add an import in the same edit as its first use.
