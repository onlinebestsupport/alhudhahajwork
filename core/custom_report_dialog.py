# =================================================================================
# SECTION 17 — CUSTOM REPORT DIALOG (FLET 1.0, MOBILE-RESPONSIVE)
# =================================================================================
# PURPOSE
#   Self-contained report generator embedded in the admin app. Lets the
#   user pick columns from Travelers / Batches / Payments, filter by date,
#   batch, status, method, amount, generate a summary or ledger report,
#   and export to Excel / CSV / PDF.
#
# VERSION
#   v1.4 — 2026-10-07
#     • §17.3.23/24/25 export_to_excel/csv/pdf now open the download in
#       a NEW TAB (web_only_window_name="_blank"). This keeps the report
#       tab alive so Safari doesn't reload /admin and lose the session.
#     • Helper §17.3.2d _launch_in_new_tab() centralises the Flet 1.0
#       web_only_window_name fallback logic.
#     • All v1.3 features preserved (scroll fix, mobile layout, etc.).
#
# SECTION INDEX
#   17.1   Imports
#   17.1b  _fmt_inr_                — INR number formatter
#   17.1c  _app_base                — find project root
#   17.1d  _export_dir / _assets_export_dir / _open_local_file
#   17.1e  _fmt_date_ddmmyyyy / _parse_ui_date
#   17.1f  _photo_data_uri / _find_photo_path
#   17.1g  _is_money_label
#   17.1h  FIELD CATALOGS
#
#   17.2   class ColumnOrderDialog
#   17.2.1  __init__
#   17.2.2  _rebuild_list
#   17.2.3  setup_ui
#   17.2.4  show
#
#   17.3   class CustomReportDialog
#   17.3.1   __init__
#   17.3.1b  _fmt_money_inr
#   17.3.1c  _load_live_tax_rates
#   17.3.1d  _refresh_invoice_caches
#   17.3.1e  _resolve_invoice_for_payment
#   17.3.1f  _is_invoice_paid_for_payment
#   17.3.1g  _get_payment_share
#   17.3.1h  _get_invoice_share
#   17.3.2   PATH / STRING HELPERS
#   17.3.2d  _launch_in_new_tab               ← NEW v1.4
#   17.3.3   setup_ui
#   17.3.4   setup_left_panel
#   17.3.5   setup_traveler_tab
#   17.3.6   setup_batch_tab
#   17.3.7   setup_payment_tab
#   17.3.8   setup_right_panel
#   17.3.9   setup_filters
#   17.3.9b  _on_report_format_changed
#   17.3.10  setup_preview
#   17.3.11  setup_buttons
#   17.3.12  setup_status
#   17.3.13  create_checkbox_group
#   17.3.14  select_all_checkboxes
#   17.3.15  get_selected_columns
#   17.3.16  date quick filter handlers
#   17.3.17  open_column_ordering_dialog
#   17.3.18  load_data_preview
#   17.3.18b _force_reload_csv
#   17.3.18c _diagnose
#   17.3.19  generate_preview
#   17.3.19b _generate_ledger_preview
#   17.3.20  _build_row_wide
#   17.3.21  _format_payment_value
#   17.3.22  display_preview
#   17.3.23  export_to_excel                  ← updated v1.4
#   17.3.24  export_to_csv                    ← updated v1.4
#   17.3.25  export_to_pdf                    ← updated v1.4
#   17.3.26  generate_pdf_report
#   17.3.27  _build_pdf_photo_cell
#   17.3.28  show / reject / _snack / _set_status
#
#   17.4   MAINTENANCE WARNINGS
# =================================================================================


# =================================================================================
# 17.1 — IMPORTS
# =================================================================================
import os
import sys
import csv
import io
import base64
import shutil
import subprocess
import traceback
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import flet as ft
import pandas as pd

try:
    from core.settings_manager import SettingsManager
except ImportError:
    SettingsManager = None

try:
    from core.helpers import send_file_to_user
except ImportError:
    def send_file_to_user(page, path, label="Download"):
        return None


# =================================================================================
# 17.1b — MODULE HELPER: _fmt_inr_
# PURPOSE
#   Format a number as Indian Rupees with lakh/crore grouping.
#   (e.g. 1234567.89 → "12,34,567.89"). Never raises.
# =================================================================================
if '_fmt_inr_' not in globals():
    def _fmt_inr_(value):
        try:
            v = float(value or 0)
        except (TypeError, ValueError):
            return "0.00"
        if v != v:  # NaN
            return "0.00"
        negative = v < 0
        v = abs(v)
        v = round(v, 2)
        int_part = int(v)
        dec_part = int(round((v - int_part) * 100))
        if dec_part >= 100:
            int_part += 1
            dec_part = 0
        s = str(int_part)
        if len(s) <= 3:
            grouped = s
        else:
            last3 = s[-3:]
            rest = s[:-3]
            groups = []
            while len(rest) > 2:
                groups.insert(0, rest[-2:])
                rest = rest[:-2]
            if rest:
                groups.insert(0, rest)
            grouped = ",".join(groups) + "," + last3
        out = f"{grouped}.{dec_part:02d}"
        return f"-{out}" if negative else out


# =================================================================================
# 17.1c — MODULE HELPER: _app_base
# PURPOSE
#   Locate the project root regardless of whether the app is frozen
#   (PyInstaller) or running from core/ inside the repo.
# =================================================================================
def _app_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(here).lower() == "core":
        return os.path.dirname(here)
    cur = here
    for _ in range(6):
        if (os.path.exists(os.path.join(cur, "main.py"))
                or os.path.exists(os.path.join(cur, "documents"))):
            return cur
        p = os.path.dirname(cur)
        if p == cur:
            break
        cur = p
    return here


# =================================================================================
# 17.1d — MODULE HELPERS: export dirs
# PURPOSE
#   Return (and create) the correct export folders under the project root.
#   _open_local_file is a no-op on web — kept for API compatibility.
# =================================================================================
def _export_dir(sub):
    d = Path(_app_base()) / "exports" / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def _assets_export_dir(sub):
    d = Path(_app_base()) / "assets" / "exports" / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def _open_local_file(path):
    print(f"[WEB] _open_local_file is disabled on web. File: {path}")
    return False


# =================================================================================
# 17.1e — MODULE HELPERS: date formatting
# PURPOSE
#   _fmt_date_ddmmyyyy: normalise any date value → "DD/MM/YYYY" string.
#   _parse_ui_date:     parse a UI string into a datetime or None.
# =================================================================================
def _fmt_date_ddmmyyyy(dv):
    if dv is None:
        return ""
    s = str(dv).strip()
    if not s or s.lower() in ("nan", "none", "nat", "null", ""):
        return ""
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        return s[:10]
    if len(s) >= 10 and s[4] == "/" and s[7] == "/":
        return f"{s[8:10]}/{s[5:7]}/{s[0:4]}"
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return f"{s[8:10]}/{s[5:7]}/{s[0:4]}"
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19], fmt).strftime("%d/%m/%Y")
        except Exception:
            continue
    return s[:10]


def _parse_ui_date(s):
    if not s:
        return None
    s = str(s).strip()[:10]
    if not s:
        return None
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        try:
            return datetime.strptime(s, "%d/%m/%Y")
        except Exception:
            return None
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None
    if len(s) >= 10 and s[4] == "/" and s[7] == "/":
        try:
            return datetime.strptime(s, "%Y/%m/%d")
        except Exception:
            return None
    return None


# =================================================================================
# 17.1f — MODULE HELPERS: photo helpers
# PURPOSE
#   _photo_data_uri: read a photo from disk → data URI for Flet Image.
#   _find_photo_path: scan documents/<traveler_id>/photos for a photo.
# =================================================================================
def _photo_data_uri(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                "gif": "gif", "bmp": "bmp"}.get(ext, "jpeg")
        return f"data:image/{mime};base64,{data}"
    except Exception:
        return None


def _find_photo_path(t):
    base = _app_base()
    rel = (t.get("photo", "") or "").strip()
    if rel:
        p = os.path.join(base, rel)
        if os.path.exists(p):
            return p
    tid = str(t.get("id", "") or "").strip()
    if not tid:
        return None
    folder = tid.replace("/", "_").replace("\\", "_")
    for sub in ("photos", "photo", "images", "img", ""):
        pdir = (os.path.join(base, "documents", folder, sub)
                if sub else os.path.join(base, "documents", folder))
        if not os.path.exists(pdir):
            continue
        try:
            for f in os.listdir(pdir):
                if f.lower().endswith(
                        (".jpg", ".jpeg", ".png", ".bmp", ".gif")):
                    return os.path.join(pdir, f)
        except Exception:
            pass
    return None


# =================================================================================
# 17.1g — MODULE HELPER: money label detection
# PURPOSE
#   Decide whether a column label represents a currency value so we
#   render it right-aligned with the correct ₹ formatting.
# =================================================================================
def _is_money_label(label):
    if not label:
        return False
    if label in MONEY_FIELDS:
        return True
    if label.startswith("Payment ") and any(
            k in label for k in
            ("Amount", "GST", "TCS", "Taxable", "Outstanding", "Total")):
        return True
    if label.startswith("Invoice ") and any(
            k in label for k in
            ("Base", "Discount", "Taxable", "GST", "TCS", "Total")):
        return True
    return False


# =================================================================================
# 17.1h — FIELD CATALOGS
# PURPOSE
#   Static lists of every column the user can pick from, grouped by
#   source (traveler / batch / payment) plus helper metadata.
# =================================================================================
TRAVELER_FIELDS = [
    ("id", "ID"), ("first_name", "First Name"),
    ("last_name", "Last Name"), ("passport_name", "Passport Name"),
    ("gender", "Gender"), ("dob", "Date of Birth"),
    ("status", "Traveler Status"),
    ("registration_date", "Registration Date"),
    ("batch_id", "Batch ID"), ("batch_name", "Batch Name"),
    ("passport_no", "Passport Number"),
    ("passport_issue_date", "Passport Issue Date"),
    ("passport_expiry_date", "Passport Expiry Date"),
    ("passport_status", "Passport Status"),
    ("place_of_birth", "Place of Birth"),
    ("place_of_issue", "Place of Issue"),
    ("mobile", "Mobile Number"), ("email", "Email"),
    ("aadhaar", "Aadhaar Number"), ("pan", "PAN Number"),
    ("aadhaar_pan_linked", "Aadhaar-PAN Linked"),
    ("passport_address", "Passport Address"),
    ("mailing_address", "Mailing Address"), ("pin", "PIN"),
    ("father_name", "Father's Name"), ("mother_name", "Mother's Name"),
    ("spouse_name", "Spouse's Name"),
    ("expected_return_date", "Expected Return Date"),
    ("file_reference", "File Reference"),
    ("wheelchair", "Wheelchair Required"),
    ("emergency_contact", "Emergency Contact"),
    ("emergency_phone", "Emergency Phone"),
    ("vaccine_status", "Vaccine Status"),
    ("medical_notes", "Medical Notes"),
    ("photo", "Photo"), ("passport_scan", "Passport Scan"),
    ("aadhaar_scan", "Aadhaar Scan"), ("pan_scan", "PAN Scan"),
    ("vaccine_scan", "Vaccine Certificate"),
]

BATCH_FIELDS = [
    ("id", "Batch ID"), ("batch_name", "Batch Name"),
    ("tour_type_name", "Tour Type"), ("year", "Year"),
    ("departure_date", "Departure Date"),
    ("return_date", "Return Date"), ("total_seats", "Total Seats"),
    ("available_seats", "Available Seats"),
    ("price", "Price per Seat"), ("status", "Batch Status"),
    ("description", "Description"),
]

PAYMENT_FIELDS = [
    ("id", "Payment ID / Receipt No"),
    ("traveler_id", "Traveler ID"),
    ("batch_id", "Batch ID"),
    ("amount", "Payment Amount (without GST/TCS)"),
    ("payment_date", "Payment Date"),
    ("payment_method", "Payment Method"),
    ("status", "Payment Status"),
    ("transaction_id", "Transaction ID"),
    ("invoice_id", "Invoice ID"),
    ("notes", "Payment Notes"),
    ("passport_name", "Passport Name"),
    ("passport_no", "Passport Number"),
    ("mobile", "Mobile Number"),
    ("invoice_base_amount", "Invoice Base Amount"),
    ("invoice_discount_pct", "Invoice Discount %"),
    ("invoice_discount_amount", "Invoice Discount Amount"),
    ("invoice_taxable_value", "Invoice Taxable Value"),
    ("gst_amount", "GST Amount (from invoice)"),
    ("tcs_amount", "TCS Amount (from invoice)"),
    ("invoice_rounded_total", "Invoice Total (with GST/TCS)"),
    ("payment_without_tax", "Payment — Without GST/TCS"),
    ("payment_with_tax", "Payment — With GST/TCS"),
    ("total_with_tax", "Total — With GST/TCS"),
    ("__sum_total_paid", "Total Paid"),
    ("__sum_payment_count", "Payment Count"),
    ("__sum_additional_count", "Additional Payments"),
    ("__sum_additional_total", "Additional Total"),
    ("__sum_total_base", "Total Base"),
    ("__sum_total_discount", "Total Discount"),
    ("__sum_total_taxable", "Total Taxable"),
    ("__sum_total_gst", "Total GST"),
    ("__sum_total_tcs", "Total TCS"),
    ("__sum_total_with_tax", "Total — With GST/TCS"),
    ("__sum_pending_with_tax", "Pending — With GST/TCS"),
    ("__sum_payment_without_tax", "Payment — Without GST/TCS"),
    ("__sum_outstanding_balance", "Outstanding Balance"),
    ("__dyn_amount", "▶ Payment Amount (each, without tax)"),
    ("__dyn_date", "▶ Payment Date (each)"),
    ("__dyn_method", "▶ Payment Method (each)"),
    ("__dyn_receipt", "▶ Receipt No (each)"),
    ("__dyn_txn", "▶ Txn ID (each)"),
    ("__dyn_status", "▶ Payment Status (each)"),
    ("__dyn_gst", "▶ GST (each)"),
    ("__dyn_tcs", "▶ TCS (each)"),
    ("__dyn_total_tax", "▶ Total with tax (each)"),
    ("__inv_paid_status", "Invoice Status"),
    ("__inv_paid_is_paid", "Invoice is Paid?"),
    ("__inv_paid_base", "Invoice Base (paid)"),
    ("__inv_paid_discount", "Invoice Discount (paid)"),
    ("__inv_paid_taxable", "Invoice Taxable (paid)"),
    ("__inv_paid_gst", "Invoice GST (paid)"),
    ("__inv_paid_tcs", "Invoice TCS (paid)"),
    ("__inv_paid_total", "Invoice Total (paid)"),
]

