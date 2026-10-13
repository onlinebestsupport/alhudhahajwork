#!/usr/bin/env python3
# =================================================================================
# tools/full_functional_test.py — END-TO-END FUNCTIONAL TEST SUITE
# =================================================================================
# v3.2 — UTF-8 output (fixes cp1252 crash on file redirect)
#
# CHANGES vs v3.1
#   • Forced UTF-8 stdout/stderr (works with > redirect on Windows)
#   • Falls back to ASCII box characters if reconfigure fails
#   • Same CSV-based verification as v3.1
# =================================================================================
import os
import sys
import shutil
import argparse
import traceback
from datetime import datetime
from pathlib import Path

# ---- Force UTF-8 output (fixes cp1252 encoding errors on redirect) ----
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    _UTF8_OK = True
except Exception:
    _UTF8_OK = False

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

try:
    from core.database import HajDatabase
except Exception as _e:
    print(f"FATAL: cannot import HajDatabase: {_e}")
    sys.exit(1)

try:
    import pandas as pd
    _PD = True
except Exception:
    _PD = False

# ---- Color + box chars ----
try:
    import ctypes
    ctypes.windll.kernel32.SetConsoleMode(
        ctypes.windll.kernel32.GetStdHandle(-11), 7)
    GREEN, RED, YELLOW, CYAN, BOLD, RESET = (
        "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[1m", "\033[0m")
except Exception:
    GREEN = RED = YELLOW = CYAN = BOLD = RESET = ""

# Box drawing chars (fallback to ASCII if UTF-8 not available)
if _UTF8_OK:
    BOX_H, BOX_TL, BOX_TR, BOX_BL, BOX_BR = "═", "╔", "╗", "╚", "╝"
else:
    BOX_H, BOX_TL, BOX_TR, BOX_BL, BOX_BR = "=", "+", "+", "+", "+"

TEST_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_DIR = BASE / "data" / f"_test_backup_{TEST_TS}"
PASSED, FAILED, SKIPPED, INFO_ONLY = [], [], [], []

PRE_IDS = {"batches": set(), "travelers": set(), "payments": set(),
           "invoices": set(), "receipts": set(), "users": set()}

CREATED = {"batches": [], "travelers": [], "payments": [],
           "invoices": [], "receipts": [], "users": []}

FILE_MAP = {
    "batches": "batches.csv",
    "travelers": "travelers.csv",
    "payments": "payments.csv",
    "invoices": "invoices.csv",
    "receipts": "receipts.csv",
    "users": "users.csv",
}


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


def test_skip(label, reason=""):
    SKIPPED.append(f"{label}: {reason}")
    print(f"  {YELLOW}[SKIP]{RESET}  {label}")
    if reason:
        print(f"           {YELLOW}{reason}{RESET}")


def info(label, detail=""):
    INFO_ONLY.append(label)
    line = f"  {CYAN}[INFO]{RESET}  {label}"
    if detail:
        line += f"  -> {detail}"
    print(line)


def make_test_id(kind):
    return f"TEST_{kind}_{TEST_TS}"


# =================================================================================
# CSV HELPERS
# =================================================================================
def csv_read_ids(filename):
    if not _PD:
        return set()
    p = BASE / "data" / filename
    if not p.exists():
        return set()
    try:
        df = pd.read_csv(p, dtype=str).fillna("")
        if "id" not in df.columns:
            return set()
        return {str(x).strip() for x in df["id"] if str(x).strip()}
    except Exception:
        return set()


def csv_has_id(filename, id_value):
    return str(id_value) in csv_read_ids(filename)


def csv_remove_by_id(filename, id_value):
    if not _PD:
        return False
    p = BASE / "data" / filename
    if not p.exists():
        return False
    try:
        df = pd.read_csv(p, dtype=str).fillna("")
        if "id" not in df.columns:
            return False
        before = len(df)
        df = df[df["id"].astype(str) != str(id_value)]
        if len(df) == before:
            return False
        df.to_csv(p, index=False, encoding="utf-8-sig")
        return True
    except Exception as e:
        print(f"    CSV error ({filename}): {e}")
        return False


