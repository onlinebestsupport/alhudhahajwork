# =================================================================================
# system_test.py — Full System Diagnostic
# =================================================================================
# Run this in Railway Shell to test every critical function:
#     python system_test.py
#
# Tests:
#   1. Environment & paths
#   2. Static files & downloads folder
#   3. Database loading
#   4. Database accessors (get_travelers, get_invoices, etc.)
#   5. Helper functions
#   6. PDF generation
#   7. Excel generation
#   8. CSV generation
#   9. FastAPI /download endpoint simulation
#   10. Session / Flet page availability
# =================================================================================

import os
import sys
import traceback
from datetime import datetime

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"

results = []


def test(name):
    """Decorator to wrap each test with error handling."""
    def decorator(fn):
        def wrapper():
            print(f"\n{'─' * 70}")
            print(f"TEST: {name}")
            print('─' * 70)
            try:
                result = fn()
                if result is True or result is None:
                    print(f"{PASS}: {name}")
                    results.append((name, "PASS", ""))
                elif result is False:
                    print(f"{FAIL}: {name}")
                    results.append((name, "FAIL", "returned False"))
                else:
                    print(f"{WARN}: {name} — {result}")
                    results.append((name, "WARN", str(result)))
            except Exception as ex:
                print(f"{FAIL}: {name}")
                print(f"   Error: {ex}")
                traceback.print_exc()
                results.append((name, "FAIL", str(ex)))
        return wrapper
    return decorator


# =================================================================================
# 1. ENVIRONMENT
# =================================================================================
@test("1.1 Environment variables")
def t_env():
    print(f"  PORT                    : {os.getenv('PORT', '<unset>')}")
    print(f"  RAILWAY_ENVIRONMENT     : {os.getenv('RAILWAY_ENVIRONMENT', '<unset>')}")
    print(f"  RAILWAY_VOLUME_MOUNT    : {os.getenv('RAILWAY_VOLUME_MOUNT_PATH', '<unset>')}")
    print(f"  RAILWAY_PUBLIC_DOMAIN   : {os.getenv('RAILWAY_PUBLIC_DOMAIN', '<unset>')}")
    print(f"  PYTHONUNBUFFERED        : {os.getenv('PYTHONUNBUFFERED', '<unset>')}")
    print(f"  cwd                     : {os.getcwd()}")
    print(f"  python                  : {sys.version}")
    return True


# =================================================================================
# 2. PATHS
# =================================================================================
@test("2.1 get_app_base_path()")
def t_base_path():
    from core.helpers import get_app_base_path
    base = get_app_base_path()
    print(f"  Base path: {base}")
    print(f"  Exists   : {os.path.isdir(base)}")
    assert os.path.isdir(base), f"Base path does not exist: {base}"
    return True


@test("2.2 Data directory exists & writable")
def t_data_dir():
    from core.helpers import get_app_base_path
    data = os.path.join(get_app_base_path(), "data")
    print(f"  Data dir: {data}")
    assert os.path.isdir(data), f"Missing: {data}"

    # Write test
    test_file = os.path.join(data, ".write_test")
    try:
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        print(f"  Write test: OK")
    except Exception as e:
        raise RuntimeError(f"Data dir not writable: {e}")

    # List CSVs
    files = [f for f in os.listdir(data) if f.endswith(".csv")]
    print(f"  CSV files : {len(files)}")
    for f in sorted(files):
        size = os.path.getsize(os.path.join(data, f))
        print(f"    {f:<30} {size:>8} bytes")
    return True


@test("2.3 Static directory exists")
def t_static_dir():
    from core.helpers import get_app_base_path
    static = os.path.join(get_app_base_path(), "static")
    print(f"  Static dir: {static}")
    print(f"  Exists    : {os.path.isdir(static)}")
    assert os.path.isdir(static), f"Missing: {static}"

    downloads = os.path.join(static, "downloads")
    print(f"  Downloads : {downloads}")
    print(f"  Exists    : {os.path.isdir(downloads)}")

    if os.path.isdir(downloads):
        files = os.listdir(downloads)
        print(f"  Files in downloads: {len(files)}")
        for f in files[:10]:
            size = os.path.getsize(os.path.join(downloads, f))
            print(f"    {f:<55} {size:>8} bytes")
    return True


