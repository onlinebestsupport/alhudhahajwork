# =================================================================================
# system_check.py — FULL SYSTEM DIAGNOSTIC
# =================================================================================
# Covers:
#   1. Environment & dependencies
#   2. Every .py file (front + back)
#   3. Module imports (cross-module API)
#   4. Class / method inventory
#   5. Database layer API
#   6. Settings manager API
#   7. Reports / custom report API
#   8. Data integrity (CSV rows, relationships)
#   9. Photo system API
#  10. Export pipeline API
#  11. Route / view integrity
#  12. Cross-module call verification
# =================================================================================
import os
import sys
import importlib
import inspect
import traceback
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# =================================================================================
# HELPERS
# =================================================================================
FAILS = []
WARNS = []


def section(n, title):
    print()
    print("╔" + "═" * 70 + "╗")
    print(f"║ {n}. {title:<66}║")
    print("╚" + "═" * 70 + "╝")


def ok(label, detail=""):
    line = f"  ✅  {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)


def warn(label, detail=""):
    line = f"  ⚠️   {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)
    WARNS.append(label)


def fail(label, detail=""):
    line = f"  ❌  {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)
    FAILS.append(label)


def info(label, detail=""):
    line = f"  ℹ️   {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)


def try_import(mod_name, alias=None):
    """Import a module, return (module, error_str)."""
    try:
        if alias:
            mod = importlib.import_module(mod_name)
            return mod, None
        mod = importlib.import_module(mod_name)
        return mod, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def list_methods(cls, public_only=True):
    """Return list of (name, signature) tuples for methods of a class."""
    out = []
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if public_only and name.startswith("_"):
            continue
        try:
            sig = str(inspect.signature(member))
        except Exception:
            sig = "(?)"
        out.append((name, sig))
    return out


# =================================================================================
# 1. ENVIRONMENT
# =================================================================================
def check_environment():
    section(1, "ENVIRONMENT & DEPENDENCIES")
    print(f"  Python executable : {sys.executable}")
    print(f"  Python version    : {sys.version.split()[0]}")
    print(f"  Platform          : {sys.platform}")
    print(f"  Working dir       : {os.getcwd()}")
    print(f"  Project root      : {BASE}")
    print()

    deps = [
        ("flet", "Flet"),
        ("pandas", "Pandas"),
        ("numpy", "Numpy"),
        ("PIL", "Pillow"),
        ("openpyxl", "openpyxl"),
        ("reportlab", "reportlab"),
        ("matplotlib", "Matplotlib"),
    ]
    for mod_name, label in deps:
        try:
            m = importlib.import_module(mod_name)
            ver = getattr(m, "__version__", "") or getattr(m, "Version", "") or "?"
            ok(label, ver)
        except ImportError:
            if mod_name in ("PIL", "openpyxl", "reportlab"):
                fail(f"{label} MISSING", "required for exports")
            else:
                fail(f"{label} MISSING")


# =================================================================================
# 2. ALL .PY FILES (FRONT + BACK)
# =================================================================================
def check_files():
    section(2, "ALL .PY FILES (FRONT + BACK)")
    print(f"  Scanning: {BASE}")
    print()

    # Root-level .py files
    print("  [ Root ]")
    root_py = sorted(BASE.glob("*.py"))
    for f in root_py:
        size = f.stat().st_size
        lines = sum(1 for _ in f.open("r", encoding="utf-8", errors="ignore"))
        ok(f.name, f"{lines} lines, {size:,} bytes")

    # core/ .py files
    print()
    print("  [ core/ ]")
    core = BASE / "core"
    if not core.exists():
        fail("core/ folder missing")
        return
    core_py = sorted(core.glob("*.py"))
    if not core_py:
        fail("no .py files in core/")
    for f in core_py:
        size = f.stat().st_size
        lines = sum(1 for _ in f.open("r", encoding="utf-8", errors="ignore"))
        ok(f.name, f"{lines} lines, {size:,} bytes")

    # Any other subfolder .py files
    print()
    print("  [ Other folders ]")
    others = [f for f in BASE.rglob("*.py")
              if f.parent not in (BASE, core)]
    if not others:
        info("(no other .py files)")
    for f in sorted(others):
        rel = f.relative_to(BASE)
        ok(str(rel))


# =================================================================================
# 3. MODULE IMPORTS (CROSS-MODULE API)
# =================================================================================
def check_imports():
    section(3, "MODULE IMPORTS (CROSS-MODULE API)")

    modules = [
        # Backend
        "core.database",
        "core.settings_manager",
        # Views
        "core.main_window",
        "core.login_view",
        "core.dashboard_tab",
        "core.travelers_tab",
        "core.batches_tab",
        "core.payments_tab",
        "core.receipts_tab",
        "core.invoices_tab",
        "core.reports_tab",
        "core.custom_report_dialog",
        "core.users_tab",
        "core.backups_tab",
    ]

    loaded = {}
    for mod_name in modules:
        mod, err = try_import(mod_name)
        if err:
            warn(mod_name, err.split(":")[0])
            loaded[mod_name] = None
        else:
            ok(mod_name)
            loaded[mod_name] = mod

    return loaded