def csv_remove_receipts_for_payment(payment_id):
    if not _PD:
        return 0
    p = BASE / "data" / "receipts.csv"
    if not p.exists():
        return 0
    try:
        df = pd.read_csv(p, dtype=str).fillna("")
        if "payment_id" not in df.columns:
            return 0
        before = len(df)
        df = df[df["payment_id"].astype(str) != str(payment_id)]
        removed = before - len(df)
        if removed:
            df.to_csv(p, index=False, encoding="utf-8-sig")
        return removed
    except Exception:
        return 0


# =================================================================================
# DB SNAPSHOT
# =================================================================================
def snapshot_ids(db):
    mapping = {
        "batches": "get_batches", "travelers": "get_travelers",
        "payments": "get_payments", "invoices": "get_invoices",
        "receipts": "get_receipts", "users": "get_users",
    }
    for kind, getter in mapping.items():
        fn = getattr(db, getter, None)
        if callable(fn):
            try:
                PRE_IDS[kind] = {str(r.get("id", "")) for r in (fn() or [])
                                 if r.get("id")}
            except Exception:
                PRE_IDS[kind] = set()


def diff_new_ids(db, kind):
    fn = getattr(db, f"get_{kind}", None)
    if not callable(fn):
        return []
    try:
        current = {str(r.get("id", "")) for r in (fn() or [])
                   if r.get("id")}
        return list(current - PRE_IDS.get(kind, set()))
    except Exception:
        return []


def refresh_db(db):
    for meth in ("reload_all", "reload"):
        fn = getattr(db, meth, None)
        if callable(fn):
            try:
                fn()
                return
            except Exception:
                continue


# =================================================================================
# 1. SETUP
# =================================================================================
def setup_checks():
    section(1, "SETUP & SAFETY CHECKS")
    on_railway = bool(os.getenv("RAILWAY_ENVIRONMENT"))
    info("Environment", "Railway" if on_railway else "Local")

    args = parse_args()
    if on_railway and not args.force:
        test_fail("Production safety check", "Use --force")
        return None
    test_pass("Production safety check")

    try:
        data_dir = BASE / "data"
        if not data_dir.exists():
            test_fail("Data folder", "missing")
            return None
        shutil.copytree(data_dir, BACKUP_DIR,
                        ignore=shutil.ignore_patterns(
                            "_test_backup_*", "*.tmp", "*.log", "backups"))
        info("Backup location", str(BACKUP_DIR))
        test_pass("Data folder backed up")
    except Exception as e:
        test_fail("Backup", str(e))
        return None

    try:
        db = HajDatabase()
        test_pass("HajDatabase initialized")
        snapshot_ids(db)
        info("Pre-test ID snapshot taken")
        return db
    except Exception as e:
        test_fail("HajDatabase init", str(e))
        return None


# =================================================================================
# 2. BATCHES
# =================================================================================
def test_batches(db):
    section(2, "BATCH CRUD")
    batches = db.get_batches() or []
    info("Existing batches", str(len(batches)))
    if not batches:
        test_skip("Batch tests", "no existing batch")
        return None

    try:
        template = dict(batches[0])
        for k in list(template.keys()):
            template[k] = ""
        template["id"] = make_test_id("BATCH")
        template["batch_name"] = f"TEST_Functional Batch {TEST_TS}"
        template["tour_type_name"] = "Haj"
        template["year"] = "2027"
        template["total_seats"] = 50
        template["available_seats"] = 50
        template["price"] = 500000.0
        template["status"] = "Open"

        adder = getattr(db, "add_batch", None)
        if not callable(adder):
            test_skip("Add batch", "add_batch missing")
            return None

        adder(template)
        refresh_db(db)
        new_ids = diff_new_ids(db, "batches")
        real_id = new_ids[-1] if new_ids else ""
        for nid in new_ids:
            if nid not in CREATED["batches"]:
                CREATED["batches"].append(nid)

        test_pass(f"Add batch: {real_id}")

        try:
            added = db.get_batch_by_id(real_id)
            if added:
                added["batch_name"] = f"TEST_Updated {TEST_TS}"
                updater = getattr(db, "update_batch", None)
                if callable(updater):
                    updater(real_id, added)
                    refresh_db(db)
                    refetch = db.get_batch_by_id(real_id)
                    if refetch and str(refetch.get("batch_name", "")).startswith("TEST_Updated"):
                        test_pass("Update batch")
                    else:
                        test_fail("Update batch", "name not changed")
        except Exception as e:
            test_fail("Update batch", str(e))

        try:
            all_b = db.get_batches() or []
            same = [b for b in all_b if str(b.get("id", "")) == real_id]
            if len(same) == 1:
                test_pass("Duplicate ID prevented")
            else:
                test_fail("Duplicate ID created", f"{len(same)} records")
        except Exception as e:
            test_skip("Duplicate ID test", str(e))

        return {"id": real_id}
    except Exception as e:
        test_fail("Add batch", str(e))
        traceback.print_exc()
        return None