MONEY_FIELDS = {
    "Payment Amount", "Payment Amount (without GST/TCS)",
    "Invoice Base Amount", "Invoice Discount Amount",
    "Invoice Taxable Value", "Invoice Total",
    "Invoice Total (with GST/TCS)",
    "GST Amount (from invoice)", "TCS Amount (from invoice)",
    "GST Amount", "TCS Amount",
    "Payment — Without GST/TCS", "Payment — With GST/TCS",
    "Total — With GST/TCS", "Total (with GST/TCS)",
    "Total Paid", "Additional Total",
    "Total Base", "Total Discount", "Total Taxable",
    "Total GST", "Total TCS",
    "Pending — With GST/TCS", "Pending Payment (with GST/TCS)",
    "Payment (without GST/TCS)", "Payment (with GST/TCS)",
    "Outstanding Balance",
    "Price per Seat", "Price",
    "Invoice Base (paid)", "Invoice Discount (paid)",
    "Invoice Taxable (paid)", "Invoice GST (paid)",
    "Invoice TCS (paid)", "Invoice Total (paid)",
}


def _dyn_label(key, n):
    """Return the per-slot label for a dynamic payment column."""
    return {
        "__dyn_amount":    f"Payment {n} Amount",
        "__dyn_date":      f"Payment {n} Date",
        "__dyn_method":    f"Payment {n} Method",
        "__dyn_receipt":   f"Payment {n} Receipt No",
        "__dyn_txn":       f"Payment {n} Txn ID",
        "__dyn_status":    f"Payment {n} Status",
        "__dyn_gst":       f"Payment {n} GST",
        "__dyn_tcs":       f"Payment {n} TCS",
        "__dyn_total_tax": f"Payment {n} Total (with tax)",
    }.get(key, f"Payment {n} Field")


