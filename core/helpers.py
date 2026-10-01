# =================================================================================
# core/helpers.py — Shared utilities (Flet 1.0 + FastAPI, cloud-ready)
# =================================================================================
# v3.0 — Download trigger uses JavaScript anchor injection.
#        This is the ONLY method that works reliably in every modern browser
#        when the download URL is known AFTER an async server round-trip.
# =================================================================================

import os
import sys
import shutil
import json
import base64
from pathlib import Path
from datetime import datetime


def get_app_base_path():
    """Resolve project root (cloud-aware)."""
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


def format_currency_indian(amount):
    """Return a string like '₹ 12,34,567.89'."""
    if amount is None:
        return "₹ 0.00"
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return "₹ 0.00"
    if v != v:
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


def round_as_per_rules(value):
    """Round half up to the nearest integer."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    if v != v:
        return 0
    import math
    return int(math.floor(v + 0.5))


# =================================================================================
# INTERNAL — trigger a download in the browser
# =================================================================================
def _trigger_download_js(page, url):
    """
    Force the browser to download `url` using JavaScript anchor injection.

    This is the ONLY reliable way to bypass Chrome's popup blocker when the
    download URL is produced by an async server call. We create an <a> element
    with the `download` attribute, click it programmatically, and remove it.

    The `download` attribute tells the browser to save (not navigate), and
    because the click is a synthesized DOM event, it doesn't trigger the
    popup blocker.
    """
    if page is None:
        return False

    # Escape single quotes in URL just in case
    safe_url = url.replace("'", "%27")
    js = (
        "(function() {"
        "try {"
        "  var a = document.createElement('a');"
        f"  a.href = '{safe_url}';"
        "  a.download = '';"          # force download, don't navigate
        "  a.style.display = 'none';"
        "  document.body.appendChild(a);"
        "  a.click();"
        "  setTimeout(function(){ document.body.removeChild(a); }, 100);"
        "  return true;"
        "} catch(err) { console.error('download error:', err); return false; }"
        "})();"
    )

    try:
        page.run_javascript(js)
        print(f"[download] JS anchor triggered: {url}")
        return True
    except Exception as ex:
        print(f"[download] JS anchor failed: {ex}")

    # Fallback 1: launch_url with _self (navigate + download)
    try:
        page.launch_url(url, web_window_name="_self")
        print(f"[download] launch_url(_self): {url}")
        return True
    except Exception as ex:
        print(f"[download] launch_url(_self) failed: {ex}")

    # Fallback 2: plain launch_url
    try:
        page.launch_url(url)
        print(f"[download] launch_url: {url}")
        return True
    except Exception as ex:
        print(f"[download] launch_url failed: {ex}")

    return False


# =================================================================================
# send_file_to_user — the one function all tabs call
# =================================================================================
def send_file_to_user(page, filepath, label="Download"):
    """
    Cloud-aware file delivery.

    Web mode:
      1. Copy file into <base>/static/downloads/
      2. Build absolute URL: https://<RAILWAY_PUBLIC_DOMAIN>/download/<fname>
      3. Trigger browser download via JS anchor injection
      4. Return None (callers' `if url:` blocks skip — no double-launch)

    Desktop mode:
      • Launch the local file with the OS default app
      • Return None
    """
    if not filepath or not os.path.exists(filepath):
        print(f"[send_file_to_user] file missing: {filepath}")
        return None

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

            # Collision handling: if a different file with same name exists,
            # add a timestamp so we don't overwrite
            if (os.path.exists(dest)
                    and os.path.getsize(dest) != os.path.getsize(filepath)):
                stem, ext = os.path.splitext(fname)
                stamp = datetime.now().strftime("%H%M%S")
                fname = f"{stem}_{stamp}{ext}"
                dest = os.path.join(downloads_dir, fname)

            shutil.copy2(filepath, dest)

            # Build the absolute URL — JS anchor needs a full URL
            domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
            if domain:
                url = f"https://{domain}/download/{fname}"
            else:
                # Fallback for local dev or unknown domains
                url = f"/download/{fname}"

            print(f"[send_file_to_user] copied -> {dest}")
            print(f"[send_file_to_user] url    = {url}")

            _trigger_download_js(page, url)
            return None  # callers' `if url:` blocks skip

        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f"[send_file_to_user] failed: {ex}")
            return None

    # Desktop fallback
    try:
        if page is not None:
            page.launch_url(f"file://{os.path.abspath(filepath)}")
    except Exception as ex:
        print(f"[send_file_to_user] desktop failed: {ex}")
    return None


# =================================================================================
# photo_data_uri — inline base64 image for reports
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