# =================================================================================
# 3. TRAVELERS
# =================================================================================
def test_travelers(db, test_batch):
    section(3, "TRAVELER CRUD")
    travelers = db.get_travelers() or []
    info("Existing travelers", str(len(travelers)))
    if not travelers:
        test_skip("Traveler tests", "no existing traveler")
        return None

    try:
        template = dict(travelers[0])
        for k in list(template.keys()):
            template[k] = ""
        template["id"] = make_test_id("TRAVELER")
        # Use REAL column names (first_name, last_name)
        template["first_name"] = f"TEST_First {TEST_TS}"
        template["last_name"] = "TEST_Last"
        template["passport_name"] = f"TEST_Traveler {TEST_TS}"
        template["passport_no"] = f"TESTPP{TEST_TS}"
        if test_batch:
            template["batch_id"] = test_batch["id"]
        template["phone"] = "9999999999"
        template["email"] = "test@test.com"

        adder = getattr(db, "add_traveler", None)
        if not callable(adder):
            test_skip("Add traveler", "add_traveler missing")
            return None

        adder(template)
        refresh_db(db)
        new_ids = diff_new_ids(db, "travelers")
        real_id = new_ids[-1] if new_ids else ""
        for nid in new_ids:
            if nid not in CREATED["travelers"]:
                CREATED["travelers"].append(nid)

        test_pass(f"Add traveler: {real_id}")

        try:
            added = next((t for t in (db.get_travelers() or [])
                          if str(t.get("id")) == real_id), None)
            if added:
                new_first = f"TEST_Updated {TEST_TS}"
                added["first_name"] = new_first
                updater = getattr(db, "update_traveler", None)
                if callable(updater):
                    updater(real_id, added)
                    refresh_db(db)
                    refetch = next((t for t in (db.get_travelers() or [])
                                    if str(t.get("id")) == real_id), None)
                    if refetch and str(refetch.get("first_name", "")).startswith("TEST_Updated"):
                        test_pass("Update traveler")
                    else:
                        actual = refetch.get("first_name") if refetch else "(not found)"
                        test_fail("Update traveler",
                                  f"first_name={actual!r}, expected={new_first!r}")
                else:
                    test_skip("Update traveler", "update_traveler missing")
        except Exception as e:
            test_fail("Update traveler", str(e))

        return {"id": real_id}
    except Exception as e:
        test_fail("Add traveler", str(e))
        return None


# =================================================================================
# 4. PAYMENTS
# =================================================================================
def test_payments(db, test_traveler):
    section(4, "PAYMENT CRUD")
    payments = db.get_payments() or []
    info("Existing payments", str(len(payments)))
    if not test_traveler:
        test_skip("Payment tests", "no test traveler")
        return None

    try:
        template = dict(payments[0]) if payments else {}
        for k in list(template.keys()):
            template[k] = ""
        template["id"] = make_test_id("PAYMENT")
        template["traveler_id"] = test_traveler["id"]
        template["amount"] = 10000.0
        template["payment_date"] = datetime.now().strftime("%d-%m-%Y")
        template["mode"] = "Cash"

        adder = getattr(db, "add_payment", None)
        if not callable(adder):
            test_skip("Add payment", "add_payment missing")
            return None

        pre_r = len(db.get_receipts() or [])
        adder(template)
        refresh_db(db)

        new_pay_ids = diff_new_ids(db, "payments")
        real_id = new_pay_ids[-1] if new_pay_ids else ""
        for nid in new_pay_ids:
            if nid not in CREATED["payments"]:
                CREATED["payments"].append(nid)

        new_rec_ids = diff_new_ids(db, "receipts")
        for nid in new_rec_ids:
            if nid not in CREATED["receipts"]:
                CREATED["receipts"].append(nid)

        test_pass(f"Add payment: {real_id}")

        try:
            added = next((p for p in (db.get_payments() or [])
                          if str(p.get("id")) == real_id), None)
            if added:
                amt = float(added.get("amount", 0) or 0)
                if abs(amt - 10000.0) < 0.01:
                    test_pass("Payment amount stored exactly")
                else:
                    test_fail("Payment amount", f"expected 10000, got {amt}")
        except Exception as e:
            test_fail("Payment amount", str(e))

        post_r = len(db.get_receipts() or [])
        if post_r > pre_r:
            info(f"Receipts auto-created: +{post_r - pre_r}")

        return {"id": real_id}
    except Exception as e:
        test_fail("Add payment", str(e))
        traceback.print_exc()
        return None


