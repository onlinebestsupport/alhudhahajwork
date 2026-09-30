# =================================================================================
# SECTION 17 — CUSTOM REPORT DIALOG (FLET 1.0)
# =================================================================================
# 17.0 — SECTION OVERVIEW
# ---------------------------------------------------------------------------------
# This file mirrors the PyQt6 source 1:1. Same section numbers, same method
# names, same business logic. Only the UI layer uses Flet (AlertDialog,
# DataTable, Checkbox, Tabs) instead of PyQt (QDialog, QTableWidget, QCheckBox,
# QTabWidget).
#
# Fixes preserved from PyQt6 source:
#   FIX-PAID-CASCADE, FIX-PER-INVOICE-SHARE, FIX-TAX-INVOICE-SOURCE,
#   FIX-TAX-RATIO-DENOM, FIX-TAX-CUMULATIVE-CAP, FIX-NEW-PAY-COLUMNS,
#   FIX-INR-FORMAT, FIX-EXACT-PCT, FIX-SLOT-PAY-COLUMNS,
#   FIX-PAYMENT-LEDGER, FIX-ADV-FILTERS, FIX-OUTSTANDING-BAL, FIX-PRO-UI.
#
# NEW in this Flet port:
#   FIX-DYNAMIC-PAY-DYNAMIC — max_slots = max payments across FILTERED
#                              travelers, capped at HARD_CAP = 10.
#   FIX-CSV-AUTHORITY       — _load_data() prints every CSV path & row
#                              count and picks the source with the MOST
#                              rows (DB vs. all candidate CSVs). Prevents
#                              stale-cache missing-payments bugs.
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
from datetime import datetime, timedelta
from pathlib import Path

import flet as ft
import pandas as pd

try:
    from core.settings_manager import SettingsManager
except ImportError:
    SettingsManager = None


# =================================================================================
# 17.1b — MODULE HELPER: _fmt_inr_
# =================================================================================
if '_fmt_inr_' not in globals():
    def _fmt_inr_(value):
        """Indian-format currency string."""
        try:
            v = float(value or 0)
        except (TypeError, ValueError):
            return "0.00"
        if v != v:
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
    try:
        if sys.platform == "win32":
            os.startfile(path); return True
        if sys.platform.startswith("darwin"):
            subprocess.run(["open", path], check=False); return True
        subprocess.run(["xdg-open", path], check=False); return True
    except Exception as e:
        print(f"[open_local_file] {e}")
        return False


# =================================================================================
# 17.1e — MODULE HELPER: date formatting
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
# 17.1f — MODULE HELPER: photo helpers
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
# =================================================================================

# 17.1h.1 — Traveler fields (mirrors PyQt6 setup_traveler_tab)
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

# 17.1h.2 — Batch fields
BATCH_FIELDS = [
    ("id", "Batch ID"), ("batch_name", "Batch Name"),
    ("tour_type_name", "Tour Type"), ("year", "Year"),
    ("departure_date", "Departure Date"),
    ("return_date", "Return Date"), ("total_seats", "Total Seats"),
    ("available_seats", "Available Seats"),
    ("price", "Price per Seat"), ("status", "Batch Status"),
    ("description", "Description"),
]

# 17.1h.3 — Payment fields (mirrors PyQt6 setup_payment_tab)
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

# 17.1h.4 — Money field labels (mirrors PyQt6 _MONEY_FIELDS)
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

