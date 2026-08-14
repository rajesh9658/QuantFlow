"""Structured logging module with contextvars-based correlation ID propagation."""

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# ContextVar for async task correlation ID tracking
_correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def set_correlation_id(correlation_id: str | None) -> contextvars.Token[str | None]:
    """Set the correlation ID for the current async execution context."""
    return _correlation_id_ctx.set(correlation_id)


def reset_correlation_id(token: contextvars.Token[str | None]) -> None:
    """Reset the correlation ID context token."""
    _correlation_id_ctx.reset(token)


def get_correlation_id() -> str | None:
    """Get the active correlation ID for the current execution context."""
    return _correlation_id_ctx.get()


class CorrelationIdFilter(logging.Filter):
    """Logging filter to automatically inject correlation_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        setattr(record, "correlation_id", get_correlation_id())
        return True


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter for QuantFlow."""

    def __init__(self, json_format: bool = False) -> None:
        super().__init__()
        self.json_format = json_format

    def format(self, record: logging.LogRecord) -> str:
        correlation_id = getattr(record, "correlation_id", None) or get_correlation_id()
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

        if self.json_format:
            log_obj: dict[str, Any] = {
                "timestamp": timestamp,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "correlation_id": correlation_id,
            }
            if record.exc_info:
                log_obj["exception"] = self.formatException(record.exc_info)
            return json.dumps(log_obj)
        else:
            cid_str = f" [cid={correlation_id}]" if correlation_id else ""
            msg = f"{timestamp} [{record.levelname}] {record.name}{cid_str}: {record.getMessage()}"
            if record.exc_info:
                msg += f"\n{self.formatException(record.exc_info)}"
            return msg


def setup_logging(level: str = "INFO", json_format: bool = False) -> logging.Logger:
    """Configure root quantflow logging with structured formatting and correlation ID support."""
    logger = logging.getLogger("quantflow")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter(json_format=json_format))
    handler.addFilter(CorrelationIdFilter())

    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str = "quantflow") -> logging.Logger:
    """Retrieve a logger instance by name under the quantflow hierarchy."""
    if not name.startswith("quantflow"):
        full_name = f"quantflow.{name}"
    else:
        full_name = name
    return logging.getLogger(full_name)