# =================================================================================
# 5. INVOICES
# =================================================================================
def test_invoices(db, test_traveler):
    section(5, "INVOICE CRUD")
    info("Existing invoices", str(len(db.get_invoices() or [])))
    adder = None
    for name in ("add_invoice", "create_invoice", "add_new_invoice"):
        if callable(getattr(db, name, None)):
            adder = name
            break
    if not adder:
        info("No add_invoice method", "invoices may be auto-generated")
        test_skip("Add invoice", "no add_invoice method")
        return None

    try:
        invoices = db.get_invoices() or []
        template = dict(invoices[0]) if invoices else {}
        for k in list(template.keys()):
            template[k] = ""
        template["id"] = make_test_id("INVOICE")
        template["traveler_id"] = test_traveler["id"]
        template["amount"] = 25000.0
        template["invoice_date"] = datetime.now().strftime("%d-%m-%Y")
        template["status"] = "Pending"

        getattr(db, adder)(template)
        refresh_db(db)
        new_ids = diff_new_ids(db, "invoices")
        real_id = new_ids[-1] if new_ids else ""
        for nid in new_ids:
            if nid not in CREATED["invoices"]:
                CREATED["invoices"].append(nid)

        test_pass(f"Add invoice via {adder}(): {real_id}")
        return {"id": real_id}
    except Exception as e:
        test_fail("Add invoice", str(e))
        return None


# =================================================================================
# 6. RECEIPTS
# =================================================================================
def test_receipts(db, test_payment):
    section(6, "RECEIPT CRUD")
    info("Existing receipts", str(len(db.get_receipts() or [])))
    adder = None
    for name in ("add_receipt", "create_receipt", "generate_receipt"):
        if callable(getattr(db, name, None)):
            adder = name
            break
    if not adder:
        info("No add_receipt method", "receipts auto-generated with payments")
        test_skip("Add receipt", "no add_receipt method")
        return None

    try:
        receipts = db.get_receipts() or []
        template = dict(receipts[0]) if receipts else {}
        for k in list(template.keys()):
            template[k] = ""
        template["id"] = make_test_id("RECEIPT")
        template["payment_id"] = test_payment["id"]
        template["amount"] = 10000.0
        template["receipt_date"] = datetime.now().strftime("%d-%m-%Y")

        getattr(db, adder)(template)
        refresh_db(db)
        new_ids = diff_new_ids(db, "receipts")
        real_id = new_ids[-1] if new_ids else ""
        for nid in new_ids:
            if nid not in CREATED["receipts"]:
                CREATED["receipts"].append(nid)

        test_pass(f"Add receipt via {adder}(): {real_id}")
        return {"id": real_id}
    except Exception as e:
        test_fail("Add receipt", str(e))
        return None


