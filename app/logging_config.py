"""Structured JSON logging configuration.

Emits one JSON object per line to stdout/stderr with contextvars
for request-level metadata (request_id, user_id, correlation_id).
"""

import json
import logging
import logging.config
import sys
from contextvars import ContextVar
from typing import Any

# Context vars populated by RequestContextMiddleware
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "message": record.getMessage(),
        }

        # Include exception info when present
        if record.exc_info and record.exc_info[0]:
            payload["exception"] = self.formatException(record.exc_info)

        # Include context vars when available
        rid = request_id_var.get()
        uid = user_id_var.get()
        cid = correlation_id_var.get()

        if rid:
            payload["request_id"] = rid
        if uid:
            payload["user_id"] = uid
        if cid:
            payload["correlation_id"] = cid

        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """Configure root logger with JSON output to stdout.

    Must be called once at application startup, before any other code.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # Remove any existing handlers to avoid duplicate output
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    root_logger.addHandler(handler)

    # Third-party log levels
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)

    # Security/auth events use WARNING level
    logging.getLogger("app.auth").setLevel(logging.WARNING)
    logging.getLogger("app.middleware").setLevel(logging.INFO)
