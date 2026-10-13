# =================================================================================
# system_check.py — FULL SYSTEM DIAGNOSTIC
# =================================================================================
# v3.1 — Production-safe auto-fix with sanity guards
#
# KEY LESSON LEARNED (v3.0 → v3.1):
#   • `booked_seats` field may not exist in batches.csv — MUST count travelers
#     directly from travelers.csv by matching batch_id
#   • Local and Railway data may differ significantly
#   • Auto-fix without guards can write mathematically impossible values
#
# SAFETY GUARDS ADDED:
#   • Never set available_seats > total_seats
#   • Refuse auto-fix if delta > 50% of total (likely data drift)
#   • Print full BEFORE / AFTER / VERIFY report
#   • All computations use ONLY real traveler counts
#
# COVERS
#   1. Environment & dependencies
#   2. File inventory
#   3. Module imports
#   4. Class inventory
#   5. Database layer
#   6. Settings manager
#   7. Data integrity (safe auto-fix)
#   8. Photo system
#   9. Export pipeline
#  10. Security wiring
#  11. Cross-module calls
#  12. Summary
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

AUTOFIX = os.environ.get("NO_AUTOFIX", "").lower() not in ("1", "true", "yes")

# =================================================================================
# STATE
# =================================================================================
FAILS = []
WARNS = []
FIXED = []


# =================================================================================
# OUTPUT HELPERS
# =================================================================================
def section(n, title):
    print()
    print("╔" + "═" * 70 + "╗")
    print(f"║ {n:>2}. {title:<65}║")
    print("╚" + "═" * 70 + "╝")


def ok(label, detail=""):
    line = f"  ✅  {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)


def warn(label, detail="", fix=""):
    line = f"  ⚠️   {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)
    if fix:
        print(f"         FIX: {fix}")
    WARNS.append(label)


def fail(label, detail="", fix=""):
    line = f"  ❌  {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)
    if fix:
        print(f"         FIX: {fix}")
    FAILS.append(label)


def info(label, detail=""):
    line = f"  ℹ️   {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)


def fixed(label, detail=""):
    line = f"  🔧  {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)
    FIXED.append(label)


def try_import(mod_name):
    try:
        return importlib.import_module(mod_name), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def list_methods(cls):
    out = []
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_"):
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
    info("Python", f"{sys.version.split()[0]} ({sys.platform})")
    info("Project root", str(BASE))
    info("Environment", "Railway" if os.getenv("RAILWAY_ENVIRONMENT")
         else "Local")
    print()

    deps = [
        ("flet",        "Flet",       True),
        ("fastapi",     "FastAPI",    True),
        ("uvicorn",     "Uvicorn",    True),
        ("pandas",      "Pandas",     True),
        ("numpy",       "Numpy",      False),
        ("PIL",         "Pillow",     False),
        ("openpyxl",    "openpyxl",   False),
        ("reportlab",   "reportlab",  False),
        ("matplotlib",  "Matplotlib", False),
    ]
    for mod_name, label, required in deps:
        try:
            m = importlib.import_module(mod_name)
            ver = getattr(m, "__version__", "") or "?"
            ok(label, ver)
        except ImportError:
            if required:
                fail(f"{label} MISSING", "required",
                     f"pip install {mod_name}")
            else:
                warn(f"{label} not installed", "needed for exports",
                     f"pip install {mod_name}")


# =================================================================================
# 2. FILES
# =================================================================================
def check_files():
    section(2, "FILE INVENTORY")

    required_files = [
        "main.py",
        "core/database.py",
        "core/security.py",
        "core/frontpage_config.py",
        "core/frontpage_settings_tab.py",
        "core/main_window.py",
        "core/login_view.py",
    ]
    for rel in required_files:
        p = BASE / rel
        if p.exists():
            ok(rel, f"{p.stat().st_size:,} bytes")
        else:
            fail(f"{rel} MISSING", "required file",
                 "git checkout " + rel)

    optional = [
        "static/robots.txt",
        "static/gallery_upload.html",
        "tools/health_check.py",
    ]
    for rel in optional:
        p = BASE / rel
        if p.exists():
            ok(rel)
        else:
            warn(f"{rel} not present", "recommended")

    info("Total .py files", str(len(list(BASE.rglob("*.py")))))


