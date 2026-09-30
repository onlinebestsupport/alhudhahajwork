# =================================================================================
# SECTION 1 (FLET VERSION) — HELPER FUNCTIONS
# =================================================================================

import os
import sys
import subprocess
import shutil
from pathlib import Path

# =================================================================================
# 1.1 — FUNCTION: round_as_per_rules   (UNCHANGED)
# =================================================================================
def round_as_per_rules(amount):
    """Indian financial rounding: <0.50 rounds down, >=0.50 rounds up."""
    if amount is None:
        return 0
    decimal_part = amount - int(amount)
    if decimal_part < 0.50:
        return int(amount)
    else:
        return int(amount) + 1


# =================================================================================
# 1.2 — FUNCTION: number_to_words_indian   (UNCHANGED)
# =================================================================================
def number_to_words_indian(num):
    """Converts a number into words (Indian system: Thousand, Lakh, Crore)."""
    if num is None or (isinstance(num, float) and num != num):
        return "Zero Only"
    if num == 0:
        return "Zero Only"

    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
            "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
            "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen",
            "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty",
            "Seventy", "Eighty", "Ninety"]

    def convert_less_than_thousand(n):
        if n < 20:
            return ones[n]
        elif n < 100:
            return tens[n // 10] + ("" if n % 10 == 0 else " " + ones[n % 10])
        else:
            return ones[n // 100] + " Hundred" + (
                "" if n % 100 == 0
                else " " + convert_less_than_thousand(n % 100))

    if num < 1000:
        result = convert_less_than_thousand(num)
    elif num < 100000:
        thousands = num // 1000
        remainder = num % 1000
        result = convert_less_than_thousand(thousands) + " Thousand"
        if remainder > 0:
            result += " " + convert_less_than_thousand(remainder)
    elif num < 10000000:
        lakhs = num // 100000
        remainder = num % 100000
        result = convert_less_than_thousand(lakhs) + " Lakh"
        if remainder > 0:
            if remainder < 1000:
                result += " " + convert_less_than_thousand(remainder)
            else:
                thousands = remainder // 1000
                thousands_remainder = remainder % 1000
                result += " " + convert_less_than_thousand(thousands) + " Thousand"
                if thousands_remainder > 0:
                    result += " " + convert_less_than_thousand(thousands_remainder)
    else:
        crores = num // 10000000
        remainder = num % 10000000
        result = convert_less_than_thousand(crores) + " Crore"
        if remainder > 0:
            if remainder < 100000:
                if remainder < 1000:
                    result += " " + convert_less_than_thousand(remainder)
                else:
                    thousands = remainder // 1000
                    thousands_remainder = remainder % 1000
                    result += " " + convert_less_than_thousand(thousands) + " Thousand"
                    if thousands_remainder > 0:
                        result += " " + convert_less_than_thousand(thousands_remainder)
            else:
                lakhs = remainder // 100000
                lakhs_remainder = remainder % 100000
                result += " " + convert_less_than_thousand(lakhs) + " Lakh"
                if lakhs_remainder > 0:
                    if lakhs_remainder < 1000:
                        result += " " + convert_less_than_thousand(lakhs_remainder)
                    else:
                        thousands = lakhs_remainder // 1000
                        thousands_remainder = lakhs_remainder % 1000
                        result += " " + convert_less_than_thousand(thousands) + " Thousand"
                        if thousands_remainder > 0:
                            result += " " + convert_less_than_thousand(thousands_remainder)

    return result + " Only"


# =================================================================================
# 1.3 — FUNCTION: format_currency_indian   (UNCHANGED)
# =================================================================================
def format_currency_indian(amount):
    """Formats a number into Indian style: ₹1,23,456."""
    if amount is None:
        return "₹0"
    amount = int(amount)
    s = str(amount)
    if len(s) <= 3:
        return f"₹{s}"
    last_three = s[-3:]
    rest = s[:-3]
    if len(rest) <= 2:
        formatted = f"{rest},{last_three}"
    else:
        rest_groups = []
        while rest:
            rest_groups.insert(0, rest[-2:])
            rest = rest[:-2]
        formatted = f"{','.join(rest_groups)},{last_three}"
    return f"₹{formatted}"


# =================================================================================
# 1.4 — FUNCTION: get_app_base_path   (UPDATED — with diagnostic log)
# =================================================================================
# In the desktop app, this pointed to the folder containing the .exe or script.
# In the Flet web app, this always points to the FLET_HAJ root folder on the SERVER.
#
# On Railway, this resolves to: /app
# On your local PC, this resolves to: C:\Users\Masood\Desktop\FLET_HAJ
_BASE_PATH_CACHE = None


def get_app_base_path():
    """Returns the base directory of the app (server-side)."""
    global _BASE_PATH_CACHE
    if _BASE_PATH_CACHE is None:
        _BASE_PATH_CACHE = str(Path(__file__).resolve().parent.parent)
        print(f"[HELPERS] Base path resolved to: {_BASE_PATH_CACHE}")
    return _BASE_PATH_CACHE


# =================================================================================
# 1.4b — FUNCTION: get_data_path   (NEW)
# =================================================================================
def get_data_path():
    """Returns the data folder path (creates it if missing)."""
    p = Path(get_app_base_path()) / "data"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


# =================================================================================
# 1.4c — FUNCTION: get_static_path   (NEW)
# =================================================================================
def get_static_path():
    """Returns the static folder path (for browser-downloadable files)."""
    p = Path(get_app_base_path()) / "static"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


# =================================================================================
# 1.5 — FUNCTION: open_file_with_default_app   (WEB STUB)
# =================================================================================
# On the web, you CANNOT open files on the user's PC from the server.
# Instead, when a user clicks "Open PDF", we trigger a browser DOWNLOAD.
#
# The function below is kept as a NO-OP fallback so any old code that calls
# it will not crash. Instead, we've added `send_file_to_user()` which uses
# Flet's built-in download mechanism.
def open_file_with_default_app(path):
    """
    Desktop-only helper. On web this does nothing and returns False.
    Use send_file_to_user() + page.launch_url() to download files instead.
    """
    print(f"[WEB] open_file_with_default_app is disabled on web. File: {path}")
    return False


# =================================================================================
# 1.6 — FUNCTION: send_file_to_user   (FLET-SPECIFIC)
# =================================================================================
def send_file_to_user(page, file_path: str, label: str = "Download"):
    """
    Triggers a browser download of a server-side file.

    HOW IT WORKS:
      1. Copies the file to the app's static folder (so the browser can reach it).
      2. Returns a download URL that you can attach to a button or open with
         page.launch_url().

    USAGE EXAMPLE (inside a Flet event handler):

        def on_export_click(e):
            path = export_pdf(...)          # your existing export logic
            url = send_file_to_user(page, path, "Invoice PDF")
            page.launch_url(url)

    IMPORTANT:
      - The `FLET_HAJ/static/` folder must exist and be registered with
        ft.run(..., assets_dir="static").
    """
    src = Path(file_path)
    if not src.exists():
        print(f"[WEB] File not found: {file_path}")
        return None

    static_dir = Path(get_static_path())
    dst = static_dir / src.name
    try:
        shutil.copy2(src, dst)
    except Exception as e:
        print(f"[WEB] Failed to copy to static: {e}")
        return None

    # Build a relative URL. Flet serves /static/ from the root.
    return f"/static/{src.name}"


# =================================================================================
# 1.7 — MAINTENANCE NOTES
# =================================================================================
# • round_as_per_rules, number_to_words_indian, format_currency_indian:
#   Unchanged — they are pure Python and work identically on web.
#
# • get_app_base_path:
#   Points to FLET_HAJ/ (root of your web project).
#   Prints the resolved path once on first call — check Railway logs to verify.
#
# • get_data_path (NEW):
#   Returns the data folder — use this in database.py instead of hardcoding.
#
# • get_static_path (NEW):
#   Returns the static folder — used by send_file_to_user().
#
# • open_file_with_default_app:
#   Kept as a stub to avoid breaking any code that still calls it.
#
# • send_file_to_user:
#   The web-equivalent of "open file". Copies the file into /static/ and
#   returns a URL the browser can download from.
# =================================================================================
# SECTION 1 END (FLET VERSION)
# =================================================================================