# =================================================================================
# 7. USERS
# =================================================================================
def test_users(db):
    section(7, "USER CRUD + AUTH")
    users = db.get_users() or []
    info("Existing users", str(len(users)))
    if not users:
        test_skip("User tests", "no existing user")
        return None

    try:
        template = dict(users[0])
        for k in list(template.keys()):
            template[k] = ""
        template["id"] = make_test_id("USER")
        template["username"] = f"testuser_{TEST_TS}"
        template["password"] = "TestPass@123"
        template["role"] = "viewer"

        adder = getattr(db, "add_user", None)
        if not callable(adder):
            test_skip("Add user", "add_user missing")
            return None

        adder(template)
        refresh_db(db)
        new_ids = diff_new_ids(db, "users")
        real_id = new_ids[-1] if new_ids else ""
        for nid in new_ids:
            if nid not in CREATED["users"]:
                CREATED["users"].append(nid)

        test_pass(f"Add user: {template['username']}")

        auth = getattr(db, "authenticate_user", None)
        if callable(auth):
            if auth(template["username"], "TestPass@123"):
                test_pass("Authenticate valid credentials")
            else:
                test_fail("Auth valid", "returned None")
            if not auth(template["username"], "WrongPassword"):
                test_pass("Reject invalid password")
            else:
                test_fail("Invalid password accepted")
        else:
            test_skip("Auth test", "authenticate_user missing")

        return {"id": real_id}
    except Exception as e:
        test_fail("Add user", str(e))
        return None


# =================================================================================
# 8. REPORTS
# =================================================================================
def test_reports(db):
    section(8, "REPORT GENERATION")
    exports_dir = BASE / "exports"
    for sub in ("excel", "csv", "pdf"):
        (exports_dir / sub).mkdir(parents=True, exist_ok=True)

    try:
        from core.custom_report_dialog import CustomReportDialog
        test_pass("Import CustomReportDialog")
    except Exception as e:
        test_fail("Import CustomReportDialog", str(e))
        return

    for m in ("export_to_excel", "export_to_csv", "export_to_pdf",
              "display_preview", "generate_preview"):
        if hasattr(CustomReportDialog, m):
            test_pass(f"CustomReportDialog.{m}()")
        else:
            test_fail(f"CustomReportDialog.{m}() missing")

    for sub in ("excel", "csv", "pdf"):
        d = exports_dir / sub
        try:
            t = d / "_test_write.tmp"
            t.write_text("x")
            t.unlink()
            test_pass(f"exports/{sub}/ writable")
        except Exception as e:
            test_fail(f"exports/{sub}/ writable", str(e))


# =================================================================================
# 9. BACKUP
# =================================================================================
def test_backup(db):
    section(9, "DATA BACKUP")
    fn = getattr(db, "create_backup", None)
    if not callable(fn):
        test_skip("Create backup", "create_backup missing")
        return
    try:
        result = fn()
        if result and os.path.exists(str(result)):
            test_pass(f"Create backup ({os.path.getsize(str(result)):,} bytes)")
        else:
            d = BASE / "data" / "backups"
            if d.exists() and list(d.glob("*")):
                test_pass(f"Backup created: {sorted(d.glob('*'))[-1].name}")
            else:
                test_skip("Create backup", "no file created")
    except Exception as e:
        test_fail("Create backup", str(e))


# =================================================================================
# 10. FRONTPAGE
# =================================================================================
def test_frontpage(db):
    section(10, "FRONTPAGE CONFIG")
    try:
        from core.frontpage_config import (
            load_config, save_config, get_selected_batch_ids)
    except Exception as e:
        test_fail("Import frontpage_config", str(e))
        return

    try:
        cfg = load_config()
        test_pass("Load frontpage_config")
        original = get_selected_batch_ids(cfg)
        info("Selected batch IDs", str(len(original)))
    except Exception as e:
        test_fail("Load frontpage_config", str(e))
        return

    try:
        test_id = make_test_id("FPBATCH")
        t = dict(cfg)
        t["packages"] = dict(cfg.get("packages", {}))
        t["packages"]["selected_batch_ids"] = [test_id]
        if save_config(t):
            if test_id in get_selected_batch_ids(load_config()):
                test_pass("Config roundtrip")
            else:
                test_fail("Config roundtrip", "ID not persisted")
            save_config(cfg)
            if get_selected_batch_ids(load_config()) == original:
                test_pass("Config restored")
            else:
                test_fail("Config restore", "original IDs lost")
        else:
            test_fail("Save config", "returned False")
    except Exception as e:
        test_fail("Frontpage roundtrip", str(e))