# =================================================================================
# 3. DATABASE
# =================================================================================
@test("3.1 HajDatabase initialization")
def t_db_init():
    from core.database import HajDatabase
    db = HajDatabase()
    print(f"  DB object: {type(db).__name__}")
    globals()["_test_db"] = db  # save for later tests
    return True


@test("3.2 db.get_travelers()")
def t_db_travelers():
    db = globals().get("_test_db")
    assert db, "DB not initialized"
    rows = db.get_travelers()
    print(f"  Travelers: {len(rows)}")
    if rows:
        print(f"  Sample   : {rows[0].get('first_name', '?')} "
              f"{rows[0].get('last_name', '?')}")
    return True


@test("3.3 db.get_batches()")
def t_db_batches():
    db = globals().get("_test_db")
    assert db, "DB not initialized"
    rows = db.get_batches()
    print(f"  Batches: {len(rows)}")
    for b in rows[:3]:
        print(f"    {b.get('batch_name', '?')} — ₹{b.get('price', 0)}")
    return True


@test("3.4 db.get_payments()")
def t_db_payments():
    db = globals().get("_test_db")
    assert db, "DB not initialized"
    rows = db.get_payments()
    print(f"  Payments: {len(rows)}")
    return True


@test("3.5 db.get_invoices()")
def t_db_invoices():
    db = globals().get("_test_db")
    assert db, "DB not initialized"
    rows = db.get_invoices()
    print(f"  Invoices: {len(rows)}")
    if rows:
        print(f"  Sample  : {rows[0].get('invoice_no', '?')}")
    return True


@test("3.6 db.get_receipts()")
def t_db_receipts():
    db = globals().get("_test_db")
    assert db, "DB not initialized"
    rows = db.get_receipts()
    print(f"  Receipts: {len(rows)}")
    return True


@test("3.7 db.get_users()")
def t_db_users():
    db = globals().get("_test_db")
    assert db, "DB not initialized"
    rows = db.get_users()
    print(f"  Users: {len(rows)}")
    for u in rows:
        print(f"    {u.get('username', '?')} ({u.get('role', '?')})")
    return True


@test("3.8 db.get_payments() with traveler_id filter")
def t_db_payments_filter():
    db = globals().get("_test_db")
    assert db, "DB not initialized"
    travelers = db.get_travelers()
    if not travelers:
        return "No travelers — skipping"
    tid = travelers[0].get("id")
    rows = db.get_payments(tid)
    print(f"  Traveler: {tid}")
    print(f"  Payments: {len(rows)}")
    return True


# =================================================================================
# 4. HELPERS
# =================================================================================
@test("4.1 format_currency_indian()")
def t_currency():
    from core.helpers import format_currency_indian
    print(f"  1234.56      → {format_currency_indian(1234.56)}")
    print(f"  1234567.89   → {format_currency_indian(1234567.89)}")
    print(f"  0            → {format_currency_indian(0)}")
    print(f"  -500         → {format_currency_indian(-500)}")
    return True


@test("4.2 number_to_words_indian()")
def t_words():
    from core.helpers import number_to_words_indian
    print(f"  0        → {number_to_words_indian(0)}")
    print(f"  123      → {number_to_words_indian(123)}")
    print(f"  1234     → {number_to_words_indian(1234)}")
    print(f"  123456   → {number_to_words_indian(123456)}")
    return True


@test("4.3 round_as_per_rules()")
def t_round():
    from core.helpers import round_as_per_rules
    print(f"  99.49  → {round_as_per_rules(99.49)}")
    print(f"  99.50  → {round_as_per_rules(99.50)}")
    print(f"  99.51  → {round_as_per_rules(99.51)}")
    print(f"  100.99 → {round_as_per_rules(100.99)}")
    return True


