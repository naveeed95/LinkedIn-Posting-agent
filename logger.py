"""
Structured logging for the posting agent.

Usage:
    from logger import get_logger
    log = get_logger("research")
    log.info("RSS %s: %d items", name, count)
    log.warning("HN returned only %d items — retrying", n)

Output format is controlled by the LOG_FORMAT env var:
  - LOG_FORMAT=json — one JSON object per line (ts, level, area, msg, +extras)
  - anything else   — human-readable "HH:MM:SS [area] msg" (default)

GitHub Actions workflows set LOG_FORMAT=json so log lines are queryable.
Local runs default to text for readability.

Pass structured fields via the `extra` kwarg — they appear as top-level keys
in JSON mode and are appended as "key=value" in text mode:
    log.info("variant generated", extra={"model": "deepseek", "tokens": 512})
"""

import json
import logging
import os
import sys

_LOGRECORD_BUILTIN_ATTRS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":    self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname.lower(),
            "area":  record.name,
            "msg":   record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _LOGRECORD_BUILTIN_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts     = self.formatTime(record, "%H:%M:%S")
        prefix = f"[{record.name}]"
        extras = " ".join(
            f"{k}={v}" for k, v in record.__dict__.items()
            if k not in _LOGRECORD_BUILTIN_ATTRS
        )
        msg = record.getMessage()
        if extras:
            msg = f"{msg} {extras}"
        if record.levelno >= logging.WARNING:
            return f"{ts} {prefix} {record.levelname}: {msg}"
        return f"{ts} {prefix} {msg}"


_configured = False


def setup_logging(level: str | int | None = None) -> None:
    """Initialise the root logger. Idempotent."""
    global _configured
    if _configured:
        return

    lvl_str = (level if isinstance(level, str) else None) or os.environ.get("LOG_LEVEL", "INFO")
    lvl     = level if isinstance(level, int) else getattr(logging, lvl_str.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(lvl)

    # Windows consoles default stdout to cp1252 — emoji in research titles
    # (RSS/Reddit/HN headlines) raise UnicodeEncodeError on log emit otherwise.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # non-reconfigurable stream (e.g. piped/captured in some test runners)

    handler = logging.StreamHandler(sys.stdout)
    fmt = os.environ.get("LOG_FORMAT", "text").lower()
    handler.setFormatter(JSONFormatter() if fmt == "json" else TextFormatter())

    root.handlers = [handler]
    _configured = True


def get_logger(area: str) -> logging.Logger:
    """Return a logger for the given area. Auto-initialises root config."""
    if not _configured:
        setup_logging()
    return logging.getLogger(area)