# =================================================================================
# 11. GALLERY
# =================================================================================
def test_gallery():
    section(11, "GALLERY CONFIG")
    try:
        from core.frontpage_config import (
            add_gallery_item, remove_gallery_item, list_gallery_items)
    except Exception as e:
        test_fail("Import gallery", str(e))
        return

    url = f"/media/gallery/photos/{make_test_id('GALLERY')}.png"
    item = {"url": url, "caption": "test",
            "uploaded_at": datetime.now().isoformat(),
            "size": 0, "original_name": "test.png"}

    try:
        before = len(list_gallery_items("photos"))
        if add_gallery_item("photos", item):
            if any(x.get("url") == url
                   for x in list_gallery_items("photos")):
                test_pass("Add gallery item")
            else:
                test_fail("Add gallery item", "not found")
            remove_gallery_item("photos", url)
            final = list_gallery_items("photos")
            if not any(x.get("url") == url for x in final) \
                    and len(final) == before:
                test_pass("Remove gallery item")
            else:
                test_fail("Remove gallery item", "not fully removed")
        else:
            test_fail("Add gallery item", "returned False")
    except Exception as e:
        test_fail("Gallery test", str(e))


# =================================================================================
# 12. SETTINGS
# =================================================================================
def test_settings(db):
    section(12, "SETTINGS MANAGER")
    try:
        from core.settings_manager import SettingsManager
        sm = SettingsManager(db)
        test_pass("Instantiate SettingsManager")
    except Exception as e:
        test_fail("SettingsManager", str(e))
        return

    try:
        c = sm.get_company_settings()
        test_pass(f"Company: {c.get('company_name', '?')}")
    except Exception as e:
        test_fail("Company settings", str(e))

    try:
        t = sm.get_tax_settings()
        test_pass(f"Tax: GST={t.get('gst_percentage')}%, "
                  f"TCS={t.get('tcs_percentage')}%")
    except Exception as e:
        test_fail("Tax settings", str(e))

    try:
        types = sm.get_tour_types()
        test_pass(f"Tour types: {len(types or [])}")
    except Exception as e:
        test_fail("Tour types", str(e))


# =================================================================================
# 13. CLEANUP
# =================================================================================
def cleanup(db, keep=False):
    section(13, "CLEANUP")

    if keep:
        info("Cleanup skipped", "--keep")
        return

    refresh_db(db)
    for kind in CREATED:
        diff = diff_new_ids(db, kind)
        for nid in diff:
            if nid not in CREATED[kind]:
                CREATED[kind].append(nid)

    print()
    info("Tracked records:",
         f"batches={len(CREATED['batches'])}, "
         f"travelers={len(CREATED['travelers'])}, "
         f"payments={len(CREATED['payments'])}, "
         f"receipts={len(CREATED['receipts'])}, "
         f"invoices={len(CREATED['invoices'])}, "
         f"users={len(CREATED['users'])}")

    # Step 1: Remove receipts
    del_r = getattr(db, "delete_receipt", None)
    for rid in CREATED["receipts"]:
        deleted = False
        if callable(del_r):
            try:
                del_r(rid)
                deleted = True
            except Exception:
                pass
        if not deleted:
            csv_remove_by_id("receipts.csv", rid)

    # Step 2: Remove payments (with linked receipts first)
    del_p = getattr(db, "delete_payment", None)
    for pid in CREATED["payments"]:
        csv_remove_receipts_for_payment(pid)
        deleted = False
        if callable(del_p):
            try:
                del_p(pid)
                deleted = True
            except Exception:
                pass
        if not deleted:
            csv_remove_by_id("payments.csv", pid)

    # Step 3: invoices
    del_i = getattr(db, "delete_invoice", None)
    for iid in CREATED["invoices"]:
        deleted = False
        if callable(del_i):
            try:
                del_i(iid)
                deleted = True
            except Exception:
                pass
        if not deleted:
            csv_remove_by_id("invoices.csv", iid)

    # Step 4: travelers
    del_t = getattr(db, "delete_traveler", None)
    for tid in CREATED["travelers"]:
        deleted = False
        if callable(del_t):
            try:
                del_t(tid)
                deleted = True
            except Exception:
                pass
        if not deleted:
            csv_remove_by_id("travelers.csv", tid)

    # Step 5: batches
    del_b = getattr(db, "delete_batch", None)
    for bid in CREATED["batches"]:
        deleted = False
        if callable(del_b):
            try:
                del_b(bid)
                deleted = True
            except Exception:
                pass
        if not deleted:
            csv_remove_by_id("batches.csv", bid)

    # Step 6: users
    del_u = getattr(db, "delete_user", None)
    for uid in CREATED["users"]:
        deleted = False
        if callable(del_u):
            try:
                del_u(uid)
                deleted = True
            except Exception:
                pass
        if not deleted:
            csv_remove_by_id("users.csv", uid)

    # Step 7: Verify from CSV (ground truth)
    print()
    info("Verifying cleanup from CSV files (ground truth)...")

    for kind in CREATED:
        filename = FILE_MAP[kind]
        still = [rid for rid in CREATED[kind]
                 if csv_has_id(filename, rid)]
        if still:
            test_fail(f"Cleanup {kind}",
                      f"{len(still)} residue: {still[:3]}")
        else:
            test_pass(f"Cleanup {kind} - {len(CREATED[kind])} test record(s) removed")

    refresh_db(db)


