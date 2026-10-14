#!/usr/bin/env python3
# =================================================================================
# tools/master_test.py — MASTER TEST SUITE (ALL-IN-ONE)
# =================================================================================
# Runs EVERY test on your Alhudha Haj Travel System.
#
# v2.0 — Fixed false positive on mobile button labels
#   • Section 3 now correctly ignores `display: none` on inner labels/icons
#   • Only flags `display: none` on the BUTTON itself, not its content
#
# USAGE
#   python tools\master_test.py
#   python tools\master_test.py --key YOUR_ADMIN_KEY
# =================================================================================

import os
import sys
import re
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ---- Force UTF-8 output ----
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- Colored output ----
try:
    import ctypes
    ctypes.windll.kernel32.SetConsoleMode(
        ctypes.windll.kernel32.GetStdHandle(-11), 7)
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
except Exception:
    GREEN = RED = YELLOW = CYAN = BOLD = RESET = ""

# ---- Constants ----
BASE = "https://alhudhahaj.work"
ADMIN_KEY = ""
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Results
PASSED, FAILED, WARNED = [], [], []
ISSUES_WITH_FIXES = []


# =================================================================================
# OUTPUT HELPERS
# =================================================================================
def section(n, title):
    print()
    print(f"{BOLD}{CYAN}{'═' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  {n}. {title}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 70}{RESET}")


def ok(msg):
    PASSED.append(msg)
    print(f"  {GREEN}[OK]{RESET}    {msg}")


def bad(msg, reason="", fix=""):
    FAILED.append(msg)
    print(f"  {RED}[BROKEN]{RESET} {msg}")
    if reason:
        print(f"            {RED}Reason: {reason}{RESET}")
    if fix:
        print(f"            {YELLOW}How to fix: {fix}{RESET}")
        ISSUES_WITH_FIXES.append((msg, fix))


def warn(msg, fix=""):
    WARNED.append(msg)
    print(f"  {YELLOW}[WARN]{RESET}  {msg}")
    if fix:
        print(f"            {YELLOW}Note: {fix}{RESET}")


def info(msg):
    print(f"  {CYAN}[INFO]{RESET}  {msg}")


