"""Structured JSON logging to STDERR, with a per-request correlation id.

In stdio mode STDOUT carries the JSON-RPC stream, so logs MUST go to STDERR. Never
log tokens, secrets or PII (e-mails, names, message bodies) — only internal ids
(tenant uuid, key-hash prefix) and upstream request ids.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

# Set by the correlation middleware for the lifetime of one HTTP request.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# httpx/httpcore log full request URLs at INFO. Providers that take the token as a
# query parameter (Meta Graph: access_token + appsecret_proof) leak it at any level
# below WARNING — this has happened in production.
_NOISY_LOGGERS = ("httpx", "httpcore")

# Mutable module state without `global`: configure once per process.
_STATE = {"configured": False}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: int | str | None = None) -> None:
    """Install the STDERR JSON handler once; ``level`` may be (re)applied any time."""
    root = logging.getLogger()
    if not _STATE["configured"]:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(_JsonFormatter())
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
        _STATE["configured"] = True
    if level is not None:
        root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger (configuring logging on first use)."""
    configure_logging()
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    """Emit ``msg`` with structured ``fields`` attached (ids only, never PII)."""
    logger.log(level, msg, extra={"extra_fields": fields})