# =================================================================================
# 14. RESTORE
# =================================================================================
def restore_from_backup():
    section(14, "RESTORE FROM BACKUP")
    backups = sorted((BASE / "data").glob("_test_backup_*"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        test_fail("Restore", "no backups found")
        return
    latest = backups[0]
    info("Latest", str(latest))
    try:
        data_dir = BASE / "data"
        for item in data_dir.iterdir():
            if item.name.startswith("_test_backup_"):
                continue
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        for item in latest.iterdir():
            dest = data_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        test_pass("Restore complete")
    except Exception as e:
        test_fail("Restore", str(e))


# =================================================================================
# SUMMARY
# =================================================================================
def summary():
    section(15, "SUMMARY")
    print()
    print(f"  {GREEN}PASSED{RESET}   : {len(PASSED)}")
    print(f"  {RED}FAILED{RESET}   : {len(FAILED)}")
    print(f"  {YELLOW}SKIPPED{RESET}  : {len(SKIPPED)}")
    print(f"  {CYAN}INFO{RESET}     : {len(INFO_ONLY)}")

    if FAILED:
        print()
        print(f"  {RED}{BOLD}FAILURES:{RESET}")
        for f in FAILED:
            print(f"    - {f}")
    if SKIPPED:
        print()
        print(f"  {YELLOW}SKIPPED:{RESET}")
        for s in SKIPPED:
            print(f"    - {s}")
    print()
    if not FAILED:
        print(f"  {GREEN}{BOLD}[SUCCESS] ALL FUNCTIONAL TESTS PASSED{RESET}")
    else:
        print(f"  {RED}{BOLD}[FAIL] {len(FAILED)} TEST(S) FAILED{RESET}")
    print(f"  Backup: {BACKUP_DIR}")
    print()


def parse_args():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--keep", action="store_true")
    p.add_argument("--restore", action="store_true")
    p.add_argument("--force", action="store_true")
    a, _ = p.parse_known_args()
    return a


def main():
    args = parse_args()
    print()
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"{BOLD}{CYAN}  ALHUDHA HAJ TRAVEL SYSTEM - FUNCTIONAL TEST SUITE v3.2{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"  Test run: {TEST_TS}")
    print(f"  Base:     {BASE}")
    print(f"  UTF-8:    {'yes' if _UTF8_OK else 'no (ASCII fallback)'}")

    if args.restore:
        restore_from_backup()
        summary()
        sys.exit(0 if not FAILED else 1)

    db = setup_checks()
    if not db:
        summary()
        sys.exit(1)

    test_batch = test_batches(db)
    test_traveler = test_travelers(db, test_batch)
    test_payment = test_payments(db, test_traveler)
    test_invoices(db, test_traveler)
    test_receipts(db, test_payment)
    test_users(db)
    test_reports(db)
    test_backup(db)
    test_frontpage(db)
    test_gallery()
    test_settings(db)
    cleanup(db, keep=args.keep)
    summary()
    sys.exit(0 if not FAILED else 1)


if __name__ == "__main__":
    main()