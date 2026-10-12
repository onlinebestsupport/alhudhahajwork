#!/usr/bin/env python3
# =============================================================================
# FLET_HAJ — System Health Check (Windows + Linux/Railway compatible)
# =============================================================================
# v2 — Auto-detects project root, port, and OS
# =============================================================================

import os
import sys
import json
import socket
import tempfile
import traceback
import urllib.request
import urllib.error
from pathlib import Path

# -----------------------------------------------------------------------------
# [0] AUTO-DETECT PROJECT ROOT
#     This script lives at:  <project>/tools/health_check.py
#     So project root is:    parent of tools/
# -----------------------------------------------------------------------------
SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent  # .../FLET_HAJ

# Add project root to import path — works on Windows & Linux
sys.path.insert(0, str(PROJECT_ROOT))

IS_WINDOWS = (os.name == "nt")

# -----------------------------------------------------------------------------
# [1] COLOR SUPPORT (Windows CMD-safe)
# -----------------------------------------------------------------------------
USE_COLOR = True
if IS_WINDOWS:
    try:
        # Try to enable ANSI in Windows CMD
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        USE_COLOR = False

if USE_COLOR:
    GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
    CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"
else:
    GREEN = RED = YELLOW = CYAN = BOLD = RESET = ""

PASS = f"{GREEN}[PASS]{RESET}"
FAIL = f"{RED}[FAIL]{RESET}"
WARN = f"{YELLOW}[WARN]{RESET}"
INFO = f"{CYAN}[INFO]{RESET}"

results = {"passed": 0, "failed": 0, "warned": 0}


def ok(msg):
    results["passed"] += 1
    print(f"  {PASS}  {msg}")


def bad(msg, detail=""):
    results["failed"] += 1
    print(f"  {FAIL}  {msg}")
    if detail:
        print(f"           {detail}")


def warn(msg):
    results["warned"] += 1
    print(f"  {WARN}  {msg}")


def info(msg):
    print(f"  {INFO}  {msg}")


def header(title):
    line = "-" * 70
    print()
    print(f"{BOLD}{CYAN}{line}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{line}{RESET}")


# =============================================================================
# §1 — ENVIRONMENT
# =============================================================================
header("§1  ENVIRONMENT")

info(f"OS              : {os.name} ({'Windows' if IS_WINDOWS else 'POSIX'})")
info(f"Python          : {sys.version.split()[0]}")
info(f"Executable      : {sys.executable}")
info(f"Project root    : {PROJECT_ROOT}")

for pkg_name in ("flet", "fastapi", "uvicorn", "pandas"):
    try:
        mod = __import__(pkg_name)
        ver = getattr(mod, "__version__", "unknown")
        info(f"{pkg_name:15s} : {ver}")
        ok(f"{pkg_name} package importable")
    except Exception as e:
        bad(f"{pkg_name} import failed", str(e))

for var in ("PORT", "RAILWAY_ENVIRONMENT", "RAILWAY_VOLUME_MOUNT_PATH"):
    val = os.getenv(var, "")
    info(f"{var:30s} = {val or '(not set)'}")

# Auto-detect port (8000 on Windows, 8080 on Railway)
DEFAULT_PORT = 8080 if os.getenv("RAILWAY_ENVIRONMENT") else 8000
PORT = int(os.getenv("PORT", DEFAULT_PORT))
info(f"Using port      : {PORT}")


# =============================================================================
# §2 — FILESYSTEM
# =============================================================================
header("§2  FILESYSTEM")

base = str(PROJECT_ROOT)
info(f"Base path       : {base}")

if os.path.isdir(base):
    ok(f"Base path exists")
else:
    bad(f"Base path missing: {base}")

for name, path in [
    ("Static dir",     os.path.join(base, "static")),
    ("Data dir",       os.path.join(base, "data")),
    ("Gallery root",   os.path.join(base, "data", "gallery")),
    ("Gallery photos", os.path.join(base, "data", "gallery", "photos")),
    ("Gallery videos", os.path.join(base, "data", "gallery", "videos")),
    ("Documents dir",  os.path.join(base, "data", "documents")),
    ("Flet assets",    os.path.join(base, "flet_assets")),
    ("Core package",   os.path.join(base, "core")),
    ("Tools dir",      os.path.join(base, "tools")),
]:
    if os.path.isdir(path):
        count = len(os.listdir(path))
        ok(f"{name:16s} exists ({count} items) -> {path}")
    else:
        bad(f"{name:16s} MISSING -> {path}")

# /app/documents symlink — Linux only
if not IS_WINDOWS:
    link = "/app/documents"
    target = "/app/data/documents"
    if os.path.islink(link):
        resolved = os.path.realpath(link)
        if resolved == target:
            ok(f"Symlink correct: {link} -> {target}")
        else:
            warn(f"Symlink points elsewhere: {link} -> {resolved}")
    else:
        warn(f"Symlink missing: {link}")
else:
    info("Symlink check skipped on Windows (Linux-only feature)")