# =================================================================================
# 4. CLASS / METHOD INVENTORY
# =================================================================================
def check_classes(loaded):
    section(4, "CLASS & METHOD INVENTORY")

    targets = [
        ("core.database", "HajDatabase"),
        ("core.settings_manager", "SettingsManager"),
        ("core.main_window", "MainWindowView"),
        ("core.login_view", "LoginView"),
        ("core.dashboard_tab", "DashboardTab"),
        ("core.travelers_tab", "TravelersTab"),
        ("core.batches_tab", "BatchesTab"),
        ("core.payments_tab", "PaymentsTab"),
        ("core.receipts_tab", "ReceiptsTab"),
        ("core.invoices_tab", "InvoicesTab"),
        ("core.reports_tab", "ReportsTab"),
        ("core.reports_tab", "UpdatedReportsTab"),
        ("core.custom_report_dialog", "CustomReportDialog"),
        ("core.custom_report_dialog", "ColumnOrderDialog"),
        ("core.users_tab", "UsersTab"),
        ("core.backups_tab", "BackupTab"),
    ]

    for mod_name, cls_name in targets:
        mod = loaded.get(mod_name)
        if mod is None:
            warn(f"{mod_name}.{cls_name}", "module failed to import")
            continue
        cls = getattr(mod, cls_name, None)
        if cls is None:
            warn(f"{mod_name}.{cls_name}", "class not found")
            continue
        methods = list_methods(cls, public_only=True)
        ok(f"{cls_name}",
           f"{len(methods)} public methods")
        # Print first 6 methods as a preview
        for name, sig in methods[:6]:
            info(f"  └─ {name}{sig}")
        if len(methods) > 6:
            info(f"  └─ … {len(methods) - 6} more")


# =================================================================================
# 5. DATABASE LAYER API
# =================================================================================
def check_database():
    section(5, "DATABASE LAYER API")

    mod, err = try_import("core.database")
    if err:
        # Try alternate location
        mod, err = try_import("core.main_window")

    # Look for HajDatabase class anywhere
    db_cls = None
    for candidate_mod in ["core.database", "core.main_window"]:
        m = None
        try:
            m = importlib.import_module(candidate_mod)
        except Exception:
            continue
        if hasattr(m, "HajDatabase"):
            db_cls = m.HajDatabase
            break

    if db_cls is None:
        fail("HajDatabase class not found in core/")
        return None

    # Instantiate
    try:
        db = db_cls()
        ok("HajDatabase instantiated")
    except Exception as e:
        fail("HajDatabase init failed", str(e))
        traceback.print_exc()
        return None

    # Required API methods
    required = [
        "get_travelers", "get_batches", "get_payments",
        "get_invoices", "get_receipts", "get_users",
        "get_batch_by_id", "authenticate_user",
        "add_traveler", "update_batch", "delete_batch",
        "log_activity",
    ]
    for m in required:
        if hasattr(db, m):
            ok(f"db.{m}()")
        else:
            warn(f"db.{m}()", "method missing")

    # DataFrames present?
    for attr in ["users", "travelers", "batches", "payments",
                 "invoices", "receipts", "activity_log",
                 "company_settings"]:
        df = getattr(db, attr, None)
        if df is None:
            fail(f"db.{attr} not loaded")
        else:
            ok(f"db.{attr}", f"{len(df)} rows")
    return db


# =================================================================================
# 6. SETTINGS MANAGER API
# =================================================================================
def check_settings(db):
    section(6, "SETTINGS MANAGER API")

    mod, err = try_import("core.settings_manager")
    if err:
        fail("core.settings_manager import failed", err)
        return

    cls = getattr(mod, "SettingsManager", None)
    if cls is None:
        fail("SettingsManager class not found")
        return

    if db is None:
        warn("Skipping settings checks — DB not available")
        return

    try:
        sm = cls(db)
        ok("SettingsManager instantiated")
    except Exception as e:
        fail("SettingsManager init failed", str(e))
        return

    for m in ["get_company_settings", "get_tax_settings",
              "update_tax_settings", "get_tour_types",
              "add_tour_type", "get_tour_years"]:
        if hasattr(sm, m):
            ok(f"sm.{m}()")
        else:
            warn(f"sm.{m}()", "method missing")

    try:
        company = sm.get_company_settings()
        ok("Company settings loaded",
           f"{company.get('company_name', '?')}")
    except Exception as e:
        fail("get_company_settings failed", str(e))

    try:
        tax = sm.get_tax_settings()
        ok("Tax settings loaded",
           f"GST={tax.get('gst_percentage')}%, TCS={tax.get('tcs_percentage')}%")
    except Exception as e:
        fail("get_tax_settings failed", str(e))