# =================================================================================
# 17.2 — CLASS: ColumnOrderDialog
# =================================================================================
# PURPOSE
#   Small modal for reordering the columns in the current report. Shows
#   the selected columns as a list; tap a row, use Up/Down to move it.
# =================================================================================
class ColumnOrderDialog:

    # -----------------------------------------------------------------------------
    # 17.2.1 — __init__
    # PURPOSE
    #   Capture the column list, wire the on-apply callback, prep the list.
    # -----------------------------------------------------------------------------
    def __init__(self, page, columns, on_apply):
        self.page = page
        self.columns = list(columns)
        self.original_columns = list(columns)
        self.on_apply = on_apply
        self._sel = 0
        self._list = ft.Column(spacing=4)
        self._rebuild_list()
        self.setup_ui()

    # -----------------------------------------------------------------------------
    # 17.2.2 — _rebuild_list
    # PURPOSE
    #   Redraw the clickable list of columns. Selected row is highlighted.
    # -----------------------------------------------------------------------------
    def _rebuild_list(self):
        self._list.controls.clear()
        for i, col in enumerate(self.columns):
            is_sel = (i == self._sel)
            source_icon = ("👤" if col["source"] == "traveler"
                           else "📦" if col["source"] == "batch"
                           else "💰")

            def _click(e, idx=i):
                self._sel = idx
                self._rebuild_list()
                self.page.update()

            self._list.controls.append(ft.Container(
                content=ft.Row([
                    ft.Text(f"{i+1}.", size=11, width=24,
                            color=ft.Colors.GREY_600),
                    ft.Text(source_icon, size=14),
                    ft.Text(col["label"], size=12, expand=True,
                            color="#1e40af" if is_sel
                            else ft.Colors.GREY_900,
                            weight=(ft.FontWeight.BOLD if is_sel
                                    else ft.FontWeight.NORMAL)),
                ], spacing=6),
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                bgcolor="#dbeafe" if is_sel else "#f9fafb",
                border=ft.Border.all(2, "#2563eb") if is_sel
                else ft.Border.all(1, ft.Colors.GREY_200),
                border_radius=6, on_click=_click, ink=True))

    # -----------------------------------------------------------------------------
    # 17.2.3 — setup_ui
    # PURPOSE
    #   Build the modal. Buttons: Up / Down / Reset / Apply / Cancel.
    # -----------------------------------------------------------------------------
    def setup_ui(self):
        header = ft.Container(
            content=ft.Row([
                ft.Text("📌", size=18),
                ft.Text("Reorder Columns", size=13,
                        weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
            ], spacing=8),
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#7c3aed", "#a855f7"]),
            border_radius=10)

        def move_up(e):
            if self._sel > 0:
                i = self._sel
                self.columns[i - 1], self.columns[i] = (
                    self.columns[i], self.columns[i - 1])
                self._sel = i - 1
                self._rebuild_list()
                self.page.update()

        def move_down(e):
            if self._sel < len(self.columns) - 1:
                i = self._sel
                self.columns[i + 1], self.columns[i] = (
                    self.columns[i], self.columns[i + 1])
                self._sel = i + 1
                self._rebuild_list()
                self.page.update()

        def reset_order(e):
            self.columns = list(self.original_columns)
            self._sel = 0
            self._rebuild_list()
            self.page.update()

        def apply(e):
            try:
                self.page.pop_dialog()
            except Exception:
                pass
            if self.on_apply:
                try:
                    self.on_apply(self.columns)
                except Exception as ex:
                    print(f"[CR] apply error: {ex}")

        def cancel(e):
            try:
                self.page.pop_dialog()
            except Exception:
                pass

        pw = self.page.width or 400
        ph = self.page.height or 700
        dlg_w = max(300, min(480, pw - 30))
        dlg_h = max(400, min(560, ph - 100))

        content = ft.Container(
            content=ft.Column([
                header,
                ft.Text("Tap a row, then use Up/Down to reorder",
                        size=11, color=ft.Colors.GREY_600, italic=True),
                ft.Container(
                    content=ft.Column([self._list],
                                      scroll=ft.ScrollMode.AUTO,
                                      expand=True),
                    height=320, padding=6,
                    border=ft.Border.all(1, ft.Colors.GREY_200),
                    border_radius=8),
            ], spacing=10),
            width=dlg_w, height=dlg_h, padding=6)

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("📌  Reorder Columns",
                          weight=ft.FontWeight.BOLD, size=14),
            content=content,
            actions=[
                ft.Button(content=ft.Text("⬆  Up", size=11),
                          on_click=move_up, height=34,
                          bgcolor="#2563eb", color=ft.Colors.WHITE),
                ft.Button(content=ft.Text("⬇  Down", size=11),
                          on_click=move_down, height=34,
                          bgcolor="#2563eb", color=ft.Colors.WHITE),
                ft.Button(content=ft.Text("🔄  Reset", size=11),
                          on_click=reset_order, height=34,
                          bgcolor="#d97706", color=ft.Colors.WHITE),
                ft.Button(content=ft.Text("✅  Apply", size=11),
                          on_click=apply,
                          bgcolor="#059669", color=ft.Colors.WHITE),
                ft.TextButton(content=ft.Text("Cancel", size=11),
                              on_click=cancel),
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER)

    # -----------------------------------------------------------------------------
    # 17.2.4 — show
    # -----------------------------------------------------------------------------
    def show(self):
        self.page.show_dialog(self.dialog)


# =================================================================================
# 17.3 — CLASS: CustomReportDialog
# =================================================================================
class CustomReportDialog:

    _MONEY_FIELDS = MONEY_FIELDS
    HARD_CAP = 10  # max dynamic payment slots

    # =============================================================================
    # 17.3.1 — __init__
    # PURPOSE
    #   Load data, prime invoice caches, then build the UI.
    # =============================================================================
    def __init__(self, page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user or {}

        self.selected_columns = []
        self.report_data = None
        self.traveler_data = []
        self.batch_data = []
        self.payment_data = []
        self.invoice_lookup = {}
        self.traveler_discount = {}
        self.traveler_invoice_data = {}
        self.invoice_by_id = {}
        self.invoice_by_no = {}
        self.default_invoice_by_traveler = {}
        self.gst_rate = 0.0
        self.tcs_rate = 0.0
        self.traveler_checkboxes = {}
        self.batch_checkboxes = {}
        self.payment_checkboxes = {}
        self.current_report_mode = 'summary'
        self._column_order = {}
        self._last_payment_source = "(not loaded)"

        self.column_group = None
        self.column_group_title = None
        self.column_tabs = None
        self.report_format_dropdown = None
        self.reg_date_from = None
        self.reg_date_to = None
        self.batch_filter_combo = None
        self.status_filter = None
        self.payment_method_filter = None
        self.payment_status_filter = None
        self.min_amount_input = None
        self.max_amount_input = None
        self.preview_table = None
        self._preview_inner = None
        self._preview_hview = None
        self._preview_body = None
        self.status_icon = None
        self.status_label = None
        self.record_count_label = None
        self.dialog = None

        self._left_panel_container = None
        self._body_responsive_row = None

        self._load_live_tax_rates()
        self._refresh_invoice_caches()
        self.load_data_preview()
        self.setup_ui()

    # =============================================================================
    # 17.3.1b — _fmt_money_inr
    # =============================================================================
    def _fmt_money_inr(self, value):
        return _fmt_inr_(value)

    # =============================================================================
    # 17.3.1c — _load_live_tax_rates
    # PURPOSE
    #   Read GST and TCS percentages from SettingsManager.
    # =============================================================================
    def _load_live_tax_rates(self):
        try:
            if SettingsManager is not None:
                sm = SettingsManager(self.db)
                tax = sm.get_tax_settings()
                self.gst_rate = float(tax.get('gst_percentage', 18) or 0)
                self.tcs_rate = float(tax.get('tcs_percentage', 0.1) or 0)
        except Exception as e:
            print(f"[CR] _load_live_tax_rates failed: {e}")
            self.gst_rate = 0.0
            self.tcs_rate = 0.0

    # =============================================================================
    # 17.3.1d — _refresh_invoice_caches   (FIX-PAID-CASCADE)
    # PURPOSE
    #   Build three dicts from the invoices table:
    #     invoice_by_id / invoice_by_no       — fast lookup by ID or number
    #     default_invoice_by_traveler         — fallback invoice per traveler
    #     traveler_invoice_data               — SUM per traveler (all invoices)
    #   This is what lets us pro-rate any payment across its invoice.
    # =============================================================================
    def _refresh_invoice_caches(self):
        self.traveler_invoice_data = {}
        self.invoice_by_id = {}
        self.invoice_by_no = {}
        self.default_invoice_by_traveler = {}

        def _f(v):
            try:
                return float(v or 0)
            except (TypeError, ValueError):
                return 0.0

        try:
            for inv in self.db.get_invoices():
                tid = inv.get('traveler_id')
                if not tid:
                    continue

                inv_entry = {
                    'base':            _f(inv.get('amount', 0)),
                    'discount_amount': _f(inv.get('discount_amount', 0)),
                    'discount_pct':    _f(inv.get('discount_percentage', 0)),
                    'taxable':         _f(inv.get('taxable_value', 0)),
                    'gst':             _f(inv.get('gst_amount', 0)),
                    'gst_pct':         _f(inv.get('gst_percentage', 0)),
                    'tcs':             _f(inv.get('tcs_amount', 0)),
                    'tcs_pct':         _f(inv.get('tcs_percentage', 0)),
                    'total_amount':    _f(inv.get('total_amount', 0)),
                    'rounded_total':   _f(inv.get('rounded_total', 0)),
                    'status':          str(inv.get('status', '') or '').lower(),
                    'is_paid':         (str(inv.get('status', '')).lower()
                                        == 'paid'),
                }
                if inv_entry['total_amount'] <= 0:
                    inv_entry['total_amount'] = (
                        inv_entry['taxable'] + inv_entry['gst']
                        + inv_entry['tcs'])
                if inv_entry['rounded_total'] <= 0:
                    inv_entry['rounded_total'] = inv_entry['total_amount']

                iid = str(inv.get('id', '') or '').strip()
                ino = str(inv.get('invoice_no', '') or '').strip()
                if iid:
                    self.invoice_by_id[iid] = inv_entry
                if ino:
                    self.invoice_by_no[ino] = inv_entry

                if (str(inv.get('status', '')).lower() != 'cancelled'
                        and tid not in self.default_invoice_by_traveler):
                    self.default_invoice_by_traveler[tid] = inv_entry

                entry = self.traveler_invoice_data.setdefault(tid, {
                    'base': 0.0,
                    'discount_amount': 0.0,
                    'discount_pct': None,
                    'discount_pct_calc': 0.0,
                    'taxable': 0.0,
                    'gst': 0.0,
                    'gst_pct': None,
                    'gst_pct_calc': 0.0,
                    'tcs': 0.0,
                    'tcs_pct': None,
                    'tcs_pct_calc': 0.0,
                    'total_amount': 0.0,
                    'rounded_total': 0.0,
                    'has_paid_invoice': False,
                })
                entry['base']            += inv_entry['base']
                entry['discount_amount'] += inv_entry['discount_amount']
                entry['taxable']         += inv_entry['taxable']
                entry['gst']             += inv_entry['gst']
                entry['tcs']             += inv_entry['tcs']
                entry['total_amount']    += inv_entry['total_amount']
                entry['rounded_total']   += inv_entry['rounded_total']
                if entry['discount_pct'] is None:
                    entry['discount_pct'] = inv_entry['discount_pct']
                    entry['gst_pct'] = inv_entry['gst_pct']
                    entry['tcs_pct'] = inv_entry['tcs_pct']
                if inv_entry['is_paid']:
                    entry['has_paid_invoice'] = True

            for tid, data in self.traveler_invoice_data.items():
                if data['base'] > 0:
                    data['discount_pct_calc'] = (
                        data['discount_amount'] / data['base'] * 100.0)
                if data['taxable'] > 0:
                    data['gst_pct_calc'] = (
                        data['gst'] / data['taxable'] * 100.0)
                    data['tcs_pct_calc'] = (
                        data['tcs'] / data['taxable'] * 100.0)
        except Exception as e:
            print(f"[CR] _refresh_invoice_caches failed: {e}")

    # =============================================================================
    # 17.3.1e — _resolve_invoice_for_payment
    # PURPOSE
    #   Find the invoice that a payment belongs to. Uses payment.invoice_id
    #   first, then falls back to the traveler's default invoice.
    # =============================================================================
    def _resolve_invoice_for_payment(self, payment, traveler_id):
        inv_id = str(payment.get('invoice_id', '') or '').strip()
        if inv_id:
            inv = self.invoice_by_id.get(inv_id)
            if inv:
                return inv
            inv = self.invoice_by_no.get(inv_id)
            if inv:
                return inv
        if traveler_id:
            inv = self.default_invoice_by_traveler.get(traveler_id)
            if inv:
                return inv
        return None

    # =============================================================================
    # 17.3.1f — _is_invoice_paid_for_payment
    # PURPOSE
    #   True if the payment's invoice is marked Paid. Falls back to
    #   a live DB scan if the cache misses.
    # =============================================================================
    def _is_invoice_paid_for_payment(self, payment, traveler_id):
        try:
            inv = self._resolve_invoice_for_payment(payment, traveler_id)
            if inv is not None:
                return bool(inv.get('is_paid', False))
            if traveler_id:
                for dbinv in self.db.get_invoices(traveler_id):
                    inv_id = str(payment.get('invoice_id', '') or '').strip()
                    ino = str(dbinv.get('invoice_no', '') or '').strip()
                    iid = str(dbinv.get('id', '') or '').strip()
                    if inv_id and (inv_id == iid or inv_id == ino):
                        return (str(dbinv.get('status', '')).lower()
                                == 'paid')
        except Exception as e:
            print(f"[CR] _is_invoice_paid_for_payment error: {e}")
        return False

    # =============================================================================
    # 17.3.1g — _get_payment_share
    # PURPOSE
    #   Given a single payment and its traveler, return the pro-rated
    #   invoice components (base, discount, taxable, GST, TCS, total)
    #   that this payment represents.
    # =============================================================================
    def _get_payment_share(self, payment, traveler_id):
        amt = 0.0
        try:
            amt = float(payment.get('amount', 0) or 0)
        except (TypeError, ValueError):
            amt = 0.0

        inv = self._resolve_invoice_for_payment(payment, traveler_id)
        if not inv:
            return self._get_invoice_share(traveler_id, amt)

        denom = inv['base'] or 0.0
        if denom <= 0:
            denom = inv['total_amount'] or inv['rounded_total'] or 0.0
        if denom <= 0:
            return {
                'base': 0.0, 'discount_pct': 0.0, 'discount_amount': 0.0,
                'taxable': 0.0, 'gst': 0.0, 'gst_pct': 0.0,
                'tcs': 0.0, 'tcs_pct': 0.0, 'total': 0.0, 'ratio': 0.0,
            }

        ratio = amt / denom
        if ratio > 1.0:
            ratio = 1.0

        return {
            'base':            inv['base'] * ratio,
            'discount_pct':    inv['discount_pct'],
            'discount_amount': inv['discount_amount'] * ratio,
            'taxable':         inv['taxable'] * ratio,
            'gst':             inv['gst'] * ratio,
            'gst_pct':         inv['gst_pct'],
            'tcs':             inv['tcs'] * ratio,
            'tcs_pct':         inv['tcs_pct'],
            'total':           inv['total_amount'] * ratio,
            'ratio':           ratio,
        }

    # =============================================================================
    # 17.3.1h — _get_invoice_share
    # PURPOSE
    #   Fallback when no single invoice can be resolved: pro-rate the
    #   traveler's total invoice components by the payment amount.
    # =============================================================================
    def _get_invoice_share(self, traveler_id, payment_amount):
        data = self.traveler_invoice_data.get(traveler_id)
        empty = {
            'base': 0.0, 'discount_pct': 0.0, 'discount_amount': 0.0,
            'taxable': 0.0, 'gst': 0.0, 'gst_pct': 0.0,
            'tcs': 0.0, 'tcs_pct': 0.0, 'total': 0.0, 'ratio': 0.0,
        }
        if not data:
            return empty

        denom = data.get('base') or 0.0
        if denom <= 0:
            denom = (data.get('total_amount')
                     or data.get('rounded_total') or 0.0)
        if denom <= 0:
            return empty

        try:
            amt = float(payment_amount or 0)
        except (TypeError, ValueError):
            amt = 0.0

        ratio = amt / denom
        if ratio > 1.0:
            ratio = 1.0

        invoice_total = (data.get('total_amount')
                         or data.get('rounded_total') or 0.0)

        disc_pct = (data.get('discount_pct')
                    if data.get('discount_pct') is not None
                    else data.get('discount_pct_calc', 0.0))
        gst_pct = (data.get('gst_pct')
                   if data.get('gst_pct') is not None
                   else data.get('gst_pct_calc', 0.0))
        tcs_pct = (data.get('tcs_pct')
                   if data.get('tcs_pct') is not None
                   else data.get('tcs_pct_calc', 0.0))

        return {
            'base':            data['base'] * ratio,
            'discount_pct':    disc_pct,
            'discount_amount': data['discount_amount'] * ratio,
            'taxable':         data['taxable'] * ratio,
            'gst':             data['gst'] * ratio,
            'gst_pct':         gst_pct,
            'tcs':             data['tcs'] * ratio,
            'tcs_pct':         tcs_pct,
            'total':           invoice_total * ratio,
            'ratio':           ratio,
        }

    # =============================================================================
    # 17.3.2 — PATH / STRING HELPERS
    # =============================================================================
    def get_app_base_path(self):
        return _app_base()

    def get_photo_path(self, traveler):
        photo_path = traveler.get('photo', '')
        if photo_path:
            base = self.get_app_base_path()
            abs_path = os.path.join(base, photo_path)
            if os.path.exists(abs_path):
                return abs_path
        traveler_id = traveler.get('id')
        if traveler_id:
            base = self.get_app_base_path()
            folder_name = traveler_id.replace('/', '_').replace('\\', '_')
            docs_dir = os.path.join(base, "documents", folder_name, "photos")
            if os.path.exists(docs_dir):
                for file in os.listdir(docs_dir):
                    if file.lower().endswith(
                            ('.jpg', '.jpeg', '.png', '.bmp', '.gif')):
                        return os.path.join(docs_dir, file)
        return None

    def safe_str(self, value):
        if value is None:
            return ''
        try:
            if isinstance(value, float):
                if value != value:
                    return ''
                val_str = (str(int(value)) if value.is_integer()
                           else str(value))
                if len(val_str) == 12 and val_str.isdigit():
                    return f"{val_str[:4]} {val_str[4:8]} {val_str[8:]}"
                if value.is_integer():
                    return str(int(value))
                return str(value)
            if isinstance(value, int):
                val_str = str(int(value))
                if len(val_str) == 12 and val_str.isdigit():
                    return f"{val_str[:4]} {val_str[4:8]} {val_str[8:]}"
                return val_str
            if hasattr(value, 'strftime'):
                return value.strftime('%d/%m/%Y')
            if isinstance(value, str) and value.endswith('.0'):
                return value[:-2]
            return str(value)
        except Exception:
            return str(value) if value else ''

    def safe_csv_value(self, value, quote_numeric=False):
        if value is None:
            return ''
        try:
            if isinstance(value, float):
                if value != value:
                    return ''
                if value.is_integer():
                    val_str = str(int(value))
                    if len(val_str) == 12 and val_str.isdigit():
                        return f'"{val_str}"'
                    return val_str
                return str(value)
            if isinstance(value, int):
                val_str = str(int(value))
                if len(val_str) == 12 and val_str.isdigit():
                    return f'"{val_str}"'
                return val_str
            if hasattr(value, 'strftime'):
                return value.strftime('%d/%m/%Y')
            if isinstance(value, str):
                if value.isdigit() and quote_numeric:
                    return f'"{value}"'
                return value
            return str(value)
        except Exception:
            return str(value) if value else ''

    def format_date_to_ddmmyyyy(self, date_str):
        return _fmt_date_ddmmyyyy(date_str)

    def convert_scientific_to_number(self, value):
        if value is None or value == '':
            return ''
        try:
            if isinstance(value, float):
                if value > 9999999999:
                    return str(int(value))
                return str(value)
            value_str = str(value).strip()
        except Exception:
            return str(value) if value else ''
        if not value_str:
            return ''
        import re as _re
        scientific_pattern = _re.compile(r'^[\d.]+[Ee][+-]?\d+$')
        if scientific_pattern.match(value_str):
            try:
                float_val = float(value_str)
                return (str(int(float_val)) if float_val.is_integer()
                        else str(float_val))
            except Exception:
                return value_str
        try:
            float_val = float(value_str)
            if (float_val.is_integer()
                    and len(str(int(float_val))) >= 10):
                return str(int(float_val))
            return value_str
        except Exception:
            return value_str

    def wrap_text(self, text, max_width=35):
        if not text:
            return ''
        try:
            text = str(text)
        except Exception:
            return ''
        if len(text) <= max_width:
            return text
        words = text.split()
        lines = []
        current_line = []
        current_len = 0
        for word in words:
            word_len = len(word)
            if current_len + word_len + 1 <= max_width:
                current_line.append(word)
                current_len += word_len + 1
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_len = word_len + 1
        if current_line:
            lines.append(' '.join(current_line))
        return '\n'.join(lines)

    # =============================================================================
    # 17.3.2d — _launch_in_new_tab   ← NEW v1.4
    # PURPOSE
    #   Open a URL in a NEW browser tab. Used by all export methods so
    #   the report tab is NOT navigated away from, keeping the Flet
    #   session alive (fixes "logged out after viewing report" on iOS
    #   Safari).
    #
    #   Falls back through three Flet API variants:
    #     1. UrlLauncher.launch_url(url, web_only_window_name="_blank")
    #        (Flet 1.0)
    #     2. UrlLauncher.launch_url(url, web_window_name="_blank")
    #        (legacy)
    #     3. UrlLauncher.launch_url(url) (bare — most browsers open
    #        in new tab by default for cross-origin urls; for same-
    #        origin, will fall through to whatever the browser does)
    # =============================================================================
    def _launch_in_new_tab(self, url):
        if not url:
            return

        async def _do():
            # Attempt 1 — Flet 1.0 parameter name
            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url(url,
                                        web_only_window_name="_blank")
                if asyncio.iscoroutine(r):
                    await r
                print(f"[EXPORT] OK new tab: {url}")
                return
            except TypeError as te:
                print(f"[EXPORT] 1.0 param rejected: {te}")
            except Exception as e:
                print(f"[EXPORT] 1.0 param raised: {e}")

            # Attempt 2 — legacy parameter name
            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url(url,
                                        web_window_name="_blank")
                if asyncio.iscoroutine(r):
                    await r
                print(f"[EXPORT] OK legacy new tab: {url}")
                return
            except Exception as e:
                print(f"[EXPORT] legacy param failed: {e}")

            # Attempt 3 — bare (browser default)
            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url(url)
                if asyncio.iscoroutine(r):
                    await r
                print(f"[EXPORT] OK bare launch: {url}")
                return
            except Exception as e:
                print(f"[EXPORT] bare launch failed: {e}")

        try:
            self.page.run_task(_do)
        except Exception as ex:
            print(f"[EXPORT] run_task failed: {ex}")
            # =============================================================================
    # 17.3.3 — setup_ui   (MOBILE-RESPONSIVE + SCROLL)
    # PURPOSE
    #   Build the dialog. Everything below the header is inside a
    #   scrollable Column so the bottom buttons stay reachable on any
    #   viewport height. Dialog clamps to (viewport − margins).
    # =============================================================================
    def setup_ui(self):
        # ---- 17.3.3.1  Header (compact, close always visible) ----
        header = ft.Container(
            content=ft.Row([
                ft.Text("📊", size=20),
                ft.Column([
                    ft.Text("Custom Report Generator", size=13,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE,
                            no_wrap=False, max_lines=2),
                    ft.Text("Traveler Summary OR Payment Ledger",
                            size=9, color=ft.Colors.BLUE_100),
                ], spacing=1, expand=True),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_color=ft.Colors.WHITE,
                    icon_size=20,
                    tooltip="Close",
                    on_click=lambda e: self.reject()),
            ], spacing=6),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#1e40af", "#2563eb", "#7c3aed"]),
            border_radius=10)

        # ---- 17.3.3.2  Build panels ----
        left_panel = self.setup_left_panel()
        right_panel = self.setup_right_panel()

        self._body_responsive_row = ft.ResponsiveRow(
            controls=[
                ft.Container(content=left_panel,
                             col={"xs": 12, "sm": 12, "md": 4, "lg": 4}),
                ft.Container(content=right_panel,
                             col={"xs": 12, "sm": 12, "md": 8, "lg": 8}),
            ],
            spacing=10, run_spacing=10,
        )

        filters_card = self.setup_filters()
        buttons = self.setup_buttons()
        status = self.setup_status()

        # ---- 17.3.3.3  Inner scrollable column ----
        inner = ft.Column(
            controls=[
                filters_card,
                self._body_responsive_row,
                buttons,
                status,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        # ---- 17.3.3.4  Dialog clamped to viewport ----
        try:
            vw = self.page.width or 400
        except Exception:
            vw = 400
        try:
            vh = self.page.height or 700
        except Exception:
            vh = 700

        dlg_w = max(320, min(1400, vw - 24))
        dlg_h = max(400, min(800, vh - 60))

        dialog_content = ft.Container(
            content=ft.Column([
                header,
                ft.Container(content=inner, expand=True),
            ], spacing=8, expand=True),
            width=dlg_w,
            height=dlg_h,
            padding=4)

        self.dialog = ft.AlertDialog(
            modal=True,
            title=None,
            content=dialog_content,
            actions=[],
            actions_alignment=ft.MainAxisAlignment.CENTER,
            inset_padding=ft.Padding.symmetric(horizontal=6, vertical=6),
        )

    # =============================================================================
    # 17.3.4 — setup_left_panel
    # PURPOSE
    #   Wrap the column selector tabs in a fixed-height card that
    #   stacks full-width on mobile, sits 380px wide on desktop.
    # =============================================================================
    def setup_left_panel(self):
        column_group_title = ft.Text(
            "📋  Select Columns",
            size=12, weight=ft.FontWeight.BOLD, color="#1e3a8a")
        self.column_group_title = column_group_title

        self.column_tabs = ft.Tabs(
            selected_index=0,
            animation_duration=200,
            length=3,
            expand=True,
            content=ft.Column([
                ft.TabBar(tabs=[
                    ft.Tab(label="👥 Travelers"),
                    ft.Tab(label="📦 Batches"),
                    ft.Tab(label="💰 Payments"),
                ], scrollable=True),
                ft.TabBarView(expand=True, controls=[
                    self.setup_traveler_tab(),
                    self.setup_batch_tab(),
                    self.setup_payment_tab(),
                ]),
            ], expand=True))

        self._left_panel_container = ft.Container(
            content=ft.Column([
                column_group_title,
                ft.Container(
                    content=self.column_tabs,
                    border=ft.Border.all(1, "#e5e7eb"),
                    border_radius=8,
                    expand=True),
            ], spacing=8, expand=True),
            padding=10, bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1.5, "#dbeafe"),
            border_radius=10,
            height=460)
        return self._left_panel_container

    # =============================================================================
    # 17.3.5 — setup_traveler_tab
    # PURPOSE
    #   Build the "Travelers" tab in the column selector with All/Clear
    #   buttons and a scrollable list of checkboxes.
    # =============================================================================
    def setup_traveler_tab(self):
        for k, l in TRAVELER_FIELDS:
            self.traveler_checkboxes[k] = ft.Checkbox(label=l, value=False)

        lv = ft.ListView(expand=True, spacing=2, auto_scroll=False)
        for cb in self.traveler_checkboxes.values():
            lv.controls.append(cb)

        def _all(e):
            for cb in self.traveler_checkboxes.values():
                cb.value = True
            self.page.update()

        def _clear(e):
            for cb in self.traveler_checkboxes.values():
                cb.value = False
            self.page.update()

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Button(content=ft.Text("✓ All", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_all, height=30,
                              bgcolor="#059669", color=ft.Colors.WHITE,
                              expand=True),
                    ft.Button(content=ft.Text("✗ Clear", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_clear, height=30,
                              bgcolor="#dc2626", color=ft.Colors.WHITE,
                              expand=True),
                ], spacing=6),
                lv,
            ], spacing=6, expand=True),
            padding=8, expand=True)

    # =============================================================================
    # 17.3.6 — setup_batch_tab
    # =============================================================================
    def setup_batch_tab(self):
        for k, l in BATCH_FIELDS:
            self.batch_checkboxes[k] = ft.Checkbox(label=l, value=False)

        lv = ft.ListView(expand=True, spacing=2, auto_scroll=False)
        for cb in self.batch_checkboxes.values():
            lv.controls.append(cb)

        def _all(e):
            for cb in self.batch_checkboxes.values():
                cb.value = True
            self.page.update()

        def _clear(e):
            for cb in self.batch_checkboxes.values():
                cb.value = False
            self.page.update()

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Button(content=ft.Text("✓ All", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_all, height=30,
                              bgcolor="#059669", color=ft.Colors.WHITE,
                              expand=True),
                    ft.Button(content=ft.Text("✗ Clear", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_clear, height=30,
                              bgcolor="#dc2626", color=ft.Colors.WHITE,
                              expand=True),
                ], spacing=6),
                lv,
            ], spacing=6, expand=True),
            padding=8, expand=True)

    # =============================================================================
    # 17.3.7 — setup_payment_tab
    # =============================================================================
    def setup_payment_tab(self):
        for k, l in PAYMENT_FIELDS:
            self.payment_checkboxes[k] = ft.Checkbox(label=l, value=False)

        lv = ft.ListView(expand=True, spacing=2, auto_scroll=False)
        for cb in self.payment_checkboxes.values():
            lv.controls.append(cb)

        def _all(e):
            for cb in self.payment_checkboxes.values():
                cb.value = True
            self.page.update()

        def _clear(e):
            for cb in self.payment_checkboxes.values():
                cb.value = False
            self.page.update()

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Button(content=ft.Text("✓ All", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_all, height=30,
                              bgcolor="#059669", color=ft.Colors.WHITE,
                              expand=True),
                    ft.Button(content=ft.Text("✗ Clear", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_clear, height=30,
                              bgcolor="#dc2626", color=ft.Colors.WHITE,
                              expand=True),
                ], spacing=6),
                lv,
            ], spacing=6, expand=True),
            padding=8, expand=True)

    # =============================================================================
    # 17.3.8 — setup_right_panel
    # =============================================================================
    def setup_right_panel(self):
        return ft.Container(
            content=ft.Column([
                self.setup_preview(),
            ], spacing=8, expand=True),
            padding=0, expand=True)

    # =============================================================================
    # 17.3.9 — setup_filters
    # PURPOSE
    #   Build the entire filter bar. Uses ResponsiveRow so each field
    #   wraps to its own row on xs, packs tighter on md and up.
    # =============================================================================
    def setup_filters(self):
        self.report_format_dropdown = ft.Dropdown(
            label="Report Format",
            options=[
                ft.dropdown.Option("summary",
                                   "📋 Traveler Summary"),
                ft.dropdown.Option("ledger",
                                   "🧾 Payment Ledger"),
            ],
            value="summary", text_size=12, content_padding=8)
        self.report_format_dropdown.on_change = self._on_report_format_changed

        self.reg_date_from = ft.TextField(
            label="From",
            value=(datetime.now() - timedelta(days=90)
                   ).strftime("%d/%m/%Y"),
            text_size=12, content_padding=8)
        self.reg_date_to = ft.TextField(
            label="To",
            value=datetime.now().strftime("%d/%m/%Y"),
            text_size=12, content_padding=8)

        self.batch_filter_combo = ft.Dropdown(
            label="Batch",
            options=[ft.dropdown.Option("", "All Batches")],
            value="", text_size=12, content_padding=8)
        try:
            for batch in self.db.get_batches():
                self.batch_filter_combo.options.append(
                    ft.dropdown.Option(
                        batch['id'],
                        batch.get('batch_name', 'Unknown')[:30]))
        except Exception:
            pass

        self.status_filter = ft.Dropdown(
            label="Traveler Status",
            options=[ft.dropdown.Option(x) for x in
                     ["All", "Active", "Inactive", "Completed"]],
            value="All", text_size=12, content_padding=8)

        self.payment_method_filter = ft.Dropdown(
            label="Method",
            options=[ft.dropdown.Option(x) for x in
                     ["All", "Bank Transfer", "Cash", "Card", "UPI",
                      "Cheque", "NEFT", "RTGS", "IMPS"]],
            value="All", text_size=12, content_padding=8)

        self.payment_status_filter = ft.Dropdown(
            label="Pay Status",
            options=[ft.dropdown.Option(x) for x in
                     ["All", "completed", "pending", "failed", "refunded"]],
            value="All", text_size=12, content_padding=8)

        self.min_amount_input = ft.TextField(
            label="Min ₹", text_size=12, content_padding=8)
        self.max_amount_input = ft.TextField(
            label="Max ₹", text_size=12, content_padding=8)

        def _quick(days):
            def _h(e):
                self.reg_date_from.value = (
                    datetime.now() - timedelta(days=days)
                ).strftime("%d/%m/%Y")
                self.reg_date_to.value = datetime.now().strftime("%d/%m/%Y")
                self.generate_preview(None)
            return _h

        def _qbtn(label, days):
            return ft.Button(
                content=ft.Text(label, size=10),
                on_click=_quick(days), height=32,
                bgcolor="#e0f2fe", color="#0369a1")

        row1 = ft.ResponsiveRow(
            controls=[
                ft.Container(content=self.report_format_dropdown,
                             col={"xs": 12, "sm": 6, "md": 4}),
                ft.Container(content=self.reg_date_from,
                             col={"xs": 6, "sm": 3, "md": 2}),
                ft.Container(content=self.reg_date_to,
                             col={"xs": 6, "sm": 3, "md": 2}),
            ], spacing=8, run_spacing=8)

        quick_btns = ft.Row([
            _qbtn("Today", 0), _qbtn("Week", 7),
            _qbtn("Month", 30), _qbtn("3M", 90),
        ], spacing=6, wrap=True)

        row2 = ft.ResponsiveRow(
            controls=[
                ft.Container(content=self.batch_filter_combo,
                             col={"xs": 6, "sm": 4, "md": 3}),
                ft.Container(content=self.status_filter,
                             col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(content=self.payment_method_filter,
                             col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(content=self.payment_status_filter,
                             col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(content=self.min_amount_input,
                             col={"xs": 6, "sm": 3, "md": 1}),
                ft.Container(content=self.max_amount_input,
                             col={"xs": 6, "sm": 3, "md": 1}),
            ], spacing=8, run_spacing=8)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("🔍", size=14),
                    ft.Text("Filters", size=12,
                            weight=ft.FontWeight.BOLD, color="#1e3a8a"),
                ], spacing=6),
                row1,
                quick_btns,
                row2,
            ], spacing=8),
            padding=10, bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, "#dbeafe"),
            border_radius=10)

    # =============================================================================
    # 17.3.9b — _on_report_format_changed
    # =============================================================================
    def _on_report_format_changed(self, e=None):
        try:
            mode = self.report_format_dropdown.value or "summary"
            self.current_report_mode = mode
            if mode == 'ledger':
                self.column_group_title.value = (
                    "📋  Columns (auto-managed)")
                self.column_group_title.color = "#6b7280"
            else:
                self.column_group_title.value = (
                    "📋  Select Columns")
                self.column_group_title.color = "#1e3a8a"
            self.page.update()
        except Exception as ex:
            print(f"[CR] _on_report_format_changed error: {ex}")

    # =============================================================================
    # 17.3.10 — setup_preview   (MOBILE-RESPONSIVE: shorter height)
    # PURPOSE
    #   Build the preview area with horizontal scroll. Height is
    #   smaller on mobile (220px) than desktop (380px).
    # =============================================================================
    def setup_preview(self):
        pw = self.page.width or 1000
        PREVIEW_H = 220 if pw < 700 else 380

        self.preview_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("Preview", size=11,
                                           weight=ft.FontWeight.BOLD,
                                           color=ft.Colors.WHITE))],
            rows=[],
            heading_row_color="#1e293b",
            column_spacing=14,
            data_row_min_height=42,
            data_row_max_height=64)

        inner_col = ft.Column(
            controls=[self.preview_table],
            scroll=ft.ScrollMode.ALWAYS,
            auto_scroll=False, expand=True)

        self._preview_inner = ft.Container(
            content=inner_col, width=900, height=PREVIEW_H,
            clip_behavior=ft.ClipBehavior.HARD_EDGE)

        self._preview_hview = ft.ListView(
            controls=[self._preview_inner], horizontal=True,
            scroll=ft.ScrollMode.ALWAYS, height=PREVIEW_H,
            spacing=0, padding=0, auto_scroll=False)

        self._preview_body = ft.Container(
            content=self._preview_hview, height=PREVIEW_H,
            bgcolor="#f9fafb", border=ft.Border.all(1, "#cbd5e1"),
            border_radius=8, padding=0,
            clip_behavior=ft.ClipBehavior.HARD_EDGE, expand=True)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("📄", size=14),
                    ft.Text("Report Preview", size=12,
                            weight=ft.FontWeight.BOLD, color="#1e3a8a"),
                    ft.Container(expand=True),
                    ft.Text("↔ scroll", size=9,
                            color=ft.Colors.GREY_500, italic=True),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self._preview_body,
            ], spacing=8, expand=True),
            padding=10, bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, "#dbeafe"),
            border_radius=10, expand=True)

    # =============================================================================
    # 17.3.11 — setup_buttons   (MOBILE-RESPONSIVE: 2 per row on xs)
    # =============================================================================
    def setup_buttons(self):
        def _btn(label, icon, color, handler):
            return ft.Button(
                content=ft.Row([
                    ft.Icon(icon, size=14, color=ft.Colors.WHITE),
                    ft.Text(label, size=11, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=6, tight=True),
                on_click=handler, height=40, bgcolor=color)

        items = [
            (_btn("Generate", ft.Icons.REFRESH, "#2563eb",
                  self.generate_preview), 6),
            (_btn("Reload CSV", ft.Icons.DOWNLOAD, "#0ea5e9",
                  self._force_reload_csv), 6),
            (_btn("Diagnose", ft.Icons.BUG_REPORT, "#f59e0b",
                  self._diagnose), 6),
            (_btn("Reorder", ft.Icons.SORT, "#7c3aed",
                  self.open_column_ordering_dialog), 6),
            (_btn("Excel", ft.Icons.TABLE_CHART, "#059669",
                  self.export_to_excel), 6),
            (_btn("CSV", ft.Icons.DESCRIPTION, "#0891b2",
                  self.export_to_csv), 6),
            (_btn("PDF", ft.Icons.PICTURE_AS_PDF, "#dc2626",
                  self.export_to_pdf), 6),
        ]

        controls = [
            ft.Container(content=item[0],
                         col={"xs": item[1], "sm": item[1], "md": 2})
            for item in items
        ]
        close_btn = ft.Container(
            content=ft.TextButton(content=ft.Text("Close", size=11),
                                  on_click=lambda e: self.reject()),
            col={"xs": 12, "sm": 6, "md": 2})

        return ft.ResponsiveRow(
            controls=controls + [close_btn],
            spacing=6, run_spacing=6)

    # =============================================================================
    # 17.3.12 — setup_status
    # =============================================================================
    def setup_status(self):
        self.status_icon = ft.Text("✅", size=13)
        self.status_label = ft.Text(
            "Ready. Pick format & click Generate",
            size=11, color="#059669", weight=ft.FontWeight.BOLD,
            max_lines=2, no_wrap=False)
        self.record_count_label = ft.Text(
            "", size=10, color="#6b7280")

        return ft.Container(
            content=ft.Row([
                self.status_icon,
                ft.Container(content=self.status_label, expand=True),
                self.record_count_label,
            ], spacing=6),
            padding=8, bgcolor="#f9fafb",
            border=ft.Border.all(1, "#e5e7eb"),
            border_radius=8)

    # =============================================================================
    # 17.3.13 — create_checkbox_group
    # =============================================================================
    def create_checkbox_group(self, items):
        return {k: ft.Checkbox(label=l, value=False) for k, l in items}

    # =============================================================================
    # 17.3.14 — select_all_checkboxes
    # =============================================================================
    def select_all_checkboxes(self, checkboxes, select):
        if isinstance(checkboxes, dict):
            for cb in checkboxes.values():
                cb.value = select
        else:
            for cb in checkboxes:
                cb.value = select
        try:
            self.page.update()
        except Exception:
            pass

    # =============================================================================
    # 17.3.15 — get_selected_columns
    # PURPOSE
    #   Return the list of {key, label, source} for every checked box
    #   across the three column tabs.
    # =============================================================================
    def get_selected_columns(self):
        selected = []
        for k, cb in self.traveler_checkboxes.items():
            if cb.value:
                label = next(l for kk, l in TRAVELER_FIELDS if kk == k)
                selected.append({'key': k, 'label': label,
                                 'source': 'traveler'})
        for k, cb in self.batch_checkboxes.items():
            if cb.value:
                label = next(l for kk, l in BATCH_FIELDS if kk == k)
                selected.append({'key': k, 'label': label,
                                 'source': 'batch'})
        for k, cb in self.payment_checkboxes.items():
            if cb.value:
                label = next(l for kk, l in PAYMENT_FIELDS if kk == k)
                selected.append({'key': k, 'label': label,
                                 'source': 'payment'})
        return selected

    # =============================================================================
    # 17.3.16 — date quick filter handlers
    # =============================================================================
    def set_date_today(self):
        self.reg_date_from.value = datetime.now().strftime("%d/%m/%Y")
        self.reg_date_to.value = datetime.now().strftime("%d/%m/%Y")
        self.generate_preview(None)

    def set_date_this_week(self):
        today = datetime.now()
        start = today - timedelta(days=today.weekday())
        self.reg_date_from.value = start.strftime("%d/%m/%Y")
        self.reg_date_to.value = today.strftime("%d/%m/%Y")
        self.generate_preview(None)

    def set_date_this_month(self):
        today = datetime.now()
        self.reg_date_from.value = today.replace(day=1).strftime("%d/%m/%Y")
        self.reg_date_to.value = today.strftime("%d/%m/%Y")
        self.generate_preview(None)

    def set_date_last_month(self):
        today = datetime.now()
        first_this = today.replace(day=1)
        last_last = first_this - timedelta(days=1)
        self.reg_date_from.value = last_last.replace(
            day=1).strftime("%d/%m/%Y")
        self.reg_date_to.value = last_last.strftime("%d/%m/%Y")
        self.generate_preview(None)

    def set_date_this_year(self):
        today = datetime.now()
        self.reg_date_from.value = today.replace(
            month=1, day=1).strftime("%d/%m/%Y")
        self.reg_date_to.value = today.replace(
            month=12, day=31).strftime("%d/%m/%Y")
        self.generate_preview(None)

    def set_date_default(self):
        today = datetime.now()
        self.reg_date_from.value = (
            today - timedelta(days=90)).strftime("%d/%m/%Y")
        self.reg_date_to.value = today.strftime("%d/%m/%Y")
        self.generate_preview(None)

    # =============================================================================
    # 17.3.17 — open_column_ordering_dialog
    # =============================================================================
    def open_column_ordering_dialog(self, e=None):
        if self.current_report_mode == 'ledger':
            self._snack("ℹ️ In Payment Ledger mode, columns are managed "
                        "automatically.", "#3b82f6")
            return
        if self.selected_columns:
            selected = self.selected_columns
        else:
            selected = self.get_selected_columns()
        if not selected:
            self._snack("⚠️ Please select columns first.", "#dc2626")
            return

        def _apply(new_order):
            self.selected_columns = new_order
            self._column_order = {
                (c["key"], c.get("dyn_index")): i
                for i, c in enumerate(new_order)
            }
            if self.report_data:
                self.display_preview(new_order, self.report_data)
            self._snack("✅ Column order updated!", "#059669")

        ColumnOrderDialog(self.page, selected, _apply).show()

    # =============================================================================
    # 17.3.18 — load_data_preview   (FIX-CSV-AUTHORITY)
    # PURPOSE
    #   Initial data load. Chooses between DB memory and CSV file by
    #   row count (CSV is authoritative if it has more rows).
    # =============================================================================
    def load_data_preview(self):
        try:
            for mn in ("reload_payments", "refresh_payments",
                       "_reload_payments", "load_payments",
                       "reload_all", "_load_all"):
                if hasattr(self.db, mn):
                    try:
                        getattr(self.db, mn)()
                    except Exception:
                        pass

            self.traveler_data = self.db.get_travelers()
            self.batch_data = {b['id']: b for b in self.db.get_batches()}

            try:
                db_payments = list(self.db.get_payments() or [])
            except Exception:
                db_payments = []

            print("[CR] ─── payment source check ───")
            print(f"[CR]   DB  → {len(db_payments)} rows")

            candidates = []
            if hasattr(self.db, "data_dir"):
                try:
                    candidates.append(
                        os.path.join(str(self.db.data_dir),
                                     "payments.csv"))
                except Exception:
                    pass
            base = self.get_app_base_path()
            candidates.extend([
                os.path.join(base, "data", "payments.csv"),
                os.path.join(base, "payments.csv"),
            ])

            best_rows = db_payments
            best_src = f"DB ({len(db_payments)} rows)"
            seen = set()
            for cp in candidates:
                if not cp or cp in seen:
                    continue
                seen.add(cp)
                if not os.path.exists(cp):
                    print(f"[CR]   CSV not found: {cp}")
                    continue
                try:
                    with open(cp, "r", encoding="utf-8-sig") as f:
                        disk_rows = list(csv.DictReader(f))
                    print(f"[CR]   CSV {cp} → {len(disk_rows)} rows")
                    if len(disk_rows) > len(best_rows):
                        best_rows = disk_rows
                        best_src = f"CSV {cp} ({len(disk_rows)} rows)"
                except Exception as e:
                    print(f"[CR]   CSV read error {cp}: {e}")

            self.payment_data = best_rows
            self._last_payment_source = best_src
            print(f"[CR]   ✔ USING → {best_src}")
            print("[CR] ──────────────────────────")

            self.invoice_lookup = {
                str(i['id']).strip(): i for i in self.db.get_invoices()
            }
            self._load_live_tax_rates()
            self._refresh_invoice_caches()

            try:
                self.batch_filter_combo.options = [
                    ft.dropdown.Option("", "All Batches")]
                for batch in self.db.get_batches():
                    self.batch_filter_combo.options.append(
                        ft.dropdown.Option(
                            batch['id'],
                            batch.get('batch_name', 'Unknown')[:30]))
            except Exception:
                pass
        except Exception as e:
            print(f"[CR] Error loading data: {e}")
            traceback.print_exc()

    # =============================================================================
    # 17.3.18b — _force_reload_csv
    # PURPOSE
    #   Force a fresh read of payments.csv and regenerate the preview.
    # =============================================================================
    def _force_reload_csv(self, e=None):
        try:
            print("[CR] 🔃 FORCE RELOAD from CSV …")

            try:
                if hasattr(self.db, "reload_all"):
                    self.db.reload_all()
            except Exception as ex:
                print(f"[CR] db.reload_all failed: {ex}")

            self.traveler_data = self.db.get_travelers()
            self.batch_data = self.db.get_batches()

            base = self.get_app_base_path()
            candidates = []
            if hasattr(self.db, "data_dir"):
                try:
                    candidates.append(
                        os.path.join(str(self.db.data_dir),
                                     "payments.csv"))
                except Exception:
                    pass
            candidates.extend([
                os.path.join(base, "data", "payments.csv"),
                os.path.join(base, "payments.csv"),
            ])

            best_rows = None
            best_path = None
            for cp in candidates:
                if not os.path.exists(cp):
                    continue
                try:
                    with open(cp, "r", encoding="utf-8-sig") as f:
                        rows = list(csv.DictReader(f))
                    print(f"[CR] FORCE: {cp} → {len(rows)} rows")
                    if best_rows is None or len(rows) > len(best_rows):
                        best_rows = rows
                        best_path = cp
                except Exception as ex:
                    print(f"[CR] FORCE read error {cp}: {ex}")

            if best_rows is not None:
                self.payment_data = best_rows
                self._last_payment_source = (
                    f"CSV {best_path} ({len(best_rows)} rows) [FORCE]")
            self._refresh_invoice_caches()
            self.generate_preview(None)
            self._snack(f"✅ Loaded {len(self.payment_data)} payments "
                        f"from CSV", "#059669")
        except Exception as ex:
            traceback.print_exc()
            self._snack(f"❌ Force reload failed: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.18c — _diagnose
    # PURPOSE
    #   Dump the payment source and per-traveler counts to stdout so
    #   the user can debug why a report is empty.
    # =============================================================================
    def _diagnose(self, e=None):
        try:
            print("[CR] ============ DIAGNOSTICS ============")
            print(f"[CR] Payment source  : {self._last_payment_source}")
            print(f"[CR] Travelers loaded: {len(self.traveler_data)}")
            print(f"[CR] Payments loaded : {len(self.payment_data)}")
            print(f"[CR] Batches loaded  : {len(self.batch_data)}")

            counts = {}
            for p in self.payment_data:
                tid = p.get("traveler_id", "?")
                counts[tid] = counts.get(tid, 0) + 1

            top = sorted(counts.items(), key=lambda x: -x[1])[:20]
            print("[CR] --- Top travelers by raw payment count ---")
            for tid, c in top:
                print(f"[CR]   {tid}: {c} payment(s)")

            meera = counts.get("HAJ/TRV/2027/002", 0)
            print(f"[CR] Meera HAJ/TRV/2027/002 → {meera} payments")

            print("[CR] Meera's payment rows:")
            for p in self.payment_data:
                if p.get("traveler_id") == "HAJ/TRV/2027/002":
                    print(f"[CR]   {p.get('id')} | "
                          f"{p.get('payment_date')} | "
                          f"₹{p.get('amount')} | {p.get('status')}")
            print("[CR] =======================================")

            self._snack(f"Source: {self._last_payment_source}", "#2563eb")
        except Exception as ex:
            traceback.print_exc()
            self._snack(f"❌ Diagnose failed: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.19 — generate_preview   (FIX-FRESH-DATA preserved)
    # PURPOSE
    #   Main entry point for report generation. Reloads payments +
    #   invoices from the DB, then either generates the summary (with
    #   column picker) or delegates to ledger generation.
    # =============================================================================
    def generate_preview(self, e=None):
        try:
            try:
                if hasattr(self.db, "reload_payments"):
                    self.db.reload_payments()
                if hasattr(self.db, "reload_invoices"):
                    self.db.reload_invoices()
                if hasattr(self.db, "reload_travelers"):
                    self.db.reload_travelers()
            except Exception as ex:
                print(f"[CR] reload failed: {ex}")

            self.traveler_data = self.db.get_travelers()
            self.batch_data = {b['id']: b for b in self.db.get_batches()}
            self.payment_data = list(self.db.get_payments() or [])
            self.invoice_lookup = {
                str(i['id']).strip(): i for i in self.db.get_invoices()
            }

            self._load_live_tax_rates()
            self._refresh_invoice_caches()
        except Exception as ex:
            print(f"[CR] generate_preview refresh failed: {ex}")

        mode = (self.report_format_dropdown.value
                if self.report_format_dropdown else "summary") or "summary"
        self.current_report_mode = mode

        if mode == 'ledger':
            try:
                self._generate_ledger_preview()
            except Exception as ex:
                traceback.print_exc()
                self._set_status("❌", f"Error: {ex}", "#dc2626")
                self._snack(f"Could not generate report: {ex}", "#dc2626")
            return

        selected = self.get_selected_columns()
        if not selected:
            self._set_status("⚠️",
                             "Please select at least one column",
                             "#dc2626")
            self._snack("Please select at least one column for the report.",
                        "#dc2626")
            return

        try:
            batch_filter = (self.batch_filter_combo.value
                            if self.batch_filter_combo else "")
            traveler_status_filter = (
                self.status_filter.value if self.status_filter else "All")
            payment_status_filter = (
                self.payment_status_filter.value
                if self.payment_status_filter else "All")
            payment_method_filter = (
                self.payment_method_filter.value
                if self.payment_method_filter else "All")

            d_from = _parse_ui_date(self.reg_date_from.value
                                    if self.reg_date_from else "")
            d_to = _parse_ui_date(self.reg_date_to.value
                                  if self.reg_date_to else "")

            try:
                min_amt = float((self.min_amount_input.value
                                 if self.min_amount_input else "") or 0)
            except ValueError:
                min_amt = 0.0
            try:
                max_amt = float((self.max_amount_input.value
                                 if self.max_amount_input else "") or 0) \
                    or float('inf')
            except ValueError:
                max_amt = float('inf')

            self._set_status("⏳", "Generating report...", "#d97706")

            traveler_cols = [c for c in selected
                             if c['source'] == 'traveler']
            batch_cols = [c for c in selected if c['source'] == 'batch']
            payment_cols = [c for c in selected if c['source'] == 'payment']
            has_payment_cols = len(payment_cols) > 0

            # ---- Filter travelers ----
            filtered_travelers = []
            for traveler in self.traveler_data:
                try:
                    rd = _parse_ui_date(traveler.get('registration_date'))
                    if rd is not None:
                        if d_from is not None and rd < d_from:
                            continue
                        if d_to is not None and rd > d_to:
                            continue
                    if batch_filter and traveler.get(
                            'batch_id') != batch_filter:
                        continue
                    if traveler_status_filter != "All":
                        if (traveler.get('status', 'Active')
                                != traveler_status_filter):
                            continue

                    if has_payment_cols:
                        _pays = [p for p in self.payment_data
                                 if p.get('traveler_id')
                                 == traveler.get('id')]
                        if payment_status_filter != "All":
                            _pays = [p for p in _pays
                                     if p.get('status')
                                     == payment_status_filter]
                        if payment_method_filter != "All":
                            _pays = [p for p in _pays
                                     if p.get('payment_method')
                                     == payment_method_filter]
                        _pays = [p for p in _pays
                                 if min_amt <= float(
                                     p.get('amount', 0) or 0) <= max_amt]
                        if not _pays:
                            continue

                    filtered_travelers.append(traveler)
                except Exception as ex:
                    print(f"[CR] Error filtering traveler: {ex}")

            # ---- Determine how many payment slots are needed ----
            max_slots = 0
            if has_payment_cols:
                for traveler in filtered_travelers:
                    pays = [p for p in self.payment_data
                            if p.get('traveler_id') == traveler.get('id')]
                    if payment_status_filter != "All":
                        pays = [p for p in pays
                                if p.get('status')
                                == payment_status_filter]
                    if payment_method_filter != "All":
                        pays = [p for p in pays
                                if p.get('payment_method')
                                == payment_method_filter]
                    pays = [p for p in pays
                            if min_amt <= float(
                                p.get('amount', 0) or 0) <= max_amt]
                    if len(pays) > max_slots:
                        max_slots = len(pays)
                if max_slots > self.HARD_CAP:
                    max_slots = self.HARD_CAP
                if max_slots < 1:
                    max_slots = 1

            # ---- Classify payment columns ----
            slot_source_fields = [
                pf for pf in payment_cols
                if not pf['key'].startswith('__sum_')
                and not pf['key'].startswith('__dyn_')
                and not pf['key'].startswith('__inv_paid_')
            ]
            dyn_fields = [
                pf for pf in payment_cols
                if pf['key'].startswith('__dyn_')
            ]
            summary_fields = [
                pf for pf in payment_cols
                if pf['key'].startswith('__sum_')
            ]
            snapshot_fields = [
                pf for pf in payment_cols
                if pf['key'].startswith('__inv_paid_')
            ]

            # ---- Expand dynamic columns ----
            dynamic_payment_cols = []
            if has_payment_cols:
                for slot in range(1, max_slots + 1):
                    for pf in slot_source_fields:
                        dynamic_payment_cols.append({
                            'key': f'__pay{slot}_{pf["key"]}',
                            'label': f'Payment {slot} {pf["label"]}',
                            'source': 'payment_slot',
                            'orig_key': pf['key'],
                            'slot': slot,
                        })
                for slot in range(1, max_slots + 1):
                    for pf in dyn_fields:
                        dynamic_payment_cols.append({
                            'key': pf['key'],
                            'label': _dyn_label(pf['key'], slot),
                            'source': 'payment_dyn',
                            'dyn_index': slot - 1,
                        })
                for sf in summary_fields:
                    dynamic_payment_cols.append({
                        'key': sf['key'],
                        'label': sf['label'],
                        'source': 'payment_summary',
                    })
                for sf in snapshot_fields:
                    dynamic_payment_cols.append({
                        'key': sf['key'],
                        'label': sf['label'],
                        'source': 'invoice_snapshot',
                    })

            final_columns = (traveler_cols + batch_cols
                             + dynamic_payment_cols)

            # ---- Build rows ----
            report_data = []
            batch_lookup = {b['id']: b for b in self.db.get_batches()}
            for traveler in filtered_travelers:
                try:
                    batch = batch_lookup.get(traveler.get('batch_id'))
                    pays = [p for p in self.payment_data
                            if p.get('traveler_id') == traveler.get('id')]
                    if payment_status_filter != "All":
                        pays = [p for p in pays
                                if p.get('status')
                                == payment_status_filter]
                    if payment_method_filter != "All":
                        pays = [p for p in pays
                                if p.get('payment_method')
                                == payment_method_filter]
                    pays = [p for p in pays
                            if min_amt <= float(
                                p.get('amount', 0) or 0) <= max_amt]
                    pays_sorted = sorted(
                        pays,
                        key=lambda p: str(p.get('payment_date', '') or ''))
                    row = self._build_row_wide(
                        traveler_cols=traveler_cols,
                        batch_cols=batch_cols,
                        payment_cols=payment_cols,
                        traveler=traveler,
                        batch=batch,
                        payments=pays_sorted,
                        max_slots=max_slots)
                    report_data.append(row)
                except Exception as ex:
                    print(f"[CR] Error building row: {ex}")
                    continue

            self.report_data = report_data
            self.selected_columns = final_columns
            self.display_preview(final_columns, report_data)

            if has_payment_cols:
                self._set_status(
                    "✅",
                    f"Traveler Summary — {max_slots} payment slot(s)",
                    "#059669")
            else:
                self._set_status("✅",
                                 "Traveler Summary generated!",
                                 "#059669")
            if self.record_count_label:
                self.record_count_label.value = (
                    f"📊 {len(report_data)} travelers | "
                    f"{len(final_columns)} cols")
            try:
                self.page.update()
            except Exception:
                pass
        except Exception as ex:
            traceback.print_exc()
            self._set_status("❌", f"Error: {ex}", "#dc2626")
            self._snack(f"Could not generate report: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.19b — _generate_ledger_preview
    # PURPOSE
    #   Alternate flow: one row per payment (flattened). Filters apply
    #   to both payment and traveler sides. Auto-managed columns.
    # =============================================================================
    def _generate_ledger_preview(self):
        try:
            batch_filter = (self.batch_filter_combo.value
                            if self.batch_filter_combo else "")
            traveler_status_filter = (
                self.status_filter.value if self.status_filter else "All")
            payment_status_filter = (
                self.payment_status_filter.value
                if self.payment_status_filter else "All")
            payment_method_filter = (
                self.payment_method_filter.value
                if self.payment_method_filter else "All")

            d_from = _parse_ui_date(self.reg_date_from.value
                                    if self.reg_date_from else "")
            d_to = _parse_ui_date(self.reg_date_to.value
                                  if self.reg_date_to else "")

            try:
                min_amt = float((self.min_amount_input.value
                                 if self.min_amount_input else "") or 0)
            except ValueError:
                min_amt = 0.0
            try:
                max_amt = float((self.max_amount_input.value
                                 if self.max_amount_input else "") or 0) \
                    or float('inf')
            except ValueError:
                max_amt = float('inf')

            self._set_status("⏳", "Generating payment ledger...", "#d97706")

            traveler_lookup = {t['id']: t for t in self.traveler_data}
            batch_lookup = {b['id']: b for b in self.db.get_batches()}

            total_paid_by_traveler = {}
            for p in self.payment_data:
                tid = p.get('traveler_id')
                if tid:
                    try:
                        total_paid_by_traveler[tid] = (
                            total_paid_by_traveler.get(tid, 0.0)
                            + float(p.get('amount', 0) or 0))
                    except (TypeError, ValueError):
                        pass

            filtered_payments = []
            for p in self.payment_data:
                try:
                    pd = _parse_ui_date(p.get('payment_date'))
                    if pd is not None:
                        if d_from is not None and pd < d_from:
                            continue
                        if d_to is not None and pd > d_to:
                            continue
                    if payment_status_filter != "All":
                        if p.get('status') != payment_status_filter:
                            continue
                    if payment_method_filter != "All":
                        if p.get('payment_method') != payment_method_filter:
                            continue
                    amt = float(p.get('amount', 0) or 0)
                    if amt < min_amt or amt > max_amt:
                        continue
                    traveler = traveler_lookup.get(p.get('traveler_id'))
                    if not traveler:
                        continue
                    if batch_filter and traveler.get(
                            'batch_id') != batch_filter:
                        continue
                    if traveler_status_filter != "All":
                        if (traveler.get('status', 'Active')
                                != traveler_status_filter):
                            continue
                    filtered_payments.append(p)
                except Exception as ex:
                    print(f"[CR] Error filtering payment: {ex}")

            filtered_payments.sort(
                key=lambda p: (str(p.get('payment_date', '') or ''),
                               str(p.get('id', '') or '')))

            ledger_columns = [
                {'key': '__ledger_payment_date',
                 'label': 'Payment Date', 'source': 'payment'},
                {'key': '__ledger_receipt_no',
                 'label': 'Receipt No', 'source': 'payment'},
                {'key': '__ledger_traveler',
                 'label': 'Traveler', 'source': 'traveler'},
                {'key': '__ledger_batch',
                 'label': 'Batch', 'source': 'batch'},
                {'key': '__ledger_invoice_no',
                 'label': 'Invoice No', 'source': 'payment'},
                {'key': '__ledger_method',
                 'label': 'Method', 'source': 'payment'},
                {'key': '__ledger_txn_id',
                 'label': 'Transaction ID', 'source': 'payment'},
                {'key': '__ledger_status',
                 'label': 'Status', 'source': 'payment'},
                {'key': '__ledger_amount',
                 'label': 'Payment Amount', 'source': 'payment'},
                {'key': '__ledger_base',
                 'label': 'Invoice Base', 'source': 'payment'},
                {'key': '__ledger_gst',
                 'label': 'GST Amount', 'source': 'payment'},
                {'key': '__ledger_tcs',
                 'label': 'TCS Amount', 'source': 'payment'},
                {'key': '__ledger_total_with_tax',
                 'label': 'Total (with Tax)', 'source': 'payment'},
                {'key': '__ledger_outstanding',
                 'label': 'Outstanding Balance', 'source': 'payment'},
            ]

            report_data = []
            for p in filtered_payments:
                traveler = traveler_lookup.get(p.get('traveler_id'))
                if not traveler:
                    continue
                batch = batch_lookup.get(traveler.get('batch_id'))
                tid = traveler.get('id')

                share = self._get_payment_share(p, tid)

                try:
                    amt_raw = float(p.get('amount', 0) or 0)
                except (TypeError, ValueError):
                    amt_raw = 0.0

                traveler_entry = self.traveler_invoice_data.get(tid, {})
                has_paid_inv = bool(
                    traveler_entry.get('has_paid_invoice', False))

                if has_paid_inv:
                    outstanding = 0.0
                else:
                    total_invoice = traveler_entry.get('total_amount', 0.0)
                    total_paid = total_paid_by_traveler.get(tid, 0.0)
                    outstanding = max(0.0, total_invoice - total_paid)

                traveler_name = (
                    traveler.get('passport_name')
                    or f"{traveler.get('first_name', '')} "
                       f"{traveler.get('last_name', '')}".strip()
                    or traveler.get('id', '')
                )

                row = {
                    'Payment Date':
                        self.format_date_to_ddmmyyyy(
                            p.get('payment_date', '')),
                    'Receipt No':
                        str(p.get('id', '') or ''),
                    'Traveler':
                        traveler_name,
                    'Batch':
                        (batch.get('batch_name') if batch else '—'),
                    'Invoice No':
                        str(p.get('invoice_id', '') or ''),
                    'Method':
                        str(p.get('payment_method', '') or ''),
                    'Transaction ID':
                        self.convert_scientific_to_number(
                            p.get('transaction_id', '')),
                    'Status':
                        str(p.get('status', '') or ''),
                    'Payment Amount':
                        f"₹{_fmt_inr_(amt_raw)}",
                    'Invoice Base':
                        f"₹{_fmt_inr_(share['base'])}",
                    'GST Amount':
                        f"₹{_fmt_inr_(share['gst'])}",
                    'TCS Amount':
                        f"₹{_fmt_inr_(share['tcs'])}",
                    'Total (with Tax)':
                        f"₹{_fmt_inr_(share['taxable'] + share['gst'] + share['tcs'])}",
                    'Outstanding Balance':
                        f"₹{_fmt_inr_(outstanding)}",
                }
                report_data.append(row)

            self.report_data = report_data
            self.selected_columns = ledger_columns
            self.display_preview(ledger_columns, report_data)

            self._set_status(
                "✅",
                f"Payment Ledger — {len(report_data)} row(s)",
                "#059669")
            if self.record_count_label:
                self.record_count_label.value = (
                    f"🧾 {len(report_data)} payments")
            try:
                self.page.update()
            except Exception:
                pass

        except Exception as ex:
            traceback.print_exc()
            self._set_status("❌", f"Ledger error: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.20 — _build_row_wide
    # PURPOSE
    #   Flatten one traveler + its batch + its payments into a single
    #   dict keyed by column label. Handles:
    #     • traveler-side fields (dates, aadhaar grouping, photos)
    #     • batch-side fields (name, dates, price)
    #     • dynamic payment slots (Payment 1, Payment 2, ...)
    #     • summary totals (Total Paid, GST, Outstanding, etc.)
    #     • invoice snapshots for paid invoices
    # =============================================================================
    def _build_row_wide(self, traveler_cols, batch_cols, payment_cols,
                        traveler, batch, payments, max_slots):
        row = {}

        def _resolve_batch_name(traveler, batch):
            if batch:
                try:
                    name = batch.get('batch_name', '')
                    if name is not None:
                        name = str(name).strip()
                        if name and name.lower() not in ('nan', 'none'):
                            return name
                except Exception:
                    pass
            try:
                bid = (traveler.get('batch_id') or '').strip()
                if bid:
                    for b in self.db.get_batches():
                        if str(b.get('id', '')).strip() == bid:
                            n = b.get('batch_name', '')
                            if n is not None:
                                n = str(n).strip()
                                if n and n.lower() not in ('nan', 'none'):
                                    return n
            except Exception:
                pass
            return '—'

        path_columns = ['passport_scan', 'aadhaar_scan', 'pan_scan',
                        'vaccine_scan', 'photo']

        for col in traveler_cols:
            key = col['key']
            label = col['label']

            if key == 'batch_name':
                row[label] = _resolve_batch_name(traveler, batch)
                continue

            value = traveler.get(key, '')

            if key == 'photo':
                photo_path = self.get_photo_path(traveler)
                value = photo_path if photo_path else ''
            elif key in path_columns:
                value = '' if value is None else str(value).strip()
            elif key == 'aadhaar':
                if value is None:
                    value = ''
                else:
                    v = str(value).strip()
                    if v and v not in ['', 'nan', 'None', 'null']:
                        digits = ''.join(c for c in v if c.isdigit())
                        if len(digits) == 12:
                            value = f"{digits[:4]} {digits[4:8]} {digits[8:]}"
                        else:
                            value = v
                    else:
                        value = ''
            elif key in ['dob', 'registration_date',
                         'passport_issue_date', 'passport_expiry_date',
                         'expected_return_date']:
                try:
                    sval = str(value) if value else ''
                    value = (self.format_date_to_ddmmyyyy(sval)
                             if sval else '')
                except Exception:
                    value = ''
            else:
                value = self.safe_str(value)
            row[label] = value

        for col in batch_cols:
            key = col['key']
            label = col['label']
            if not batch:
                row[label] = 'No Batch'
                continue
            if key in ['departure_date', 'return_date']:
                sval = self.safe_str(batch.get(key, ''))
                row[label] = (self.format_date_to_ddmmyyyy(sval)
                              if sval else '')
            elif key == 'price':
                price = batch.get('price', 0)
                try:
                    row[label] = f"₹{_fmt_inr_(float(price))}"
                except Exception:
                    row[label] = f"₹{price}"
            else:
                row[label] = self.safe_str(batch.get(key, ''))

        traveler_id = traveler.get('id')
        base_total = 0.0
        discount_total = 0.0
        taxable_total = 0.0
        gst_total = 0.0
        tcs_total = 0.0
        total_share_total = 0.0
        running_paid_per_invoice = {}

        for p in payments:
            inv_obj = self._resolve_invoice_for_payment(p, traveler_id)
            inv_key = id(inv_obj) if inv_obj is not None else None
            try:
                amt = float(p.get('amount', 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if inv_obj is not None and inv_obj['base'] > 0:
                running = running_paid_per_invoice.get(inv_key, 0.0)
                remaining = max(0.0, inv_obj['base'] - running)
                effective_amt = min(amt, remaining)
                running_paid_per_invoice[inv_key] = running + effective_amt
            else:
                effective_amt = amt
            temp_p = dict(p)
            temp_p['amount'] = effective_amt
            share = self._get_payment_share(temp_p, traveler_id)
            base_total        += share['base']
            discount_total    += share['discount_amount']
            taxable_total     += share['taxable']
            gst_total         += share['gst']
            tcs_total         += share['tcs']
            total_share_total += share['total']

        if payment_cols:
            slot_fields = [
                pf for pf in payment_cols
                if not pf['key'].startswith('__sum_')
                and not pf['key'].startswith('__dyn_')
                and not pf['key'].startswith('__inv_paid_')
            ]
            dyn_fields = [
                pf for pf in payment_cols
                if pf['key'].startswith('__dyn_')
            ]

            for slot in range(1, max_slots + 1):
                idx = slot - 1
                for pf in slot_fields:
                    label = f"Payment {slot} {pf['label']}"
                    if idx < len(payments):
                        row[label] = self._format_payment_value(
                            pf['key'], payments[idx], traveler)
                    else:
                        row[label] = ''
                for pf in dyn_fields:
                    label = _dyn_label(pf['key'], slot)
                    if idx < len(payments):
                        row[label] = self._format_payment_value(
                            pf['key'], payments[idx], traveler)
                    else:
                        row[label] = ''

            total_paid = sum(
                float(p.get('amount', 0) or 0) for p in payments)
            overflow = payments[max_slots:]
            ov_total = sum(
                float(p.get('amount', 0) or 0) for p in overflow)

            pending_payments = []
            for p in payments:
                p_status = str(p.get('status', '')).lower()
                if p_status != 'pending':
                    continue
                if self._is_invoice_paid_for_payment(p, traveler_id):
                    continue
                pending_payments.append(p)

            pending_with_tax_total = 0.0
            for pp in pending_payments:
                share = self._get_payment_share(pp, traveler_id)
                pending_with_tax_total += share['total']

            payment_without_tax_total = sum(
                float(p.get('amount', 0) or 0) for p in payments)

            traveler_entry = self.traveler_invoice_data.get(
                traveler_id, {})
            has_paid_inv = bool(
                traveler_entry.get('has_paid_invoice', False))

            if has_paid_inv:
                outstanding_balance = 0.0
            else:
                total_invoice_amount = traveler_entry.get(
                    'total_amount', 0.0)
                outstanding_balance = max(
                    0.0, total_invoice_amount - total_paid)

            summary_values = {
                'Total Paid':                 f"₹{_fmt_inr_(total_paid)}",
                'Payment Count':              str(len(payments)),
                'Additional Payments':        str(len(overflow)) if overflow else '0',
                'Additional Total':           f"₹{_fmt_inr_(ov_total)}" if overflow else '₹0.00',
                'Total Base':                 f"₹{_fmt_inr_(base_total)}",
                'Total Discount':             f"₹{_fmt_inr_(discount_total)}",
                'Total Taxable':              f"₹{_fmt_inr_(taxable_total)}",
                'Total GST':                  f"₹{_fmt_inr_(gst_total)}",
                'Total TCS':                  f"₹{_fmt_inr_(tcs_total)}",
                'Total — With GST/TCS':       f"₹{_fmt_inr_(total_share_total)}",
                'Pending — With GST/TCS':     f"₹{_fmt_inr_(pending_with_tax_total)}",
                'Payment — Without GST/TCS':  f"₹{_fmt_inr_(payment_without_tax_total)}",
                'Outstanding Balance':        f"₹{_fmt_inr_(outstanding_balance)}",
                'Total (with GST/TCS)':       f"₹{_fmt_inr_(total_share_total)}",
                'Pending Payment (with GST/TCS)': f"₹{_fmt_inr_(pending_with_tax_total)}",
                'Payment (without GST/TCS)':  f"₹{_fmt_inr_(payment_without_tax_total)}",
            }

            requested_summary_labels = {
                pf['label'] for pf in payment_cols
                if pf['key'].startswith('__sum_')
            }
            for label, value in summary_values.items():
                if label in requested_summary_labels:
                    row[label] = value

            inv = self.default_invoice_by_traveler.get(traveler_id)
            requested_snapshots = {
                pf['label'] for pf in payment_cols
                if pf['key'].startswith('__inv_paid_')
            }
            if requested_snapshots:
                if not inv:
                    for lbl in requested_snapshots:
                        row[lbl] = "—"
                else:
                    snapshot_values = {
                        "Invoice Status":
                            str(inv.get("status", "") or "—"),
                        "Invoice is Paid?":
                            "✅ Yes" if inv.get("is_paid") else "—",
                        "Invoice Base (paid)":
                            f"₹{_fmt_inr_(inv['base'])}",
                        "Invoice Discount (paid)":
                            f"₹{_fmt_inr_(inv['discount_amount'])}",
                        "Invoice Taxable (paid)":
                            f"₹{_fmt_inr_(inv['taxable'])}",
                        "Invoice GST (paid)":
                            f"₹{_fmt_inr_(inv['gst'])}",
                        "Invoice TCS (paid)":
                            f"₹{_fmt_inr_(inv['tcs'])}",
                        "Invoice Total (paid)":
                            f"₹{_fmt_inr_(inv['total_amount'])}",
                    }
                    for lbl, val in snapshot_values.items():
                        if lbl in requested_snapshots:
                            row[lbl] = val

        return row

    # =============================================================================
    # 17.3.21 — _format_payment_value
    # PURPOSE
    #   Format one field from one payment row (used by dynamic and
    #   per-slot column expansion). Money fields are ₹-formatted;
    #   dates become DD/MM/YYYY; other fields pass through safe_str.
    # =============================================================================
    def _format_payment_value(self, key, payment, traveler):
        if key == 'passport_name':
            return self.safe_str(traveler.get('passport_name', ''))
        if key == 'passport_no':
            return self.safe_str(traveler.get('passport_no', ''))
        if key == 'mobile':
            return self.safe_str(traveler.get('mobile', ''))
        if key == 'amount':
            try:
                amt = float(payment.get('amount', 0))
                return f"₹{_fmt_inr_(amt)}"
            except Exception:
                return f"₹{payment.get('amount', 0)}"
        if key == 'payment_date':
            val = payment.get('payment_date', '')
            return self.format_date_to_ddmmyyyy(
                str(val) if val else '')
        if key == 'payment_method':
            return str(payment.get('payment_method', ''))
        if key == 'status':
            return str(payment.get('status', ''))
        if key == 'transaction_id':
            tid = payment.get('transaction_id', '')
            if tid is None:
                return ''
            if isinstance(tid, float):
                if tid > 9999999999:
                    return str(int(tid))
                return str(tid)
            return self.convert_scientific_to_number(
                str(tid) if tid else '')
        if key == 'invoice_id':
            return str(payment.get('invoice_id', ''))
        if key == 'notes':
            return str(payment.get('notes', ''))
        if key == 'id':
            return str(payment.get('id', ''))
        if key == 'traveler_id':
            return self.safe_str(traveler.get('id', ''))
        if key == 'batch_id':
            return self.safe_str(traveler.get('batch_id', ''))

        traveler_id = traveler.get('id')
        share = self._get_payment_share(payment, traveler_id)

        try:
            amt = float(payment.get('amount', 0) or 0)
        except (TypeError, ValueError):
            amt = 0.0

        if key == 'gst_amount':
            return f"₹{_fmt_inr_(share['gst'])}"
        if key == 'tcs_amount':
            return f"₹{_fmt_inr_(share['tcs'])}"
        if key == 'total_with_tax':
            return f"₹{_fmt_inr_(share['taxable'] + share['gst'] + share['tcs'])}"
        if key == 'invoice_base_amount':
            return f"₹{_fmt_inr_(share['base'])}"
        if key == 'invoice_discount_pct':
            return f"{share['discount_pct']:.1f}%"
        if key == 'invoice_discount_amount':
            return f"₹{_fmt_inr_(share['discount_amount'])}"
        if key == 'invoice_taxable_value':
            return f"₹{_fmt_inr_(share['taxable'])}"
        if key == 'invoice_rounded_total':
            return f"₹{_fmt_inr_(share['total'])}"
        if key == 'payment_with_tax':
            total = share['taxable'] + share['gst'] + share['tcs']
            return f"₹{_fmt_inr_(total)}"
        if key == 'payment_without_tax':
            return f"₹{_fmt_inr_(amt)}"

        if key == '__dyn_amount':
            return f"₹{_fmt_inr_(amt)}"
        if key == '__dyn_date':
            return self.format_date_to_ddmmyyyy(
                str(payment.get('payment_date', '') or ''))
        if key == '__dyn_method':
            return str(payment.get('payment_method', '') or '')
        if key == '__dyn_receipt':
            return str(payment.get('id', '') or '')
        if key == '__dyn_txn':
            return self.convert_scientific_to_number(
                str(payment.get('transaction_id', '') or ''))
        if key == '__dyn_status':
            return str(payment.get('status', '') or '')
        if key == '__dyn_gst':
            return f"₹{_fmt_inr_(share['gst'])}"
        if key == '__dyn_tcs':
            return f"₹{_fmt_inr_(share['tcs'])}"
        if key == '__dyn_total_tax':
            total = share['taxable'] + share['gst'] + share['tcs']
            return f"₹{_fmt_inr_(total)}"

        return ''

    # =============================================================================
    # 17.3.22 — display_preview
    # PURPOSE
    #   Render the preview DataTable from the generated rows.
    #   Column widths adapt to viewport; money cells are right-aligned;
    #   photo cells use base64 data URIs.
    # =============================================================================
    def display_preview(self, selected, report_data):
        try:
            self.preview_table.columns.clear()
            self.preview_table.rows.clear()
        except Exception as e:
            print(f"[CR] preview cleanup warn: {e}")

        if not selected or not report_data:
            return

        pw = self.page.width or 1000
        col_min = 100 if pw < 700 else 130
        col_pad = 8 if pw < 700 else 10

        total_w = 0
        spacing = 10 if pw < 700 else 14
        for col in selected:
            lbl = col['label']
            w = 100 if lbl == 'Photo' else max(col_min,
                                               len(lbl) * col_pad)
            total_w += w
            self.preview_table.columns.append(
                ft.DataColumn(ft.Container(
                    content=ft.Text(lbl, size=10,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE,
                                    no_wrap=True),
                    width=w)))
        if len(selected) > 1:
            total_w += (len(selected) - 1) * spacing
        total_w += 60
        total_w = max(total_w, 900)
        self._preview_inner.width = total_w

        for row in report_data:
            cells = []
            for col in selected:
                lbl = col['label']
                if lbl == 'Photo':
                    pp = (row.get('__photo_path__', '')
                          or row.get('Photo', ''))
                    if pp and not os.path.isabs(pp):
                        pp = os.path.join(self.get_app_base_path(), pp)
                    uri = _photo_data_uri(pp)
                    if uri:
                        cells.append(ft.DataCell(ft.Container(
                            content=ft.Image(
                                src=uri, width=38, height=38,
                                fit=ft.BoxFit.COVER,
                                border_radius=6),
                            padding=2,
                            alignment=ft.Alignment.CENTER)))
                    else:
                        cells.append(ft.DataCell(ft.Text(
                            "—", size=10,
                            color=ft.Colors.RED_400,
                            text_align=ft.TextAlign.CENTER)))
                    continue
                v = row.get(lbl, '')
                is_money = _is_money_label(lbl)
                cells.append(ft.DataCell(ft.Text(
                    str(v) if v not in (None, '') else '',
                    size=10,
                    color='#0f172a' if not is_money else '#1e40af',
                    weight=(ft.FontWeight.BOLD if is_money else None),
                    text_align=(ft.TextAlign.RIGHT if is_money
                                else ft.TextAlign.LEFT))))
            self.preview_table.rows.append(ft.DataRow(cells=cells))

    # =============================================================================
    # 17.3.23 — export_to_excel   (v1.4: opens in new tab)
    # PURPOSE
    #   Generate .xlsx with two sheets: "Report" and "Summary".
    #   Photo cells embed the actual image (via Pillow). Money cells
    #   use the INR number format. Download opens in a NEW TAB so the
    #   report tab keeps its Flet session.
    # =============================================================================
    def export_to_excel(self, e=None):
        if not self.report_data:
            self._snack("⚠️ Please generate a report first", "#dc2626")
            return
        selected = (self.selected_columns
                    or self.get_selected_columns())
        if not selected:
            self._snack("⚠️ Please select columns first.", "#dc2626")
            return
        try:
            from openpyxl import Workbook
            from openpyxl.styles import (Font, Alignment, PatternFill,
                                         Border, Side)
            from openpyxl.utils import get_column_letter
            from openpyxl.drawing.image import Image as XLImage
            try:
                from PIL import Image as PILImage
                PIL_OK = True
            except ImportError:
                PIL_OK = False
        except ImportError as ex:
            self._snack(f"Missing module: {ex}", "#dc2626")
            return

        d = _export_dir("excel")
        path = d / (f"custom_report_"
                    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")

        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Report"

            hdr_font = Font(bold=True, color="FFFFFF", size=11)
            hdr_fill = PatternFill(start_color="1e40af",
                                   end_color="1e40af",
                                   fill_type="solid")
            hdr_align = Alignment(horizontal="center",
                                  vertical="center",
                                  wrap_text=True)
            cell_align = Alignment(horizontal="left",
                                   vertical="center",
                                   wrap_text=True)
            num_align = Alignment(horizontal="right",
                                  vertical="center",
                                  wrap_text=True)
            thin_border = Border(
                left=Side(style='thin'), right=Side(style='thin'),
                top=Side(style='thin'), bottom=Side(style='thin'))

            labels = [c['label'] for c in selected]
            photo_col_idx = -1
            for idx, label in enumerate(labels):
                if label.lower() in ('photo', 'photo path'):
                    photo_col_idx = idx
                    break

            for col_idx, label in enumerate(labels, 1):
                cell = ws.cell(row=1, column=col_idx, value=label)
                cell.font = hdr_font
                cell.fill = hdr_fill
                cell.alignment = hdr_align
                cell.border = thin_border
                ws.column_dimensions[
                    get_column_letter(col_idx)].width = (
                    25 if photo_col_idx == col_idx - 1 else 20)

            for row_idx, row_data in enumerate(self.report_data, 2):
                photo_path = None
                for col_idx, label in enumerate(labels, 1):
                    value = row_data.get(label, '')
                    if label.lower() in ('photo', 'photo path'):
                        value = row_data.get(label, '')
                        if value and os.path.exists(str(value)):
                            photo_path = str(value)
                        value = "📸" if photo_path else ""
                    elif label in self._MONEY_FIELDS:
                        try:
                            if isinstance(value, str):
                                v = value.replace('₹', '').replace(
                                    ',', '').strip()
                                if v:
                                    value = float(v)
                        except Exception:
                            value = str(value) if value else ''
                    elif label in ('Date of Birth', 'Registration Date',
                                   'Passport Issue Date',
                                   'Passport Expiry Date',
                                   'Expected Return Date',
                                   'Payment Date', 'Departure Date',
                                   'Return Date'):
                        value = self.format_date_to_ddmmyyyy(value)
                    else:
                        value = self.safe_str(value) if value else ''

                    cell = ws.cell(row=row_idx, column=col_idx, value=value)
                    cell.border = thin_border
                    if label in self._MONEY_FIELDS:
                        cell.alignment = num_align
                        if isinstance(value, (int, float)):
                            cell.number_format = '[$₹-en-IN]#,##,##0.00'
                    else:
                        cell.alignment = cell_align

                if photo_path and PIL_OK:
                    try:
                        pimg = PILImage.open(photo_path)
                        pimg.thumbnail((60, 60))
                        buf = io.BytesIO()
                        pimg.convert("RGB").save(buf, format='PNG')
                        buf.seek(0)
                        xl_img = XLImage(buf)
                        xl_img.width = 60
                        xl_img.height = 60
                        addr = (get_column_letter(photo_col_idx + 1)
                                + str(row_idx))
                        ws.add_image(xl_img, addr)
                        ws.row_dimensions[row_idx].height = 80
                    except Exception as ex:
                        print(f"[EXCEL] photo error row {row_idx}: {ex}")

            ws.freeze_panes = 'A2'

            summary_ws = wb.create_sheet("Summary")
            summary_ws['A1'] = "Report Summary"
            summary_ws['A1'].font = Font(bold=True, size=14)
            summary_ws['A2'] = (f"Generated on: "
                                f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
            summary_ws['A3'] = (f"Date Range: "
                                f"{self.reg_date_from.value} to "
                                f"{self.reg_date_to.value}")
            summary_ws['A4'] = f"Total Records: {len(self.report_data)}"
            summary_ws['A5'] = f"Total Columns: {len(selected)}"
            summary_ws['A6'] = (f"Report Format: "
                                f"{self.report_format_dropdown.value}")
            summary_ws['A7'] = (f"GST %: {self.gst_rate} | "
                                f"TCS %: {self.tcs_rate}")
            summary_ws['A8'] = (f"Payment source: "
                                f"{self._last_payment_source}")

            wb.save(str(path))

            url = send_file_to_user(self.page, str(path), "Excel Report")
            self._snack(f"✅ Excel saved → {path}", "#059669")
            if url:
                # v1.4: open in NEW TAB so the report tab keeps
                # its Flet session.
                self._launch_in_new_tab(url)
        except Exception as ex:
            traceback.print_exc()
            self._snack(f"❌ Excel export failed: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.24 — export_to_csv   (v1.4: opens in new tab)
    # PURPOSE
    #   Write the report as a UTF-8-BOM CSV with a metadata header
    #   block (7 comment lines) followed by the table. Download opens
    #   in a NEW TAB so the report tab keeps its Flet session.
    # =============================================================================
    def export_to_csv(self, e=None):
        if not self.report_data:
            self._snack("⚠️ Please generate a report first", "#dc2626")
            return
        selected = (self.selected_columns
                    or self.get_selected_columns())
        if not selected:
            self._snack("⚠️ Please select columns first.", "#dc2626")
            return
        try:
            labels = [c['label'] for c in selected]
            out = []
            for row in self.report_data:
                d = {}
                for label in labels:
                    value = row.get(label, '')
                    if label.lower() in ('photo', 'photo path'):
                        photo_path = None
                        for k in ('Photo', 'Photo Path', 'photo',
                                  'photo_path'):
                            if k in row:
                                val = row.get(k, '')
                                if val and os.path.exists(str(val)):
                                    photo_path = str(val)
                                    break
                        value = "Yes" if photo_path else "No"
                    elif label in self._MONEY_FIELDS:
                        if isinstance(value, (int, float)):
                            value = f"₹{_fmt_inr_(value)}"
                    elif label in ('Date of Birth', 'Registration Date',
                                   'Passport Issue Date',
                                   'Passport Expiry Date',
                                   'Expected Return Date',
                                   'Payment Date', 'Departure Date',
                                   'Return Date'):
                        value = self.format_date_to_ddmmyyyy(value)
                    else:
                        value = self.safe_csv_value(value)
                    d[label] = value
                out.append(d)

            d = _export_dir("csv")
            path = d / (f"custom_report_"
                        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(
                    f, fieldnames=labels, quoting=csv.QUOTE_MINIMAL)
                writer.writerow(
                    {labels[0]: f"# Report Generated: "
                                f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"})
                writer.writerow(
                    {labels[0]: f"# Date Range: "
                                f"{self.reg_date_from.value} to "
                                f"{self.reg_date_to.value}"})
                writer.writerow(
                    {labels[0]: f"# Report Format: "
                                f"{self.report_format_dropdown.value}"})
                writer.writerow(
                    {labels[0]: f"# Payment source: "
                                f"{self._last_payment_source}"})
                writer.writerow(
                    {labels[0]: f"# Total Records: {len(out)}"})
                writer.writerow({labels[0]: "#" * 50})
                writer.writerow({})
                writer.writeheader()
                writer.writerows(out)

            url = send_file_to_user(self.page, str(path), "CSV Report")
            self._snack(f"✅ CSV saved → {path}", "#059669")
            if url:
                # v1.4: open in NEW TAB
                self._launch_in_new_tab(url)
        except Exception as ex:
            traceback.print_exc()
            self._snack(f"❌ CSV export failed: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.25 — export_to_pdf   (v1.4: opens in new tab)
    # PURPOSE
    #   Thin wrapper around generate_pdf_report() that saves to the PDF
    #   export folder and serves the file. Download opens in a NEW TAB
    #   so the report tab keeps its Flet session.
    # =============================================================================
    def export_to_pdf(self, e=None):
        if not self.report_data:
            self._snack("⚠️ Please generate a report first", "#dc2626")
            return
        selected = (self.selected_columns
                    or self.get_selected_columns())
        if not selected:
            self._snack("⚠️ Please select columns first.", "#dc2626")
            return
        d = _export_dir("pdf")
        path = d / (f"custom_report_"
                    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        try:
            self.generate_pdf_report(
                str(path), selected, self.report_data)
            url = send_file_to_user(self.page, str(path), "PDF Report")
            self._snack(f"✅ PDF saved → {path}", "#059669")
            if url:
                # v1.4: open in NEW TAB
                self._launch_in_new_tab(url)
        except Exception as ex:
            traceback.print_exc()
            self._snack(f"❌ PDF export failed: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.26 — generate_pdf_report
    # PURPOSE
    #   Build a landscape PDF with reportlab. If more than 7 columns,
    #   splits the table into multiple pages (7 columns per page) so
    #   nothing gets squished. Photo cells embed the actual image.
    # =============================================================================
    def generate_pdf_report(self, filepath, selected, report_data):
        try:
            from reportlab.lib.pagesizes import landscape, A4
            from reportlab.platypus import (
                SimpleDocTemplate, Table, TableStyle, Paragraph,
                Spacer, PageBreak, Image as RLImage)
            from reportlab.lib import colors as rl_colors
            from reportlab.lib.styles import (getSampleStyleSheet,
                                              ParagraphStyle)
            from reportlab.lib.enums import (TA_CENTER, TA_LEFT, TA_RIGHT)
            from reportlab.lib.units import mm

            if not report_data or not selected:
                doc = SimpleDocTemplate(filepath, pagesize=A4)
                styles = getSampleStyleSheet()
                doc.build([Paragraph("Custom Report",
                                     styles['Heading1']),
                           Paragraph("No data available.",
                                     styles['Normal'])])
                return

            company_name = "Alhudha Haj Travel"
            try:
                if not self.db.company_settings.empty:
                    company_name = str(
                        self.db.company_settings.iloc[0].get(
                            'company_name', company_name)
                    ) or company_name
            except Exception:
                pass

            PAGE = landscape(A4)
            MLR = 12 * mm
            MTB = 12 * mm
            AVAIL = PAGE[0] - 2 * MLR
            doc = SimpleDocTemplate(str(filepath), pagesize=PAGE,
                                    leftMargin=MLR, rightMargin=MLR,
                                    topMargin=MTB, bottomMargin=MTB)

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                "T", parent=styles["Heading1"], fontSize=15,
                textColor=rl_colors.HexColor("#1e40af"),
                alignment=TA_CENTER, spaceAfter=4)
            subtitle_style = ParagraphStyle(
                "ST", parent=styles["Normal"], fontSize=9,
                textColor=rl_colors.HexColor("#6b7280"),
                alignment=TA_CENTER, spaceAfter=10)
            page_lbl = ParagraphStyle(
                "PL", parent=styles["Normal"], fontSize=8,
                textColor=rl_colors.HexColor("#1e40af"),
                fontName="Helvetica-Bold", alignment=TA_LEFT,
                spaceAfter=6)
            header_style = ParagraphStyle(
                "H", parent=styles["Normal"], fontSize=8, leading=10,
                textColor=rl_colors.white, fontName="Helvetica-Bold",
                alignment=TA_CENTER)
            cl = ParagraphStyle("CL", parent=styles["Normal"], fontSize=7,
                                leading=9, alignment=TA_LEFT,
                                wordWrap="CJK")
            cr = ParagraphStyle("CR", parent=styles["Normal"], fontSize=7,
                                leading=9, alignment=TA_RIGHT,
                                wordWrap="CJK")
            cc = ParagraphStyle("CC", parent=styles["Normal"], fontSize=7,
                                leading=9, alignment=TA_CENTER,
                                wordWrap="CJK")

            labels = [c['label'] for c in selected]
            MAX_COLS = 7
            chunks = [labels[i:i+MAX_COLS]
                      for i in range(0, len(labels), MAX_COLS)]
            if not chunks:
                chunks = [labels]
            total_pages = len(chunks)
            total_cols = len(labels)
            elements = []

            for pn, chunk in enumerate(chunks, 1):
                if pn == 1:
                    elements.append(Paragraph(company_name, title_style))
                    elements.append(Paragraph("Custom Report",
                                              title_style))
                    elements.append(Paragraph(
                        f"Generated on "
                        f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
                        f" · Rows: {len(report_data)}"
                        f" · Columns: {total_cols}", subtitle_style))
                else:
                    elements.append(Paragraph("Custom Report (continued)",
                                              title_style))
                start_c = labels.index(chunk[0]) + 1
                end_c = start_c + len(chunk) - 1
                elements.append(Paragraph(
                    f"<b>Page {pn} of {total_pages}</b> · "
                    f"Columns {start_c}–{end_c} of {total_cols}", page_lbl))
                elements.append(Spacer(1, 4))

                table_data = [[Paragraph(l, header_style) for l in chunk]]
                for row in report_data:
                    row_cells = []
                    for l in chunk:
                        if l == 'Photo':
                            pp = (row.get('__photo_path__')
                                  or row.get('Photo', ''))
                            if pp and not os.path.isabs(pp):
                                pp = os.path.join(
                                    self.get_app_base_path(), pp)
                            if pp and os.path.exists(pp):
                                try:
                                    img = RLImage(pp)
                                    md = 40
                                    iw = img.imageWidth or 1
                                    ih = img.imageHeight or 1
                                    ar = iw / ih
                                    if ar >= 1:
                                        img.drawWidth = md
                                        img.drawHeight = md / ar
                                    else:
                                        img.drawHeight = md
                                        img.drawWidth = md * ar
                                    img.hAlign = 'CENTER'
                                    row_cells.append(img)
                                except Exception:
                                    row_cells.append(Paragraph("—", cl))
                            else:
                                row_cells.append(Paragraph("—", cl))
                            continue
                        v = row.get(l, '')
                        is_m = _is_money_label(l)
                        is_d = l in ('Date of Birth', 'Registration Date',
                                     'Passport Issue Date',
                                     'Passport Expiry Date',
                                     'Expected Return Date',
                                     'Payment Date', 'Departure Date',
                                     'Return Date')
                        txt = str(v) if v not in (None, '') else ''
                        txt = (txt.replace('&', '&amp;')
                               .replace('<', '&lt;')
                               .replace('>', '&gt;'))
                        st = cr if is_m else cc if is_d else cl
                        row_cells.append(Paragraph(txt or '&nbsp;', st))
                    table_data.append(row_cells)

                min_w = []
                for l in chunk:
                    if l == 'Photo':
                        min_w.append(55)
                        continue
                    hlen = len(l)
                    dmax = 0
                    for r in report_data[:200]:
                        vv = str(r.get(l, '') or '')
                        if len(vv) > dmax:
                            dmax = len(vv)
                    mc = max(hlen, min(dmax, 40))
                    w = mc * 4.2 + 10
                    min_w.append(max(45, min(w, 140)))
                tot_w = sum(min_w)
                if tot_w < AVAIL:
                    extra = AVAIL - tot_w
                    per = extra / len(min_w)
                    cw = [w + per for w in min_w]
                elif tot_w > AVAIL:
                    sc = AVAIL / tot_w
                    cw = [w * sc for w in min_w]
                else:
                    cw = min_w

                t = Table(table_data, colWidths=cw, repeatRows=1)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0),
                     rl_colors.HexColor("#1e40af")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("VALIGN", (0, 1), (-1, -1), "MIDDLE"),
                    ("FONTSIZE", (0, 1), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.4,
                     rl_colors.HexColor("#d1d5db")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [rl_colors.white,
                      rl_colors.HexColor("#f9fafb")]),
                ]))
                elements.append(t)
                if pn < total_pages:
                    elements.append(PageBreak())

            doc.build(elements)
        except Exception as ex:
            traceback.print_exc()
            raise

    # =============================================================================
    # 17.3.27 — _build_pdf_photo_cell
    # PURPOSE
    #   Helper to build a scaled reportlab image cell for a photo path.
    #   Kept for future reuse (main PDF flow inlines the logic).
    # =============================================================================
    def _build_pdf_photo_cell(self, rel_path, base_path, max_size,
                              cell_style):
        if not rel_path:
            return None
        try:
            from reportlab.platypus import Image as RLImage
            abs_path = (rel_path if os.path.isabs(rel_path)
                        else os.path.join(base_path, rel_path))
            if not os.path.exists(abs_path):
                return None
            img = RLImage(abs_path)
            iw = img.imageWidth or 1
            ih = img.imageHeight or 1
            ar = iw / ih
            if ar >= 1:
                img.drawWidth = max_size
                img.drawHeight = max_size / ar
            else:
                img.drawHeight = max_size
                img.drawWidth = max_size * ar
            img.hAlign = 'CENTER'
            return img
        except Exception as ex:
            print(f"[PDF] photo embed: {ex}")
            return None

    # =============================================================================
    # 17.3.28 — SHOW / REJECT / SNACK / STATUS HELPERS
    # =============================================================================
    def show(self):
        try:
            self.page.show_dialog(self.dialog)
            self.page.run_task(self._auto_preview)
        except Exception as ex:
            print(f"[CR] show failed: {ex}")

    async def _auto_preview(self):
        await asyncio.sleep(0.25)
        try:
            self.generate_preview(None)
        except Exception as ex:
            print(f"[CR] auto preview: {ex}")

    def reject(self):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def _snack(self, msg, color="#059669"):
        try:
            self.page.snack_bar = ft.SnackBar(
                content=ft.Text(msg), bgcolor=color)
            self.page.snack_bar.open = True
            self.page.update()
        except Exception:
            pass

    def _set_status(self, icon, text, color):
        try:
            if self.status_icon:
                self.status_icon.value = icon
            if self.status_label:
                self.status_label.value = text
                self.status_label.color = color
            self.page.update()
        except Exception:
            pass


# =================================================================================
# 17.4 — MAINTENANCE WARNINGS
# =================================================================================
# 17.4.1  — FIX-CLOUD-EXPORTS : exports use send_file_to_user (HTTP).
#            Files are written to /app/exports/<type>/ on the volume.
# 17.4.2  — FIX-FRESH-DATA    : generate_preview() reloads CSVs first.
# 17.4.3  — All prior fixes preserved (paid-cascade, per-invoice share,
#              dynamic payments, CSV authority, tax-in-source,
#              slot columns, INR format, ledger, filters, outstanding,
#              pro UI, ledger auto-columns, summary outstanding,
#              excel/pdf meta).
# 17.4.4  — MOBILE-RESPONSIVE (v1.3 preserved):
#              • §17.3.3: whole dialog body inside a scrollable Column
#              • dialog clamps to (viewport − 60px)
#              • §17.3.10: preview height 220 (mobile) vs 380 (desktop)
#              • §17.3.11: buttons wrap to 2 per row on xs
#              • header inside scroll content (no title bar)
# 17.4.5  — NEW-TAB DOWNLOADS (v1.4):
#              • All three export methods call §17.3.2d
#                _launch_in_new_tab() so the download opens in a
#                separate browser tab. The report tab stays alive,
#                which keeps the Flet session (no more "logged out
#                after viewing report" on iOS Safari).
# =================================================================================
# SECTION 17 END — CUSTOM REPORT DIALOG (FLET 1.0.0 VERSION)
# =================================================================================