def fetch(path, timeout=15, headers=None):
    url = path if path.startswith("http") else f"{BASE}{path}"
    h = {"User-Agent": "MasterTest/2.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


# =================================================================================
# 1. SERVER ONLINE?
# =================================================================================
def test_server_online():
    section(1, "IS THE SERVER ONLINE?")
    info(f"Checking: {BASE}")

    status, _ = fetch("/", timeout=10)
    if status == 200:
        ok("Server is online and responding")
        return True
    else:
        bad("Server is not reachable",
            f"Got status: {status}",
            "Check Railway dashboard. Is the service running?")
        return False


# =================================================================================
# 2. PAGES EXIST?
# =================================================================================
def test_pages_exist():
    section(2, "DO ALL PAGES LOAD?")

    pages = [
        ("/",             "Home page"),
        ("/traveler",     "Traveler login page"),
        ("/robots.txt",   "Search engine rules file"),
    ]

    for path, label in pages:
        status, content = fetch(path)
        if status == 200:
            size = len(content)
            ok(f"{label} loads ({size:,} characters)")
        elif status in (301, 302, 307):
            warn(f"{label} redirects to another page",
                 "This is usually fine")
        else:
            bad(f"{label} does not load",
                f"Got status: {status}",
                f"Check that {path} is a valid route")


# =================================================================================
# 3. MOBILE FRIENDLINESS  (v2.0 — fixed false positive)
# =================================================================================
def test_mobile_friendly():
    section(3, "WILL IT WORK ON MOBILE PHONES?")

    status, html = fetch("/")
    if status != 200:
        bad("Cannot check mobile friendliness", "Home page did not load")
        return

    # Check 1: viewport meta tag
    if re.search(r'<meta[^>]*name=["\']viewport["\'][^>]*>', html, re.IGNORECASE):
        m = re.search(
            r'<meta[^>]*name=["\']viewport["\'][^>]*content=["\']([^"\']+)["\']',
            html, re.IGNORECASE)
        if m and "width=device-width" in m.group(1):
            ok("Viewport tag is correct (mobile will render properly)")
        else:
            bad("Viewport tag is present but incorrect",
                f"Content: {m.group(1) if m else 'unknown'}",
                'Should be: <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    else:
        bad("Viewport meta tag is MISSING",
            "Without this, phones show a zoomed-out desktop page",
            'Add to <head> of index.html:\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">')

    # Check 2: CSS media queries
    media_queries = re.findall(r'@media\s*\(([^)]+)\)', html, re.IGNORECASE)
    mobile_queries = [m for m in media_queries if "max-width" in m.lower()]
    if mobile_queries:
        ok(f"Found {len(mobile_queries)} mobile CSS breakpoints")
    else:
        warn("No mobile CSS breakpoints found",
             "Page may not adapt to phone screens")

    # Check 3: does anything hide login/nav buttons on mobile?
    print()
    info("Checking if login buttons are hidden on mobile...")

    # Find all @media blocks
    media_blocks = re.findall(
        r'@media\s*\([^)]*max-width[^)]*\)\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',
        html, re.DOTALL | re.IGNORECASE)

    hidden_found = False
    for block in media_blocks:
        if re.search(r'display\s*:\s*none', block, re.IGNORECASE):
            # Strip out rules that ONLY hide inner labels/icons
            # (those are cosmetic — not a functional problem)
            stripped = block
            # Remove any CSS rule whose selector ends in .btn-label, .btn-icon,
            # .nav-text, .label, or .icon (inner parts of a button)
            stripped = re.sub(
                r'[^{}]*\.(?:btn-label|btn-icon|nav-text|label|icon)'
                r'\s*\{[^}]*\}',
                '', stripped, flags=re.IGNORECASE)
            # Also strip pseudo-elements (:before, :after)
            stripped = re.sub(
                r'[^{}]*::(?:before|after)\s*\{[^}]*\}',
                '', stripped, flags=re.IGNORECASE)
            stripped = re.sub(
                r'[^{}]*:(?:before|after)\s*\{[^}]*\}',
                '', stripped, flags=re.IGNORECASE)

            # If no display:none remains after stripping inner labels,
            # this rule is cosmetic — skip it
            if not re.search(r'display\s*:\s*none', stripped, re.IGNORECASE):
                continue

            # Check if the remaining display:none is on login/nav/btn
            if re.search(r'(login|admin|traveler|nav|btn|button|header)',
                         stripped, re.IGNORECASE):
                hidden_found = True
                bad("Login/nav buttons are HIDDEN on mobile screens",
                    "Found CSS rule 'display: none' in a mobile media query "
                    "on the button itself (not just its label)",
                    "Open static/index.html and find this block. "
                    "Remove or modify the line that hides the login buttons.")
                print()
                print(f"            {YELLOW}The problematic CSS block:{RESET}")
                print(f"            {stripped[:400]}")
                print()

    if not hidden_found:
        ok("Login buttons are visible on mobile (no rules hiding them)")


# =================================================================================
# 4. LOGIN BUTTONS PRESENT?
# =================================================================================
def test_login_buttons_present():
    section(4, "ARE LOGIN BUTTONS IN THE HTML?")

    status, html = fetch("/")
    if status != 200:
        bad("Cannot check login buttons", "Home page did not load")
        return

    # Admin login
    if re.search(r'href=["\'][^"\']*admin[^"\']*["\']', html, re.IGNORECASE):
        ok("Admin login link exists in HTML")
    elif re.search(r'>\s*admin\s*<', html, re.IGNORECASE):
        ok("Admin login text exists in HTML")
    else:
        bad("Admin login button NOT FOUND",
            "No link to /admin found in the HTML",
            "Add a link like: <a href='/admin'>Admin Login</a>")

    # Traveler login
    if re.search(r'href=["\'][^"\']*traveler[^"\']*["\']', html, re.IGNORECASE):
        ok("Traveler login link exists in HTML")
    elif re.search(r'>\s*traveler\s*<', html, re.IGNORECASE):
        ok("Traveler login text exists in HTML")
    else:
        bad("Traveler login button NOT FOUND",
            "No link to /traveler found in the HTML",
            "Add a link like: <a href='/traveler'>Traveler Login</a>")


# =================================================================================
# 5. API ENDPOINTS WORKING?
# =================================================================================
def test_apis_work():
    section(5, "DO THE DATA APIs WORK?")

    apis = [
        ("/api/frontpage", "Front page settings"),
        ("/api/batches",   "Package/batch data"),
    ]

    for path, label in apis:
        status, content = fetch(path)
        if status == 200:
            try:
                json.loads(content)
                ok(f"{label} works and returns valid data")
            except Exception:
                warn(f"{label} responds but returns invalid JSON")
        else:
            bad(f"{label} does not work",
                f"Status: {status}",
                "Check the server logs in Railway")


# =================================================================================
# 6. STATIC FILES PRESENT?
# =================================================================================
def test_static_files():
    section(6, "ARE LOGO AND OTHER FILES AVAILABLE?")

    files = [
        ("/static/logo.png", "Website logo"),
        ("/robots.txt",      "Search engine rules"),
    ]

    for path, label in files:
        status, content = fetch(path)
        if status == 200 and len(content) > 0:
            ok(f"{label} is available")
        else:
            bad(f"{label} is missing",
                f"Status: {status}",
                f"Check that {path} exists on the server")


# =================================================================================
# 7. SECURITY — ADMIN PROTECTED?
# =================================================================================
def test_security():
    section(7, "IS THE ADMIN AREA PROTECTED?")

    status, _ = fetch("/api/admin/frontpage/why-empty")
    if status == 401:
        ok("Admin API blocks anonymous access (secure)")
    elif status == 200:
        bad("Admin API is OPEN — ANYONE CAN ACCESS IT!",
            "Got 200 without a key",
            "This is a SECURITY HOLE. Check main.py has require_admin on admin routes.")
    elif status == 503:
        warn("Admin API not configured",
             "ADMIN_API_KEY may be missing on Railway")
    else:
        warn(f"Admin API returns status {status}")

    if ADMIN_KEY:
        status, _ = fetch("/api/admin/frontpage/why-empty",
                          headers={"Authorization": f"Bearer {ADMIN_KEY}"})
        if status == 200:
            ok("Admin API accepts valid key (working)")
        else:
            bad("Admin API rejects valid key",
                f"Status: {status}",
                "Check the ADMIN_API_KEY on Railway matches what you typed")

    # Security headers
    try:
        import http.client
        import urllib.parse
        parsed = urllib.parse.urlparse(BASE)
        conn = http.client.HTTPSConnection(parsed.netloc, timeout=10)
        conn.request("HEAD", "/")
        resp = conn.getresponse()
        headers = dict(resp.getheaders())
        conn.close()

        expected = [
            "strict-transport-security",
            "x-frame-options",
            "x-content-type-options",
            "content-security-policy",
        ]
        missing = [h for h in expected if h not in headers]
        if not missing:
            ok("All security headers present")
        else:
            bad("Some security headers missing",
                f"Missing: {', '.join(missing)}",
                "Check SecurityHeadersMiddleware in main.py")
    except Exception as e:
        warn(f"Could not check security headers: {e}")


# =================================================================================
# 8. LOCAL FILES — ALL PRESENT?
# =================================================================================
def test_local_files():
    section(8, "ARE ALL YOUR LOCAL FILES PRESENT?")

    required = [
        "main.py",
        "core/database.py",
        "core/security.py",
        "core/frontpage_config.py",
        "core/frontpage_settings_tab.py",
        "core/main_window.py",
        "core/login_view.py",
        "static/index.html",
        "static/traveler.html",
        "static/gallery_upload.html",
        "static/robots.txt",
    ]

    for rel in required:
        p = PROJECT_ROOT / rel
        if p.exists():
            size = p.stat().st_size
            ok(f"{rel} ({size:,} bytes)")
        else:
            bad(f"{rel} is MISSING",
                "File does not exist locally",
                "Restore from GitHub: git checkout " + rel)


# =================================================================================
# 9. CSS BREAKPOINTS FOR MOBILE
# =================================================================================
def test_css_breakpoints():
    section(9, "DOES THE CSS HANDLE ALL SCREEN SIZES?")

    css_files = list((PROJECT_ROOT / "static").glob("*.css"))

    if not css_files:
        index_file = PROJECT_ROOT / "static" / "index.html"
        if index_file.exists():
            html = index_file.read_text(encoding="utf-8", errors="replace")
            breaks = re.findall(
                r'@media[^{]*max-width[^{]*\{', html, re.IGNORECASE)
            if breaks:
                ok(f"Found {len(breaks)} breakpoints in index.html")
            else:
                warn("No CSS media queries found",
                     "Your page may not adapt to different screen sizes")
        return

    for css_file in css_files:
        content = css_file.read_text(encoding="utf-8", errors="replace")
        breaks = re.findall(
            r'@media[^{]*max-width[^{]*\{', content, re.IGNORECASE)
        if breaks:
            ok(f"{css_file.name}: {len(breaks)} breakpoints")
        else:
            warn(f"{css_file.name}: no breakpoints",
                 "Consider adding responsive rules")


# =================================================================================
# 10. LOCAL PYTHON TESTS
# =================================================================================
def test_local_python():
    section(10, "DOES YOUR LOCAL PYTHON CODE WORK?")

    sys.path.insert(0, str(PROJECT_ROOT))

    modules = [
        ("core.database", "Database module"),
        ("core.security", "Security module"),
        ("core.frontpage_config", "Front page config"),
    ]

    for mod_name, label in modules:
        try:
            __import__(mod_name)
            ok(f"{label} imports cleanly")
        except Exception as e:
            bad(f"{label} has errors",
                str(e)[:100],
                f"Check {mod_name.replace('.', '/')}.py for syntax errors")


# =================================================================================
# 11. DATA FILES VALID?
# =================================================================================
def test_data_files():
    section(11, "ARE YOUR DATA FILES VALID?")

    data_dir = PROJECT_ROOT / "data"

    csvs = [
        "users.csv", "travelers.csv", "batches.csv",
        "payments.csv", "invoices.csv", "receipts.csv",
    ]

    try:
        import pandas as pd
    except ImportError:
        warn("Cannot check CSVs — pandas not installed")
        return

    for csv_name in csvs:
        p = data_dir / csv_name
        if not p.exists():
            bad(f"{csv_name} missing", "File not found",
                "Restore from backup or GitHub")
            continue
        try:
            df = pd.read_csv(p, dtype=str).fillna("")
            ok(f"{csv_name}: {len(df)} rows, {len(df.columns)} columns")
        except Exception as e:
            bad(f"{csv_name} is corrupted",
                str(e)[:80],
                "Restore this file from your backups folder")


# =================================================================================
# 12. FINAL SUMMARY & ACTION PLAN
# =================================================================================
def summary():
    section(12, "SUMMARY & ACTION PLAN")

    total = len(PASSED) + len(FAILED)
    print()
    print(f"  {BOLD}Test Results:{RESET}")
    print(f"    {GREEN}✓ Passed:  {len(PASSED)}{RESET}")
    print(f"    {RED}✗ Failed:  {len(FAILED)}{RESET}")
    print(f"    {YELLOW}⚠ Warnings: {len(WARNED)}{RESET}")
    print()

    if not FAILED and not WARNED:
        print(f"  {GREEN}{BOLD}🎉 EVERYTHING WORKS PERFECTLY{RESET}")
        print(f"  {GREEN}Your system has no problems.{RESET}")
    elif not FAILED:
        print(f"  {GREEN}{BOLD}✓ SYSTEM WORKS — minor warnings only{RESET}")
    else:
        print(f"  {RED}{BOLD}✗ {len(FAILED)} PROBLEM(S) FOUND — see below{RESET}")
        print()
        print(f"  {BOLD}What to do (in simple words):{RESET}")
        print()
        for i, (issue, fix) in enumerate(ISSUES_WITH_FIXES, 1):
            print(f"  {BOLD}{i}. {issue}{RESET}")
            print(f"     {YELLOW}Fix: {fix}{RESET}")
            print()

    print(f"  {CYAN}Completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print()


# =================================================================================
# MAIN
# =================================================================================
def parse_args():
    global BASE, ADMIN_KEY
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--base", default="https://alhudhahaj.work")
    p.add_argument("--key", default="")
    a, _ = p.parse_known_args()
    BASE = a.base.rstrip("/")
    ADMIN_KEY = a.key.strip()


def main():
    parse_args()

    print()
    print(f"{BOLD}{CYAN}{'═' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  ALHUDHA HAJ TRAVEL — MASTER TEST SUITE v2.0{RESET}")
    print(f"{BOLD}{CYAN}  Testing: {BASE}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 70}{RESET}")
    print(f"  Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not test_server_online():
        summary()
        return

    test_pages_exist()
    test_mobile_friendly()
    test_login_buttons_present()
    test_apis_work()
    test_static_files()
    test_security()
    test_local_files()
    test_css_breakpoints()
    test_local_python()
    test_data_files()

    summary()


if __name__ == "__main__":
    main()