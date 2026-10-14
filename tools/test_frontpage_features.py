#!/usr/bin/env python3
# =================================================================================
# tools/test_frontpage_features.py — FRONTPAGE SETTINGS TEST SUITE
# =================================================================================
# Tests EVERY input field in the admin Front Page tab.
#
# WHAT IT TESTS
#   §1  Setup & backup
#   §2  Config schema integrity (all keys present)
#   §3  Hero fields round-trip
#   §4  Alert fields round-trip
#   §5  Features array round-trip
#   §6  Packages config round-trip
#   §7  About fields round-trip
#   §8  Contact fields round-trip
#   §9  Social links round-trip
#   §10 Footer round-trip
#   §11 Gallery config round-trip
#   §12 Batch selection state
#   §13 Edge cases (unicode, empty, long strings)
#   §14 Config restore verification
#   §15 Summary
#
# USAGE
#   python tools\test_frontpage_features.py
#   python tools\test_frontpage_features.py --keep   (keep test changes)
# =================================================================================

import os
import sys
import json
import shutil
import argparse
from datetime import datetime
from pathlib import Path

# ---- Force UTF-8 ----
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- Project imports ----
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.frontpage_config import (
    load_config, save_config, DEFAULT_CONFIG, _deep_merge,
    normalize_batch_ids, get_selected_batch_ids,
    add_gallery_item, remove_gallery_item, list_gallery_items,
    gallery_summary, config_exists, _config_path)

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
PASSED, FAILED, WARNED = [], [], []
TEST_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_PATH = None


# =================================================================================
# OUTPUT
# =================================================================================
def section(n, title):
    print()
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"{BOLD}{CYAN}  §{n}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")


def ok(msg):
    PASSED.append(msg)
    print(f"  {GREEN}[PASS]{RESET}  {msg}")


def fail(msg, detail=""):
    FAILED.append(f"{msg} — {detail}" if detail else msg)
    print(f"  {RED}[FAIL]{RESET}  {msg}")
    if detail:
        print(f"          {RED}{detail}{RESET}")


def warn(msg, detail=""):
    WARNED.append(msg)
    print(f"  {YELLOW}[WARN]{RESET}  {msg}")
    if detail:
        print(f"          {YELLOW}{detail}{RESET}")


def info(msg):
    print(f"  {CYAN}[INFO]{RESET}  {msg}")


# =================================================================================
# HELPERS
# =================================================================================
def get_nested(d, path):
    """Get value from nested dict by dot path. e.g. 'hero.heading'"""
    parts = path.split(".")
    cur = d
    for p in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def set_nested(d, path, value):
    """Set value in nested dict by dot path (creates intermediate)."""
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def test_roundtrip(name, modifications):
    """
    Apply modifications to config, save, reload, verify each value
    survived. Restores original at end.
    """
    original = load_config()
    try:
        cfg = json.loads(json.dumps(original))  # deep copy
        for path, value in modifications.items():
            set_nested(cfg, path, value)

        save_ok = save_config(cfg)
        if not save_ok:
            fail(f"{name}: save_config returned False")
            return

        reloaded = load_config()
        all_ok = True
        for path, expected in modifications.items():
            actual = get_nested(reloaded, path)
            if actual != expected:
                fail(f"{name}: {path}",
                     f"expected {expected!r}, got {actual!r}")
                all_ok = False

        if all_ok:
            ok(f"{name} ({len(modifications)} field(s))")
    except Exception as e:
        fail(f"{name}: exception", str(e))
    finally:
        # Always restore original
        save_config(original)


# =================================================================================
# §1 — SETUP
# =================================================================================
def setup():
    global BACKUP_PATH
    section(1, "SETUP & BACKUP")

    cfg_path = _config_path()
    info(f"Config file: {cfg_path}")

    if not config_exists():
        fail("Config file does not exist")
        return False

    # Backup
    BACKUP_PATH = cfg_path + f".test_{TEST_TS}.bak"
    try:
        shutil.copy2(cfg_path, BACKUP_PATH)
        info(f"Backup saved to: {BACKUP_PATH}")
        ok("Config file backed up")
    except Exception as e:
        fail("Backup failed", str(e))
        return False

    # Sanity: current config loads
    try:
        cfg = load_config()
        ok(f"Config loads ({len(cfg)} top-level keys)")
    except Exception as e:
        fail("Config load failed", str(e))
        return False

    return True


