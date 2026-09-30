# =================================================================================
# SECTION 0 (FLET 1.0.0 VERSION) — ALL IMPORTS & APP CONSTANTS
# =================================================================================
# PATCHES APPLIED (v1.1):
#   0.1.A — Cloud-aware BASE_DIR resolution (Railway Volume support)
#   0.1.B — Removed stale `warnings.filterwarnings("ignore")` (was hiding
#           pandas/reportlab deprecation warnings that matter on cloud)
#   0.1.C — Trimmed dead imports (numpy, csv, reportlab.canvas, letter, landscape)
#   0.1.D — Light logging setup so Railway logs are useful
# =================================================================================

# ---- 0.1 — System & environment ----
import os
import sys
import logging
import shutil
import json
import uuid
import zipfile
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

# ---- 0.2 — Data science ----
import pandas as pd

# ---- 0.3 — PDF generation (server-side, still works on web) ----
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm, cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ---- 0.4 — Excel export (server-side) ----
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# ---- 0.5 — Image processing (optional) ----
try:
    from PIL import Image
except ImportError:
    Image = None

# ---- 0.6 — Flet ----
import flet as ft


# =================================================================================
# 0.7 — App-wide constants  (CLOUD-AWARE)
# =================================================================================
APP_NAME = "Alhudha Haj Travel System"
APP_VERSION = "3.0.0 (Web)"


def _resolve_base_dir() -> Path:
    """Resolve the writable data root.

    Priority order:
      1. DATA_ROOT env var (explicit override)
      2. RAILWAY_VOLUME_MOUNT_PATH env var (auto-set when a Railway
         Volume is attached — this is the recommended deployment path
         for persistent CSVs on Railway)
      3. PyInstaller frozen executable directory (desktop builds)
      4. Project root (local dev)
    """
    for env_key in ("DATA_ROOT", "RAILWAY_VOLUME_MOUNT_PATH"):
        candidate = os.environ.get(env_key)
        if candidate:
            p = Path(candidate)
            try:
                p.mkdir(parents=True, exist_ok=True)
                return p
            except Exception as e:
                print(f"[config] Could not use {env_key}={candidate}: {e}")

    if getattr(sys, "frozen", False):
        return Path(os.path.dirname(sys.executable))

    return Path(__file__).resolve().parent.parent


BASE_DIR = _resolve_base_dir()
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
EXPORT_DIR = BASE_DIR / "exports"

# Ensure folders exist
for folder in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR):
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[config] Failed to create {folder}: {e}")


# =================================================================================
# 0.8 — Logging
# =================================================================================
def _setup_logging():
    """Configure root logger so Railway logs show timestamps & levels."""
    root = logging.getLogger()
    if root.handlers:
        return  # already configured (e.g. re-import)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_setup_logging()

# Emit a startup banner so Railway logs immediately reveal which data
# root the container is using — critical for debugging volume mounts.
logging.getLogger("config").info(
    "Data root: %s (DATA_DIR=%s)", BASE_DIR, DATA_DIR)