# =============================================================================
# §3 — DATA FILES
# =============================================================================
header("§3  DATA FILES (CSVs)")

expected_csvs = [
    "users.csv", "travelers.csv", "batches.csv",
    "payments.csv", "invoices.csv", "receipts.csv",
]
found = 0
for fname in expected_csvs:
    path = os.path.join(base, "data", fname)
    if os.path.exists(path):
        size = os.path.getsize(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = sum(1 for _ in f)
        except Exception:
            lines = 0
        ok(f"{fname:16s} {size:>8d} B  ({lines} rows)")
        found += 1
    else:
        warn(f"{fname:16s} not found at {path}")

if found == 0:
    bad("No CSVs found in data directory")
else:
    info(f"{found}/{len(expected_csvs)} CSVs present")

fp_cfg = os.path.join(base, "data", "frontpage_config.json")
if os.path.exists(fp_cfg):
    ok(f"frontpage_config.json exists ({os.path.getsize(fp_cfg)} B)")
else:
    warn("frontpage_config.json not yet created")


# =============================================================================
# §4 — FRONTPAGE CONFIG
# =============================================================================
header("§4  FRONTPAGE CONFIG")

try:
    from core.frontpage_config import (
        load_config, save_config, get_selected_batch_ids,
        get_selected_batches, _normalize_id,
        config_exists, MAX_PACKAGES_SHOWN_DEFAULT)
    ok("frontpage_config module importable")

    cfg = load_config()
    ok("load_config() succeeded")

    ids = get_selected_batch_ids(cfg)
    info(f"Selected batch IDs     : {ids}")
    info(f"max_shown              : {cfg.get('packages', {}).get('max_shown')}")
    info(f"source                 : {cfg.get('packages', {}).get('source')}")
    info(f"MAX_PACKAGES_DEFAULT   : {MAX_PACKAGES_SHOWN_DEFAULT}")

    if ids:
        ok(f"{len(ids)} batch(es) selected")
    else:
        warn("No batches selected - front page shows 0 packages")

    # Round-trip save/load
    save_config(cfg)
    reloaded = load_config()
    if json.dumps(reloaded, sort_keys=True) == json.dumps(cfg, sort_keys=True):
        ok("Config round-trip identical")
    else:
        warn("Config round-trip differs (defaults merge)")

    assert _normalize_id(123) == "123"
    assert _normalize_id(123.0) == "123"
    assert _normalize_id("  456  ") == "456"
    assert _normalize_id(None) == ""
    ok("_normalize_id handles int/float/str/None")

except Exception as e:
    bad("Frontpage config error", str(e))
    traceback.print_exc()


# =============================================================================
# §5 — GALLERY
# =============================================================================
header("§5  GALLERY")

try:
    from core.frontpage_config import (
        gallery_summary, add_gallery_item,
        remove_gallery_item, list_gallery_items)

    summary = gallery_summary()
    info(f"Photos : {summary['photos']}")
    info(f"Videos : {summary['videos']}")
    info(f"Total  : {summary['total_human']}")
    ok("gallery_summary() works")

    test_url = "/media/gallery/photos/__healthcheck__.png"
    test_item = {
        "url": test_url, "caption": "health check",
        "uploaded_at": "1970-01-01T00:00:00", "size": 0,
        "original_name": "__healthcheck__",
    }
    before = gallery_summary()["photos"]
    add_ok = add_gallery_item("photos", test_item)
    found = any(x.get("url") == test_url
                for x in list_gallery_items("photos"))
    remove_ok = remove_gallery_item("photos", test_url)
    after = gallery_summary()["photos"]

    if add_ok and found and remove_ok:
        ok("Gallery add/remove round-trip works")
    else:
        bad("Gallery round-trip failed",
            f"add={add_ok} found={found} remove={remove_ok}")

    if after == before:
        ok("Gallery count restored")
    else:
        warn(f"Count mismatch: before={before} after={after}")

except Exception as e:
    bad("Gallery error", str(e))
    traceback.print_exc()


# =============================================================================
# §6 — DATABASE
# =============================================================================
header("§6  DATABASE")

try:
    from core.database import HajDatabase
    db = HajDatabase()
    ok("HajDatabase instantiated")

    users = db.get_users() or []
    travelers = db.get_travelers() or []
    batches = db.get_batches() or []
    info(f"Users     : {len(users)}")
    info(f"Travelers : {len(travelers)}")
    info(f"Batches   : {len(batches)}")

    if len(batches) > 0:
        ok(f"Loaded {len(batches)} batches")
        for b in batches[:5]:
            info(f"  - {b.get('id','?')}  {b.get('batch_name','?')}")
    else:
        warn("No batches in DB")

    from core.frontpage_config import get_selected_batches, load_config
    cfg = load_config()
    selected = get_selected_batches(cfg, batches)
    info(f"get_selected_batches returns: {len(selected)}")
    if len(selected) > 0:
        ok(f"Front page would show {len(selected)} package(s)")
    else:
        warn("Front page would show 0 packages")

except Exception as e:
    bad("Database error", str(e))
    traceback.print_exc()


# =============================================================================
# §7 — MAIN APP MODULE
# =============================================================================
header("§7  MAIN APP MODULE")

try:
    main_path = os.path.join(base, "main.py")
    if not os.path.exists(main_path):
        bad(f"main.py not found at {main_path}")
    else:
        info(f"main.py size: {os.path.getsize(main_path)} B")
        ok("main.py present")

        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()

        required = [
            "def flet_main", "def _build_app", "def _init_db",
            "def _seed_volume_if_empty", "def _ensure_documents_symlink",
            "async def api_frontpage", "async def api_batches",
            "async def upload_gallery_media", "async def traveler_login",
            'app.mount("/admin"', 'app.mount("/static"',
        ]
        missing = [s for s in required if s not in content]
        if missing:
            bad(f"Missing symbols in main.py: {missing}")
        else:
            ok(f"All {len(required)} required symbols found in main.py")

except Exception as e:
    bad("Main app inspection error", str(e))
    traceback.print_exc()


# =============================================================================
# §8 — HTTP SELF-TEST
# =============================================================================
header("§8  HTTP SELF-TEST (localhost)")

base_url = f"http://127.0.0.1:{PORT}"

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(2)
try:
    result = sock.connect_ex(("127.0.0.1", PORT))
    if result == 0:
        ok(f"Server listening on port {PORT}")
        server_up = True
    else:
        warn(f"Server NOT listening on port {PORT}")
        info("Start it with: python main.py  (in another terminal)")
        server_up = False
finally:
    sock.close()


def http_test(method, path, timeout=10):
    url = f"{base_url}{path}"
    try:
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()


if server_up:
    endpoints = [
        ("GET", "/",                          "Public front page"),
        ("GET", "/api/frontpage",             "Front page config API"),
        ("GET", "/api/batches",               "Batches API"),
        ("GET", "/admin",                     "Flet admin mount"),
        ("GET", "/traveler",                  "Traveler portal"),
        ("GET", "/gallery-upload",            "Gallery upload page"),
        ("GET", "/traveler-doc-upload",       "Traveler doc upload"),
        ("GET", "/static/logo.png",           "Static logo"),
        ("GET", "/api/admin/frontpage/why-empty", "Why-empty diagnostic"),
    ]
    for method, path, desc in endpoints:
        status, body = http_test(method, path)
        if status is None:
            bad(f"{desc:35s} {path}", f"Failed: {body[:80]}")
        elif status in (200, 301, 302, 307, 308):
            ok(f"{desc:35s} {path}  ->  {status}  ({len(body)} B)")
        elif status in (401, 403):
            info(f"{desc:35s} {path}  ->  {status}  (auth required)")
        else:
            bad(f"{desc:35s} {path}  ->  {status}")

    status, body = http_test("GET", "/api/traveler/me")
    if status in (401, 403):
        ok(f"{'Traveler /me (needs auth)':35s} /api/traveler/me  ->  {status}")
    else:
        warn(f"Traveler /me returned {status} (expected 401)")
else:
    info("Skipping HTTP tests (server not running)")
    info("Run: python main.py  in another terminal, then re-run this script")


# =============================================================================
# §9 — DISK WRITE PERMISSIONS
# =============================================================================
header("§9  DISK WRITE PERMISSIONS")

paths = [
    ("Data dir",       os.path.join(base, "data")),
    ("Gallery photos", os.path.join(base, "data", "gallery", "photos")),
    ("Gallery videos", os.path.join(base, "data", "gallery", "videos")),
    ("Documents",      os.path.join(base, "data", "documents")),
    ("Temp dir",       tempfile.gettempdir()),
]
for name, path in paths:
    if not os.path.isdir(path):
        warn(f"{name:16s} does not exist")
        continue
    try:
        tf = tempfile.NamedTemporaryFile(
            mode="w", dir=path, prefix=".hc_",
            suffix=".tmp", delete=False)
        tf.write("test"); tf.close()
        os.unlink(tf.name)
        ok(f"{name:16s} writable")
    except Exception as e:
        bad(f"{name:16s} NOT writable", str(e))


# =============================================================================
# §10 — SUMMARY
# =============================================================================
header("§10  SUMMARY")

total = sum(results.values())
print()
print(f"  Total checks : {total}")
print(f"  {GREEN}Passed{RESET}       : {results['passed']}")
print(f"  {YELLOW}Warned{RESET}       : {results['warned']}")
print(f"  {RED}Failed{RESET}       : {results['failed']}")
print()

if results["failed"] == 0 and results["warned"] == 0:
    print(f"  {GREEN}{BOLD}*** ALL CHECKS PASSED - SYSTEM HEALTHY ***{RESET}")
    sys.exit(0)
elif results["failed"] == 0:
    print(f"  {YELLOW}{BOLD}System operational with "
          f"{results['warned']} warning(s){RESET}")
    sys.exit(0)
else:
    print(f"  {RED}{BOLD}*** {results['failed']} CHECK(S) FAILED ***{RESET}")
    sys.exit(1)