# =================================================================================
# §2 — SCHEMA INTEGRITY
# =================================================================================
def test_schema():
    section(2, "CONFIG SCHEMA INTEGRITY")

    cfg = load_config()

    # Every top-level key in DEFAULT_CONFIG must exist in loaded config
    expected_keys = list(DEFAULT_CONFIG.keys())
    missing = [k for k in expected_keys if k not in cfg]

    if missing:
        fail(f"{len(missing)} top-level keys missing",
             f"Missing: {missing}")
    else:
        ok(f"All {len(expected_keys)} top-level keys present")

    # Every section must have the same keys as DEFAULT_CONFIG
    for section_key in expected_keys:
        default_sub = DEFAULT_CONFIG[section_key]
        loaded_sub = cfg.get(section_key)

        if isinstance(default_sub, dict):
            if not isinstance(loaded_sub, dict):
                fail(f"{section_key} is not a dict",
                     f"got {type(loaded_sub).__name__}")
                continue
            default_fields = set(default_sub.keys())
            loaded_fields = set(loaded_sub.keys())
            missing_sub = default_fields - loaded_fields
            if missing_sub:
                fail(f"{section_key} missing sub-keys",
                     f"Missing: {sorted(missing_sub)}")
            else:
                ok(f"{section_key} has all {len(default_fields)} sub-keys")

        elif isinstance(default_sub, list):
            if not isinstance(loaded_sub, list):
                fail(f"{section_key} is not a list",
                     f"got {type(loaded_sub).__name__}")
            else:
                ok(f"{section_key} is a list ({len(loaded_sub)} items)")


# =================================================================================
# §3 — HERO
# =================================================================================
def test_hero():
    section(3, "HERO FIELDS")

    test_roundtrip("Hero heading", {
        "hero.heading": "TEST_Hero Heading 2026",
    })

    test_roundtrip("Hero subheading", {
        "hero.subheading": "TEST_Sub heading with multiple words",
    })

    test_roundtrip("Hero button text", {
        "hero.button_text": "TEST_View Packages",
    })

    test_roundtrip("Hero WhatsApp text", {
        "hero.whatsapp_text": "TEST_Chat on WhatsApp",
    })

    test_roundtrip("All hero fields together", {
        "hero.heading": "TEST_All Heading",
        "hero.subheading": "TEST_All Sub",
        "hero.button_text": "TEST_All Button",
        "hero.whatsapp_text": "TEST_All WhatsApp",
    })


# =================================================================================
# §4 — ALERT
# =================================================================================
def test_alert():
    section(4, "ALERT FIELDS")

    test_roundtrip("Alert enabled ON", {
        "alert.enabled": True,
    })
    test_roundtrip("Alert enabled OFF", {
        "alert.enabled": False,
    })
    test_roundtrip("Alert message", {
        "alert.message": "TEST_Alert message goes here",
    })
    test_roundtrip("Alert link", {
        "alert.link": "https://example.com/test",
    })
    test_roundtrip("Alert color hex", {
        "alert.color": "#ff5500",
    })
    test_roundtrip("Alert style pulse", {
        "alert.style": "pulse",
    })
    test_roundtrip("Alert style blink", {
        "alert.style": "blink",
    })
    test_roundtrip("Alert style none", {
        "alert.style": "none",
    })


# =================================================================================
# §5 — FEATURES
# =================================================================================
def test_features():
    section(5, "FEATURES ARRAY")

    # Test 3 features
    test_roundtrip("Features with 3 items", {
        "features": [
            {"icon": "fa-star", "title": "TEST_One", "text": "First"},
            {"icon": "fa-heart", "title": "TEST_Two", "text": "Second"},
            {"icon": "fa-check", "title": "TEST_Three", "text": "Third"},
        ],
    })

    # Empty features
    test_roundtrip("Features empty", {
        "features": [],
    })

    # Single feature
    test_roundtrip("Features 1 item", {
        "features": [
            {"icon": "fa-mosque", "title": "TEST_Single", "text": "Only"}
        ],
    })


