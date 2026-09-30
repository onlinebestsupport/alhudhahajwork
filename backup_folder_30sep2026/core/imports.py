# =================================================================================
# SECTION 0 (FLET VERSION) — ALL IMPORTS
# =================================================================================

# ---- 0.1 — System & environment ----
import os
import sys
import warnings
import shutil
import json
import uuid
import zipfile
import csv
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

# ---- 0.2 — Data science ----
import pandas as pd
import numpy as np

# ---- 0.3 — PDF generation (server-side, still works on web) ----
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm, cm
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ---- 0.4 — Excel export (server-side) ----
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# ---- 0.5 — Image processing ----
try:
    from PIL import Image
except ImportError:
    pass

# ---- 0.6 — Flet (replaces ALL PyQt6 imports) ----
import flet as ft

# ---- 0.7 — Suppress Qt warnings (no longer needed, but harmless) ----
warnings.filterwarnings("ignore")

# ---- 0.8 — App-wide constants ----
APP_NAME = "Alhudha Haj Travel System"
APP_VERSION = "3.0.0 (Web)"
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
EXPORT_DIR = BASE_DIR / "exports"

# Ensure folders exist
for folder in [DATA_DIR, UPLOAD_DIR, EXPORT_DIR]:
    folder.mkdir(parents=True, exist_ok=True)