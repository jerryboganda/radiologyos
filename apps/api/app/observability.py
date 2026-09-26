"""Structured, allowlisted JSON logs for the API boundary (ADR 0032)."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class RedactingJsonFormatter(logging.Formatter):
    """Emit only allowlisted operational fields as one JSON object."""

    _events = frozenset({
        "request_completed", "rate_limited", "rate_limit_unavailable", "audit_write_failed",
        "tutor_model_failed", "tutor_stream_failed", "idp_revocation_failed",
    })
    # Ids, route templates, numbers, and error class names only (hard rule 4).
    _fields = ("request_id", "method", "path", "status_code", "duration_ms", "tenant_id",
               "bucket", "error_type")

    def format(self, record: logging.LogRecord) -> str:
        event = record.getMessage() if record.getMessage() in self._events else "unknown_event"
        payload: dict[str, Any] = {
            "event": event,
            "service": "api",
        }
        for field in self._fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging() -> logging.Logger:
    """Configure the API's bounded, non-content-bearing log format."""

    logger = logging.getLogger("radbrain.api")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(RedactingJsonFormatter())
        logger.addHandler(handler)
    return logger


logger = configure_logging()
