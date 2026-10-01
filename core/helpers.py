# =================================================================================
# core/helpers.py — Shared utilities (Flet 1.0.3 + FastAPI, cloud-ready)
# =================================================================================
# PATCHES APPLIED (v3.5):
#   • get_app_base_path() strips trailing "/data" so RAILWAY_VOLUME_MOUNT_PATH
#     = /app/data doesn't become /app/data/data downstream.
#   • _trigger_download_js uses ft.UrlLauncher() (Flet 1.0.3 API).
#   • send_file_to_user copies into /app/static/downloads and returns None.
# =================================================================================

import os
import sys
import shutil
import base64
import asyncio
import inspect
from datetime import datetime


# =================================================================================
# get_app_base_path — resolve the project root (cloud-aware, no double-path)
# =================================================================================
def get_app_base_path():
    """
    Resolve project root (cloud-aware).

    If RAILWAY_VOLUME_MOUNT_PATH points to a folder named 'data'
    (e.g. /app/data), return its PARENT (/app) so downstream
    os.path.join(base, "data") still resolves to the volume mount.
    Prevents the /app/data/data double-path bug.
    """
    for env_key in ("RAILWAY_VOLUME_MOUNT_PATH", "DATA_ROOT"):
        candidate = os.environ.get(env_key)
        if candidate and os.path.isdir(candidate):
            normalized = os.path.normpath(candidate)
            if os.path.basename(normalized) == "data":
                return os.path.dirname(normalized)
            return normalized

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
# number_to_words_indian
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
# format_currency_indian
# =================================================================================
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


# =================================================================================
# round_as_per_rules
# =================================================================================
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
# _trigger_download_js — schedules the browser download (Flet 1.0.3)
# =================================================================================
def _trigger_download_js(page, url):
    """
    Trigger a browser download via ft.UrlLauncher().launch_url().

    Flet 1.0.3 removed Page.launch_url(). The replacement is:
        launcher = ft.UrlLauncher()
        await launcher.launch_url(url, web_only_window_name="_self")

    Because the FastAPI /download endpoint sets Content-Disposition:
    attachment, navigating the current tab downloads the file and stays
    on the app page (no popup blocker).
    """
    import flet as ft

    if page is None:
        print("[download] page is None")
        return False

    async def _do_launch():
        # Attempt 1: _self (current tab — no popup)
        try:
            launcher = ft.UrlLauncher()
            await launcher.launch_url(
                url,
                mode=ft.LaunchMode.EXTERNAL_APPLICATION,
                web_only_window_name="_self",
            )
            print(f"[download] ✅ UrlLauncher(_self) OK: {url}")
            return
        except TypeError as te:
            print(f"[download] _self TypeError: {te}")
        except Exception as ex:
            print(f"[download] _self exception: {ex}")

        # Attempt 2: default (no explicit target)
        try:
            launcher = ft.UrlLauncher()
            await launcher.launch_url(url)
            print(f"[download] ✅ UrlLauncher(default) OK: {url}")
            return
        except Exception as ex:
            print(f"[download] default exception: {ex}")

        print("[download] ❌ all UrlLauncher methods failed")

    run_task = getattr(page, "run_task", None)
    if run_task is None:
        print("[download] ⚠️ page.run_task MISSING — trying sync fallback")
        try:
            launcher = ft.UrlLauncher()
            result = launcher.launch_url(
                url,
                mode=ft.LaunchMode.EXTERNAL_APPLICATION,
                web_only_window_name="_self",
            )
            if inspect.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    asyncio.run(result)
            print(f"[download] sync launch scheduled: {url}")
            return True
        except Exception as ex:
            print(f"[download] sync fallback failed: {ex}")
            return False

    try:
        run_task(_do_launch)
        print(f"[download] 🚀 run_task scheduled: {url}")
        return True
    except Exception as ex:
        print(f"[download] ❌ run_task failed: {ex}")
        return False


# =================================================================================
# send_file_to_user — the function all tabs call
# =================================================================================
def send_file_to_user(page, filepath, label="Download"):
    """
    Cloud-aware file delivery.

    Web mode:
      1. Copy file into <base>/static/downloads/
      2. Build absolute URL: https://<RAILWAY_PUBLIC_DOMAIN>/download/<fname>
      3. Trigger browser download via UrlLauncher
      4. Return None (callers' `if url:` blocks skip double-launch)

    Desktop:
      • Set page.url to file:// URI
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

            if (os.path.exists(dest)
                    and os.path.getsize(dest) != os.path.getsize(filepath)):
                stem, ext = os.path.splitext(fname)
                stamp = datetime.now().strftime("%H%M%S")
                fname = f"{stem}_{stamp}{ext}"
                dest = os.path.join(downloads_dir, fname)

            shutil.copy2(filepath, dest)

            domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
            url = (f"https://{domain}/download/{fname}"
                   if domain else f"/download/{fname}")

            print(f"[send_file_to_user] copied -> {dest}")
            print(f"[send_file_to_user] url    = {url}")

            _trigger_download_js(page, url)
            return None
        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f"[send_file_to_user] failed: {ex}")
            return None

    # Desktop
    try:
        if page is not None:
            try:
                page.url = f"file://{os.path.abspath(filepath)}"
            except Exception:
                pass
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