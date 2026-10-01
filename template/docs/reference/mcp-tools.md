# Reference — MCP tools

Authentication tool names are prefixed with the slug (`SERVICE_SLUG` in `config.py`).

| Tool | Annotations | Parameters | Returns |
|---|---|---|---|
| `bootstrap_login` | — | — | local: `authorize_url`; hosted: `connected` |
| `bootstrap_submit_callback` | — | `callback_url` | `success`, `account`, `scopes` |
| `bootstrap_token_status` | readOnly | — | `authenticated`, `account`, `scopes`, `access_expires_at` |
| `bootstrap_refresh_token` | — | — | `success`, `access_expires_at` |
| `list_items` | readOnly | `limit` (1–100, default 20) | `[Item]` |
| `get_item` | readOnly | `item_id` | `Item` |
| `create_item` | write | `name`, `preview` | `WriteResult` |
| `delete_item` | destructive | `item_id`, `confirm` | `WriteResult` |

`WriteResult`: `executed` (bool), `detail`, `payload` (what was/would be sent), `result`.

Errors reach the model as a `ToolError` carrying the domain error's message; unexpected
errors become a generic message (the detail stays in the log only).
