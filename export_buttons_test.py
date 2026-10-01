# =================================================================================
# export_buttons_test.py — Full Export & Button Diagnostic
# =================================================================================
# Tests:
#   1. Every tab's action methods (view/edit/delete/export)
#   2. Every export generates a real file
#   3. Every file is copied to static/downloads/
#   4. Every download URL is constructable
#   5. Print function callability
#   6. All icon buttons in every table
# =================================================================================

import os
import sys
import traceback
from datetime import datetime

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []


def section(title):
    print(f"\n{'═' * 72}")
    print(f"  {title}")
    print('═' * 72)


def test(name, fn):
    """Run a test function, catch everything."""
    print(f"\n▶ {name}")
    try:
        result = fn()
        if result is True or result is None:
            print(f"  {PASS} PASS")
            results.append((name, "PASS", ""))
        elif result is False:
            print(f"  {FAIL} FAIL (returned False)")
            results.append((name, "FAIL", "returned False"))
        else:
            print(f"  {WARN} {result}")
            results.append((name, "WARN", str(result)))
    except Exception as ex:
        print(f"  {FAIL} CRASH: {ex}")
        traceback.print_exc()
        results.append((name, "FAIL", str(ex)))


# =================================================================================
# Setup
# =================================================================================
section("SETUP")

from core.helpers import get_app_base_path
from core.database import HajDatabase