# 17.1h.5 — Dynamic label builder
def _dyn_label(key, n):
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
# 17.2 — CLASS: ColumnOrderDialog  (mirrors PyQt6 ColumnOrderDialog)
# =================================================================================
class ColumnOrderDialog:
    """17.2.0 — Reorder columns dialog."""

    def __init__(self, page, columns, on_apply):
        self.page = page
        self.columns = list(columns)
        self.original_columns = list(columns)
        self.on_apply = on_apply
        self._sel = 0
        self._list = ft.Column(spacing=4)
        self._rebuild_list()
        self.setup_ui()

    # 17.2.1 — _rebuild_list
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

    # 17.2.2 — setup_ui
    def setup_ui(self):
        header = ft.Container(
            content=ft.Row([
                ft.Text("📌", size=20),
                ft.Text("Reorder Columns", size=14,
                        weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
            ], spacing=8),
            padding=ft.Padding.symmetric(horizontal=18, vertical=12),
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

        content = ft.Container(
            content=ft.Column([
                header,
                ft.Text("Click a row, then Up/Down to reorder",
                        size=11, color=ft.Colors.GREY_600, italic=True),
                ft.Container(
                    content=ft.Column([self._list],
                                      scroll=ft.ScrollMode.AUTO,
                                      expand=True),
                    height=380, padding=6,
                    border=ft.Border.all(1, ft.Colors.GREY_200),
                    border_radius=8),
            ], spacing=10),
            width=520, height=500, padding=6)

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("📌  Reorder Columns",
                          weight=ft.FontWeight.BOLD),
            content=content,
            actions=[
                ft.Button(content=ft.Text("⬆  Move Up"),
                          on_click=move_up, height=38,
                          bgcolor="#2563eb", color=ft.Colors.WHITE),
                ft.Button(content=ft.Text("⬇  Move Down"),
                          on_click=move_down, height=38,
                          bgcolor="#2563eb", color=ft.Colors.WHITE),
                ft.Button(content=ft.Text("🔄  Reset"),
                          on_click=reset_order, height=38,
                          bgcolor="#d97706", color=ft.Colors.WHITE),
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=cancel),
                ft.Button(content=ft.Text("✅  Apply Order"),
                          on_click=apply,
                          bgcolor="#059669", color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER)

    # 17.2.3 — show
    def show(self):
        self.page.show_dialog(self.dialog)


# =================================================================================
# 17.3 — CLASS: CustomReportDialog  (mirrors PyQt6 CustomReportDialog)
# =================================================================================
class CustomReportDialog:
    """17.3.0 — Main Custom Report Generator Dialog."""

    # Mirrors PyQt6 `_MONEY_FIELDS` (module-level MONEY_FIELDS reused)
    _MONEY_FIELDS = MONEY_FIELDS

    # 17.3.1 — HARD_CAP
    HARD_CAP = 10

    # =============================================================================
    # 17.3.1 — METHOD: __init__
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

        # UI refs
        self.column_group = None
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

        self._load_live_tax_rates()
        self._refresh_invoice_caches()
        self.load_data_preview()
        self.setup_ui()

    # =============================================================================
    # 17.3.1b — METHOD: _fmt_money_inr
    # =============================================================================
    def _fmt_money_inr(self, value):
        return _fmt_inr_(value)

    # =============================================================================
    # 17.3.1c — METHOD: _load_live_tax_rates
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
    # 17.3.1d — METHOD: _refresh_invoice_caches   (FIX-PAID-CASCADE)
    #              Stores 'status' and 'is_paid' per invoice.
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
    # 17.3.1e — METHOD: _resolve_invoice_for_payment
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
    # 17.3.1f — METHOD: _is_invoice_paid_for_payment   (FIX-PAID-CASCADE)
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
    # 17.3.1g — METHOD: _get_payment_share   (FIX-PER-INVOICE-SHARE)
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
    # 17.3.1h — METHOD: _get_invoice_share   (aggregate fallback)
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
    # 17.3.2 — PATH HELPERS (mirrors PyQt6 17.3.2)
    # =============================================================================
    def get_app_base_path(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        here = os.path.dirname(os.path.abspath(__file__))
        if os.path.basename(here).lower() == "core":
            return os.path.dirname(here)
        return here

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
            if isinstance(value, (int,)):
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
        if not date_str:
            return ''
        try:
            date_str = str(date_str).strip()
            # Already dd/mm/yyyy
            if len(date_str) >= 10 and date_str[2] == '/' and date_str[5] == '/':
                return date_str[:10]
            # yyyy/mm/dd
            if len(date_str) >= 10 and date_str[4] == '/' and date_str[7] == '/':
                return f"{date_str[8:10]}/{date_str[5:7]}/{date_str[0:4]}"
            # yyyy-mm-dd
            if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
                return f"{date_str[8:10]}/{date_str[5:7]}/{date_str[0:4]}"
            formats = ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y',
                       '%Y-%m-%d %H:%M:%S', '%d-%m-%Y %H:%M:%S',
                       '%d-%m-%y', '%d/%m/%y']
            for fmt in formats:
                try:
                    return datetime.strptime(
                        date_str[:19], fmt).strftime('%d/%m/%Y')
                except Exception:
                    continue
            return date_str[:10] if len(date_str) > 10 else date_str
        except Exception:
            return date_str if date_str else ''

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
    # 17.3.3 — METHOD: setup_ui   (mirrors PyQt6 setup_ui)
    # =============================================================================
    def setup_ui(self):
        # ---- Header ----
        header = ft.Container(
            content=ft.Row([
                ft.Text("📊", size=26),
                ft.Column([
                    ft.Text("Custom Report Generator", size=16,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                    ft.Text("Traveler Summary (wide) OR Payment Ledger "
                            "(long) — with accurate per-invoice tax shares",
                            size=10, color=ft.Colors.BLUE_100),
                ], spacing=2, expand=True),
                ft.IconButton(icon=ft.Icons.CLOSE,
                              icon_color=ft.Colors.WHITE,
                              tooltip="Close",
                              on_click=lambda e: self.reject()),
            ], spacing=10),
            padding=ft.Padding.symmetric(horizontal=20, vertical=12),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#1e40af", "#2563eb", "#7c3aed"]),
            border_radius=12)

        # ---- Left panel (column picker) ----
        left_panel = self.setup_left_panel()

        # ---- Right panel (filters + preview) ----
        right_panel = self.setup_right_panel()

        # ---- Layout: two columns ----
        body = ft.Container(
            content=ft.Row(
                [left_panel, right_panel],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
                expand=True),
            expand=True)

        # ---- Filter card + buttons + status ----
        filters_card = self.setup_filters()
        buttons = self.setup_buttons()
        status = self.setup_status()

        # ---- Assemble dialog ----
        pw = self.page.width or 1400
        ph = self.page.height or 900
        init_w = max(900, min(1400, pw - 40))
        init_h = max(560, min(780, ph - 80))

        dialog_content = ft.Container(
            content=ft.Column([
                header,
                filters_card,
                body,
                buttons,
                status,
            ], spacing=12, expand=True),
            width=init_w, height=init_h, padding=4)

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("📊 Custom Report Generator",
                          weight=ft.FontWeight.BOLD),
            content=dialog_content,
            actions=[],
            actions_alignment=ft.MainAxisAlignment.CENTER)

    # =============================================================================
    # 17.3.4 — METHOD: setup_left_panel
    # =============================================================================
    def setup_left_panel(self):
        column_group_title = ft.Text(
            "📋  Select Columns  (Traveler Summary mode)",
            size=13, weight=ft.FontWeight.BOLD, color="#1e3a8a")
        self.column_group_title = column_group_title

        # Tabs: Travelers / Batches / Payments
        self.column_tabs = ft.Tabs(
            selected_index=0,
            animation_duration=200,
            length=3,
            expand=True,
            content=ft.Column([
                ft.TabBar(tabs=[
                    ft.Tab(label="👥  Travelers"),
                    ft.Tab(label="📦  Batches"),
                    ft.Tab(label="💰  Payments"),
                ]),
                ft.TabBarView(expand=True, controls=[
                    self.setup_traveler_tab(),
                    self.setup_batch_tab(),
                    self.setup_payment_tab(),
                ]),
            ], expand=True))

        return ft.Container(
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
            width=390,
            height=560)

    # =============================================================================
    # 17.3.5 — METHOD: setup_traveler_tab
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
                    ft.Button(content=ft.Text("✓  Select All", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_all, height=32,
                              bgcolor="#059669", color=ft.Colors.WHITE,
                              expand=True),
                    ft.Button(content=ft.Text("✗  Clear All", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_clear, height=32,
                              bgcolor="#dc2626", color=ft.Colors.WHITE,
                              expand=True),
                ], spacing=6),
                lv,
            ], spacing=6, expand=True),
            padding=10, expand=True)

    # =============================================================================
    # 17.3.6 — METHOD: setup_batch_tab
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
                    ft.Button(content=ft.Text("✓  Select All", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_all, height=32,
                              bgcolor="#059669", color=ft.Colors.WHITE,
                              expand=True),
                    ft.Button(content=ft.Text("✗  Clear All", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_clear, height=32,
                              bgcolor="#dc2626", color=ft.Colors.WHITE,
                              expand=True),
                ], spacing=6),
                lv,
            ], spacing=6, expand=True),
            padding=10, expand=True)

    # =============================================================================
    # 17.3.7 — METHOD: setup_payment_tab
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
                    ft.Button(content=ft.Text("✓  Select All", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_all, height=32,
                              bgcolor="#059669", color=ft.Colors.WHITE,
                              expand=True),
                    ft.Button(content=ft.Text("✗  Clear All", size=11,
                                              weight=ft.FontWeight.BOLD),
                              on_click=_clear, height=32,
                              bgcolor="#dc2626", color=ft.Colors.WHITE,
                              expand=True),
                ], spacing=6),
                lv,
            ], spacing=6, expand=True),
            padding=10, expand=True)

    # =============================================================================
    # 17.3.8 — METHOD: setup_right_panel
    # =============================================================================
    def setup_right_panel(self):
        return ft.Container(
            content=ft.Column([
                self.setup_preview(),
            ], spacing=8, expand=True),
            padding=0, expand=True)

    # =============================================================================
    # 17.3.9 — METHOD: setup_filters   (mirrors PyQt6 setup_filters)
    # =============================================================================
    def setup_filters(self):
        self.report_format_dropdown = ft.Dropdown(
            label="Report Format",
            options=[
                ft.dropdown.Option("summary",
                                   "📋  Traveler Summary (wide)"),
                ft.dropdown.Option("ledger",
                                   "🧾  Payment Ledger (long)"),
            ],
            value="summary", width=280, text_size=12,
            content_padding=10)
        self.report_format_dropdown.on_change = self._on_report_format_changed

        self.reg_date_from = ft.TextField(
            label="From (dd/mm/yyyy)",
            value=(datetime.now() - timedelta(days=90)
                   ).strftime("%d/%m/%Y"),
            width=170, text_size=12, content_padding=10)
        self.reg_date_to = ft.TextField(
            label="To (dd/mm/yyyy)",
            value=datetime.now().strftime("%d/%m/%Y"),
            width=170, text_size=12, content_padding=10)

        self.batch_filter_combo = ft.Dropdown(
            label="Batch Filter",
            options=[ft.dropdown.Option("", "All Batches")],
            value="", width=170, text_size=12, content_padding=10)
        try:
            for batch in self.db.get_batches():
                self.batch_filter_combo.options.append(
                    ft.dropdown.Option(
                        batch['id'],
                        batch.get('batch_name', 'Unknown')))
        except Exception:
            pass

        self.status_filter = ft.Dropdown(
            label="Traveler Status",
            options=[ft.dropdown.Option(x) for x in
                     ["All", "Active", "Inactive", "Completed"]],
            value="All", width=140, text_size=12, content_padding=10)

        self.payment_method_filter = ft.Dropdown(
            label="Payment Method",
            options=[ft.dropdown.Option(x) for x in
                     ["All", "Bank Transfer", "Cash", "Card", "UPI",
                      "Cheque", "NEFT", "RTGS", "IMPS"]],
            value="All", width=160, text_size=12, content_padding=10)

        self.payment_status_filter = ft.Dropdown(
            label="Payment Status",
            options=[ft.dropdown.Option(x) for x in
                     ["All", "completed", "pending", "failed", "refunded"]],
            value="All", width=150, text_size=12, content_padding=10)

        self.min_amount_input = ft.TextField(
            label="Min ₹", width=110, text_size=12, content_padding=10)
        self.max_amount_input = ft.TextField(
            label="Max ₹", width=110, text_size=12, content_padding=10)

        def _quick(days):
            def _h(e):
                self.reg_date_from.value = (
                    datetime.now() - timedelta(days=days)
                ).strftime("%d/%m/%Y")
                self.reg_date_to.value = datetime.now().strftime("%d/%m/%Y")
                self.generate_preview(None)
            return _h

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("🔍", size=16),
                    ft.Text("Report Format & Filters", size=13,
                            weight=ft.FontWeight.BOLD, color="#1e3a8a"),
                ], spacing=6),
                ft.Row([
                    self.report_format_dropdown,
                    self.reg_date_from,
                    self.reg_date_to,
                    ft.Button(content=ft.Text("Today", size=11),
                              on_click=_quick(0), height=36,
                              bgcolor="#e0f2fe", color="#0369a1"),
                    ft.Button(content=ft.Text("Week", size=11),
                              on_click=_quick(7), height=36,
                              bgcolor="#e0f2fe", color="#0369a1"),
                    ft.Button(content=ft.Text("Month", size=11),
                              on_click=_quick(30), height=36,
                              bgcolor="#e0f2fe", color="#0369a1"),
                    ft.Button(content=ft.Text("3M", size=11),
                              on_click=_quick(90), height=36,
                              bgcolor="#e0f2fe", color="#0369a1"),
                ], spacing=8, wrap=True),
                ft.Row([
                    self.batch_filter_combo,
                    self.status_filter,
                    self.payment_method_filter,
                    self.payment_status_filter,
                    self.min_amount_input,
                    self.max_amount_input,
                ], spacing=8, wrap=True),
            ], spacing=10),
            padding=12, bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, "#dbeafe"),
            border_radius=10)

    # =============================================================================
    # 17.3.9b — METHOD: _on_report_format_changed
    # =============================================================================
    def _on_report_format_changed(self, e=None):
        try:
            mode = self.report_format_dropdown.value or "summary"
            self.current_report_mode = mode
            if mode == 'ledger':
                self.column_group_title.value = (
                    "📋  Columns  (auto-managed in Payment Ledger mode)")
                self.column_group_title.color = "#6b7280"
            else:
                self.column_group_title.value = (
                    "📋  Select Columns  (Traveler Summary mode)")
                self.column_group_title.color = "#1e3a8a"
            self.page.update()
        except Exception as ex:
            print(f"[CR] _on_report_format_changed error: {ex}")

    # =============================================================================
    # 17.3.10 — METHOD: setup_preview
    # =============================================================================
    def setup_preview(self):
        PREVIEW_H = 380
        self.preview_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("Preview", size=11,
                                           weight=ft.FontWeight.BOLD,
                                           color=ft.Colors.WHITE))],
            rows=[],
            heading_row_color="#1e293b",
            column_spacing=14,
            data_row_min_height=46,
            data_row_max_height=70)

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
                    ft.Text("Report Preview", size=13,
                            weight=ft.FontWeight.BOLD, color="#1e3a8a"),
                    ft.Container(expand=True),
                    ft.Text("↔ scroll inside", size=9,
                            color=ft.Colors.GREY_500, italic=True),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self._preview_body,
            ], spacing=8, expand=True),
            padding=12, bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, "#dbeafe"),
            border_radius=10, expand=True)

    # =============================================================================
    # 17.3.11 — METHOD: setup_buttons   (mirrors PyQt6 setup_buttons)
    # =============================================================================
    def setup_buttons(self):
        def _btn(label, icon, color, handler):
            return ft.Button(
                content=ft.Row([
                    ft.Icon(icon, size=16, color=ft.Colors.WHITE),
                    ft.Text(label, size=12, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                ], spacing=6, tight=True),
                on_click=handler, height=42, bgcolor=color)

        return ft.Row([
            _btn("Generate Preview", ft.Icons.REFRESH, "#2563eb",
                 self.generate_preview),
            _btn("Force Reload CSV", ft.Icons.DOWNLOAD, "#0ea5e9",
                 self._force_reload_csv),
            _btn("Diagnose", ft.Icons.BUG_REPORT, "#f59e0b",
                 self._diagnose),
            _btn("Reorder Columns", ft.Icons.SORT, "#7c3aed",
                 self.open_column_ordering_dialog),
            _btn("Export Excel", ft.Icons.TABLE_CHART, "#059669",
                 self.export_to_excel),
            _btn("Export CSV", ft.Icons.DESCRIPTION, "#0891b2",
                 self.export_to_csv),
            _btn("Export PDF", ft.Icons.PICTURE_AS_PDF, "#dc2626",
                 self.export_to_pdf),
            ft.TextButton(content=ft.Text("Close"),
                          on_click=lambda e: self.reject()),
        ], spacing=8, wrap=True)

    # =============================================================================
    # 17.3.12 — METHOD: setup_status
    # =============================================================================
    def setup_status(self):
        self.status_icon = ft.Text("✅", size=14)
        self.status_label = ft.Text(
            "Ready. Pick a report format and click 'Generate Preview'",
            size=12, color="#059669", weight=ft.FontWeight.BOLD)
        self.record_count_label = ft.Text(
            "", size=11, color="#6b7280")

        return ft.Row([
            self.status_icon,
            self.status_label,
            ft.Container(expand=True),
            self.record_count_label,
        ], spacing=8)

    # =============================================================================
    # 17.3.13 — METHOD: create_checkbox_group   (compat with PyQt6 name)
    # =============================================================================
    def create_checkbox_group(self, items):
        """Return dict of {key: ft.Checkbox} for the given field list."""
        return {k: ft.Checkbox(label=l, value=False) for k, l in items}

    # =============================================================================
    # 17.3.14 — METHOD: select_all_checkboxes   (compat)
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
    # 17.3.15 — METHOD: get_selected_columns
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
    # 17.3.16 — METHOD: date quick filters   (mirrors PyQt6)
    # =============================================================================
    def set_date_today(self):
        today = datetime.now()
        self.reg_date_from.value = today.strftime("%d/%m/%Y")
        self.reg_date_to.value = today.strftime("%d/%m/%Y")
        self.generate_preview(None)

    def set_date_this_week(self):
        today = datetime.now()
        start = today - timedelta(days=today.weekday())
        self.reg_date_from.value = start.strftime("%d/%m/%Y")
        self.reg_date_to.value = today.strftime("%d/%m/%Y")
        self.generate_preview(None)

    def set_date_this_month(self):
        today = datetime.now()
        start = today.replace(day=1)
        self.reg_date_from.value = start.strftime("%d/%m/%Y")
        self.reg_date_to.value = today.strftime("%d/%m/%Y")
        self.generate_preview(None)

    def set_date_last_month(self):
        today = datetime.now()
        first_this = today.replace(day=1)
        last_last = first_this - timedelta(days=1)
        start = last_last.replace(day=1)
        self.reg_date_from.value = start.strftime("%d/%m/%Y")
        self.reg_date_to.value = last_last.strftime("%d/%m/%Y")
        self.generate_preview(None)

    def set_date_this_year(self):
        today = datetime.now()
        start = today.replace(month=1, day=1)
        end = today.replace(month=12, day=31)
        self.reg_date_from.value = start.strftime("%d/%m/%Y")
        self.reg_date_to.value = end.strftime("%d/%m/%Y")
        self.generate_preview(None)

    def set_date_default(self):
        today = datetime.now()
        self.reg_date_from.value = (
            today - timedelta(days=90)).strftime("%d/%m/%Y")
        self.reg_date_to.value = today.strftime("%d/%m/%Y")
        self.generate_preview(None)

    # =============================================================================
    # 17.3.17 — METHOD: open_column_ordering_dialog
    # =============================================================================
    def open_column_ordering_dialog(self, e=None):
        if self.current_report_mode == 'ledger':
            self._snack("ℹ️ In Payment Ledger mode, columns are managed "
                        "automatically. Switch to 'Traveler Summary' "
                        "to reorder columns.", "#3b82f6")
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
    # 17.3.18 — METHOD: load_data_preview   (FIX-CSV-AUTHORITY)
    # =============================================================================
    def load_data_preview(self):
        try:
            # Force DB cache refresh if such a method exists
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

            # Refresh batch filter
            try:
                self.batch_filter_combo.options = [
                    ft.dropdown.Option("", "All Batches")]
                for batch in self.db.get_batches():
                    self.batch_filter_combo.options.append(
                        ft.dropdown.Option(
                            batch['id'],
                            batch.get('batch_name', 'Unknown')))
            except Exception:
                pass
        except Exception as e:
            print(f"[CR] Error loading data: {e}")
            traceback.print_exc()

    # =============================================================================
    # 17.3.18b — METHOD: _force_reload_csv   (bypasses DB)
    # =============================================================================
    def _force_reload_csv(self, e=None):
        try:
            print("[CR] 🔃 FORCE RELOAD from CSV …")
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
    # 17.3.18c — METHOD: _diagnose
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
    # 17.3.19 — METHOD: generate_preview   (mirrors PyQt6 generate_preview)
    # =============================================================================
    def generate_preview(self, e=None):
        self._load_live_tax_rates()
        self._refresh_invoice_caches()

        # Reload payments (uses DB; CSV fallback already ran in load_data_preview)
        try:
            self.payment_data = self.payment_data or self.db.get_payments()
        except Exception as ex:
            print(f"[CR] generate_preview: payments refresh failed: {ex}")

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

            # ---- Compute max_slots   (FIX-DYNAMIC-PAY-DYNAMIC) ----
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

            # ---- Expand dynamic payment columns ----
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

            dynamic_payment_cols = []
            if has_payment_cols:
                # Per-slot columns for regular payment fields
                for slot in range(1, max_slots + 1):
                    for pf in slot_source_fields:
                        dynamic_payment_cols.append({
                            'key': f'__pay{slot}_{pf["key"]}',
                            'label': f'Payment {slot} {pf["label"]}',
                            'source': 'payment_slot',
                            'orig_key': pf['key'],
                            'slot': slot,
                        })
                # Dynamic per-payment columns (▶)
                for slot in range(1, max_slots + 1):
                    for pf in dyn_fields:
                        dynamic_payment_cols.append({
                            'key': pf['key'],
                            'label': _dyn_label(pf['key'], slot),
                            'source': 'payment_dyn',
                            'dyn_index': slot - 1,
                        })
                # Summary aggregates
                for sf in summary_fields:
                    dynamic_payment_cols.append({
                        'key': sf['key'],
                        'label': sf['label'],
                        'source': 'payment_summary',
                    })
                # Invoice-paid snapshot
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
                    f"Traveler Summary generated — {max_slots} payment "
                    f"slot(s) per traveler — tax shown as per-invoice share",
                    "#059669")
            else:
                self._set_status("✅",
                                 "Traveler Summary generated successfully!",
                                 "#059669")
            if self.record_count_label:
                self.record_count_label.value = (
                    f"📊 {len(report_data)} travelers | "
                    f"{len(final_columns)} columns")
            try:
                self.page.update()
            except Exception:
                pass
        except Exception as ex:
            traceback.print_exc()
            self._set_status("❌", f"Error: {ex}", "#dc2626")
            self._snack(f"Could not generate report: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.19b — METHOD: _generate_ledger_preview   (FIX-PAID-CASCADE)
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

                # FIX-PAID-CASCADE
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
                f"Payment Ledger generated — {len(report_data)} payment "
                f"row(s) with per-invoice tax share and outstanding balance",
                "#059669")
            if self.record_count_label:
                self.record_count_label.value = (
                    f"🧾 {len(report_data)} payments | "
                    f"{len(ledger_columns)} ledger columns")
            try:
                self.page.update()
            except Exception:
                pass

        except Exception as ex:
            traceback.print_exc()
            self._set_status("❌", f"Ledger error: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.20 — METHOD: _build_row_wide   (FIX-PAID-CASCADE)
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

        # ---- Traveler columns ----
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

        # ---- Batch columns ----
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

        # ---- Per-payment aggregate summary (with FIX-PAID-CASCADE) ----
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

        # ---- Per-slot columns ----
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
                # Regular slot columns
                for pf in slot_fields:
                    label = f"Payment {slot} {pf['label']}"
                    if idx < len(payments):
                        row[label] = self._format_payment_value(
                            pf['key'], payments[idx], traveler)
                    else:
                        row[label] = ''
                # Dynamic per-payment (▶)
                for pf in dyn_fields:
                    label = _dyn_label(pf['key'], slot)
                    if idx < len(payments):
                        row[label] = self._format_payment_value(
                            pf['key'], payments[idx], traveler)
                    else:
                        row[label] = ''

            # ---- Summary aggregates ----
            total_paid = sum(
                float(p.get('amount', 0) or 0) for p in payments)
            overflow = payments[max_slots:]
            ov_total = sum(
                float(p.get('amount', 0) or 0) for p in overflow)

            # FIX-PAID-CASCADE
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

            # ---- Summary values (both label styles) ----
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
                # New labels with em-dash — must match PAYMENT_FIELDS exactly:
                'Total — With GST/TCS':       f"₹{_fmt_inr_(total_share_total)}",
                'Pending — With GST/TCS':     f"₹{_fmt_inr_(pending_with_tax_total)}",
                'Payment — Without GST/TCS':  f"₹{_fmt_inr_(payment_without_tax_total)}",
                'Outstanding Balance':        f"₹{_fmt_inr_(outstanding_balance)}",
                # Keep old keys too, so BOTH label styles resolve correctly:
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

            # ---- Invoice-paid snapshot ----
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
    # 17.3.21 — METHOD: _format_payment_value
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

        # Dynamic per-payment (▶) labels
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
    # 17.3.22 — METHOD: display_preview   (mirrors PyQt6 display_preview)
    # =============================================================================
    def display_preview(self, selected, report_data):
        try:
            self.preview_table.columns.clear()
            self.preview_table.rows.clear()
        except Exception as e:
            print(f"[CR] preview cleanup warn: {e}")

        if not selected or not report_data:
            return

        total_w = 0
        spacing = 14
        for col in selected:
            lbl = col['label']
            w = 150 if lbl == 'Photo' else max(130, len(lbl) * 10)
            total_w += w
            self.preview_table.columns.append(
                ft.DataColumn(ft.Container(
                    content=ft.Text(lbl, size=11,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE,
                                    no_wrap=True),
                    width=w)))
        if len(selected) > 1:
            total_w += (len(selected) - 1) * spacing
        total_w += 60
        total_w = max(total_w, 900)
        self._preview_inner.width = total_w
        print(f"[CR] preview width={total_w}, cols={len(selected)}")

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
                                src=uri, width=44, height=44,
                                fit=ft.BoxFit.COVER,
                                border_radius=6),
                            padding=2,
                            alignment=ft.Alignment.CENTER)))
                    else:
                        cells.append(ft.DataCell(ft.Text(
                            "❌ No Photo", size=10,
                            color=ft.Colors.RED_400,
                            text_align=ft.TextAlign.CENTER)))
                    continue
                v = row.get(lbl, '')
                is_money = _is_money_label(lbl)
                cells.append(ft.DataCell(ft.Text(
                    str(v) if v not in (None, '') else '',
                    size=11,
                    color='#0f172a' if not is_money else '#1e40af',
                    weight=(ft.FontWeight.BOLD if is_money else None),
                    text_align=(ft.TextAlign.RIGHT if is_money
                                else ft.TextAlign.LEFT))))
            self.preview_table.rows.append(ft.DataRow(cells=cells))

    # =============================================================================
    # 17.3.23 — METHOD: export_to_excel
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

            # Summary sheet
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
            summary_ws['A10'] = "Column List:"
            for idx, col in enumerate(selected, 1):
                summary_ws[f'A{idx+10}'] = (
                    f"{idx}. {col['label']} ({col['source'].title()})")

            wb.save(str(path))
            self._snack(f"✅ Excel saved → {path}", "#059669")
            try:
                self.page.launch_url(
                    f"/assets/exports/excel/{path.name}")
            except Exception:
                pass
            _open_local_file(str(path))
        except Exception as ex:
            traceback.print_exc()
            self._snack(f"❌ Excel export failed: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.24 — METHOD: export_to_csv
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

            self._snack(f"✅ CSV saved → {path}", "#059669")
            try:
                self.page.launch_url(
                    f"/assets/exports/csv/{path.name}")
            except Exception:
                pass
            _open_local_file(str(path))
        except Exception as ex:
            traceback.print_exc()
            self._snack(f"❌ CSV export failed: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.25 — METHOD: export_to_pdf
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
            self._snack(f"✅ PDF saved → {path}", "#059669")
            try:
                self.page.launch_url(
                    f"/assets/exports/pdf/{path.name}")
            except Exception:
                pass
            _open_local_file(str(path))
        except Exception as ex:
            traceback.print_exc()
            self._snack(f"❌ PDF export failed: {ex}", "#dc2626")

    # =============================================================================
    # 17.3.26 — METHOD: generate_pdf_report
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
    # 17.3.27 — METHOD: _build_pdf_photo_cell
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
            # Auto-generate first preview
            self.page.run_task(self._auto_preview)
        except Exception as ex:
            print(f"[CR] show failed: {ex}")

    async def _auto_preview(self):
        import asyncio
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
# 17.4.1  — FIX #12  — Photo thumbnails in Preview.
# 17.4.2  — FIX #20  — One row per traveler, dynamic payment slots.
# 17.4.3  — FIX #24  — Professional visual overhaul.
# 17.4.4  — FIX #25b — Robust batch-name lookup.
# 17.4.5  — FIX #25c — Ghost widget cleanup.
# 17.4.6  — FIX-TAX-INVOICE-SOURCE
# 17.4.7  — FIX-TAX-RATIO-DENOM (v2)
# 17.4.8  — FIX-TAX-CUMULATIVE-CAP
# 17.4.9  — FIX-TAX-DOUBLE-COUNT
# 17.4.10 — HARD_CAP = 10.
# 17.4.11 — ColumnOrderDialog reorders dynamic slots too.
# 17.4.12 — Excel/CSV exports parse ₹ and use Indian comma for display.
# 17.4.13 — Verified clean.
# 17.4.14 — FIX-NEW-PAY-COLUMNS
# 17.4.15 — FIX-INR-FORMAT
# 17.4.16 — FIX-EXACT-PCT
# 17.4.17 — FIX-SLOT-PAY-COLUMNS
# 17.4.18 — FIX-PER-INVOICE-SHARE
# 17.4.19 — FIX-PAYMENT-LEDGER
# 17.4.20 — FIX-ADV-FILTERS
# 17.4.21 — FIX-OUTSTANDING-BAL
# 17.4.22 — FIX-PRO-UI
# 17.4.23 — FIX-LEDGER-AUTOCOLS
# 17.4.24 — FIX-SUMMARY-OUTSTANDING
# 17.4.25 — FIX-EXCEL-PDF-META
# 17.4.26 — FIX-PAID-CASCADE
# 17.4.27 — FIX-DYNAMIC-PAY-DYNAMIC  (Flet port):
#              max_slots = max payments across FILTERED travelers, capped
#              at HARD_CAP = 10.
# 17.4.28 — FIX-CSV-AUTHORITY  (Flet port):
#              _load_data_preview prints every CSV path & row count and
#              picks the source with the MOST rows (DB vs. all candidate
#              CSVs). Prevents stale-cache missing-payments bugs.
# 17.4.29 — Added two buttons in 17.3.11:
#                🔃 Force Reload CSV → _force_reload_csv (bypasses DB)
#                🔎 Diagnose         → _diagnose
# =================================================================================
# SECTION 17 END — CUSTOM REPORT DIALOG
# =================================================================================