# =================================================================================
# 7. DATA INTEGRITY
# =================================================================================
def check_data_integrity(db):
    section(7, "DATA INTEGRITY")

    if db is None:
        warn("Skipping — DB not available")
        return

    try:
        import pandas as pd

        # Travelers → Batches FK
        travelers = db.get_travelers()
        batches = {b["id"] for b in db.get_batches()}
        orphan = [t for t in travelers
                  if t.get("batch_id") and t["batch_id"] not in batches]
        if orphan:
            warn(f"{len(orphan)} travelers have invalid batch_id")
        else:
            ok("Traveler → Batch FK valid")

        # Payments → Travelers FK
        payments = db.get_payments()
        traveler_ids = {t["id"] for t in travelers}
        orphan_p = [p for p in payments
                    if p.get("traveler_id")
                    and p["traveler_id"] not in traveler_ids]
        if orphan_p:
            warn(f"{len(orphan_p)} payments have invalid traveler_id")
        else:
            ok("Payment → Traveler FK valid")

        # Batches seat math
        bookings = {}
        for t in travelers:
            bid = t.get("batch_id")
            if bid:
                bookings[bid] = bookings.get(bid, 0) + 1
        bad = 0
        for b in db.get_batches():
            total = int(float(b.get("total_seats", 0) or 0))
            avail = int(float(b.get("available_seats", 0) or 0))
            booked = bookings.get(b["id"], 0)
            if avail != max(0, total - booked):
                bad += 1
        if bad:
            warn(f"{bad} batches have stale available_seats",
                 "run fix_available_seats.py")
        else:
            ok("Batch seat math consistent")

        # Invoice → Traveler FK
        invoices = db.get_invoices()
        orphan_i = [i for i in invoices
                    if i.get("traveler_id")
                    and i["traveler_id"] not in traveler_ids]
        if orphan_i:
            warn(f"{len(orphan_i)} invoices have invalid traveler_id")
        else:
            ok("Invoice → Traveler FK valid")

    except Exception as e:
        fail("Data integrity check crashed", str(e))
        traceback.print_exc()


# =================================================================================
# 8. PHOTO SYSTEM API
# =================================================================================
def check_photos(db):
    section(8, "PHOTO SYSTEM API")

    docs = BASE / "documents"
    ok("documents/ exists" if docs.exists()
       else "documents/ missing")

    if not docs.exists():
        return

    traveler_folders = [d for d in docs.iterdir() if d.is_dir()]
    ok(f"Traveler folders", f"{len(traveler_folders)} folders")

    total_photos = 0
    with_photo = 0
    for d in traveler_folders:
        photos_dir = d / "photos"
        if photos_dir.exists():
            files = [f for f in photos_dir.iterdir()
                     if f.suffix.lower() in (".jpg", ".jpeg", ".png",
                                             ".bmp", ".gif")]
            if files:
                with_photo += 1
                total_photos += len(files)

    ok("Folders with photos", f"{with_photo} / {len(traveler_folders)}")
    ok("Total photo files", str(total_photos))

    # Test the resolution function
    try:
        from core.custom_report_dialog import _find_photo_path
        if db:
            travelers = db.get_travelers()
            resolved = 0
            for t in travelers:
                if _find_photo_path(t):
                    resolved += 1
            ok(f"_find_photo_path resolved",
               f"{resolved} / {len(travelers)} travelers")
        else:
            ok("_find_photo_path importable")
    except Exception as e:
        fail("_find_photo_path test failed", str(e))


# =================================================================================
# 9. EXPORT PIPELINE API
# =================================================================================
def check_exports():
    section(9, "EXPORT PIPELINE API")

    # Check output folders
    for sub in ["excel", "csv", "pdf"]:
        d = BASE / "exports" / sub
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
        count = len([f for f in d.glob("*.*")])
        ok(f"exports/{sub}/", f"{count} files")

    # Check asset serving folders
    for sub in ["excel", "csv", "pdf"]:
        d = BASE / "assets" / "exports" / sub
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
        count = len([f for f in d.glob("*.*")])
        ok(f"assets/exports/{sub}/", f"{count} files")

    # Test custom report dialog API
    try:
        from core.custom_report_dialog import CustomReportDialog
        for m in ["export_to_excel", "export_to_csv", "export_to_pdf",
                  "display_preview", "generate_preview"]:
            if hasattr(CustomReportDialog, m):
                ok(f"CustomReportDialog.{m}()")
            else:
                fail(f"CustomReportDialog.{m}() MISSING")
    except Exception as e:
        fail("CustomReportDialog import failed", str(e))


