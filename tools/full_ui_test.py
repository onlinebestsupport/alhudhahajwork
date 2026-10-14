#!/usr/bin/env python3
# =================================================================================
# tools/full_ui_test.py — FULL UI + CROSS-PLATFORM TEST SUITE
# =================================================================================
# v1.0 — Tests every page across desktop/tablet/mobile viewports
#
# WHAT IT CHECKS
#   1. All public pages respond with 200
#   2. Required HTML elements exist (buttons, nav, forms)
#   3. Mobile viewport meta tag present
#   4. Login buttons visible (not CSS-hidden on mobile)
#   5. Responsive media queries present
#   6. API endpoints return expected shapes
#   7. Static assets served (logo, robots, css)
#   8. Admin routes (with auth key)
#   9. Traveler portal integrity
#  10. Search for mobile-only CSS hiding login/nav
#
# USAGE
#   python tools\full_ui_test.py
#   python tools\full_ui_test.py --base https://alhudhahaj.work
#   python tools\full_ui_test.py --key YOUR_ADMIN_KEY
# =================================================================================

import os
import sys
import re
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime

# ---- UTF-8 output ----
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- Colors ----
try:
    import ctypes
    ctypes.windll.kernel32.SetConsoleMode(
        ctypes.windll.kernel32.GetStdHandle(-11), 7)
    GREEN, RED, YELLOW, CYAN, BOLD, RESET = (
        "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[1m", "\033[0m")
except Exception:
    GREEN = RED = YELLOW = CYAN = BOLD = RESET = ""

# ---- State ----
PASSED, FAILED, WARNED, INFO_ONLY = [], [], [], []
BASE = "https://alhudhahaj.work"
ADMIN_KEY = ""


# =================================================================================
# OUTPUT
# =================================================================================
def section(n, title):
    print()
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"{BOLD}{CYAN}  {n}. {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")


def test_pass(label):
    PASSED.append(label)
    print(f"  {GREEN}[PASS]{RESET}  {label}")


def test_fail(label, detail=""):
    FAILED.append(f"{label}: {detail}")
    print(f"  {RED}[FAIL]{RESET}  {label}")
    if detail:
        print(f"           {RED}{detail}{RESET}")


def test_warn(label, detail=""):
    WARNED.append(f"{label}: {detail}")
    print(f"  {YELLOW}[WARN]{RESET}  {label}")
    if detail:
        print(f"           {YELLOW}{detail}{RESET}")


def info(label, detail=""):
    INFO_ONLY.append(label)
    line = f"  {CYAN}[INFO]{RESET}  {label}"
    if detail:
        line += f"  -> {detail}"
    print(line)


# =================================================================================
# HTTP HELPERS
# =================================================================================
def fetch(path, timeout=15, headers=None, method="GET"):
    """Fetch URL and return (status, content, headers)."""
    url = path if path.startswith("http") else f"{BASE}{path}"
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "FullUITest/1.0",
        "Accept": "*/*",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)
    except Exception as e:
        return None, str(e).encode(), {}


def fetch_text(path, timeout=15, headers=None):
    status, content, _ = fetch(path, timeout, headers)
    try:
        return status, content.decode("utf-8", errors="replace")
    except Exception:
        return status, ""


# =================================================================================
# 1. SERVER REACHABILITY
# =================================================================================
def test_reachability():
    section(1, "SERVER REACHABILITY")
    info("Base URL", BASE)

    status, content, _ = fetch("/", timeout=10)
    if status == 200:
        test_pass(f"Root reachable ({len(content):,} bytes)")
    else:
        test_fail("Root unreachable", f"status={status}")
        return False
    return True


# =================================================================================
# 2. PUBLIC PAGES (all viewports)
# =================================================================================
def test_public_pages():
    section(2, "PUBLIC PAGES")

    pages = [
        ("/",           "Home / Front Page"),
        ("/traveler",   "Traveler Portal"),
        ("/robots.txt", "robots.txt"),
    ]

    for path, label in pages:
        status, text = fetch_text(path)
        if status == 200:
            test_pass(f"{label} ({len(text):,} chars)")
        elif status in (301, 302, 307):
            test_warn(f"{label} redirects", f"status={status}")
        else:
            test_fail(f"{label} unreachable", f"status={status}")