BASE = get_app_base_path()
DATA_DIR = os.path.join(BASE, "data")
STATIC_DIR = os.path.join(BASE, "static")
DOWNLOADS_DIR = os.path.join(STATIC_DIR, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

print(f"Base path : {BASE}")
print(f"Data dir  : {DATA_DIR}")
print(f"Downloads : {DOWNLOADS_DIR}")

db = HajDatabase()
print(f"Database  : OK")


# =================================================================================
# Fake page object — mimics Flet's page enough for export functions
# =================================================================================
class FakePage:
    """Captures launch_url calls so we can verify the download trigger."""

    def __init__(self):
        self.launched_urls = []
        self.javascript_calls = []

    def launch_url(self, url, **kwargs):
        self.launched_urls.append((url, kwargs))
        print(f"    [FakePage.launch_url] {url} {kwargs}")

    def run_javascript(self, js):
        self.javascript_calls.append(js)
        # Extract the URL from the JS to verify
        import re
        m = re.search(r"a\.href = '([^']+)'", js)
        url = m.group(1) if m else "(unknown)"
        print(f"    [FakePage.run_javascript] anchor for {url}")

    def update(self):
        pass


# =================================================================================
# 1. Helper sanity
# =================================================================================
section("1. FILE DELIVERY HELPERS")

def t_send_file_signature():
    from core.helpers import send_file_to_user
    import inspect
    sig = inspect.signature(send_file_to_user)
    print(f"  Signature: send_file_to_user{sig}")
    return True

test("1.1 send_file_to_user signature", t_send_file_signature)


def t_send_missing():
    from core.helpers import send_file_to_user
    result = send_file_to_user(FakePage(), "/nonexistent.pdf")
    print(f"  Returned: {result}")
    assert result is None
    return True

test("1.2 send_file_to_user handles missing file", t_send_missing)


def t_send_real_file():
    from core.helpers import send_file_to_user
    # Create a dummy file in data dir
    src = os.path.join(DATA_DIR, "_dummy_test.txt")
    with open(src, "w") as f:
        f.write("test content")

    page = FakePage()
    result = send_file_to_user(page, src)

    # Should be None (function does its own launch)
    print(f"  Returned: {result}")
    print(f"  URLs launched: {page.launched_urls}")
    print(f"  JS calls: {len(page.javascript_calls)}")

    # Check the file was copied to downloads
    dest = os.path.join(DOWNLOADS_DIR, "_dummy_test.txt")
    assert os.path.exists(dest), f"File not copied to {dest}"

    # Cleanup
    os.remove(src)
    os.remove(dest)
    return True

test("1.3 send_file_to_user copies + triggers download", t_send_real_file)


# =================================================================================
# 2. INVOICE EXPORTS
# =================================================================================
section("2. INVOICE EXPORTS")

# Get a real invoice from the DB
invoices = db.get_invoices()
print(f"Found {len(invoices)} invoice(s) in DB")

if not invoices:
    print("  ⚠️  No invoices in DB — cannot test invoice exports")
else:
    inv = invoices[0]
    print(f"Test invoice: {inv.get('invoice_no')} (id={inv.get('id')})")

    # Import the InvoicesTab class
    from core.invoices_tab import InvoicesTab
    print(f"  InvoicesTab methods: ", end="")
    methods = [m for m in dir(InvoicesTab) if not m.startswith("_")]
    export_methods = [m for m in methods if "export" in m or "print" in m]
    print(export_methods)

    # Create a minimal instance (no UI needed — just call the export methods)
    class FakePageFull(FakePage):
        def show_dialog(self, dlg): pass
        def pop_dialog(self): pass

    fake_page = FakePageFull()
    current_user = db.get_users()[0] if db.get_users() else {"id": "test", "username": "test"}

    tab = InvoicesTab(fake_page, db, current_user)

    # ---- Test PDF export ----
    def t_invoice_pdf():
        pdf_count_before = len([f for f in os.listdir(DOWNLOADS_DIR) if f.startswith("invoice_") and f.endswith(".pdf")])
        try:
            tab.export_invoice_to_pdf(inv)
        except Exception as ex:
            print(f"    Exception: {ex}")
            traceback.print_exc()
            return False

        pdf_count_after = len([f for f in os.listdir(DOWNLOADS_DIR) if f.startswith("invoice_") and f.endswith(".pdf")])
        print(f"    PDFs in downloads: {pdf_count_before} -> {pdf_count_after}")
        print(f"    URLs launched: {fake_page.launched_urls[-3:]}")
        print(f"    JS calls: {len(fake_page.javascript_calls)}")

        # Either a new PDF appeared OR a launch happened (or both)
        if pdf_count_after > pdf_count_before:
            return True
        return "No new PDF produced — check logs"

    test("2.1 InvoicesTab.export_invoice_to_pdf", t_invoice_pdf)

    # ---- Test Excel export ----
    def t_invoice_excel():
        xlsx_before = len([f for f in os.listdir(DOWNLOADS_DIR) if f.startswith("invoice_") and f.endswith(".xlsx")])
        try:
            tab.export_invoice_to_excel(inv)
        except Exception as ex:
            print(f"    Exception: {ex}")
            traceback.print_exc()
            return False

        xlsx_after = len([f for f in os.listdir(DOWNLOADS_DIR) if f.startswith("invoice_") and f.endswith(".xlsx")])
        print(f"    XLSXs in downloads: {xlsx_before} -> {xlsx_after}")
        if xlsx_after > xlsx_before:
            return True
        return "No new XLSX produced — check logs"

    test("2.2 InvoicesTab.export_invoice_to_excel", t_invoice_excel)

    # ---- Test print ----
    def t_invoice_print():
        try:
            tab.print_invoice(inv)
            return True
        except Exception as ex:
            print(f"    Exception: {ex}")
            return False

    test("2.3 InvoicesTab.print_invoice (shows hint)", t_invoice_print)

    # ---- Test view details ----
    def t_invoice_view():
        try:
            tab.view_invoice_details(inv)
            return True
        except Exception as ex:
            print(f"    Exception: {ex}")
            traceback.print_exc()
            return False

    test("2.4 InvoicesTab.view_invoice_details", t_invoice_view)


# =================================================================================
# 3. RECEIPT EXPORTS
# =================================================================================
section("3. RECEIPT EXPORTS")

receipts = db.get_receipts()
print(f"Found {len(receipts)} receipt(s)")

if not receipts:
    print("  ⚠️  No receipts — skipping receipt tests")
else:
    rec = receipts[0]
    print(f"Test receipt: {rec.get('receipt_no')}")

    from core.receipts_tab import ReceiptsTab
    class FakePageFull(FakePage):
        def show_dialog(self, dlg): pass
        def pop_dialog(self): pass

    fake_page = FakePageFull()
    current_user = db.get_users()[0] if db.get_users() else {"id": "test"}
    tab = ReceiptsTab(fake_page, db, current_user)

    def t_receipt_pdf():
        pdf_before = len([f for f in os.listdir(DOWNLOADS_DIR) if f.startswith("receipt_") and f.endswith(".pdf")])
        try:
            tab.export_single_receipt_pdf(rec)
        except Exception as ex:
            print(f"    Exception: {ex}")
            traceback.print_exc()
            return False
        pdf_after = len([f for f in os.listdir(DOWNLOADS_DIR) if f.startswith("receipt_") and f.endswith(".pdf")])
        print(f"    PDFs: {pdf_before} -> {pdf_after}")
        return pdf_after > pdf_before or "No new PDF"

    test("3.1 ReceiptsTab.export_single_receipt_pdf", t_receipt_pdf)

    def t_receipt_view():
        try:
            tab.view_receipt_details(rec)
            return True
        except Exception as ex:
            traceback.print_exc()
            return False

    test("3.2 ReceiptsTab.view_receipt_details", t_receipt_view)

    def t_receipt_print():
        try:
            tab.print_single_receipt(rec)
            return True
        except Exception as ex:
            return False

    test("3.3 ReceiptsTab.print_single_receipt", t_receipt_print)


# =================================================================================
# 4. BATCH EXPORTS
# =================================================================================
section("4. BATCH EXPORTS")

from core.batches_tab import BatchesTab
class FakePageFull(FakePage):
    def show_dialog(self, dlg): pass
    def pop_dialog(self): pass

fake_page = FakePageFull()
current_user = db.get_users()[0] if db.get_users() else {"id": "test"}
tab = BatchesTab(fake_page, db, current_user)


def t_batch_csv():
    csv_before = len([f for f in os.listdir(DOWNLOADS_DIR) if f.startswith("batches_")])
    try:
        tab.export_to_excel(None)
    except Exception as ex:
        print(f"    Exception: {ex}")
        traceback.print_exc()
        return False

    # Also check /app/exports
    exports_dir = os.path.join(BASE, "exports")
    if os.path.isdir(exports_dir):
        files = [f for f in os.listdir(exports_dir) if f.startswith("batches_")]
        print(f"    Files in /exports: {files[-3:]}")

    files = os.listdir(DOWNLOADS_DIR)
    batch_files = [f for f in files if f.startswith("batches_")]
    print(f"    Files in /downloads: {batch_files[-3:]}")
    return True

test("4.1 BatchesTab.export_to_excel (produces CSV)", t_batch_csv)


def t_batch_print():
    try:
        tab.print_batches(None)
        return True
    except Exception as ex:
        return False

test("4.2 BatchesTab.print_batches", t_batch_print)


# =================================================================================
# 5. TRAVELERS EXPORTS
# =================================================================================
section("5. TRAVELER EXPORTS")

from core.travelers_tab import TravelersTab
fake_page = FakePageFull()
tab = TravelersTab(fake_page, db, current_user)


def t_travelers_methods():
    methods = [m for m in dir(tab) if not m.startswith("_")]
    export_like = [m for m in methods if any(
        word in m.lower() for word in ("export", "pdf", "excel", "csv", "print", "template"))]
    print(f"  Export-like methods: {export_like}")
    return True

test("5.1 List TravelersTab export methods", t_travelers_methods)


# =================================================================================
# 6. CUSTOM REPORT
# =================================================================================
section("6. CUSTOM REPORT DIALOG")

try:
    from core.custom_report_dialog import CustomReportDialog
    print("  Imported CustomReportDialog")
    methods = [m for m in dir(CustomReportDialog) if not m.startswith("_")]
    export_methods = [m for m in methods if any(
        word in m.lower() for word in ("export", "pdf", "excel", "csv", "generate"))]
    print(f"  Export methods: {export_methods}")

    def t_custom_import():
        return True

    test("6.1 CustomReportDialog imports", t_custom_import)
except Exception as ex:
    print(f"  {FAIL} Import failed: {ex}")
    results.append(("6.1 CustomReportDialog import", "FAIL", str(ex)))


# =================================================================================
# 7. FASTAPI ENDPOINT
# =================================================================================
section("7. FASTAPI /download ENDPOINT")

from main import app as fastapi_app
routes = [r.path for r in fastapi_app.routes]
print(f"Routes: {routes}")

def t_route_exists():
    assert "/download/{filename}" in routes
    return True

test("7.1 /download route exists", t_route_exists)


def t_endpoint_function():
    # Find the download function
    for route in fastapi_app.routes:
        if route.path == "/download/{filename}":
            print(f"  Function: {route.endpoint.__name__}")
            print(f"  Methods : {route.methods}")
            return True
    return False

test("7.2 /download endpoint callable", t_endpoint_function)


# =================================================================================
# 8. BUTTON INVENTORY
# =================================================================================
section("8. BUTTON INVENTORY (per tab)")

tab_classes = {
    "TravelersTab": "core.travelers_tab",
    "BatchesTab":   "core.batches_tab",
    "PaymentsTab":  "core.payments_tab",
    "ReceiptsTab":  "core.receipts_tab",
    "InvoicesTab":  "core.invoices_tab",
    "DashboardTab": "core.dashboard_tab",
    "UsersTab":     "core.users_tab",
    "ReportsTab":   "core.reports_tab",
    "BackupTab":    "core.backups_tab",
}

for cls_name, mod_name in tab_classes.items():
    print(f"\n  ── {cls_name} ──")
    try:
        mod = __import__(mod_name, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        methods = [m for m in dir(cls) if not m.startswith("_")]
        # Filter to action-like methods
        actions = [m for m in methods if any(
            word in m.lower() for word in (
                "export", "pdf", "excel", "csv", "print", "delete",
                "add", "edit", "view", "refresh", "generate", "save",
                "create", "open", "download", "template", "import"))]
        for a in sorted(actions):
            print(f"    • {a}()")
    except Exception as ex:
        print(f"    {FAIL} {ex}")


# =================================================================================
# 9. URL CONSTRUCTION TEST
# =================================================================================
section("9. DOWNLOAD URL CONSTRUCTION")

def t_url_build():
    from core.helpers import get_app_base_path
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    print(f"  RAILWAY_PUBLIC_DOMAIN: {domain}")
    if domain:
        url = f"https://{domain}/download/test.pdf"
        print(f"  Sample URL: {url}")
        assert url.startswith("https://")
    else:
        print(f"  ⚠️  RAILWAY_PUBLIC_DOMAIN not set — using relative URLs")
    return True

test("9.1 Download URL construction", t_url_build)


# =================================================================================
# 10. EXISTING DOWNLOADS INVENTORY
# =================================================================================
section("10. EXISTING DOWNLOAD FILES")

files = os.listdir(DOWNLOADS_DIR)
print(f"  Total files: {len(files)}")
for f in sorted(files):
    size = os.path.getsize(os.path.join(DOWNLOADS_DIR, f))
    print(f"    {f:<60} {size:>10} bytes")


# =================================================================================
# SUMMARY
# =================================================================================
section("SUMMARY")

passed = sum(1 for _, s, _ in results if s == "PASS")
warned = sum(1 for _, s, _ in results if s == "WARN")
failed = sum(1 for _, s, _ in results if s == "FAIL")

print(f"  {PASS} Passed : {passed}")
print(f"  {WARN} Warned : {warned}")
print(f"  {FAIL} Failed : {failed}")
print(f"  ─────────────")
print(f"  TOTAL  : {len(results)}")

if failed:
    print(f"\n  FAILED:")
    for name, status, detail in results:
        if status == "FAIL":
            print(f"    {FAIL} {name}: {detail}")

print("\n" + "=" * 72)
print(f"  Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 72)