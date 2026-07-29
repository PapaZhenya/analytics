"""Structured (JSON) logging for the api and worker processes.

Deliberately stdlib-only (no structlog/python-json-logger) — a custom `logging.Formatter`
is enough for "one JSON object per line, parseable by any log aggregator" and avoids
adding a dependency for something the standard library already does adequately (see
section 4 of the product spec: don't introduce infrastructure without an actual need).
"""
import json
import logging
import sys
from datetime import datetime, timezone

_RESERVED_LOG_RECORD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Anything passed via logger.info(..., extra={"call_id": ...}) rides along as a
        # top-level JSON field instead of being swallowed.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_ATTRS and key not in payload and not key.startswith("_"):
                try:
                    json.dumps(value)
                except TypeError:
                    value = str(value)
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)

    # Replace any handlers a library (uvicorn, celery) may have already attached, so
    # every log line — ours and theirs — goes through the same JSON formatter instead
    # of a mix of structured and plain-text lines.
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    for noisy_logger in ("uvicorn.access", "uvicorn.error", "celery", "sqlalchemy.engine"):
        logging.getLogger(noisy_logger).handlers = []
        logging.getLogger(noisy_logger).propagate = True