# =================================================================================
# 3. VIEWPORT META TAG (critical for mobile)
# =================================================================================
def test_viewport_meta():
    section(3, "VIEWPORT META TAG (mobile rendering)")

    for path, label in [("/", "index.html"),
                        ("/traveler", "traveler.html")]:
        status, text = fetch_text(path)
        if status != 200:
            test_fail(f"{label} not reachable", f"status={status}")
            continue

        head = text[:2000].lower()
        if 'name="viewport"' in head or "name='viewport'" in head:
            # Extract content
            m = re.search(
                r'<meta[^>]*name=["\']viewport["\'][^>]*'
                r'content=["\']([^"\']+)["\']',
                text, re.IGNORECASE)
            if m:
                content = m.group(1)
                if "width=device-width" in content:
                    test_pass(f"{label} — viewport OK: {content}")
                else:
                    test_warn(f"{label} — viewport present but no width=device-width",
                              content)
            else:
                test_pass(f"{label} — viewport meta present")
        else:
            test_fail(f"{label} — MISSING viewport meta tag",
                      "Mobile browsers will render at ~980px width")


# =================================================================================
# 4. LOGIN BUTTONS (admin + traveler) — the reported issue
# =================================================================================
def test_login_buttons():
    section(4, "LOGIN BUTTONS (Admin + Traveler)")

    status, text = fetch_text("/")
    if status != 200:
        test_fail("Home unreachable")
        return

    # Search for admin login link/button
    patterns = {
        "Admin login": [
            r'<a[^>]+href=["\'][^"\']*admin[^"\']*["\'][^>]*>[^<]*admin',
            r'admin[^<]*login',
            r'/admin',
        ],
        "Traveler login": [
            r'<a[^>]+href=["\'][^"\']*traveler[^"\']*["\'][^>]*>',
            r'traveler[^<]*login',
            r'/traveler',
        ],
    }

    for label, pattern_list in patterns.items():
        found = False
        for pattern in pattern_list:
            if re.search(pattern, text, re.IGNORECASE):
                test_pass(f"{label} link/button present in HTML")
                found = True
                break
        if not found:
            test_fail(f"{label} link/button NOT FOUND",
                      "Check index.html for the link element")

    # Check for CSS rules that might hide them on mobile
    print()
    info("Checking for CSS that hides buttons on mobile...")

    # Find all @media blocks
    media_blocks = re.findall(
        r'@media\s*\([^)]+\)\s*\{[^}]*\}',
        text, re.DOTALL | re.IGNORECASE)

    if not media_blocks:
        info("No @media blocks found in page (external CSS?)")
    else:
        for block in media_blocks:
            if re.search(r'max-width\s*:\s*(7[0-9][0-9]|6[0-9][0-9])px',
                         block, re.IGNORECASE):
                # This is a mobile media query
                if re.search(r'display\s*:\s*none',
                             block, re.IGNORECASE):
                    # Does it hide anything login-related?
                    if re.search(r'(login|admin|traveler|nav|btn|button)',
                                 block, re.IGNORECASE):
                        test_warn("Mobile CSS may hide login/nav",
                                  "Found display:none in mobile media query")
                        print()
                        print(f"    {YELLOW}Matching block:{RESET}")
                        print(f"    {block[:300]}...")
                        print()

    # Check for display:none inline on login elements
    if re.search(r'style=["\'][^"\']*display\s*:\s*none[^"\']*["\']',
                 text, re.IGNORECASE):
        inline_hidden = re.findall(
            r'<[^>]+style=["\'][^"\']*display\s*:\s*none[^"\']*["\'][^>]*>',
            text, re.IGNORECASE)
        hidden_login = [h for h in inline_hidden
                        if re.search(r'(login|admin|traveler|nav)',
                                     h, re.IGNORECASE)]
        if hidden_login:
            test_fail("Login elements hidden via inline style",
                      f"{len(hidden_login)} element(s) with display:none")


