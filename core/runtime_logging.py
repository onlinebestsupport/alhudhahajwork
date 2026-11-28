"""Structured runtime diagnostics for the admin application."""
# ==============================================================================
# SECTION 1 — DURABLE RUNTIME LOGGING
# ==============================================================================
# Maintenance index
#   1.1  Build fingerprint
#   1.2  JSON-safe field conversion
#   1.3  Structured runtime event logging
#   1.4  Exception logging with traceback
# ==============================================================================

from __future__ import annotations

import json
import os
import platform
import traceback
from datetime import datetime, timezone
from pathlib import Path


# [1.1] Build fingerprint — lets Railway logs prove which source is running
APP_BUILD_ID = "2026-11-28-passport-ocr-selector-v2"


# [1.2] _safe — convert diagnostic values without exposing secrets
# ==============================================================================
def _safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    return str(value)


# [1.3] log_event — print to Railway and append to the durable volume
# ==============================================================================
def log_event(component: str, event: str, *, level: str = "INFO",
              db=None, **fields):
    """Emit one structured event to stdout and /app/data/logs when available."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": str(level).upper(),
        "component": str(component),
        "event": str(event),
        "build": APP_BUILD_ID,
        "pid": os.getpid(),
        "python": platform.python_version(),
    }
    record.update({str(key): _safe(value) for key, value in fields.items()})
    line = json.dumps(record, ensure_ascii=False, default=str)
    print(f"[APP_LOG] {line}", flush=True)

    try:
        data_dir = getattr(db, "data_dir", None) if db is not None else None
        data_dir = data_dir or os.getenv("APP_DATA_DIR") or "/app/data"
        log_dir = Path(data_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "admin_runtime.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception as log_error:
        # Local sandboxes may not have /app. Railway still uses /app/data;
        # only the non-Railway fallback moves to the project-local data folder.
        if str(data_dir) == "/app/data":
            try:
                local_dir = Path.cwd() / "data" / "logs"
                local_dir.mkdir(parents=True, exist_ok=True)
                with (local_dir / "admin_runtime.log").open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                return
            except Exception:
                pass
        # Logging must never break the admin UI; stdout remains the fallback.
        print(f"[APP_LOG][LOGGER_ERROR] {type(log_error).__name__}: {log_error}",
              flush=True)


# [1.4] log_exception — record a failure and its complete traceback
# ==============================================================================
def log_exception(component: str, event: str, error: Exception, *, db=None,
                  **fields):
    details = dict(fields)
    details.update({
        "error_type": type(error).__name__,
        "error": str(error),
        "traceback": traceback.format_exc(),
    })
    log_event(component, event, level="ERROR", db=db, **details)