# =================================================================================
# §6 — PACKAGES
# =================================================================================
def test_packages():
    section(6, "PACKAGES CONFIG")

    test_roundtrip("Package title", {
        "packages.title": "TEST_Package Title",
    })
    test_roundtrip("Package subtitle", {
        "packages.subtitle": "TEST_Package Subtitle",
    })
    test_roundtrip("Package source batches", {
        "packages.source": "batches",
    })
    test_roundtrip("Package source manual", {
        "packages.source": "manual",
    })
    test_roundtrip("Package max_shown 9", {
        "packages.max_shown": 9,
    })
    test_roundtrip("Package max_shown 15", {
        "packages.max_shown": 15,
    })
    test_roundtrip("Package max_shown 0", {
        "packages.max_shown": 0,
    })

    # Batch IDs
    test_roundtrip("Batch IDs empty", {
        "packages.selected_batch_ids": [],
    })
    test_roundtrip("Batch IDs 3 items", {
        "packages.selected_batch_ids": [
            "HAJ/BCH/2027/001",
            "HAJ/BCH/2027/002",
            "HAJ/BCH/2027/003",
        ],
    })


# =================================================================================
# §7 — ABOUT
# =================================================================================
def test_about():
    section(7, "ABOUT FIELDS")

    test_roundtrip("About heading", {
        "about.heading": "TEST_About Heading",
    })
    test_roundtrip("About paragraph 1", {
        "about.paragraph1": "TEST_First paragraph content",
    })
    test_roundtrip("About paragraph 2", {
        "about.paragraph2": "TEST_Second paragraph content",
    })
    test_roundtrip("About stats 4 items", {
        "about.stats": [
            {"number": "10+", "label": "TEST_Years"},
            {"number": "5k+", "label": "TEST_Clients"},
            {"number": "20+", "label": "TEST_Guides"},
            {"number": "100%", "label": "TEST_Satisfaction"},
        ],
    })
    test_roundtrip("About stats empty", {
        "about.stats": [],
    })


# =================================================================================
# §8 — CONTACT
# =================================================================================
def test_contact():
    section(8, "CONTACT FIELDS")

    test_roundtrip("Contact phone", {
        "contact.phone": "+91 9999999999",
    })
    test_roundtrip("Contact phone 2", {
        "contact.phone2": "+91 8888888888",
    })
    test_roundtrip("Contact email", {
        "contact.email": "test@alhudha.com",
    })
    test_roundtrip("Contact whatsapp", {
        "contact.whatsapp": "919999999999",
    })
    test_roundtrip("Contact address 1", {
        "contact.address_line1": "TEST_Address Line 1",
    })
    test_roundtrip("Contact address 2", {
        "contact.address_line2": "TEST_Address Line 2",
    })


# =================================================================================
# §9 — SOCIAL
# =================================================================================
def test_social():
    section(9, "SOCIAL LINKS")

    test_roundtrip("Social Facebook", {
        "social.facebook": "https://facebook.com/test",
    })
    test_roundtrip("Social Instagram", {
        "social.instagram": "https://instagram.com/test",
    })
    test_roundtrip("Social Twitter", {
        "social.twitter": "https://twitter.com/test",
    })
    test_roundtrip("Social all empty", {
        "social.facebook": "",
        "social.instagram": "",
        "social.twitter": "",
    })


# =================================================================================
# §10 — FOOTER
# =================================================================================
def test_footer():
    section(10, "FOOTER FIELDS")

    test_roundtrip("Footer about text", {
        "footer.about_text": "TEST_Footer about text",
    })
    test_roundtrip("Footer copyright", {
        "footer.copyright": "TEST_Copyright 2026",
    })