# =================================================================================
# 5. RESPONSIVE MEDIA QUERIES
# =================================================================================
def test_responsive():
    section(5, "RESPONSIVE CSS (media queries)")

    status, text = fetch_text("/")
    if status != 200:
        test_fail("Home unreachable")
        return

    # Extract all media queries
    media_queries = re.findall(
        r'@media\s*\(([^)]+)\)', text, re.IGNORECASE)

    breakpoints = []
    for mq in media_queries:
        mq_clean = mq.strip()
        if "max-width" in mq_clean.lower():
            breakpoints.append(mq_clean)

    if not breakpoints:
        test_warn("No max-width media queries found",
                  "Page may not be responsive — check for external CSS")
    else:
        info(f"Found {len(breakpoints)} responsive breakpoints")
        for bp in breakpoints[:5]:
            info(f"  • {bp}")
        if len(breakpoints) > 5:
            info(f"  ... and {len(breakpoints) - 5} more")

        # Common breakpoints
        common = ["480", "600", "768", "900", "1024"]
        found_common = [c for c in common
                        if any(c in bp for bp in breakpoints)]
        if found_common:
            test_pass(f"Common breakpoints present: {found_common}")


# =================================================================================
# 6. NAV / HEADER ELEMENTS
# =================================================================================
def test_nav_elements():
    section(6, "NAV & HEADER ELEMENTS")

    status, text = fetch_text("/")
    if status != 200:
        test_fail("Home unreachable")
        return

    checks = [
        (r'<nav[\s>]', "Navigation container"),
        (r'<header[\s>]', "Header element"),
        (r'class=["\'][^"\']*nav', "Nav class"),
        (r'class=["\'][^"\']*header', "Header class"),
        (r'href=["\']/?traveler', "Traveler link"),
        (r'href=["\']/?admin', "Admin link"),
    ]

    for pattern, label in checks:
        if re.search(pattern, text, re.IGNORECASE):
            test_pass(f"{label} found")
        else:
            info(f"{label} not found (may be OK)")


# =================================================================================
# 7. TRAVELER PAGE STRUCTURE
# =================================================================================
def test_traveler_page():
    section(7, "TRAVELER PAGE")

    status, text = fetch_text("/traveler")
    if status != 200:
        test_fail("Traveler page unreachable", f"status={status}")
        return

    checks = [
        (r'passport', "Passport input"),
        (r'pin', "PIN input"),
        (r'<form', "Form element"),
        (r'<button', "Submit button"),
    ]

    for pattern, label in checks:
        if re.search(pattern, text, re.IGNORECASE):
            test_pass(f"{label} present")
        else:
            test_warn(f"{label} missing")


# =================================================================================
# 8. API ENDPOINTS
# =================================================================================
def test_api_endpoints():
    section(8, "API ENDPOINTS")

    apis = [
        ("/api/frontpage", 200, "Frontpage config JSON"),
        ("/api/batches",   200, "Batches JSON"),
    ]

    for path, expect, label in apis:
        status, text = fetch_text(path)
        if status == expect:
            # Verify it's JSON
            try:
                data = json.loads(text)
                test_pass(f"{label} ({len(text)} bytes)")
            except Exception:
                test_warn(f"{label} returned non-JSON", text[:100])
        else:
            test_fail(f"{label} status {status}", f"expected {expect}")


# =================================================================================
# 9. STATIC ASSETS
# =================================================================================
def test_static_assets():
    section(9, "STATIC ASSETS")

    assets = [
        ("/static/logo.png", "Logo image"),
        ("/robots.txt",      "robots.txt"),
    ]

    for path, label in assets:
        status, content, _ = fetch(path)
        if status == 200 and len(content) > 0:
            test_pass(f"{label} ({len(content):,} bytes)")
        else:
            test_fail(f"{label} unavailable", f"status={status}")


# =================================================================================
# 10. ADMIN ROUTES (with key)
# =================================================================================
def test_admin_routes():
    section(10, "ADMIN ROUTES")

    if not ADMIN_KEY:
        info("No ADMIN_KEY provided — skipping authenticated routes")
        info("Usage: python tools\\full_ui_test.py --key YOUR_KEY")
        return

    # Admin app
    status, text = fetch_text("/admin")
    if status in (200, 307, 301, 302):
        test_pass(f"Admin page reachable (status={status})")
    else:
        test_fail(f"Admin page unreachable", f"status={status}")

    # Admin API endpoints
    auth_header = {"Authorization": f"Bearer {ADMIN_KEY}"}
    status, text = fetch_text("/api/admin/frontpage/why-empty",
                              headers=auth_header)
    if status == 200:
        test_pass("Admin API authorized")
    else:
        test_fail("Admin API not authorized", f"status={status}")

    # Anonymous should be blocked
    status, text = fetch_text("/api/admin/frontpage/why-empty")
    if status == 401:
        test_pass("Admin API blocks anonymous access")
    else:
        test_fail("Admin API not protected", f"status={status}")


