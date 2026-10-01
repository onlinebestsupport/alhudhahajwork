# =================================================================================
# core/helpers.py — Shared utilities (Flet 1.0.0, cloud-ready)
# =================================================================================
# This is a COMPLETE drop-in replacement. If your current helpers.py has extra
# functions not listed here, keep them — just ensure send_file_to_user() is
# the version below.
# =================================================================================

import os
import sys
import shutil
import json
import base64
from pathlib import Path
from datetime import datetime


# =================================================================================
# get_app_base_path — resolve the project root
# =================================================================================
def get_app_base_path():
    """
    Return the project root.

    Priority:
      1. RAILWAY_VOLUME_MOUNT_PATH (when Railway Volume attached)
      2. DATA_ROOT env var
      3. PyInstaller frozen executable directory
      4. Project root (walks up from this file)
    """
    for env_key in ("RAILWAY_VOLUME_MOUNT_PATH", "DATA_ROOT"):
        candidate = os.environ.get(env_key)
        if candidate and os.path.isdir(candidate):
            return candidate

    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)

    here = os.path.dirname(os.path.abspath(__file__))
    cur = here
    for _ in range(6):
        if (os.path.exists(os.path.join(cur, "main.py"))
                or os.path.exists(os.path.join(cur, "core"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.dirname(here)


# =================================================================================
# number_to_words_indian — for invoice "Amount in Words"
# =================================================================================
def number_to_words_indian(number):
    """Convert integer to Indian English words (Rupees ... Only)."""
    try:
        number = int(number)
    except (TypeError, ValueError):
        return "Zero Rupees Only"

    if number < 0:
        return "Minus " + number_to_words_indian(-number)

    if number == 0:
        return "Zero Rupees Only"

    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
            "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
            "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen",
            "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty",
            "Seventy", "Eighty", "Ninety"]

    def two(n):
        if n < 20:
            return ones[n]
        return (tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")).strip()

    def three(n):
        if n >= 100:
            head = ones[n // 100] + " Hundred"
            rest = n % 100
            return head + (" " + two(rest) if rest else "")
        return two(n)

    crore = number // 10000000
    number %= 10000000
    lakh = number // 100000
    number %= 100000
    thousand = number // 1000
    number %= 1000
    hundreds = number

    parts = []
    if crore:
        parts.append(three(crore) + " Crore")
    if lakh:
        parts.append(three(lakh) + " Lakh")
    if thousand:
        parts.append(three(thousand) + " Thousand")
    if hundreds:
        parts.append(three(hundreds))

    return (" ".join(parts).strip() or "Zero") + " Rupees Only"


# =================================================================================
# format_currency_indian — ₹ + Indian grouping (12,34,567.89)
# =================================================================================
def format_currency_indian(amount):
    """Return a string like '₹ 12,34,567.89'."""
    if amount is None:
        return "₹ 0.00"
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return "₹ 0.00"
    if v != v:  # NaN
        return "₹ 0.00"

    negative = v < 0
    v = abs(v)
    s = f"{v:.2f}"
    int_part, dec_part = s.split(".")
    if len(int_part) > 3:
        last3 = int_part[-3:]
        rest = int_part[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        int_part = ",".join(groups) + "," + last3
    out = f"₹ {int_part}.{dec_part}"
    return f"-{out}" if negative else out


# =================================================================================
# round_as_per_rules — round to nearest ₹ (≥0.50 UP, <0.50 DOWN)
# =================================================================================
def round_as_per_rules(value):
    """Round half up to the nearest integer."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    if v != v:
        return 0
    # half-up rounding
    import math
    return int(math.floor(v + 0.5))


# =================================================================================
# send_file_to_user — CLOUD-AWARE file delivery
# =================================================================================
def send_file_to_user(page, filepath, label="Download"):
    """
    Cloud-aware file delivery.

    On web (Railway / Render / Fly):
      • Copy the file into <base>/static/downloads/
      • Return a URL path like "/static/downloads/foo.pdf"
      • Caller then does page.launch_url(url) → browser downloads it

    On desktop:
      • Return a file:// URI for the OS to open

    Returns the URL string on success, None on failure.
    """
    if not filepath or not os.path.exists(filepath):
        return None

    # ---- Detect web mode ----
    is_web = bool(
        os.getenv("PORT")
        or os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("RENDER")
        or os.getenv("FLY_APP_NAME")
    )

    if is_web:
        try:
            base = get_app_base_path()
            downloads_dir = os.path.join(base, "static", "downloads")
            os.makedirs(downloads_dir, exist_ok=True)

            fname = os.path.basename(filepath)
            dest = os.path.join(downloads_dir, fname)

            # Avoid collision: if a different-size file exists, add timestamp
            if (os.path.exists(dest)
                    and os.path.getsize(dest) != os.path.getsize(filepath)):
                stem, ext = os.path.splitext(fname)
                stamp = datetime.now().strftime("%H%M%S")
                fname = f"{stem}_{stamp}{ext}"
                dest = os.path.join(downloads_dir, fname)

            shutil.copy2(filepath, dest)

            # Flet serves assets_dir at /static/... — return the URL path
            return f"/static/downloads/{fname}"

        except Exception as ex:
            print(f"[send_file_to_user] web copy failed: {ex}")
            return None

    # ---- Desktop fallback ----
    try:
        return f"file://{os.path.abspath(filepath)}"
    except Exception as ex:
        print(f"[send_file_to_user] desktop failed: {ex}")
        return None


# =================================================================================
# Convenience: base64 image data URI (used by reports_tab / travel docs)
# =================================================================================
def photo_data_uri(path):
    """Return a data:image/... URI for a local image, or None."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                "gif": "gif", "bmp": "bmp"}.get(ext, "jpeg")
        return f"data:image/{mime};base64,{data}"
    except Exception as e:
        print(f"[helpers.photo_data_uri] {e}")
        return None