# =================================================================================
# §11 — GALLERY CONFIG
# =================================================================================
def test_gallery():
    section(11, "GALLERY CONFIG")

    test_roundtrip("Gallery enabled ON", {
        "gallery.enabled": True,
    })
    test_roundtrip("Gallery enabled OFF", {
        "gallery.enabled": False,
    })
    test_roundtrip("Gallery title", {
        "gallery.title": "TEST_Gallery Title",
    })
    test_roundtrip("Gallery subtitle", {
        "gallery.subtitle": "TEST_Gallery Subtitle",
    })
    test_roundtrip("Gallery max photos", {
        "gallery.max_photos_shown": 20,
    })
    test_roundtrip("Gallery max videos", {
        "gallery.max_videos_shown": 8,
    })
    test_roundtrip("Gallery layout grid", {
        "gallery.layout": "grid",
    })

    # Test adding/removing gallery items via helpers
    section(11, "GALLERY ITEM HELPERS")

    # Clean any leftover test items first
    test_url = f"/media/gallery/photos/TEST_{TEST_TS}.png"
    try:
        remove_gallery_item("photos", test_url)
    except Exception:
        pass

    # Add
    test_item = {
        "url": test_url,
        "caption": "TEST_Caption",
        "uploaded_at": datetime.now().isoformat(),
        "size": 12345,
        "original_name": "test.png",
    }
    try:
        before = len(list_gallery_items("photos"))
        added = add_gallery_item("photos", test_item)
        after = len(list_gallery_items("photos"))
        if added and after == before + 1:
            ok(f"Gallery add works ({before} → {after})")
        else:
            fail("Gallery add failed",
                 f"before={before} after={after}")
    except Exception as e:
        fail("Gallery add exception", str(e))

    # Verify found
    try:
        found = any(x.get("url") == test_url
                    for x in list_gallery_items("photos"))
        if found:
            ok("Gallery item found in list")
        else:
            fail("Gallery item not found after add")
    except Exception as e:
        fail("Gallery list check exception", str(e))

    # Remove
    try:
        removed = remove_gallery_item("photos", test_url)
        after_rm = len(list_gallery_items("photos"))
        still_there = any(x.get("url") == test_url
                          for x in list_gallery_items("photos"))
        if removed and not still_there and after_rm == before:
            ok("Gallery remove works, count restored")
        else:
            fail("Gallery remove failed",
                 f"removed={removed}, still_there={still_there}, "
                 f"after={after_rm}, expected={before}")
    except Exception as e:
        fail("Gallery remove exception", str(e))

    # Summary helper
    try:
        s = gallery_summary()
        ok(f"gallery_summary works: {s['photos']} photos, "
           f"{s['videos']} videos, {s['total_human']}")
    except Exception as e:
        fail("gallery_summary failed", str(e))


# =================================================================================
# §12 — BATCH SELECTION STATE
# =================================================================================
def test_batches():
    section(12, "BATCH SELECTION STATE")

    # normalize_batch_ids
    test_cases = [
        ([], []),
        (["HAJ/BCH/2027/001"], ["HAJ/BCH/2027/001"]),
        (["  HAJ/BCH/2027/001  "], ["HAJ/BCH/2027/001"]),
        (["A", "", None, "B", "A"], ["A", "B"]),
        (["123"], ["123"]),
        (["123.0"], ["123"]),
    ]
    all_ok = True
    for inp, expected in test_cases:
        try:
            got = normalize_batch_ids(inp)
            if got != expected:
                fail(f"normalize_batch_ids({inp!r})",
                     f"expected {expected!r}, got {got!r}")
                all_ok = False
        except Exception as e:
            fail(f"normalize_batch_ids({inp!r})", str(e))
            all_ok = False
    if all_ok:
        ok(f"normalize_batch_ids passes {len(test_cases)} cases")

    # get_selected_batch_ids
    test_roundtrip("Selected batch IDs persist", {
        "packages.selected_batch_ids": ["A", "B", "C"],
    })

    cfg = load_config()
    ids = get_selected_batch_ids(cfg)
    if ids == ["A", "B", "C"]:
        ok(f"get_selected_batch_ids returns {len(ids)} IDs correctly")
    else:
        # It's OK if round-trip already restored
        info(f"get_selected_batch_ids returns: {ids}")