# =================================================================================
# 3. IMPORTS
# =================================================================================
def check_imports():
    section(3, "MODULE IMPORTS")

    modules = [
        "core.database",
        "core.settings_manager",
        "core.security",
        "core.frontpage_config",
        "core.frontpage_settings_tab",
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
            fail(f"{mod_name} import failed", err,
                 f"check syntax in {mod_name}.py")
            loaded[mod_name] = None
        else:
            ok(mod_name)
            loaded[mod_name] = mod
    return loaded


# =================================================================================
# 4. CLASSES
# =================================================================================
def check_classes(loaded):
    section(4, "CLASS INVENTORY")

    targets = [
        ("core.database",                 "HajDatabase"),
        ("core.settings_manager",         "SettingsManager"),
        ("core.security",                 "SecurityHeadersMiddleware"),
        ("core.frontpage_settings_tab",   "FrontPageSettingsTab"),
        ("core.main_window",              "MainWindowView"),
        ("core.login_view",               "LoginView"),
        ("core.dashboard_tab",            "DashboardTab"),
        ("core.travelers_tab",            "TravelersTab"),
        ("core.batches_tab",              "BatchesTab"),
        ("core.payments_tab",             "PaymentsTab"),
        ("core.receipts_tab",             "ReceiptsTab"),
        ("core.invoices_tab",             "InvoicesTab"),
        ("core.reports_tab",              "ReportsTab"),
        ("core.custom_report_dialog",     "CustomReportDialog"),
        ("core.users_tab",                "UsersTab"),
        ("core.backups_tab",              "BackupTab"),
    ]

    for mod_name, cls_name in targets:
        mod = loaded.get(mod_name)
        if mod is None:
            continue
        cls = getattr(mod, cls_name, None)
        if cls is None:
            warn(f"{cls_name} not found in {mod_name}", "class missing")
            continue
        methods = list_methods(cls)
        ok(f"{cls_name}", f"{len(methods)} public methods")


# =================================================================================
# 5. DATABASE
# =================================================================================
def check_database():
    section(5, "DATABASE LAYER")

    db_cls = None
    for candidate in ["core.database", "core.main_window"]:
        try:
            m = importlib.import_module(candidate)
            if hasattr(m, "HajDatabase"):
                db_cls = m.HajDatabase
                break
        except Exception:
            continue

    if db_cls is None:
        fail("HajDatabase not found", "cannot load DB",
             "check core/database.py")
        return None

    try:
        db = db_cls()
        ok("HajDatabase instantiated")
    except Exception as e:
        fail("HajDatabase init failed", str(e),
             "check data/ folder + CSV permissions")
        traceback.print_exc()
        return None

    required = [
        "get_travelers", "get_batches", "get_payments",
        "get_invoices", "get_receipts", "get_users",
        "get_batch_by_id", "authenticate_user",
        "add_traveler", "update_batch", "delete_batch",
        "log_activity",
    ]
    missing = [m for m in required if not hasattr(db, m)]
    if missing:
        fail("HajDatabase missing methods", ", ".join(missing),
             "check database.py")
    else:
        ok("Required DB methods", f"{len(required)} present")

    for attr in ["users", "travelers", "batches", "payments",
                 "invoices", "receipts", "activity_log"]:
        df = getattr(db, attr, None)
        if df is None:
            warn(f"db.{attr} not loaded", "empty or missing",
                 "check data/ folder")
        else:
            ok(f"db.{attr}", f"{len(df)} rows")

    return db


# =================================================================================
# 6. SETTINGS
# =================================================================================
def check_settings(db):
    section(6, "SETTINGS MANAGER")

    mod, err = try_import("core.settings_manager")
    if err or not hasattr(mod, "SettingsManager"):
        fail("SettingsManager unavailable", err or "class missing")
        return

    if db is None:
        warn("Settings check skipped", "DB not loaded")
        return

    try:
        sm = mod.SettingsManager(db)
        ok("SettingsManager instantiated")
    except Exception as e:
        fail("SettingsManager init failed", str(e))
        return

    try:
        company = sm.get_company_settings()
        ok("Company settings", company.get("company_name", "?"))
    except Exception as e:
        warn("Company settings failed", str(e),
             "check data/company_settings.csv")

    try:
        tax = sm.get_tax_settings()
        ok("Tax settings",
           f"GST={tax.get('gst_percentage', '?')}% "
           f"TCS={tax.get('tcs_percentage', '?')}%")
    except Exception as e:
        warn("Tax settings failed", str(e),
             "check data/tax_settings.csv")


# =================================================================================
# 7. DATA INTEGRITY  (v3.1 — safe auto-fix with guards)
# =================================================================================
def check_data_integrity(db):
    section(7, "DATA INTEGRITY")

    if db is None:
        warn("Skipped", "DB not loaded")
        return

    try:
        travelers = db.get_travelers() or []
        batches = db.get_batches() or []
        payments = db.get_payments() or []
        invoices = db.get_invoices() or []

        traveler_ids = {t["id"] for t in travelers if t.get("id")}
        batch_ids = {b["id"] for b in batches if b.get("id")}

        # --- FK 1: travelers → batches ---
        orphan_t = [t for t in travelers
                    if t.get("batch_id") and t["batch_id"] not in batch_ids]
        if orphan_t:
            ids = [t.get("id", "?") for t in orphan_t[:5]]
            warn(f"{len(orphan_t)} travelers with invalid batch_id",
                 f"e.g. {', '.join(ids)}",
                 "reassign via admin → Travelers tab")
        else:
            ok("Traveler → Batch FK valid")

        # --- FK 2: payments → travelers ---
        orphan_p = [p for p in payments
                    if p.get("traveler_id")
                    and p["traveler_id"] not in traveler_ids]
        if orphan_p:
            warn(f"{len(orphan_p)} payments with invalid traveler_id",
                 "references deleted traveler",
                 "delete or reassign via admin → Payments tab")
        else:
            ok("Payment → Traveler FK valid")

        # --- FK 3: invoices → travelers ---
        orphan_i = [i for i in invoices
                    if i.get("traveler_id")
                    and i["traveler_id"] not in traveler_ids]
        if orphan_i:
            warn(f"{len(orphan_i)} invoices with invalid traveler_id",
                 "references deleted traveler",
                 "delete or reassign via admin → Invoices tab")
        else:
            ok("Invoice → Traveler FK valid")

        # --- Seat math (uses REAL traveler counts, not booked_seats field) ---
        bookings = {}
        for t in travelers:
            bid = t.get("batch_id")
            if bid:
                bookings[bid] = bookings.get(bid, 0) + 1

        bad_batches = []
        for b in batches:
            bid = b.get("id", "?")
            total = int(float(b.get("total_seats", 0) or 0))
            avail = int(float(b.get("available_seats", 0) or 0))
            booked = bookings.get(bid, 0)
            expected = max(0, total - booked)

            if avail != expected:
                # Compute severity
                delta = abs(avail - expected)
                delta_pct = (delta / total * 100) if total > 0 else 100

                bad_batches.append({
                    "id": bid,
                    "name": b.get("batch_name", "?"),
                    "total": total,
                    "booked": booked,
                    "available": avail,
                    "expected": expected,
                    "delta": delta,
                    "delta_pct": round(delta_pct, 1),
                })

        if not bad_batches:
            ok("Batch seat math consistent")
        else:
            # Print detailed report
            print()
            print("  ┌─ Batch Seat Report " + "─" * 50 + "┐")
            print(f"  │ {'ID':<22} {'Total':>6} {'Booked':>7} "
                  f"{'Stored':>7} {'Correct':>8} {'Delta':>6} │")
            print("  ├" + "─" * 68 + "┤")
            for item in bad_batches:
                print(f"  │ {item['id']:<22} {item['total']:>6} "
                      f"{item['booked']:>7} {item['available']:>7} "
                      f"{item['expected']:>8} {item['delta_pct']:>5}% │")
            print("  └" + "─" * 68 + "┘")
            print()

            if AUTOFIX:
                fixed_count = 0
                skipped_count = 0

                for item in bad_batches:
                    # --- Guard 1: refuse impossible values ---
                    if item["expected"] > item["total"]:
                        warn(f"Batch {item['id']} — refusing auto-fix",
                             f"computed {item['expected']} > "
                             f"total {item['total']}",
                             "manual review via admin panel")
                        skipped_count += 1
                        continue

                    # --- Guard 2: refuse large jumps (data drift indicator) ---
                    if item["delta_pct"] > 50:
                        warn(f"Batch {item['id']} — large delta",
                             f"{item['available']} → {item['expected']} "
                             f"(delta {item['delta_pct']}%)",
                             "verify via admin → Batches tab")
                        skipped_count += 1
                        continue

                    # --- Guard 3: sanity — total and booked non-negative ---
                    if item["total"] < 0 or item["booked"] < 0:
                        warn(f"Batch {item['id']} — invalid inputs",
                             f"total={item['total']}, booked={item['booked']}",
                             "check source data")
                        skipped_count += 1
                        continue

                    # --- Apply fix ---
                    try:
                        b = db.get_batch_by_id(item["id"])
                        if b is None:
                            warn(f"Batch {item['id']} not found")
                            continue

                        b["available_seats"] = item["expected"]
                        db.update_batch(item["id"], b)

                        fixed(
                            f"Batch {item['id']} seat corrected",
                            f"{item['available']} → {item['expected']} "
                            f"(total={item['total']}, "
                            f"booked={item['booked']})"
                        )
                        fixed_count += 1
                    except Exception as e:
                        warn(f"Auto-fix failed for {item['id']}",
                             str(e),
                             "fix manually via admin panel")

                if fixed_count:
                    ok(f"Auto-fixed {fixed_count} batch(es)")
                if skipped_count:
                    warn(f"{skipped_count} batch(es) skipped for safety",
                         "see warnings above",
                         "review and fix manually")
            else:
                warn(f"{len(bad_batches)} batches need seat corrections",
                     "auto-fix disabled (NO_AUTOFIX=1)",
                     "run without NO_AUTOFIX, or fix via admin panel")

    except Exception as e:
        fail("Data integrity check crashed", str(e))
        traceback.print_exc()


# =================================================================================
# 8. PHOTOS
# =================================================================================
def check_photos(db):
    section(8, "PHOTO SYSTEM")

    docs = None
    for candidate in [BASE / "data" / "documents", BASE / "documents"]:
        if candidate.exists():
            docs = candidate
            ok(f"Photos root: {candidate.relative_to(BASE)}")
            break

    if docs is None:
        warn("No documents folder found",
             "checked data/documents/ and documents/",
             "create the folder or check volume mount")
        return

    folders = [d for d in docs.iterdir() if d.is_dir()]
    if not folders:
        info("No traveler photo folders yet")
        return

    total_photos = 0
    with_photo = 0
    for d in folders:
        photos_dir = d / "photos"
        if photos_dir.exists():
            files = [f for f in photos_dir.iterdir()
                     if f.suffix.lower() in (".jpg", ".jpeg", ".png",
                                             ".bmp", ".gif")]
            if files:
                with_photo += 1
                total_photos += len(files)

    ok("Traveler folders", f"{len(folders)}")
    ok("Folders with photos", f"{with_photo} / {len(folders)}")
    ok("Total photo files", str(total_photos))

    if db is not None:
        try:
            travelers = db.get_travelers()
            if len(travelers) > 0:
                pct = round(100 * with_photo / max(1, len(travelers)))
                if pct >= 80:
                    ok("Photo coverage", f"{pct}% of travelers")
                elif pct >= 50:
                    info("Photo coverage", f"{pct}% of travelers")
                else:
                    warn("Low photo coverage",
                         f"{with_photo} of {len(travelers)} ({pct}%)",
                         "upload via admin → Travelers tab")
        except Exception:
            pass


# =================================================================================
# 9. EXPORTS
# =================================================================================
def check_exports():
    section(9, "EXPORT PIPELINE")

    for sub in ["excel", "csv", "pdf"]:
        d = BASE / "exports" / sub
        try:
            d.mkdir(parents=True, exist_ok=True)
            test_file = d / ".write_test"
            test_file.write_text("ok")
            test_file.unlink()
            count = len(list(d.glob("*.*")))
            ok(f"exports/{sub}/ writable", f"{count} files")
        except Exception as e:
            fail(f"exports/{sub}/ not writable", str(e),
                 "check folder permissions")

    try:
        from core.custom_report_dialog import CustomReportDialog
        for m in ["export_to_excel", "export_to_csv", "export_to_pdf"]:
            if hasattr(CustomReportDialog, m):
                ok(f"CustomReportDialog.{m}()")
            else:
                fail(f"CustomReportDialog.{m}() missing",
                     "export feature will fail")
    except Exception as e:
        fail("CustomReportDialog import failed", str(e))


# =================================================================================
# 10. SECURITY
# =================================================================================
def check_security():
    section(10, "SECURITY WIRING")

    mod, err = try_import("core.security")
    if err:
        fail("core.security import failed", err,
             "check syntax in core/security.py")
        return

    required = [
        "require_admin",
        "SecurityHeadersMiddleware",
        "generate_token",
        "login_limiter",
        "upload_limiter",
        "validate_upload_content",
        "validate_length",
        "safe_filename",
    ]
    missing = [name for name in required if not hasattr(mod, name)]
    if missing:
        fail("core.security missing exports", ", ".join(missing),
             "check security.py")
    else:
        ok(f"All {len(required)} security helpers present")

    main_py = BASE / "main.py"
    if main_py.exists():
        src = main_py.read_text(encoding="utf-8", errors="ignore")
        checks = [
            ("from core.security import", "imports security module"),
            ("SecurityHeadersMiddleware", "adds security headers"),
            ("block_scanners", "blocks scanner paths"),
            ("require_admin", "requires admin auth"),
            ("ADMIN_API_KEY", "reads admin API key env"),
        ]
        for needle, label in checks:
            if needle in src:
                ok(f"main.py: {label}")
            else:
                fail(f"main.py missing: {label}",
                     "security feature not active")

    key = os.getenv("ADMIN_API_KEY", "")
    if not key:
        info("ADMIN_API_KEY not set",
             "expected on Railway (Variables tab)")
    elif len(key) < 16:
        warn("ADMIN_API_KEY too short", f"length {len(key)}",
             'python -c "import secrets; print(secrets.token_urlsafe(32))"')
    else:
        ok("ADMIN_API_KEY configured", f"{len(key)} chars")


# =================================================================================
# 11. CROSS-MODULE
# =================================================================================
def check_cross_module(db):
    section(11, "CROSS-MODULE API CALLS")

    if db is None:
        warn("Skipped", "DB not loaded")
        return

    for tool, methods in [
        ("CustomReportDialog", ["get_travelers", "get_batches",
                                "get_payments", "get_invoices",
                                "get_batch_by_id"]),
        ("ReportsTab",         ["get_travelers", "get_batches",
                                "get_payments", "get_invoices",
                                "get_receipts", "log_activity"]),
    ]:
        missing = [m for m in methods if not hasattr(db, m)]
        if missing:
            fail(f"{tool} → DB broken", f"missing: {', '.join(missing)}")
        else:
            ok(f"{tool} → DB", f"{len(methods)} methods available")

    views = [
        ("core.dashboard_tab",  "DashboardTab"),
        ("core.travelers_tab",  "TravelersTab"),
        ("core.batches_tab",    "BatchesTab"),
        ("core.payments_tab",   "PaymentsTab"),
        ("core.receipts_tab",   "ReceiptsTab"),
        ("core.invoices_tab",   "InvoicesTab"),
        ("core.reports_tab",    "ReportsTab"),
        ("core.users_tab",      "UsersTab"),
        ("core.backups_tab",    "BackupTab"),
    ]
    missing_build = []
    for mod_name, cls_name in views:
        try:
            m = importlib.import_module(mod_name)
            cls = getattr(m, cls_name, None)
            if cls is None:
                continue
            if not hasattr(cls, "build"):
                missing_build.append(cls_name)
        except Exception:
            pass
    if missing_build:
        fail("Views missing .build()", ", ".join(missing_build))
    else:
        ok("All views expose .build()")


# =================================================================================
# 12. SUMMARY
# =================================================================================
def summary():
    section(12, "SUMMARY")
    print()

    total_problems = len(FAILS) + len(WARNS)

    if total_problems == 0 and not FIXED:
        print("  🎉  ALL SYSTEMS HEALTHY — 0 failures, 0 warnings")
    else:
        if FIXED:
            print(f"  🔧  {len(FIXED)} auto-fixed issue(s):")
            for f in FIXED:
                print(f"       • {f}")
            print()

        if FAILS:
            print(f"  ❌  {len(FAILS)} failure(s) — MUST fix:")
            for f in FAILS:
                print(f"       • {f}")
            print()

        if WARNS:
            print(f"  ⚠️   {len(WARNS)} warning(s) — SHOULD fix:")
            for w in WARNS:
                print(f"       • {w}")
            print()

        if not FAILS and not WARNS:
            print("  ✅  No failures, no warnings — system is clean")

    print(f"  Completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if not AUTOFIX:
        print("  ℹ️   Auto-fix DISABLED (NO_AUTOFIX=1)")
    else:
        print("  ℹ️   Auto-fix ENABLED (safe guards active)")
    print()


# =================================================================================
# MAIN
# =================================================================================
def main():
    print()
    print("╔" + "═" * 70 + "╗")
    print("║" + "  ALHUDHA HAJ TRAVEL SYSTEM — FULL SYSTEM DIAGNOSTIC".center(70) + "║")
    print("╚" + "═" * 70 + "╝")
    env = "Railway" if os.getenv("RAILWAY_ENVIRONMENT") else "Local"
    print(f"  Environment: {env}")
    print(f"  Auto-fix: {'ENABLED (guarded)' if AUTOFIX else 'DISABLED'}")

    check_environment()
    check_files()
    loaded = check_imports()
    check_classes(loaded)
    db = check_database()
    check_settings(db)
    check_data_integrity(db)
    check_photos(db)
    check_exports()
    check_security()
    check_cross_module(db)
    summary()


if __name__ == "__main__":
    main()