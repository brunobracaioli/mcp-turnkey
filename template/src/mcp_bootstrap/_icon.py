"""Server icon embedded as a ``data:`` URI (MCP ``initialize`` serverInfo).

Placeholder 1x1 transparent PNG — replace with a 256x256 brand icon. claude.ai does
not render custom-connector icons yet, so this is forward-compatible only; inlining
keeps it same-origin and needs no static route.
"""

ICON_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
