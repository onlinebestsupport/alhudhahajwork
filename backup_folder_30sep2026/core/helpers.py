# =================================================================================
# SECTION 1 (FLET VERSION) — HELPER FUNCTIONS
# =================================================================================

import os
import sys
import subprocess
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
# 1.4 — FUNCTION: get_app_base_path   (UPDATED FOR WEB)
# =================================================================================
# In the desktop app, this pointed to the folder containing the .exe or script.
# In the Flet web app, this always points to the FLET_HAJ root folder on the SERVER.
def get_app_base_path():
    """Returns the base directory of the app (server-side)."""
    # helpers.py is inside FLET_HAJ/core/
    # .parent → core/
    # .parent.parent → FLET_HAJ/
    return str(Path(__file__).resolve().parent.parent)


# =================================================================================
# 1.5 — FUNCTION: open_file_with_default_app   (REPLACED FOR WEB)
# =================================================================================
# NOTE: On the web, you CANNOT open files on the user's PC from the server.
# Instead, when a user clicks "Open PDF", we trigger a browser DOWNLOAD.
#
# The function below is kept as a NO-OP fallback so any old code that calls
# it will not crash. Instead, we've added `send_file_to_user()` which uses
# Flet's built-in download mechanism.
def open_file_with_default_app(path):
    """
    Desktop-only helper. On web this does nothing and returns False.
    Use ft.FilePicker + page.launch_url() to download files instead.
    """
    print(f"[WEB] open_file_with_default_app is disabled on web. File: {path}")
    return False


# =================================================================================
# 1.6 — NEW HELPER: send_file_to_user   (FLET-SPECIFIC)
# =================================================================================
def send_file_to_user(page, file_path: str, label: str = "Download"):
    """
    Triggers a browser download of a server-side file.

    HOW IT WORKS:
      1. Copies the file to the app's static folder (so the browser can reach it).
      2. Returns a download URL that you can attach to an ft.ElevatedButton
         (or open with page.launch_url()).

    USAGE EXAMPLE (inside a Flet event handler):

        def on_export_click(e):
            path = export_pdf(...)          # your existing export logic
            url = send_file_to_user(page, path, "Invoice PDF")
            page.launch_url(url)

    IMPORTANT:
      - The `FLET_HAJ/static/` folder must exist and be registered with ft.app().
      - Never expose your real DB folder as static — only use the exports folder.
    """
    import shutil
    from pathlib import Path

    # Ensure static folder exists
    base = Path(get_app_base_path())
    static_dir = base / "static"
    static_dir.mkdir(exist_ok=True)

    src = Path(file_path)
    if not src.exists():
        print(f"[WEB] File not found: {file_path}")
        return None

    dst = static_dir / src.name
    shutil.copy2(src, dst)

    # Build a relative URL. Flet serves /static/ from the root.
    return f"/static/{src.name}"


# =================================================================================
# 1.7 — MAINTENANCE NOTES
# =================================================================================
# • round_as_per_rules, number_to_words_indian, format_currency_indian:
#   Unchanged — they are pure Python and work identically on web.
#
# • get_app_base_path:
#   Now points to FLET_HAJ/ (the root of your web project) instead of the
#   folder containing the .exe. All folder paths (data, uploads, exports,
#   static) are built relative to this.
#
# • open_file_with_default_app:
#   Kept as a stub to avoid breaking any code that still calls it.
#   On the web you must download files through the browser instead.
#
# • send_file_to_user (NEW):
#   The web-equivalent of "open file". Copies the file into /static/ and
#   returns a URL the browser can download from.
#
# • test_check (recommended):
#   After every section migration, run this in a Python shell:
#       from core.helpers import format_currency_indian
#       print(format_currency_indian(1234567))  # → ₹12,34,567
#   If it prints correctly, Section 1 is OK.

# =================================================================================
# SECTION 1 END (FLET VERSION)
# =================================================================================