# =================================================================================
# 10. ROUTE / VIEW INTEGRITY
# =================================================================================
def check_routes():
    section(10, "ROUTE / VIEW INTEGRITY")

    # main.py must exist
    main_py = BASE / "main.py"
    if main_py.exists():
        ok("main.py present")
        src = main_py.read_text(encoding="utf-8", errors="ignore")
        for keyword in ["def main(page", "ft.run(", "route_change",
                        "LoginView", "MainShell"]:
            if keyword in src:
                ok(f"main.py contains: {keyword}")
            else:
                warn(f"main.py missing: {keyword}")
    else:
        fail("main.py MISSING")

    # Check main_window import wiring
    try:
        from core.main_window import MainWindowView
        ok("MainWindowView importable")
    except Exception as e:
        fail("MainWindowView import failed", str(e))


# =================================================================================
# 11. CROSS-MODULE API CALLS
# =================================================================================
def check_cross_module_calls(db):
    section(11, "CROSS-MODULE API CALL VERIFICATION")

    if db is None:
        warn("Skipping — DB not available")
        return

    # --- CustomReportDialog needs these APIs from HajDatabase ---
    print("  [ CustomReportDialog → HajDatabase ]")
    for m in ["get_travelers", "get_batches", "get_payments",
              "get_invoices", "get_batch_by_id"]:
        if hasattr(db, m):
            ok(f"db.{m}()")
        else:
            fail(f"db.{m}() — CustomReportDialog depends on this")

    # --- ReportsTab → HajDatabase ---
    print()
    print("  [ ReportsTab → HajDatabase ]")
    for m in ["get_travelers", "get_batches", "get_payments",
              "get_invoices", "get_receipts", "log_activity"]:
        if hasattr(db, m):
            ok(f"db.{m}()")
        else:
            fail(f"db.{m}() — ReportsTab depends on this")

    # --- MainWindowView → all view classes ---
    print()
    print("  [ MainWindowView → View classes ]")
    views = [
        ("core.dashboard_tab", "DashboardTab"),
        ("core.travelers_tab", "TravelersTab"),
        ("core.batches_tab", "BatchesTab"),
        ("core.payments_tab", "PaymentsTab"),
        ("core.receipts_tab", "ReceiptsTab"),
        ("core.invoices_tab", "InvoicesTab"),
        ("core.reports_tab", "ReportsTab"),
        ("core.users_tab", "UsersTab"),
        ("core.backups_tab", "BackupTab"),
    ]
    for mod_name, cls_name in views:
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name, None)
            if cls is None:
                warn(f"{cls_name}", f"{mod_name} has no {cls_name}")
            else:
                ok(f"{cls_name} from {mod_name}")
        except Exception as e:
            warn(cls_name, str(e).split(":")[0])

    # --- View class signature check ---
    print()
    print("  [ View constructor signature (page, db, current_user) ]")
    for mod_name, cls_name in views:
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name, None)
            if cls is None:
                continue
            sig = inspect.signature(cls.__init__)
            params = list(sig.parameters.keys())
            # Expect: self, page, db, current_user
            if len(params) >= 4:
                ok(f"{cls_name}.__init__{sig}")
            else:
                warn(f"{cls_name}.__init__{sig}",
                     "should accept (page, db, current_user)")
        except Exception:
            pass

    # --- View has .build() method ---
    print()
    print("  [ View has .build() method ]")
    for mod_name, cls_name in views:
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name, None)
            if cls is None:
                continue
            if hasattr(cls, "build"):
                ok(f"{cls_name}.build()")
            else:
                warn(f"{cls_name}.build()", "missing")
        except Exception:
            pass


# =================================================================================
# 12. FINAL SUMMARY
# =================================================================================
def summary():
    section(12, "SUMMARY")
    print()
    if not FAILS and not WARNS:
        print("  🎉  ALL SYSTEMS HEALTHY — 0 failures, 0 warnings")
    else:
        print(f"  ❌  {len(FAILS)} failure(s)")
        for f in FAILS:
            print(f"       • {f}")
        print()
        print(f"  ⚠️   {len(WARNS)} warning(s)")
        for w in WARNS:
            print(f"       • {w}")
    print()
    print(f"  Check completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


# =================================================================================
# MAIN
# =================================================================================
def main():
    print()
    print("╔" + "═" * 70 + "╗")
    print("║" + "  ALHUDHA HAJ TRAVEL SYSTEM — FULL SYSTEM DIAGNOSTIC".center(70) + "║")
    print("╚" + "═" * 70 + "╝")

    check_environment()
    check_files()
    loaded = check_imports()
    check_classes(loaded)
    db = check_database()
    check_settings(db)
    check_data_integrity(db)
    check_photos(db)
    check_exports()
    check_routes()
    check_cross_module_calls(db)
    summary()


if __name__ == "__main__":
    main()