# =================================================================================
# 11. CROSS-PLATFORM HINTS
# =================================================================================
def test_cross_platform_hints():
    section(11, "CROSS-PLATFORM HINTS")

    status, text = fetch_text("/")
    if status != 200:
        return

    # Check for common mobile-friendly indicators
    indicators = [
        (r'width=device-width', "Width=device-width"),
        (r'-webkit-text-size-adjust', "Text size adjust"),
        (r'tap-highlight', "Tap highlight suppression"),
        (r'flex-wrap', "Flex wrap for responsive layouts"),
        (r'touch', "Touch event hints"),
    ]

    for pattern, label in indicators:
        if re.search(pattern, text, re.IGNORECASE):
            test_pass(f"{label} present")
        else:
            info(f"{label} not present")


# =================================================================================
# 12. SUGGESTED FIXES FOR COMMON ISSUES
# =================================================================================
def suggest_fixes():
    section(12, "SUGGESTED FIXES")

    if not FAILED and not WARNED:
        print(f"  {GREEN}No issues to fix — everything looks good!{RESET}")
        return

    print(f"  {BOLD}Common mobile issues and their fixes:{RESET}")
    print()
    print(f"  {CYAN}1. Login buttons hidden on mobile{RESET}")
    print("     Search index.html for a @media block like:")
    print("     @media (max-width: 768px) {")
    print("       .login-buttons { display: none; }  <-- REMOVE")
    print("     }")
    print()
    print(f"  {CYAN}2. Missing viewport meta{RESET}")
    print("     Add to <head>:")
    print("     <meta name=\"viewport\" content=\"width=device-width,")
    print("           initial-scale=1.0, maximum-scale=5.0\">")
    print()
    print(f"  {CYAN}3. Nav overflows on mobile{RESET}")
    print("     Add to nav container:")
    print("     .nav { flex-wrap: wrap; }")
    print()
    print(f"  {CYAN}4. Buttons too small to tap{RESET}")
    print("     Ensure min size 44x44 px on mobile:")
    print("     .btn { min-width: 44px; min-height: 44px; }")


# =================================================================================
# 13. SUMMARY
# =================================================================================
def summary():
    section(13, "SUMMARY")
    print()
    print(f"  {GREEN}PASSED{RESET}   : {len(PASSED)}")
    print(f"  {RED}FAILED{RESET}   : {len(FAILED)}")
    print(f"  {YELLOW}WARNED{RESET}   : {len(WARNED)}")
    print(f"  {CYAN}INFO{RESET}     : {len(INFO_ONLY)}")

    if FAILED:
        print()
        print(f"  {RED}{BOLD}FAILURES:{RESET}")
        for f in FAILED:
            print(f"    - {f}")

    if WARNED:
        print()
        print(f"  {YELLOW}WARNINGS:{RESET}")
        for w in WARNED:
            print(f"    - {w}")

    print()
    if not FAILED:
        print(f"  {GREEN}{BOLD}[SUCCESS] ALL UI CHECKS PASSED{RESET}")
    else:
        print(f"  {RED}{BOLD}[FAIL] {len(FAILED)} CHECK(S) FAILED{RESET}")
    print(f"  Completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"{BOLD}{CYAN}  ALHUDHA HAJ TRAVEL — FULL UI & CROSS-PLATFORM TEST{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"  Base URL: {BASE}")
    print(f"  Admin key: {'provided' if ADMIN_KEY else '(none)'}")

    if not test_reachability():
        summary()
        sys.exit(1)

    test_public_pages()
    test_viewport_meta()
    test_login_buttons()
    test_responsive()
    test_nav_elements()
    test_traveler_page()
    test_api_endpoints()
    test_static_assets()
    test_admin_routes()
    test_cross_platform_hints()
    suggest_fixes()
    summary()

    sys.exit(0 if not FAILED else 1)


if __name__ == "__main__":
    main()