@test("4.4 send_file_to_user() — signature only")
def t_send_sig():
    import inspect
    from core.helpers import send_file_to_user
    sig = inspect.signature(send_file_to_user)
    print(f"  Signature: send_file_to_user{sig}")
    # Check return behavior with missing file
    result = send_file_to_user(None, "/nonexistent/file.pdf")
    print(f"  Returns None on missing file: {result is None}")
    assert result is None
    return True


# =================================================================================
# 5. PDF GENERATION
# =================================================================================
@test("5.1 reportlab import")
def t_reportlab():
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer, Image)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    print(f"  reportlab imports OK")
    return True


@test("5.2 PDF generation (test document)")
def t_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer)
    from reportlab.lib.styles import getSampleStyleSheet

    from core.helpers import get_app_base_path
    out_dir = os.path.join(get_app_base_path(), "static", "downloads")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"_test_{datetime.now().strftime('%H%M%S')}.pdf")

    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("Test PDF", styles['Title']),
        Spacer(1, 12),
        Paragraph("System diagnostic test document.", styles['Normal']),
    ]
    doc.build(elements)

    size = os.path.getsize(path)
    print(f"  Created: {os.path.basename(path)}")
    print(f"  Size   : {size} bytes")
    assert size > 100, "PDF too small — generation failed"

    # Cleanup
    try:
        os.remove(path)
    except Exception:
        pass
    return True


# =================================================================================
# 6. EXCEL GENERATION
# =================================================================================
@test("6.1 openpyxl import")
def t_openpyxl():
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill
    print(f"  openpyxl version: {openpyxl.__version__}")
    return True


@test("6.2 Excel generation (test workbook)")
def t_excel():
    import openpyxl
    from openpyxl.styles import Font

    from core.helpers import get_app_base_path
    out_dir = os.path.join(get_app_base_path(), "static", "downloads")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"_test_{datetime.now().strftime('%H%M%S')}.xlsx")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws['A1'] = "Test"
    ws['A1'].font = Font(bold=True)
    ws['A2'] = 12345
    wb.save(path)

    size = os.path.getsize(path)
    print(f"  Created: {os.path.basename(path)}")
    print(f"  Size   : {size} bytes")
    assert size > 100

    try:
        os.remove(path)
    except Exception:
        pass
    return True


# =================================================================================
# 7. STATIC FILE SERVING
# =================================================================================
@test("7.1 FastAPI routes registered")
def t_fastapi_routes():
    try:
        from main import app as fastapi_app
        routes = [r.path for r in fastapi_app.routes]
        print(f"  Routes: {routes}")
        has_download = any("/download/" in str(p) for p in routes)
        print(f"  Has /download route: {has_download}")
        assert has_download, "/download route NOT registered"
        return True
    except ImportError as ex:
        return f"Could not import main.app: {ex}"


@test("7.2 File copy to static/downloads")
def t_file_copy():
    from core.helpers import get_app_base_path
    downloads = os.path.join(get_app_base_path(), "static", "downloads")
    os.makedirs(downloads, exist_ok=True)

    test_path = os.path.join(downloads, "_copy_test.txt")
    with open(test_path, "w") as f:
        f.write("hello world")

    exists = os.path.exists(test_path)
    size = os.path.getsize(test_path)
    print(f"  Wrote: {test_path} ({size} bytes)")
    print(f"  Exists: {exists}")

    os.remove(test_path)
    assert exists and size == 11
    return True


# =================================================================================
# 8. FLET
# =================================================================================
@test("8.1 Flet version")
def t_flet_version():
    import flet
    print(f"  Flet: {flet.__version__}")
    return True


@test("8.2 Flet Page class patch")
def t_page_patch():
    from flet.controls.page import Page
    # Check whether update was patched (name won't be __update)
    print(f"  Page.update: {Page.update}")
    return True