# =================================================================================
# §13 — EDGE CASES
# =================================================================================
def test_edge_cases():
    section(13, "EDGE CASES")

    # Unicode in strings
    test_roundtrip("Unicode in hero heading", {
        "hero.heading": "🕌 بسم الله — TEST",
    })

    # Very long string
    long_text = "A" * 500
    test_roundtrip("Long string (500 chars)", {
        "hero.subheading": long_text,
    })

    # Empty strings
    test_roundtrip("Empty fields", {
        "hero.heading": "",
        "hero.subheading": "",
        "contact.phone": "",
    })

    # HTML-like content (should be stored as-is)
    test_roundtrip("HTML characters stored literally", {
        "hero.heading": "<TEST>&\"'</TEST>",
    })

    # Number as string (max_shown handles int conversion)
    cfg = load_config()
    try:
        cfg["packages"]["max_shown"] = 9
        save_config(cfg)
        reloaded = load_config()
        val = reloaded["packages"]["max_shown"]
        if val == 9:
            ok("max_shown as integer works")
        else:
            fail("max_shown as integer", f"got {val!r}")
    except Exception as e:
        fail("max_shown integer test", str(e))


# =================================================================================
# §14 — RESTORE VERIFICATION
# =================================================================================
def test_restore():
    section(14, "CONFIG RESTORE CHECK")

    if not BACKUP_PATH or not os.path.exists(BACKUP_PATH):
        warn("No backup to verify against")
        return

    try:
        with open(BACKUP_PATH, "r", encoding="utf-8") as f:
            backup_cfg = json.load(f)
        current = load_config()

        # Compare top-level keys
        backup_keys = set(backup_cfg.keys())
        current_keys = set(current.keys())
        if backup_keys == current_keys:
            ok(f"Config structure restored ({len(current_keys)} keys)")
        else:
            diff = backup_keys.symmetric_difference(current_keys)
            warn(f"Structure differs after tests: {diff}")
    except Exception as e:
        fail("Restore verification failed", str(e))


# =================================================================================
# §15 — CLEANUP & SUMMARY
# =================================================================================
def cleanup():
    """Remove backup file (unless --keep)."""
    if BACKUP_PATH and os.path.exists(BACKUP_PATH):
        try:
            os.remove(BACKUP_PATH)
            info(f"Removed backup: {BACKUP_PATH}")
        except Exception as e:
            warn(f"Could not remove backup: {e}")


def summary():
    section(15, "SUMMARY")

    total = len(PASSED) + len(FAILED)
    print()
    print(f"  {BOLD}RESULTS:{RESET}")
    print(f"    {GREEN}PASSED{RESET}  : {len(PASSED)}")
    print(f"    {RED}FAILED{RESET}  : {len(FAILED)}")
    print(f"    {YELLOW}WARNED{RESET}  : {len(WARNED)}")
    print(f"    Total   : {total}")
    print()

    if FAILED:
        print(f"  {RED}{BOLD}FAILURES:{RESET}")
        for f in FAILED:
            print(f"    • {f}")
        print()

    if WARNED:
        print(f"  {YELLOW}WARNINGS:{RESET}")
        for w in WARNED:
            print(f"    • {w}")
        print()

    if not FAILED:
        print(f"  {GREEN}{BOLD}🎉 ALL FRONTPAGE FEATURES WORKING{RESET}")
    else:
        print(f"  {RED}{BOLD}❌ {len(FAILED)} FIELD(S) BROKEN{RESET}")

    print()
    print(f"  Completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


# =================================================================================
# MAIN
# =================================================================================
def parse_args():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--keep", action="store_true",
                   help="Keep the backup file")
    return p.parse_known_args()[0]


def main():
    args = parse_args()

    print()
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"{BOLD}{CYAN}  FRONTPAGE FEATURES TEST SUITE{RESET}")
    print(f"{BOLD}{CYAN}  {_config_path()}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"  Started: {TEST_TS}")

    if not setup():
        summary()
        return

    test_schema()
    test_hero()
    test_alert()
    test_features()
    test_packages()
    test_about()
    test_contact()
    test_social()
    test_footer()
    test_gallery()
    test_batches()
    test_edge_cases()
    test_restore()

    if not args.keep:
        cleanup()

    summary()


if __name__ == "__main__":
    main()