# =================================================================================
# 9. TAB IMPORTS
# =================================================================================
@test("9.1 Import all tab modules")
def t_import_tabs():
    tabs = [
        "core.travelers_tab",
        "core.batches_tab",
        "core.payments_tab",
        "core.receipts_tab",
        "core.invoices_tab",
        "core.dashboard_tab",
        "core.users_tab",
        "core.reports_tab",
        "core.backups_tab",
        "core.login_view",
        "core.main_window",
        "core.settings_manager",
        "core.custom_report_dialog",
        "core.company_settings_dialog",
    ]
    failed = []
    for mod in tabs:
        try:
            __import__(mod)
            print(f"  ✅ {mod}")
        except Exception as ex:
            print(f"  ❌ {mod}: {ex}")
            failed.append((mod, str(ex)))
    if failed:
        raise RuntimeError(f"{len(failed)} modules failed to import")
    return True


@test("9.2 Import batch/traveler/custom report classes")
def t_import_classes():
    checks = [
        ("core.travelers_tab", "TravelersTab"),
        ("core.batches_tab", "BatchesTab"),
        ("core.payments_tab", "PaymentsTab"),
        ("core.receipts_tab", "ReceiptsTab"),
        ("core.invoices_tab", "InvoicesTab"),
        ("core.dashboard_tab", "DashboardTab"),
        ("core.users_tab", "UsersTab"),
        ("core.reports_tab", "ReportsTab"),
        ("core.backups_tab", "BackupsTab"),
    ]
    failed = []
    for mod_name, cls_name in checks:
        try:
            mod = __import__(mod_name, fromlist=[cls_name])
            cls = getattr(mod, cls_name, None)
            if cls is None:
                print(f"  ❌ {mod_name}.{cls_name} — not found")
                failed.append(f"{mod_name}.{cls_name}")
            else:
                print(f"  ✅ {mod_name}.{cls_name}")
        except Exception as ex:
            print(f"  ❌ {mod_name}.{cls_name}: {ex}")
            failed.append(f"{mod_name}.{cls_name}")
    if failed:
        raise RuntimeError(f"{len(failed)} classes missing")
    return True


# =================================================================================
# RUN ALL TESTS
# =================================================================================
def main():
    print("\n" + "=" * 70)
    print("  ALHUDHA HAJ TRAVEL — FULL SYSTEM DIAGNOSTIC")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    test_funcs = [
        # Environment
        t_env,
        # Paths
        t_base_path, t_data_dir, t_static_dir,
        # Database
        t_db_init, t_db_travelers, t_db_batches, t_db_payments,
        t_db_invoices, t_db_receipts, t_db_users, t_db_payments_filter,
        # Helpers
        t_currency, t_words, t_round, t_send_sig,
        # PDF
        t_reportlab, t_pdf,
        # Excel
        t_openpyxl, t_excel,
        # Static
        t_fastapi_routes, t_file_copy,
        # Flet
        t_flet_version, t_page_patch,
        # Imports
        t_import_tabs, t_import_classes,
    ]

    for fn in test_funcs:
        try:
            fn()
        except Exception as ex:
            print(f"\n❌ Test crashed: {fn.__name__}: {ex}")
            traceback.print_exc()
            results.append((fn.__name__, "CRASH", str(ex)))

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, status, _ in results if status == "PASS")
    warned = sum(1 for _, status, _ in results if status == "WARN")
    failed = sum(1 for _, status, _ in results if status in ("FAIL", "CRASH"))

    print(f"  ✅ Passed : {passed}")
    print(f"  ⚠️  Warned : {warned}")
    print(f"  ❌ Failed : {failed}")
    print(f"  ────────────────")
    print(f"  TOTAL     : {len(results)}")

    if failed:
        print("\n  FAILED TESTS:")
        for name, status, detail in results:
            if status in ("FAIL", "CRASH"):
                print(f"    ❌ {name}: {detail}")

    print("=" * 70)
    print(f"  Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)


if __name__ == "__main__":
    main()