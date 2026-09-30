# =================================================================================
# SECTION 14 (FLET 1.0.0 VERSION) — INVOICES TAB
# =================================================================================
# Actions use a single compact ⋮ popup menu (always visible)
#
# PATCHES APPLIED (v1.1):
#   14.1.A — refresh()   : force DB reload before reading (fresh cache)
#   14.1.B — display_invoices(): action menu captures invoice ID, re-fetches
#                                latest row before every handler (no stale dict)
#   14.3.A — InvoiceModifyDialog.save() : prefer db.update_invoice()
#   14.3.B — Cascade: status → paid creates/syncs payment record
#   14.3.C — Cascade: status leaves paid → deletes auto-created payment
# =================================================================================

import flet as ft
import json
import os
import base64
import io
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

from core.helpers import (
    get_app_base_path,
    number_to_words_indian,
    format_currency_indian,
    send_file_to_user,
    round_as_per_rules,
)
from core.settings_manager import SettingsManager
from core.company_settings_dialog import CompanySettingsDialog


# =================================================================================
# 14.1 — CLASS: InvoicesTab
# =================================================================================
class InvoicesTab:

    def __init__(self, page: ft.Page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.settings_manager = SettingsManager(db)

        self.invoices = []
        self.travelers = {}
        self.batches = {}
        self.traveler_details_cache = {}
        self.traveler_paid = {}

        self.stat_labels = {}
        self.tax_info_label = None
        self.status_filter = None
        self.search_input = None
        self.table = None
        self.root = None

        self.setup_ui()
        self.refresh()

    def build(self):
        return self.root

    # =============================================================================
    # 14.1.1 — setup_ui
    # =============================================================================
    def setup_ui(self):
        # ---- TAX INFO BAR ----
        tax = self.settings_manager.get_tax_settings()
        try:
            gst_rate = float(tax.get('gst_percentage', 18))
            tcs_rate = float(tax.get('tcs_percentage', 0.1))
        except Exception:
            gst_rate = 18.0
            tcs_rate = 0.1

        self.tax_info_label = ft.Text(
            f"CURRENT TAX RATES: GST {gst_rate}% | TCS {tcs_rate}% | "
            f"Rounding: <0.50 DOWN, ≥0.50 UP",
            size=13, weight=ft.FontWeight.BOLD,
            color="#FFD700",
            font_family="Consolas")

        def refresh_tax(e):
            self.update_tax_display()
            self._snack("✅ Tax rates refreshed")

        def open_tax_settings(e):
            dlg = CompanySettingsDialog(
                self.page, self.db, self.current_user,
                on_save_callback=self.refresh)
            dlg.show()

        tax_bar = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Text("💰", size=22),
                    self.tax_info_label,
                    ft.Container(expand=True),
                    ft.Button(
                        content=ft.Text("🔄 REFRESH TAX RATES", size=11,
                                        weight=ft.FontWeight.BOLD),
                        on_click=refresh_tax, height=38,
                        bgcolor="#f39c12", color=ft.Colors.WHITE),
                    ft.Button(
                        content=ft.Text("⚙️ TAX SETTINGS", size=11,
                                        weight=ft.FontWeight.BOLD),
                        on_click=open_tax_settings, height=38,
                        bgcolor="#2ecc71", color=ft.Colors.WHITE),
                ],
                spacing=10,
            ),
            padding=ft.Padding.symmetric(horizontal=15, vertical=10),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#2c3e50", "#1a252f", "#2c3e50"]),
            border_radius=12,
        )

        # ---- STAT CARDS ----
        stat_configs = [
            ("total_invoices",   "📊 Total Invoices",    "#3498db"),
            ("pending",          "⏳ Invoice Pending",   "#f39c12"),
            ("paid",             "✅ Paid",              "#27ae60"),
            ("discount",         "🎁 Total Discount",    "#c2185b"),
            ("tcs",              "💰 Total TCS",         "#9b59b6"),
            ("package_pending",  "📦 Package Pending",   "#e74c3c"),
        ]

        stat_cards = []
        for key, label, color in stat_configs:
            value_label = ft.Text("0", size=16,
                                  weight=ft.FontWeight.BOLD,
                                  color=ft.Colors.WHITE)
            self.stat_labels[key] = value_label
            card = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(label, size=10, color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                        value_label,
                    ],
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=10,
                gradient=ft.LinearGradient(
                    begin=ft.Alignment.TOP_CENTER,
                    end=ft.Alignment.BOTTOM_CENTER,
                    colors=[color, self._darken(color)]),
                border_radius=10,
                expand=True, height=72,
            )
            stat_cards.append(card)

        stats_row = ft.Row(controls=stat_cards, spacing=8)

        # ---- TOOLBAR ----
        def _tb(label, color, handler):
            return ft.Button(
                content=ft.Text(label, size=11,
                                weight=ft.FontWeight.BOLD),
                on_click=handler, height=38,
                bgcolor=color, color=ft.Colors.WHITE,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=8)))

        self.status_filter = ft.Dropdown(
            label="Status",
            options=[
                ft.dropdown.Option(key="All", text="All"),
                ft.dropdown.Option(key="pending", text="pending"),
                ft.dropdown.Option(key="paid", text="paid"),
                ft.dropdown.Option(key="overdue", text="overdue"),
                ft.dropdown.Option(key="cancelled", text="cancelled"),
            ],
            value="All", width=140, height=48, text_size=12)
        self.status_filter.on_change = self.apply_filters

        self.search_input = ft.TextField(
            hint_text="🔍 Search invoice no or traveler...",
            width=280, height=48,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=8))
        self.search_input.on_change = self.apply_filters

        toolbar = ft.Row(
            controls=[
                _tb("➕ Generate Invoice", "#27ae60", self.generate_invoice),
                _tb("🧾 Manual Create", "#f39c12", self.open_manual_invoice),
                self.status_filter,
                self.search_input,
            ],
            spacing=8, wrap=True,
        )

        # ---- TABLE (Actions first — 1 compact menu button) ----
        self.table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("⋮")),           # Actions (menu icon)
                ft.DataColumn(ft.Text("Invoice No")),
                ft.DataColumn(ft.Text("Date")),
                ft.DataColumn(ft.Text("Traveler")),
                ft.DataColumn(ft.Text("Base Amt")),
                ft.DataColumn(ft.Text("Disc%")),
                ft.DataColumn(ft.Text("Disc Amt")),
                ft.DataColumn(ft.Text("Taxable")),
                ft.DataColumn(ft.Text("GST%")),
                ft.DataColumn(ft.Text("GST Amt")),
                ft.DataColumn(ft.Text("TCS%")),
                ft.DataColumn(ft.Text("TCS Amt")),
                ft.DataColumn(ft.Text("Total")),
                ft.DataColumn(ft.Text("Rounded")),
                ft.DataColumn(ft.Text("Due")),
                ft.DataColumn(ft.Text("Status")),
                ft.DataColumn(ft.Text("Pkg Pend")),
            ],
            rows=[],
            column_spacing=10,
            heading_row_color=ft.Colors.BLUE_GREY_800,
            heading_row_height=40,
            data_row_min_height=46,
            data_row_max_height=58,
            border=ft.Border.all(1, ft.Colors.GREY_300),
            border_radius=10,
            vertical_lines=ft.BorderSide(1, ft.Colors.GREY_200),
            horizontal_lines=ft.BorderSide(1, ft.Colors.GREY_200),
        )

        # ---- ROOT ----
        self.root = ft.Container(
            content=ft.Column(
                controls=[
                    tax_bar,
                    stats_row,
                    ft.Container(content=toolbar, padding=10,
                                 bgcolor=ft.Colors.WHITE,
                                 border_radius=10),
                    ft.Container(
                        content=ft.Column(
                            controls=[self.table],
                            scroll=ft.ScrollMode.ADAPTIVE),
                        bgcolor=ft.Colors.WHITE,
                        border_radius=10,
                        padding=10),
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=15, bgcolor="#f0f2f5", expand=True,
        )

    def _darken(self, color):
        return {
            "#3498db": "#2471a3", "#27ae60": "#1e8449",
            "#f39c12": "#d68910", "#9b59b6": "#7d3c98",
            "#e74c3c": "#c0392b", "#c2185b": "#880e4f",
        }.get(color, color)

    # =============================================================================
    # 14.1.2 — Helpers
    # =============================================================================
    def safe_float(self, value, default=0.0):
        if value is None:
            return default
        if isinstance(value, float):
            if value != value or str(value) == 'nan':
                return default
            return float(value)
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def safe_str(self, value, default=''):
        if value is None:
            return default
        if isinstance(value, float):
            if value != value or str(value) == 'nan':
                return default
            if value.is_integer():
                return str(int(value))
            return str(value)
        return str(value)

    def _fmt_date_ddmmyyyy(self, date_val):
        if date_val is None:
            return ''
        s = str(date_val).strip()
        if not s or s.lower() in ('nan', 'none', 'nat', ''):
            return ''
        if len(s) >= 10 and s[4] == '-' and s[7] == '-':
            return f"{s[8:10]}/{s[5:7]}/{s[0:4]}"
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
            try:
                return datetime.strptime(s[:19], fmt).strftime('%d/%m/%Y')
            except Exception:
                continue
        return s[:10]

    def update_tax_display(self):
        tax = self.settings_manager.get_tax_settings()
        try:
            gst_rate = float(tax.get('gst_percentage', 18))
            tcs_rate = float(tax.get('tcs_percentage', 0.1))
        except Exception:
            gst_rate = 18.0
            tcs_rate = 0.1
        self.tax_info_label.value = (
            f"CURRENT TAX RATES: GST {gst_rate}% | TCS {tcs_rate}% | "
            f"Rounding: <0.50 DOWN, ≥0.50 UP")
        try:
            self.page.update()
        except Exception:
            pass

    # =============================================================================
    # 14.1.3 — refresh  (PATCH 14.1.A: force DB reload before reading)
    # =============================================================================
    def refresh(self, e=None):
        try:
            # ---- PATCH 14.1.A: fresh cache reload ----
            # Other tabs (payments, receipts, batches) may have written to
            # disk since our last read. Re-hydrate the DB so every get_*
            # call below returns current data — not a stale in-memory snapshot.
            try:
                if hasattr(self.db, "reload"):
                    self.db.reload()
                elif hasattr(self.db, "_load_all"):
                    self.db._load_all()
            except Exception as _reload_err:
                print(f"[InvoicesTab.refresh] reload skipped: {_reload_err}")

            self.invoices = self.db.get_invoices()
            self.travelers = {
                t['id']: (f"{t.get('first_name', '')} "
                          f"{t.get('last_name', '')}").strip() or "Unnamed"
                for t in self.db.get_travelers()
            }
            self.batches = {b['id']: b for b in self.db.get_batches()}

            self.traveler_details_cache = {}
            for t in self.db.get_travelers():
                tid = t.get('id')
                if tid:
                    batch_id = t.get('batch_id')
                    bp = 0
                    bn = 'N/A'
                    if batch_id and batch_id in self.batches:
                        bp = float(self.batches[batch_id].get('price', 0) or 0)
                        bn = self.batches[batch_id].get('batch_name', 'N/A')
                    self.traveler_details_cache[tid] = {
                        'name': (f"{t.get('first_name', '')} "
                                 f"{t.get('last_name', '')}").strip()
                                or 'Unknown',
                        'batch_id': batch_id,
                        'batch_price': bp,
                        'batch_name': bn,
                    }

            self.traveler_paid = {}
            for p in self.db.get_payments():
                tid = p.get('traveler_id')
                if tid:
                    self.traveler_paid[tid] = (
                        self.traveler_paid.get(tid, 0)
                        + float(p.get('amount', 0) or 0))

            self.display_invoices()
            self.update_summary_stats()
            self.update_tax_display()
            self.page.update()
        except Exception as ex:
            print(f"Invoices refresh error: {ex}")
            import traceback
            traceback.print_exc()

    # =============================================================================
    # 14.1.4 — display_invoices
    #   (compact ⋮ menu; PATCH 14.1.B: capture invoice ID, re-fetch latest
    #    dict on every action so no stale snapshot is ever passed to a dialog)
    # =============================================================================
    def display_invoices(self, invoices=None):
        if invoices is None:
            invoices = self.invoices

        self.table.rows.clear()
        for inv in invoices:
            inv_no = self.safe_str(inv.get('invoice_no', ''))
            date_str = self._fmt_date_ddmmyyyy(inv.get('issue_date', ''))
            traveler_name = self.travelers.get(
                inv.get('traveler_id', ''), 'Unknown')

            base = self.safe_float(inv.get('amount', 0))
            disc_pct = self.safe_float(inv.get('discount_percentage', 0))
            disc_amt = self.safe_float(inv.get('discount_amount', 0))
            taxable = self.safe_float(
                inv.get('taxable_value', base - disc_amt))
            gst_pct = self.safe_float(inv.get('gst_percentage', 18))
            gst_amt = self.safe_float(inv.get('gst_amount', 0))
            tcs_pct = self.safe_float(inv.get('tcs_percentage', 0.1))
            tcs_amt = self.safe_float(inv.get('tcs_amount', 0))
            total = self.safe_float(inv.get('total_amount', 0))
            rounded = self.safe_float(
                inv.get('rounded_total', total))
            due_date = self._fmt_date_ddmmyyyy(inv.get('due_date', ''))
            status = self.safe_str(inv.get('status', 'pending')).upper()
            status_color = ("#27ae60" if status == "PAID"
                            else "#f39c12" if status == "PENDING"
                            else "#e74c3c" if status == "OVERDUE"
                            else "#95a5a6")

            tid = inv.get('traveler_id', '')
            tdet = self.traveler_details_cache.get(
                tid, {'batch_price': 0})
            bp = tdet.get('batch_price', 0)
            paid = self.traveler_paid.get(tid, 0)
            pkg_pending = bp - paid
            if bp > 0:
                if pkg_pending <= 0:
                    pkg_txt = "✅ Paid"
                    pkg_color = "#27ae60"
                else:
                    pkg_txt = f"₹{pkg_pending:,.0f}"
                    pkg_color = ("#e67e22" if pkg_pending < bp * 0.5
                                 else "#e74c3c")
            else:
                pkg_txt = "N/A"
                pkg_color = "#95a5a6"

            # ------------------------------------------------------------
            # PATCH 14.1.B — capture ID (not dict), re-fetch before dispatch
            # ------------------------------------------------------------
            inv_id = inv.get('id')

            def _make_actions_menu(_inv_id=inv_id):
                def _fresh():
                    """Return the latest in-memory version of this invoice."""
                    return next(
                        (x for x in self.invoices
                         if x.get('id') == _inv_id), None)

                def _wrap(handler):
                    def h(e, _h=handler, _f=_fresh):
                        fresh = _f()
                        if fresh is None:
                            self._snack("⚠️ Invoice no longer exists — "
                                        "refreshing…")
                            self.refresh()
                            return
                        _h(fresh)
                    return h

                return ft.PopupMenuButton(
                    icon=ft.Icons.MORE_VERT,
                    icon_color="#3498db",
                    icon_size=22,
                    tooltip="Invoice Actions",
                    items=[
                        ft.PopupMenuItem(
                            content=ft.Text("👁️  View Details"),
                            on_click=_wrap(self.view_invoice_details)),
                        ft.PopupMenuItem(
                            content=ft.Text("✏️  Modify Invoice"),
                            on_click=_wrap(self.modify_invoice)),
                        ft.PopupMenuItem(),
                        ft.PopupMenuItem(
                            content=ft.Text("📄  Export PDF"),
                            on_click=_wrap(self.export_invoice_to_pdf)),
                        ft.PopupMenuItem(
                            content=ft.Text("📊  Export Excel"),
                            on_click=_wrap(self.export_invoice_to_excel)),
                        ft.PopupMenuItem(
                            content=ft.Text("🖨️  Print Invoice"),
                            on_click=_wrap(self.print_invoice)),
                        ft.PopupMenuItem(),
                        ft.PopupMenuItem(
                            content=ft.Text("🗑️  Delete"),
                            on_click=_wrap(self.delete_invoice)),
                    ],
                )

            self.table.rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(_make_actions_menu()),         # ← MENU
                    ft.DataCell(ft.Text(inv_no, size=10,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(date_str, size=10)),
                    ft.DataCell(ft.Text(traveler_name, size=11)),
                    ft.DataCell(ft.Text(f"₹{base:,.0f}", size=10)),
                    ft.DataCell(ft.Text(
                        f"{disc_pct:.1f}%", size=10,
                        color="#c2185b" if disc_pct > 0 else None)),
                    ft.DataCell(ft.Text(
                        f"₹{disc_amt:,.0f}", size=10,
                        color="#c2185b" if disc_amt > 0 else None)),
                    ft.DataCell(ft.Text(
                        f"₹{taxable:,.0f}", size=10,
                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(f"{gst_pct}%", size=10)),
                    ft.DataCell(ft.Text(f"₹{gst_amt:,.0f}", size=10)),
                    ft.DataCell(ft.Text(f"{tcs_pct}%", size=10)),
                    ft.DataCell(ft.Text(f"₹{tcs_amt:,.0f}", size=10)),
                    ft.DataCell(ft.Text(f"₹{total:,.0f}", size=10,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(f"₹{rounded:,.0f}", size=10,
                                        color="#003366",
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(due_date, size=10)),
                    ft.DataCell(ft.Text(status, size=10,
                                        color=status_color,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(pkg_txt, size=10,
                                        color=pkg_color)),
                ]))

    # =============================================================================
    # 14.1.5 — Stats
    # =============================================================================
    def update_summary_stats(self):
        total_inv = len(self.invoices)
        pending = sum(self.safe_float(i.get('total_amount', 0))
                      for i in self.invoices
                      if i.get('status') == 'pending')
        paid = sum(self.safe_float(i.get('total_amount', 0))
                   for i in self.invoices
                   if i.get('status') == 'paid')
        discount = sum(self.safe_float(i.get('discount_amount', 0))
                       for i in self.invoices)
        tcs = sum(self.safe_float(i.get('tcs_amount', 0))
                  for i in self.invoices)

        pkg_pending = 0
        for tid, paid_amt in self.traveler_paid.items():
            det = self.traveler_details_cache.get(
                tid, {'batch_price': 0})
            bp = det.get('batch_price', 0)
            if bp > 0 and bp - paid_amt > 0:
                pkg_pending += bp - paid_amt

        self.stat_labels['total_invoices'].value = str(total_inv)
        self.stat_labels['pending'].value = format_currency_indian(pending)
        self.stat_labels['paid'].value = format_currency_indian(paid)
        self.stat_labels['discount'].value = format_currency_indian(discount)
        self.stat_labels['tcs'].value = format_currency_indian(tcs)
        self.stat_labels['package_pending'].value = format_currency_indian(
            pkg_pending)

    # =============================================================================
    # 14.1.6 — Filter
    # =============================================================================
    def apply_filters(self, e=None):
        status = self.status_filter.value or "All"
        search = (self.search_input.value or "").lower().strip()
        filtered = self.invoices
        if status != "All":
            filtered = [i for i in filtered
                        if str(i.get('status', '')) == status]
        if search:
            filtered = [
                i for i in filtered
                if (search in str(i.get('invoice_no', '')).lower()
                    or search in self.travelers.get(
                        i.get('traveler_id', ''), '').lower())]
        self.display_invoices(filtered)
        try:
            self.page.update()
        except Exception:
            pass

    # =============================================================================
    # 14.1.7 — CRUD
    # =============================================================================
    def generate_invoice(self, e):
        dlg = InvoiceDialog(self.page, self.db, self.current_user,
                            on_save=self.refresh)
        dlg.show()

    def modify_invoice(self, invoice):
        dlg = InvoiceModifyDialog(self.page, self.db, self.current_user,
                                  invoice, on_save=self.refresh)
        dlg.show()

    def view_invoice_details(self, invoice):
        dlg = InvoiceDetailsDialog(self.page, self.db, invoice)
        dlg.show()

    def delete_invoice(self, invoice):
        try:
            payments = self.db.get_payments(invoice.get('traveler_id', ''))
            has_pay = any(p.get('invoice_id') == invoice.get('id')
                          for p in payments)
        except Exception:
            has_pay = False

        if has_pay:
            self._snack("⚠️ Cannot delete — payments linked to this invoice")
            return

        def confirm(ev):
            try:
                self.db.delete_invoice(invoice['id'])
                self.db.log_activity(
                    self.current_user['id'], "delete_invoice",
                    f"Deleted invoice {invoice.get('invoice_no', '')}")
                self.page.pop_dialog()
                self.refresh()
                self._snack("✅ Invoice deleted")
            except Exception as ex:
                self._snack(f"❌ {ex}")

        dialog = ft.AlertDialog(
            title=ft.Text("Delete Invoice?"),
            content=ft.Text(
                f"Delete invoice {invoice.get('invoice_no', 'N/A')}?"),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Delete"), on_click=confirm,
                          bgcolor=ft.Colors.RED_600,
                          color=ft.Colors.WHITE),
            ],
        )
        self.page.show_dialog(dialog)

    def open_manual_invoice(self, e):
        dlg = ManualInvoiceDialog(self.page, self.db, self.current_user,
                                  on_save=self.refresh)
        dlg.show()

    # =============================================================================
    # 14.1.8 — Export PDF
    # =============================================================================
    def export_invoice_to_pdf(self, invoice):
        try:
            data = self._get_invoice_data(invoice)
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors as rl_colors
            from reportlab.platypus import (
                SimpleDocTemplate, Table, TableStyle, Paragraph,
                Spacer, Image)
            from reportlab.lib.styles import (
                getSampleStyleSheet, ParagraphStyle)
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
            from reportlab.lib.units import cm, inch

            base = get_app_base_path()
            out_dir = Path(base) / "invoices"
            out_dir.mkdir(exist_ok=True)
            fname = (f"invoice_{data['invoice_no']}_"
                     f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            filepath = out_dir / fname

            doc = SimpleDocTemplate(
                str(filepath), pagesize=A4,
                topMargin=0.5 * cm, bottomMargin=0.5 * cm,
                leftMargin=0.6 * cm, rightMargin=0.6 * cm)
            elements = []
            styles = getSampleStyleSheet()

            company_name_style = ParagraphStyle(
                'CN', parent=styles['Heading1'], fontSize=15,
                fontName='Helvetica-Bold', alignment=TA_RIGHT,
                spaceAfter=1, leading=17,
                textColor=rl_colors.HexColor('#1a252f'))
            company_info_style = ParagraphStyle(
                'CI', parent=styles['Normal'], fontSize=8,
                alignment=TA_RIGHT, spaceAfter=0, leading=10,
                textColor=rl_colors.HexColor('#555555'))
            title_style = ParagraphStyle(
                'T', parent=styles['Heading1'], fontSize=14,
                fontName='Helvetica-Bold', alignment=TA_CENTER,
                spaceBefore=4, spaceAfter=4, leading=16,
                textColor=rl_colors.HexColor('#2c3e50'))
            meta_l = ParagraphStyle('ML', parent=styles['Normal'],
                                    fontSize=10, fontName='Helvetica-Bold',
                                    alignment=TA_LEFT, leading=12)
            meta_r = ParagraphStyle('MR', parent=styles['Normal'],
                                    fontSize=10, fontName='Helvetica-Bold',
                                    alignment=TA_RIGHT, leading=12)
            box_lbl = ParagraphStyle('BL', parent=styles['Normal'],
                                     fontSize=8, fontName='Helvetica-Bold',
                                     alignment=TA_CENTER, leading=10,
                                     textColor=rl_colors.HexColor('#333'))
            body_l = ParagraphStyle('BdL', parent=styles['Normal'],
                                    fontSize=8, alignment=TA_LEFT, leading=10)
            body_r = ParagraphStyle('BdR', parent=styles['Normal'],
                                    fontSize=8, alignment=TA_RIGHT, leading=10)
            cell = ParagraphStyle('Ce', parent=styles['Normal'],
                                  fontSize=6.5, alignment=TA_LEFT, leading=8)
            cell_c = ParagraphStyle('Cc', parent=cell, alignment=TA_CENTER)
            cell_r = ParagraphStyle('Cr', parent=cell, alignment=TA_RIGHT)
            hdr = ParagraphStyle('H', parent=styles['Normal'], fontSize=6.5,
                                 fontName='Helvetica-Bold',
                                 alignment=TA_CENTER, leading=8,
                                 textColor=rl_colors.whitesmoke)
            t_lbl = ParagraphStyle('TL', parent=styles['Normal'],
                                   fontSize=8, alignment=TA_RIGHT, leading=10)
            t_val = ParagraphStyle('TV', parent=styles['Normal'],
                                   fontSize=8, alignment=TA_RIGHT, leading=10)
            t_disc_l = ParagraphStyle('TDL', parent=t_lbl,
                                      textColor=rl_colors.HexColor('#c2185b'),
                                      fontName='Helvetica-Bold')
            t_disc_v = ParagraphStyle('TDV', parent=t_val,
                                      textColor=rl_colors.HexColor('#c2185b'),
                                      fontName='Helvetica-Bold')
            g_lbl = ParagraphStyle('GL', parent=styles['Normal'],
                                   fontSize=10, fontName='Helvetica-Bold',
                                   alignment=TA_RIGHT, leading=12)
            g_val = ParagraphStyle('GV', parent=styles['Normal'],
                                   fontSize=10, fontName='Helvetica-Bold',
                                   alignment=TA_RIGHT, leading=12)

            # HEADER
            logo_path = data['logo_path']
            logo_img = None
            if logo_path and os.path.exists(logo_path):
                try:
                    logo_img = Image(logo_path, width=1.05 * inch,
                                     height=1.05 * inch)
                except Exception:
                    logo_img = None

            addr_parts = self._split_address(data['address'])
            lines = [Paragraph(data['company_name'].upper(),
                               company_name_style)]
            if data['phone'] and data['email']:
                lines.append(Paragraph(
                    f"Phone: {data['phone']} | Email: {data['email']}",
                    company_info_style))
            lines.append(Paragraph(
                f"GST: {data['gst_no']} | PAN: {data['pan_no']} | "
                f"TAN: {data['tan_no']}",
                company_info_style))
            for part in addr_parts:
                lines.append(Paragraph(part, company_info_style))

            if logo_img:
                ht = Table([[logo_img, lines]],
                           colWidths=[2.6 * cm, 16.4 * cm])
                ht.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ]))
                elements.append(ht)
            else:
                for line in lines:
                    elements.append(line)

            div = Table([[""]], colWidths=[19 * cm], rowHeights=[1])
            div.setStyle(TableStyle([
                ('LINEBELOW', (0, 0), (-1, -1), 1.2,
                 rl_colors.HexColor('#1a252f')),
            ]))
            elements.append(div)
            elements.append(Spacer(1, 4))

            elements.append(Paragraph("TAX INVOICE", title_style))
            elements.append(Spacer(1, 2))

            meta = Table(
                [[Paragraph(f"Invoice No: {data['invoice_no']}", meta_l),
                  Paragraph(
                      f"Date: {self._fmt_date_ddmmyyyy(data['issue_date'])}",
                      meta_r)]],
                colWidths=[9.5 * cm, 9.5 * cm])
            meta.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(meta)
            elements.append(Spacer(1, 4))

            trav_parts = self._split_address(data['traveler_address'])
            bill_body = [Paragraph(data['traveler_name'], body_l)]
            for p in trav_parts:
                bill_body.append(Paragraph(p, body_l))
            if data['traveler_mobile']:
                bill_body.append(Paragraph(data['traveler_mobile'], body_l))
            if data['ref_no']:
                bill_body.append(Paragraph(f"Ref: {data['ref_no']}", body_l))

            pay_body = [Paragraph(data['company_name'], body_r)]
            for p in addr_parts:
                pay_body.append(Paragraph(p, body_r))
            if data['phone']:
                pay_body.append(Paragraph(data['phone'], body_r))
            if data['email']:
                pay_body.append(Paragraph(data['email'], body_r))

            bill_box = Table(
                [[Paragraph("BILL TO", box_lbl)], [bill_body]],
                colWidths=[9.2 * cm])
            bill_box.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, 0),
                 rl_colors.HexColor('#f0f0f0')),
                ('BOX', (0, 0), (-1, -1), 0.6,
                 rl_colors.HexColor('#bdc3c7')),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))

            pay_box = Table(
                [[Paragraph("PAY TO", box_lbl)], [pay_body]],
                colWidths=[9.2 * cm])
            pay_box.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, 0),
                 rl_colors.HexColor('#f0f0f0')),
                ('BOX', (0, 0), (-1, -1), 0.6,
                 rl_colors.HexColor('#bdc3c7')),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))

            addr_tbl = Table([[bill_box, "", pay_box]],
                             colWidths=[9.2 * cm, 0.6 * cm, 9.2 * cm])
            addr_tbl.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(addr_tbl)
            elements.append(Spacer(1, 6))

            item_header = [
                Paragraph("S.No", hdr), Paragraph("Item", hdr),
                Paragraph("HSN", hdr), Paragraph("Rate", hdr),
                Paragraph("Qty", hdr), Paragraph("Amount", hdr),
                Paragraph("Disc%", hdr), Paragraph("Disc Amt", hdr),
                Paragraph("Taxable", hdr), Paragraph("CGST", hdr),
                Paragraph("SGST", hdr), Paragraph("Total", hdr),
            ]
            item_row = [
                Paragraph("1", cell_c),
                Paragraph(data['item_desc'], cell),
                Paragraph(data['hsn_code'], cell_c),
                Paragraph(f"{data['rate']:,.2f}", cell_r),
                Paragraph("1", cell_c),
                Paragraph(f"{data['base_amount']:,.2f}", cell_r),
                Paragraph(f"{data['discount_percent']:.2f}%", cell_c),
                Paragraph(f"{data['discount_amount']:,.2f}", cell_r),
                Paragraph(f"{data['taxable_value']:,.2f}", cell_r),
                Paragraph(f"{data['cgst']:,.2f}", cell_r),
                Paragraph(f"{data['sgst']:,.2f}", cell_r),
                Paragraph(f"{data['rounded_total']:,.2f}", cell_r),
            ]
            items = Table([item_header, item_row],
                          colWidths=[0.9 * cm, 4.7 * cm, 1.2 * cm, 1.5 * cm,
                                     0.8 * cm, 1.7 * cm, 1.1 * cm, 1.6 * cm,
                                     1.7 * cm, 1.5 * cm, 1.5 * cm, 1.8 * cm])
            items.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0),
                 rl_colors.HexColor('#2c3e50')),
                ('BACKGROUND', (0, 1), (-1, 1),
                 rl_colors.HexColor('#f8f9fa')),
                ('GRID', (0, 0), (-1, -1), 0.4,
                 rl_colors.HexColor('#bdc3c7')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(items)
            elements.append(Spacer(1, 8))

            totals = [
                [Paragraph("Package Cost", t_lbl),
                 Paragraph(f"{data['base_amount']:,.2f}", t_val)],
                [Paragraph(f"Discount @ {data['discount_percent']:.2f}%",
                           t_disc_l),
                 Paragraph(f"- {data['discount_amount']:,.2f}", t_disc_v)],
                [Paragraph("Taxable Value", t_lbl),
                 Paragraph(f"{data['taxable_value']:,.2f}", t_val)],
                [Paragraph("GST", t_lbl),
                 Paragraph(f"{data['gst_amount']:,.2f}", t_val)],
                [Paragraph("Total Before TCS", t_lbl),
                 Paragraph(
                     f"{data['taxable_value'] + data['gst_amount']:,.2f}",
                     t_val)],
                [Paragraph("TCS", t_lbl),
                 Paragraph(f"{data['tcs_amount']:,.2f}", t_val)],
                [Paragraph("GRAND TOTAL", g_lbl),
                 Paragraph(f"{data['rounded_total']:,.0f}", g_val)],
            ]
            totals_inner = Table(totals, colWidths=[4.4 * cm, 3.4 * cm])
            totals_inner.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 0.4,
                 rl_colors.HexColor('#bdc3c7')),
                ('BACKGROUND', (0, 1), (-1, 1),
                 rl_colors.HexColor('#fce4ec')),
                ('BACKGROUND', (0, 6), (-1, 6),
                 rl_colors.HexColor('#f9e79f')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            totals_outer = Table([["", totals_inner]],
                                 colWidths=[11.2 * cm, 7.8 * cm])
            totals_outer.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(totals_outer)
            elements.append(Spacer(1, 6))

            words = number_to_words_indian(int(data['rounded_total']))
            if words.endswith(' Only'):
                words = words[:-5]
            ws = ParagraphStyle('W', parent=styles['Normal'], fontSize=8,
                                alignment=TA_RIGHT,
                                fontName='Helvetica-Oblique',
                                textColor=rl_colors.HexColor('#555'),
                                leading=10)
            wt = Table([["", Paragraph(
                f"Amount in Words: Rupees {words} Only", ws)]],
                colWidths=[11.2 * cm, 7.8 * cm])
            wt.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(wt)
            elements.append(Spacer(1, 10))

            qr_box = Table(
                [[Paragraph("PAYMENT QR CODE", box_lbl)]],
                colWidths=[5.5 * cm], rowHeights=[2.6 * cm])
            qr_box.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 0.6,
                 rl_colors.HexColor('#bdc3c7')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ]))

            bank_lines = [
                "<b>BANK DETAILS</b>",
                f"Bank Name : {data['bank_name']}",
                f"Account Holder : {data['company_name']}",
                f"Account Number : {data['account_no']}",
                f"IFSC Code : {data['ifsc']}",
                f"UPI ID : {data['upi']}",
            ]
            bank_body = "<br/>".join([l for l in bank_lines if l])
            bs = ParagraphStyle('BS', parent=styles['Normal'], fontSize=8,
                                alignment=TA_LEFT, leading=11)
            bank_box = Table([[Paragraph(bank_body, bs)]],
                             colWidths=[12.9 * cm])
            bank_box.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 0.6,
                 rl_colors.HexColor('#bdc3c7')),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))

            qb = Table([[qr_box, "", bank_box]],
                       colWidths=[5.5 * cm, 0.6 * cm, 12.9 * cm])
            qb.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(qb)
            elements.append(Spacer(1, 8))

            decl = ParagraphStyle('D', parent=styles['Normal'], fontSize=7.5,
                                  alignment=TA_CENTER,
                                  fontName='Helvetica-Oblique',
                                  textColor=rl_colors.HexColor('#666'),
                                  leading=10)
            elements.append(Paragraph(
                "Declaration: TCS is collected as per Section 206C(1G) "
                "of the Income Tax Act, 1961. All disputes are subject "
                "to Chennai jurisdiction.", decl))
            elements.append(Spacer(1, 16))

            sign = ParagraphStyle('S', parent=styles['Normal'], fontSize=9,
                                  alignment=TA_RIGHT,
                                  fontName='Helvetica-Bold',
                                  leading=12)
            sign_sub = ParagraphStyle('SS', parent=styles['Normal'],
                                      fontSize=9, alignment=TA_RIGHT,
                                      leading=12)
            st = Table(
                [[Paragraph(f"For {data['company_name']}", sign)],
                 [Spacer(1, 30)],
                 [Paragraph("Authorised Signatory", sign_sub)]],
                colWidths=[19 * cm])
            st.setStyle(TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            elements.append(st)

            doc.build(elements)

            url = send_file_to_user(self.page, str(filepath), "Invoice PDF")
            self._snack(f"✅ PDF saved: {filepath.name}")
            if url:
                try:
                    self.page.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ PDF error: {ex}")

    def _split_address(self, address_text):
        if not address_text:
            return []
        parts = []
        for line in str(address_text).split('\n'):
            for p in line.split(','):
                if p.strip():
                    parts.append(p.strip())
        return parts

    def _get_invoice_data(self, invoice):
        company = (self.db.company_settings.iloc[0].to_dict()
                   if not self.db.company_settings.empty else {})
        bank = company.get('bank_details', {})
        if isinstance(bank, str):
            try:
                bank = json.loads(bank)
            except Exception:
                bank = {}

        tid = invoice.get('traveler_id', '')
        traveler = self.db.get_traveler_by_id(tid) if tid else None
        if traveler:
            tn = (f"{traveler.get('first_name', '')} "
                  f"{traveler.get('last_name', '')}").strip()
            ta = (traveler.get('mailing_address', '')
                  or traveler.get('passport_address', ''))
            tm = traveler.get('mobile', '')
            te = traveler.get('email', '')
            rn = traveler.get('file_reference', '')
        else:
            tn = ta = tm = te = rn = ''

        batch = self.db.get_batch_by_id(
            invoice.get('batch_id', '')) if invoice.get('batch_id') else None
        item_desc = (batch.get('batch_name', 'Package')
                     if batch else 'Package')

        base = self.safe_float(invoice.get('amount', 0))
        dp = self.safe_float(invoice.get('discount_percentage', 0))
        da = self.safe_float(invoice.get('discount_amount', 0))
        tv = self.safe_float(invoice.get('taxable_value', base - da))
        gp = self.safe_float(invoice.get('gst_percentage', 18))
        ga = self.safe_float(invoice.get('gst_amount', 0))
        tp = self.safe_float(invoice.get('tcs_percentage', 0.1))
        ta_ = self.safe_float(invoice.get('tcs_amount', 0))
        tot = self.safe_float(invoice.get('total_amount', 0))
        rt = self.safe_float(invoice.get('rounded_total', tot))

        return {
            'company_name': company.get('company_name', 'Alhudha Haj Travel'),
            'address': company.get('address', ''),
            'phone': company.get('phone', ''),
            'email': company.get('email', ''),
            'gst_no': company.get('gst_no', ''),
            'tan_no': company.get('tan_no', ''),
            'pan_no': company.get('pan_no', ''),
            'logo_path': company.get('logo_path', ''),
            'bank_name': bank.get('bank_name', ''),
            'account_no': bank.get('account_no', ''),
            'ifsc': bank.get('ifsc', '') or bank.get('swift', ''),
            'upi': bank.get('upi', '') or bank.get('iban', ''),
            'invoice_no': invoice.get('invoice_no', ''),
            'issue_date': invoice.get('issue_date', ''),
            'traveler_name': tn,
            'traveler_address': ta,
            'traveler_mobile': tm,
            'traveler_email': te,
            'ref_no': rn,
            'item_desc': item_desc,
            'hsn_code': '998555',
            'rate': base,
            'base_amount': base,
            'discount_percent': dp,
            'discount_amount': da,
            'taxable_value': tv,
            'gst_percentage': gp,
            'gst_amount': ga,
            'cgst': ga / 2 if ga else 0,
            'sgst': ga / 2 if ga else 0,
            'tcs_percentage': tp,
            'tcs_amount': ta_,
            'total_amount': tot,
            'rounded_total': rt,
        }

    # =============================================================================
    # 14.1.9 — Export Excel
    # =============================================================================
    def export_invoice_to_excel(self, invoice):
        try:
            import openpyxl
            from openpyxl.utils import get_column_letter
            from openpyxl.styles import (
                Font, Alignment, PatternFill, Border, Side)
            from openpyxl.drawing.image import Image as XLImage
            from PIL import Image as PILImage

            data = self._get_invoice_data(invoice)

            base = get_app_base_path()
            out_dir = Path(base) / "invoices"
            out_dir.mkdir(exist_ok=True)
            fname = (f"invoice_{data['invoice_no']}_"
                     f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
            filepath = out_dir / fname

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Invoice"

            logo_path = data.get('logo_path', '')
            if logo_path and os.path.exists(logo_path):
                try:
                    pil = PILImage.open(logo_path)
                    pil.thumbnail((90, 90))
                    buf = io.BytesIO()
                    pil.save(buf, format='PNG')
                    buf.seek(0)
                    xl = XLImage(buf)
                    xl.width = 90
                    xl.height = 90
                    ws.add_image(xl, 'A1')
                except Exception:
                    pass

            title_f = Font(name='Arial', size=14, bold=True, color='1A1A1A')
            sub_f = Font(name='Arial', size=9, color='555555')
            hdr_f = Font(name='Arial', size=10, bold=True, color='1A1A1A')
            nrm_f = Font(name='Arial', size=10, color='1A1A1A')
            bold_f = Font(name='Arial', size=10, bold=True, color='1A1A1A')
            disc_f = Font(name='Arial', size=10, bold=True, color='C2185B')
            grand_f = Font(name='Arial', size=12, bold=True, color='1A1A1A')

            r_align = Alignment(horizontal="right", vertical="center")
            l_align = Alignment(horizontal="left", vertical="center")
            c_align = Alignment(horizontal="center", vertical="center")

            thin = Side(style='thin', color='AAAAAA')
            borders = Border(left=thin, right=thin, top=thin, bottom=thin)
            disc_fill = PatternFill(start_color='FCE4EC', fill_type='solid')
            grand_fill = PatternFill(start_color='F9E79F', fill_type='solid')
            hdr_fill = PatternFill(start_color='E5E7E9', fill_type='solid')

            col_widths = {'A': 5, 'B': 30, 'C': 10, 'D': 14, 'E': 6,
                          'F': 15, 'G': 10, 'H': 14, 'I': 15, 'J': 13,
                          'K': 13, 'L': 15}
            for c, w in col_widths.items():
                ws.column_dimensions[c].width = w

            row = 1
            ws.merge_cells(f'B{row}:L{row}')
            ws[f'B{row}'] = data['company_name'].upper()
            ws[f'B{row}'].font = title_f
            ws[f'B{row}'].alignment = r_align
            row += 1

            ws.merge_cells(f'B{row}:L{row}')
            ws[f'B{row}'] = data['address']
            ws[f'B{row}'].font = sub_f
            ws[f'B{row}'].alignment = r_align
            row += 1

            ws.merge_cells(f'B{row}:L{row}')
            ws[f'B{row}'] = (f"Phone: {data['phone']} | "
                             f"Email: {data['email']}")
            ws[f'B{row}'].font = sub_f
            ws[f'B{row}'].alignment = r_align
            row += 1

            ws.merge_cells(f'B{row}:L{row}')
            ws[f'B{row}'] = (f"GSTIN: {data['gst_no']} | "
                             f"PAN: {data['pan_no']} | TAN: {data['tan_no']}")
            ws[f'B{row}'].font = sub_f
            ws[f'B{row}'].alignment = r_align
            row = 6

            ws.merge_cells(f'A{row}:L{row}')
            ws[f'A{row}'] = "TAX INVOICE"
            ws[f'A{row}'].font = Font(name='Arial', size=12, bold=True)
            ws[f'A{row}'].alignment = c_align
            row += 2

            ws[f'A{row}'] = f"Invoice No: {data['invoice_no']}"
            ws[f'A{row}'].font = hdr_f
            ws[f'A{row}'].alignment = l_align
            ws.merge_cells(f'A{row}:E{row}')

            ws.merge_cells(f'H{row}:L{row}')
            ws[f'H{row}'] = (f"Date: "
                             f"{self._fmt_date_ddmmyyyy(data['issue_date'])}")
            ws[f'H{row}'].font = hdr_f
            ws[f'H{row}'].alignment = r_align
            row += 2

            ws[f'A{row}'] = "BILL TO"
            ws[f'A{row}'].font = bold_f
            row += 1
            ws.merge_cells(f'A{row}:E{row}')
            ws[f'A{row}'] = data['traveler_name']
            ws[f'A{row}'].font = bold_f
            row += 1
            ws.merge_cells(f'A{row}:E{row}')
            ws[f'A{row}'] = data['traveler_address']
            ws[f'A{row}'].font = nrm_f
            row += 2

            hdr_row = row
            hdrs = ['S.No', 'Item', 'HSN', 'Rate', 'Qty', 'Amount',
                    'Disc%', 'Disc Amt', 'Taxable', 'CGST', 'SGST', 'Total']
            for i, h in enumerate(hdrs, 1):
                col = get_column_letter(i)
                c = ws[f'{col}{hdr_row}']
                c.value = h
                c.font = hdr_f
                c.fill = hdr_fill
                c.alignment = c_align
                c.border = borders
            row += 1

            vals = [
                1, data['item_desc'], data['hsn_code'], data['rate'],
                1, data['base_amount'], f"{data['discount_percent']:.2f}%",
                data['discount_amount'], data['taxable_value'],
                data['cgst'], data['sgst'], data['rounded_total']]
            for i, v in enumerate(vals, 1):
                col = get_column_letter(i)
                c = ws[f'{col}{row}']
                c.value = v
                c.font = disc_f if i in (7, 8) else nrm_f
                c.border = borders
                if i in (7, 8):
                    c.fill = disc_fill
                if i in (6, 8, 9, 12):
                    c.number_format = '₹ #,##0.00'
            row += 2

            totals = [
                ("Package Cost", data['base_amount'], False),
                (f"Discount @ {data['discount_percent']:.2f}%",
                 -data['discount_amount'], True),
                ("Taxable Value", data['taxable_value'], False),
                ("GST", data['gst_amount'], False),
                ("Total Before TCS",
                 data['taxable_value'] + data['gst_amount'], False),
                ("TCS", data['tcs_amount'], False),
                ("GRAND TOTAL", data['rounded_total'], "grand"),
            ]
            for label, val, flag in totals:
                ws.merge_cells(f'H{row}:K{row}')
                ws[f'H{row}'] = label
                ws[f'H{row}'].alignment = r_align
                ws[f'L{row}'] = val
                ws[f'L{row}'].number_format = '₹ #,##0.00'
                ws[f'L{row}'].alignment = r_align
                if flag is True:
                    ws[f'H{row}'].font = disc_f
                    ws[f'L{row}'].font = disc_f
                    ws[f'H{row}'].fill = disc_fill
                    ws[f'L{row}'].fill = disc_fill
                elif flag == "grand":
                    ws[f'H{row}'].font = grand_f
                    ws[f'L{row}'].font = grand_f
                    ws[f'H{row}'].fill = grand_fill
                    ws[f'L{row}'].fill = grand_fill
                else:
                    ws[f'H{row}'].font = bold_f
                row += 1

            wb.save(str(filepath))
            url = send_file_to_user(
                self.page, str(filepath), "Invoice Excel")
            self._snack(f"✅ Excel saved: {filepath.name}")
            if url:
                try:
                    self.page.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ Excel error: {ex}")

    def print_invoice(self, invoice):
        self._snack(
            "ℹ️ Generate PDF first (📄), then press Ctrl+P in the browser")

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass


# =================================================================================
# 14.2 — CLASS: InvoiceDialog
# =================================================================================
class InvoiceDialog:

    def __init__(self, page, db, current_user, on_save=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.on_save = on_save
        self.settings_manager = SettingsManager(db)

        self.traveler_dd = None
        self.traveler_info = None
        self.batch_label = None
        self.amount_field = None
        self.discount_type_dd = None
        self.discount_value = None
        self.gst_dd = None
        self.tcs_field = None
        self.discount_amt_lbl = None
        self.discount_pct_lbl = None
        self.taxable_lbl = None
        self.total_lbl = None
        self.rounded_lbl = None
        self.breakdown_lbl = None
        self.notes_field = None
        self.generate_btn = None
        self.dialog = None

        self._computed_discount_pct = 0.0
        self._computed_discount_amount = 0.0
        self._computed_taxable_value = 0.0

        self.setup_ui()
        self.load_tax_rates()

    # -----------------------------------------------------------------------------
    # 14.2.1 — setup_ui
    # -----------------------------------------------------------------------------
    def setup_ui(self):
        traveler_opts = [ft.dropdown.Option(key="", text="Select Traveler")]
        try:
            for t in self.db.get_travelers():
                name = (f"{t.get('first_name', '')} "
                        f"{t.get('last_name', '')}").strip()
                pp = t.get('passport_no', '')
                label = f"{name} ({pp})" if pp else name
                traveler_opts.append(
                    ft.dropdown.Option(key=str(t['id']), text=label))
        except Exception:
            pass

        self.traveler_dd = ft.Dropdown(
            label="👤 Traveler *",
            options=traveler_opts, value="",
            height=48, text_size=12)
        self.traveler_dd.on_change = self.on_traveler_change

        self.traveler_info = ft.Text(
            "No traveler selected", size=11, color=ft.Colors.GREY_600)
        self.batch_label = ft.Text(
            "Not assigned", size=12,
            weight=ft.FontWeight.BOLD, color="#2c3e50")

        self.amount_field = ft.TextField(
            label="💰 Base Amount (₹) *", value="0",
            height=48, text_size=12)
        self.amount_field.on_change = self.recalculate

        self.discount_type_dd = ft.Dropdown(
            label="🎁 Discount Type",
            options=[
                ft.dropdown.Option(key="pct", text="Percentage (%)"),
                ft.dropdown.Option(key="amt", text="Fixed Amount (₹)"),
            ],
            value="pct", height=48, text_size=12)
        self.discount_type_dd.on_change = self.on_disc_type_change

        self.discount_value = ft.TextField(
            label="🎁 Discount Value", value="0",
            height=48, text_size=12)
        self.discount_value.on_change = self.recalculate

        self.gst_dd = ft.Dropdown(
            label="📊 GST %",
            options=[ft.dropdown.Option(x) for x in
                     ["0", "5", "12", "18", "28"]],
            value="18", height=48, text_size=12)
        self.gst_dd.on_change = self.recalculate

        self.tcs_field = ft.TextField(
            label="📊 TCS %", value="0.1",
            height=48, text_size=12)
        self.tcs_field.on_change = self.recalculate

        self.discount_amt_lbl = ft.Text(
            "Discount Amount: ₹0.00", size=12,
            weight=ft.FontWeight.BOLD, color="#c2185b")
        self.discount_pct_lbl = ft.Text(
            "Effective Discount %: 0.00%", size=11, color="#c2185b")
        self.taxable_lbl = ft.Text(
            "Taxable Value: ₹0.00", size=12,
            weight=ft.FontWeight.BOLD, color="#2c3e50")
        self.total_lbl = ft.Text(
            "Total: ₹0.00", size=13, weight=ft.FontWeight.BOLD)
        self.rounded_lbl = ft.Text(
            "★ Rounded Total: ₹0", size=15,
            weight=ft.FontWeight.BOLD, color="#e67e22")
        self.breakdown_lbl = ft.Text(
            "GST: ₹0.00 | TCS: ₹0.00", size=11, color=ft.Colors.GREY_600)

        self.notes_field = ft.TextField(
            label="📝 Notes", multiline=True,
            min_lines=2, max_lines=3, text_size=12)

        self.generate_btn = ft.Button(
            content=ft.Text("💾 Generate Invoice"),
            on_click=self.save, bgcolor="#27ae60",
            color=ft.Colors.WHITE, height=45, disabled=True)

        content = ft.Column(
            controls=[
                self.traveler_dd,
                self.traveler_info,
                self.batch_label,
                self.amount_field,
                self.discount_type_dd,
                self.discount_value,
                self.gst_dd,
                self.tcs_field,
                ft.Divider(height=10),
                self.discount_amt_lbl,
                self.discount_pct_lbl,
                self.taxable_lbl,
                self.total_lbl,
                self.rounded_lbl,
                self.breakdown_lbl,
                self.notes_field,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("📄 Generate Invoice",
                          weight=ft.FontWeight.BOLD),
            content=ft.Container(content=content,
                                 width=600, height=720, padding=10),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                self.generate_btn,
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    # -----------------------------------------------------------------------------
    # 14.2.2 — load_tax_rates
    # -----------------------------------------------------------------------------
    def load_tax_rates(self):
        tax = self.settings_manager.get_tax_settings()
        try:
            gst = float(tax.get('gst_percentage', 18))
            tcs = float(tax.get('tcs_percentage', 0.1))
        except Exception:
            gst = 18.0
            tcs = 0.1
        self.gst_dd.value = (
            str(int(gst)) if int(gst) in [0, 5, 12, 18, 28] else "18")
        self.tcs_field.value = str(tcs)
        self.recalculate(None)

    # -----------------------------------------------------------------------------
    # 14.2.3 — on_traveler_change
    # -----------------------------------------------------------------------------
    def on_traveler_change(self, e):
        tid = self.traveler_dd.value
        if not tid:
            self.traveler_info.value = "No traveler selected"
            self.batch_label.value = "Not assigned"
            self.generate_btn.disabled = True
            try:
                self.page.update()
            except Exception:
                pass
            return
        t = self.db.get_traveler_by_id(tid)
        if not t:
            self.traveler_info.value = "⚠️ Not found"
            return
        name = (f"{t.get('first_name', '')} "
                f"{t.get('last_name', '')}").strip()
        self.traveler_info.value = (
            f"✅ {name} | Passport: {t.get('passport_no', '')}")
        bid = t.get('batch_id')
        if bid:
            batches = self.db.get_batches()
            batch = next((b for b in batches if b.get('id') == bid), None)
            if batch:
                self.batch_label.value = (
                    f"📦 {batch.get('batch_name', '')} | "
                    f"Price: ₹{batch.get('price', 0):,.2f}")
                self.amount_field.value = str(batch.get('price', 0))
                self.generate_btn.disabled = False
        else:
            self.batch_label.value = "No batch assigned"
            self.generate_btn.disabled = True
        self.recalculate(None)

    # -----------------------------------------------------------------------------
    # 14.2.4 — on_disc_type_change
    # -----------------------------------------------------------------------------
    def on_disc_type_change(self, e):
        if self.discount_type_dd.value == "amt":
            self.discount_value.label = "🎁 Discount Amount (₹)"
        else:
            self.discount_value.label = "🎁 Discount Value (%)"
        self.discount_value.value = "0"
        try:
            self.page.update()
        except Exception:
            pass
        self.recalculate(None)

    # -----------------------------------------------------------------------------
    # 14.2.5 — recalculate
    # -----------------------------------------------------------------------------
    def recalculate(self, e):
        try:
            amount = float(self.amount_field.value or 0)
        except (ValueError, TypeError):
            amount = 0
        try:
            dval = float(self.discount_value.value or 0)
        except (ValueError, TypeError):
            dval = 0
        try:
            gst = float(self.gst_dd.value or 0)
        except (ValueError, TypeError):
            gst = 0
        try:
            tcs = float(self.tcs_field.value or 0)
        except (ValueError, TypeError):
            tcs = 0

        if self.discount_type_dd.value == "pct":
            disc_pct = dval
            disc_amt = amount * (disc_pct / 100.0)
        else:
            disc_amt = dval
            disc_pct = (disc_amt / amount * 100.0) if amount > 0 else 0

        if disc_amt > amount:
            disc_amt = amount
            disc_pct = 100.0 if amount > 0 else 0

        taxable = amount - disc_amt
        gst_amt = taxable * (gst / 100.0)
        taxable_with_gst = taxable + gst_amt
        tcs_amt = taxable_with_gst * (tcs / 100.0)
        total = taxable_with_gst + tcs_amt
        rounded = round_as_per_rules(total)

        self._computed_discount_pct = disc_pct
        self._computed_discount_amount = disc_amt
        self._computed_taxable_value = taxable

        self.discount_amt_lbl.value = f"Discount Amount: ₹{disc_amt:,.2f}"
        self.discount_pct_lbl.value = (
            f"Effective Discount %: {disc_pct:.2f}%")
        self.taxable_lbl.value = f"Taxable Value: ₹{taxable:,.2f}"
        self.total_lbl.value = f"Total: ₹{total:,.2f}"
        self.rounded_lbl.value = f"★ Rounded Total: ₹{rounded:,.0f}"
        self.breakdown_lbl.value = (f"GST: ₹{gst_amt:,.2f} | "
                                    f"TCS: ₹{tcs_amt:,.2f}")
        try:
            self.page.update()
        except Exception:
            pass

    # -----------------------------------------------------------------------------
    # 14.2.6 — save
    # -----------------------------------------------------------------------------
    def save(self, e):
        tid = self.traveler_dd.value
        if not tid:
            self._snack("⚠️ Select a traveler")
            return
        try:
            amount = float(self.amount_field.value or 0)
        except (ValueError, TypeError):
            amount = 0
        if amount <= 0:
            self._snack("⚠️ Invalid amount")
            return
        traveler = self.db.get_traveler_by_id(tid)
        bid = traveler.get('batch_id') if traveler else None
        if not bid:
            self._snack("⚠️ Traveler has no batch")
            return

        gst = float(self.gst_dd.value or 18)
        tcs = float(self.tcs_field.value or 0.1)
        is_pct = self.discount_type_dd.value == "pct"

        try:
            if is_pct:
                inv_id = self.db.generate_invoice(
                    tid, bid, amount, gst, tcs,
                    discount_percentage=self._computed_discount_pct,
                    discount_amount=None)
            else:
                inv_id = self.db.generate_invoice(
                    tid, bid, amount, gst, tcs,
                    discount_percentage=0.0,
                    discount_amount=self._computed_discount_amount)
            try:
                self.db.log_activity(
                    self.current_user['id'], "generate_invoice",
                    f"Generated invoice for {traveler.get('first_name', '')}")
            except Exception:
                pass
            self.page.pop_dialog()
            self._snack(f"✅ Invoice {inv_id} generated")
            if self.on_save:
                self.on_save()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ {ex}")

    def show(self):
        self.page.show_dialog(self.dialog)

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass


# =================================================================================
# 14.3 — CLASS: InvoiceModifyDialog
#   PATCHES 14.3.A / B / C — prefer db.update_invoice(), cascade paid status
# =================================================================================
class InvoiceModifyDialog:

    def __init__(self, page, db, current_user, invoice, on_save=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.invoice = dict(invoice)
        self.on_save = on_save

        self.amount_field = None
        self.disc_type_dd = None
        self.disc_value = None
        self.gst_dd = None
        self.tcs_field = None
        self.status_dd = None
        self.notes_field = None
        self.disc_amt_lbl = None
        self.disc_pct_lbl = None
        self.taxable_lbl = None
        self.rounded_lbl = None
        self.dialog = None
        self._computed = {}

        self.setup_ui()
        self.load_data()

    # -----------------------------------------------------------------------------
    # 14.3.1 — setup_ui
    # -----------------------------------------------------------------------------
    def setup_ui(self):
        self.amount_field = ft.TextField(
            label="Base Amount (₹)", height=48, text_size=12)
        self.amount_field.on_change = self.recalc

        self.disc_type_dd = ft.Dropdown(
            label="Discount Type",
            options=[
                ft.dropdown.Option(key="pct", text="Percentage (%)"),
                ft.dropdown.Option(key="amt", text="Fixed Amount (₹)"),
            ], value="pct", height=48, text_size=12)
        self.disc_type_dd.on_change = self.recalc

        self.disc_value = ft.TextField(
            label="Discount Value", value="0",
            height=48, text_size=12)
        self.disc_value.on_change = self.recalc

        self.gst_dd = ft.Dropdown(
            label="GST %",
            options=[ft.dropdown.Option(x) for x in
                     ["0", "5", "12", "18", "28"]],
            value="18", height=48, text_size=12)
        self.gst_dd.on_change = self.recalc

        self.tcs_field = ft.TextField(
            label="TCS %", value="0.1",
            height=48, text_size=12)
        self.tcs_field.on_change = self.recalc

        self.status_dd = ft.Dropdown(
            label="Status",
            options=[ft.dropdown.Option(x) for x in
                     ["pending", "paid", "overdue", "cancelled"]],
            value="pending", height=48, text_size=12)

        self.notes_field = ft.TextField(
            label="Notes", multiline=True,
            min_lines=2, max_lines=3, text_size=12)

        self.disc_amt_lbl = ft.Text(
            "Discount Amount: ₹0.00", size=12,
            weight=ft.FontWeight.BOLD, color="#c2185b")
        self.disc_pct_lbl = ft.Text(
            "Effective Discount %: 0.00%", size=11, color="#c2185b")
        self.taxable_lbl = ft.Text(
            "Taxable Value: ₹0.00", size=12,
            weight=ft.FontWeight.BOLD)
        self.rounded_lbl = ft.Text(
            "★ Rounded Total: ₹0", size=15,
            weight=ft.FontWeight.BOLD, color="#e67e22")

        content = ft.Column(
            controls=[
                ft.Text(f"Invoice: {self.invoice.get('invoice_no', '')}",
                        size=13, weight=ft.FontWeight.BOLD),
                self.amount_field,
                self.disc_type_dd,
                self.disc_value,
                self.gst_dd,
                self.tcs_field,
                self.status_dd,
                ft.Divider(height=10),
                self.disc_amt_lbl,
                self.disc_pct_lbl,
                self.taxable_lbl,
                self.rounded_lbl,
                self.notes_field,
            ], spacing=10, scroll=ft.ScrollMode.AUTO)

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("✏️ Modify Invoice",
                          weight=ft.FontWeight.BOLD),
            content=ft.Container(content=content,
                                 width=560, height=650, padding=10),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content=ft.Text("💾 Save Changes"),
                          on_click=self.save,
                          bgcolor="#27ae60", color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    # -----------------------------------------------------------------------------
    # 14.3.2 — load_data
    # -----------------------------------------------------------------------------
    def load_data(self):
        inv = self.invoice
        self.amount_field.value = f"{self._f(inv.get('amount', 0)):.2f}"
        existing_pct = self._f(inv.get('discount_percentage', 0))
        existing_amt = self._f(inv.get('discount_amount', 0))

        use_amt = (abs(existing_pct - round(existing_pct, 2)) > 0.001
                   and existing_amt > 0)
        if use_amt:
            self.disc_type_dd.value = "amt"
            self.disc_value.value = f"{existing_amt:.2f}"
        else:
            self.disc_type_dd.value = "pct"
            self.disc_value.value = f"{existing_pct:.2f}"

        self.gst_dd.value = str(int(self._f(inv.get('gst_percentage', 18))))
        self.tcs_field.value = f"{self._f(inv.get('tcs_percentage', 0.1)):.2f}"
        self.status_dd.value = str(inv.get('status', 'pending'))
        self.notes_field.value = str(inv.get('notes', ''))
        self.recalc(None)

    def _f(self, v, d=0.0):
        try:
            f = float(v)
            if f != f:
                return d
            return f
        except (ValueError, TypeError):
            return d

    # -----------------------------------------------------------------------------
    # 14.3.3 — recalc
    # -----------------------------------------------------------------------------
    def recalc(self, e=None):
        try:
            amount = float(self.amount_field.value or 0)
        except (ValueError, TypeError):
            amount = 0
        try:
            dval = float(self.disc_value.value or 0)
        except (ValueError, TypeError):
            dval = 0
        try:
            gst = float(self.gst_dd.value or 0)
        except (ValueError, TypeError):
            gst = 0
        try:
            tcs = float(self.tcs_field.value or 0)
        except (ValueError, TypeError):
            tcs = 0

        if self.disc_type_dd.value == "pct":
            disc_pct = dval
            disc_amt = amount * (disc_pct / 100.0)
        else:
            disc_amt = dval
            disc_pct = (disc_amt / amount * 100.0) if amount > 0 else 0

        if disc_amt > amount:
            disc_amt = amount
            disc_pct = 100.0 if amount > 0 else 0

        taxable = amount - disc_amt
        gst_amt = taxable * (gst / 100.0)
        taxable_with_gst = taxable + gst_amt
        tcs_amt = taxable_with_gst * (tcs / 100.0)
        total = taxable_with_gst + tcs_amt
        rounded = round_as_per_rules(total)

        self._computed = {
            'discount_pct': disc_pct, 'discount_amt': disc_amt,
            'taxable': taxable, 'gst': gst, 'gst_amt': gst_amt,
            'tcs': tcs, 'tcs_amt': tcs_amt,
            'total': total, 'rounded': rounded}

        self.disc_amt_lbl.value = f"Discount Amount: ₹{disc_amt:,.2f}"
        self.disc_pct_lbl.value = f"Effective Discount %: {disc_pct:.2f}%"
        self.taxable_lbl.value = f"Taxable Value: ₹{taxable:,.2f}"
        self.rounded_lbl.value = f"★ Rounded Total: ₹{rounded:,.0f}"
        try:
            self.page.update()
        except Exception:
            pass

    # -----------------------------------------------------------------------------
    # 14.3.4 — save  (PATCH 14.3.A: prefer db.update_invoice)
    # -----------------------------------------------------------------------------
    def save(self, e):
        try:
            c = self._computed
            if not c:
                # ensure recalc ran at least once
                self.recalc(None)
                c = self._computed

            new_status = (self.status_dd.value or 'pending').lower()
            old_status = str(self.invoice.get('status', 'pending')).lower()

            update = {
                'amount': float(self.amount_field.value or 0),
                'discount_percentage': c['discount_pct'],
                'discount_amount': c['discount_amt'],
                'taxable_value': c['taxable'],
                'gst_percentage': c['gst'],
                'gst_amount': c['gst_amt'],
                'tcs_percentage': c['tcs'],
                'tcs_amount': c['tcs_amt'],
                'total_amount': c['total'],
                'rounded_total': c['rounded'],
                'status': new_status,
                'notes': (self.notes_field.value or '').strip(),
            }

            # ---- PATCH 14.3.A: use DB method when available so cascade
            #      hooks / audit fields fire consistently ----
            if hasattr(self.db, "update_invoice"):
                self.db.update_invoice(self.invoice['id'], **update)
            else:
                for k, v in update.items():
                    self.db.invoices.loc[
                        self.db.invoices['id'] == self.invoice['id'], k] = v
                self.db._save_df(self.db.invoices, "invoices.csv")

            # ---- PATCH 14.3.B / 14.3.C: cascade status change ----
            tid = self.invoice.get('traveler_id', '')
            inv_id = self.invoice.get('id')
            try:
                if new_status == 'paid' and old_status != 'paid':
                    self._cascade_mark_paid(tid, inv_id, c['rounded'])
                elif new_status != 'paid' and old_status == 'paid':
                    self._cascade_unmark_paid(tid, inv_id)
            except Exception as _ce:
                print(f"[InvoiceModifyDialog] cascade error: {_ce}")

            try:
                self.db.log_activity(
                    self.current_user['id'], "modify_invoice",
                    f"Modified invoice {self.invoice.get('invoice_no', '')} "
                    f"({old_status} → {new_status})")
            except Exception:
                pass

            self.page.pop_dialog()
            self._snack("✅ Invoice updated")
            if self.on_save:
                self.on_save()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ {ex}")

    # -----------------------------------------------------------------------------
    # 14.3.5 — _cascade_mark_paid  (PATCH 14.3.B)
    #   When invoice status flips to 'paid', create/sync the payment record
    #   so traveler_paid + Pkg-Pending stay consistent across tabs.
    # -----------------------------------------------------------------------------
    def _cascade_mark_paid(self, traveler_id, invoice_id, amount):
        if not traveler_id or amount is None or amount <= 0:
            return
        try:
            # Look for an existing payment linked to this invoice
            existing = None
            try:
                payments = self.db.get_payments(traveler_id) or []
            except Exception:
                payments = []
            for p in payments:
                if str(p.get('invoice_id', '')) == str(invoice_id):
                    existing = p
                    break

            if existing:
                # Sync amount if drifted
                try:
                    cur = float(existing.get('amount', 0) or 0)
                except Exception:
                    cur = 0.0
                if abs(cur - float(amount)) > 0.01:
                    if hasattr(self.db, "update_payment"):
                        self.db.update_payment(
                            existing['id'],
                            amount=float(amount),
                            notes="Auto-synced via invoice status")
                    else:
                        self.db.payments.loc[
                            self.db.payments['id'] == existing['id'],
                            'amount'] = float(amount)
                        self.db._save_df(self.db.payments, "payments.csv")
            else:
                payload = {
                    'traveler_id': traveler_id,
                    'invoice_id': invoice_id,
                    'amount': float(amount),
                    'payment_date': datetime.now().strftime("%Y-%m-%d"),
                    'method': 'Auto (invoice status)',
                    'notes': 'Auto-created when invoice marked paid',
                }
                if hasattr(self.db, "add_payment"):
                    try:
                        # Support both signatures: add_payment(dict) or
                        # add_payment(**kwargs)
                        self.db.add_payment(payload)
                    except TypeError:
                        self.db.add_payment(**payload)
                else:
                    # Very old schema — append to DataFrame directly
                    try:
                        self.db.payments = pd.concat(
                            [self.db.payments,
                             pd.DataFrame([payload])],
                            ignore_index=True)
                        self.db._save_df(self.db.payments, "payments.csv")
                    except Exception as _e:
                        print(f"[cascade_mark_paid fallback] {_e}")
        except Exception as ex:
            print(f"[cascade_mark_paid] {ex}")

    # -----------------------------------------------------------------------------
    # 14.3.6 — _cascade_unmark_paid  (PATCH 14.3.C)
    #   Status moved OUT of 'paid' → delete only auto-generated payments
    #   (never delete a real payment the user entered manually).
    # -----------------------------------------------------------------------------
    def _cascade_unmark_paid(self, traveler_id, invoice_id):
        if not traveler_id:
            return
        try:
            try:
                payments = self.db.get_payments(traveler_id) or []
            except Exception:
                payments = []

            target = None
            for p in payments:
                if (str(p.get('invoice_id', '')) == str(invoice_id)
                        and 'auto' in str(p.get('method', '')).lower()):
                    target = p
                    break

            if not target:
                return

            if hasattr(self.db, "delete_payment"):
                self.db.delete_payment(target['id'])
            else:
                self.db.payments = self.db.payments[
                    self.db.payments['id'] != target['id']]
                self.db._save_df(self.db.payments, "payments.csv")
        except Exception as ex:
            print(f"[cascade_unmark_paid] {ex}")

    def show(self):
        self.page.show_dialog(self.dialog)

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass


# =================================================================================
# 14.4 — CLASS: InvoiceDetailsDialog
# =================================================================================
class InvoiceDetailsDialog:

    def __init__(self, page, db, invoice):
        self.page = page
        self.db = db
        self.invoice = invoice
        self.dialog = None
        self.setup_ui()

    def _fmt(self, d):
        if not d:
            return ''
        s = str(d).strip()
        if len(s) >= 10 and s[4] == '-' and s[7] == '-':
            return f"{s[8:10]}/{s[5:7]}/{s[0:4]}"
        return s[:10]

    def _f(self, v, d=0.0):
        try:
            f = float(v)
            return d if f != f else f
        except (ValueError, TypeError):
            return d

    # -----------------------------------------------------------------------------
    # 14.4.1 — setup_ui
    # -----------------------------------------------------------------------------
    def setup_ui(self):
        inv = self.invoice
        tid = inv.get('traveler_id', '')
        traveler = self.db.get_traveler_by_id(tid) if tid else None
        traveler_name = (
            f"{traveler.get('first_name', '')} "
            f"{traveler.get('last_name', '')}").strip() if traveler else 'Unknown'

        company_name = "Alhudha Haj Travel"
        try:
            if not self.db.company_settings.empty:
                company_name = str(
                    self.db.company_settings.iloc[0].get(
                        'company_name', company_name))
        except Exception:
            pass

        base = self._f(inv.get('amount', 0))
        disc_pct = self._f(inv.get('discount_percentage', 0))
        disc_amt = self._f(inv.get('discount_amount', 0))
        taxable = self._f(inv.get('taxable_value', base - disc_amt))
        gst_pct = self._f(inv.get('gst_percentage', 18))
        gst_amt = self._f(inv.get('gst_amount', 0))
        tcs_pct = self._f(inv.get('tcs_percentage', 0.1))
        tcs_amt = self._f(inv.get('tcs_amount', 0))
        total = self._f(inv.get('total_amount', 0))
        rounded = self._f(inv.get('rounded_total', total))

        try:
            words = number_to_words_indian(int(rounded))
        except Exception:
            words = ''

        def row(label, value, color=None):
            return ft.Row([
                ft.Text(label, width=180,
                        weight=ft.FontWeight.BOLD, size=12),
                ft.Text(str(value), size=12, expand=True, selectable=True,
                        color=color),
            ], spacing=8)

        content = ft.Column(
            controls=[
                ft.Text(company_name, size=16,
                        weight=ft.FontWeight.BOLD, color="#1e40af"),
                ft.Text(f"Invoice: {inv.get('invoice_no', '')}",
                        size=13, weight=ft.FontWeight.BOLD),
                ft.Divider(height=8),
                row("Date", self._fmt(inv.get('issue_date', ''))),
                row("Due Date", self._fmt(inv.get('due_date', ''))),
                row("Status", str(inv.get('status', 'pending')).upper()),
                ft.Divider(height=8),
                row("Traveler", traveler_name),
                ft.Divider(height=8),
                row("Package Cost", f"₹{base:,.2f}"),
                row(f"Discount @ {disc_pct:.2f}%",
                    f"- ₹{disc_amt:,.2f}", "#c2185b"),
                row("Taxable Value", f"₹{taxable:,.2f}"),
                row(f"GST @ {gst_pct}%", f"₹{gst_amt:,.2f}"),
                row("Total Before TCS",
                    f"₹{taxable + gst_amt:,.2f}"),
                row(f"TCS @ {tcs_pct}%", f"₹{tcs_amt:,.2f}"),
                ft.Divider(height=8),
                row("Total Amount", f"₹{total:,.2f}"),
                row("★ Rounded Total", f"₹{rounded:,.0f}", "#e67e22"),
                ft.Divider(height=8),
                ft.Text(f"Amount in Words: {words}", size=11,
                        italic=True, color="#27ae60"),
                ft.Text(f"Notes: {inv.get('notes', '')}", size=11,
                        color=ft.Colors.GREY_600),
            ], spacing=6, scroll=ft.ScrollMode.AUTO)

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"📄 {inv.get('invoice_no', 'Invoice')}",
                          weight=ft.FontWeight.BOLD),
            content=ft.Container(content=content,
                                 width=600, height=600, padding=10),
            actions=[
                ft.Button(content=ft.Text("Close"),
                          on_click=lambda e: self.page.pop_dialog(),
                          bgcolor="#3498db", color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def show(self):
        self.page.show_dialog(self.dialog)


# =================================================================================
# 14.5 — CLASS: ManualInvoiceDialog
# =================================================================================
class ManualInvoiceDialog:

    def __init__(self, page, db, current_user, on_save=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.on_save = on_save
        self.settings_manager = SettingsManager(db)

        self.cust_name = None
        self.cust_phone = None
        self.cust_email = None
        self.traveler_dd = None
        self.package_dd = None
        self.invoice_date = None
        self.items_table = None
        self.item_rows = []

        self.sub_lbl = None
        self.disc_lbl = None
        self.taxable_lbl = None
        self.total_lbl = None

        self.dialog = None
        self.setup_ui()

    # -----------------------------------------------------------------------------
    # 14.5.1 — setup_ui
    # -----------------------------------------------------------------------------
    def setup_ui(self):
        topts = [ft.dropdown.Option(key="", text="Select Traveler")]
        try:
            for t in self.db.get_travelers():
                name = (f"{t.get('first_name', '')} "
                        f"{t.get('last_name', '')}").strip()
                topts.append(ft.dropdown.Option(
                    key=str(t['id']), text=name))
        except Exception:
            pass
        self.traveler_dd = ft.Dropdown(
            label="Traveler", options=topts, value="",
            width=200, height=48, text_size=12)

        bopts = [ft.dropdown.Option(key="", text="Select Batch")]
        try:
            for b in self.db.get_batches():
                bopts.append(ft.dropdown.Option(
                    key=str(b['id']),
                    text=(f"{b.get('batch_name', '')} "
                          f"(₹{b.get('price', 0):,.0f})")))
        except Exception:
            pass
        self.package_dd = ft.Dropdown(
            label="Package", options=bopts, value="",
            width=280, height=48, text_size=12)

        self.invoice_date = ft.TextField(
            label="Invoice Date (YYYY-MM-DD)",
            value=datetime.now().strftime("%Y-%m-%d"),
            width=200, height=48, text_size=12)

        self.cust_name = ft.TextField(
            label="Customer Name *", width=200, height=48, text_size=12)
        self.cust_phone = ft.TextField(
            label="Phone *", width=180, height=48, text_size=12)
        self.cust_email = ft.TextField(
            label="Email", width=220, height=48, text_size=12)

        self.items_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("#")),
                ft.DataColumn(ft.Text("Item")),
                ft.DataColumn(ft.Text("Rate")),
                ft.DataColumn(ft.Text("Qty")),
                ft.DataColumn(ft.Text("Amount")),
                ft.DataColumn(ft.Text("Disc%")),
                ft.DataColumn(ft.Text("Taxable")),
                ft.DataColumn(ft.Text("CGST")),
                ft.DataColumn(ft.Text("SGST")),
                ft.DataColumn(ft.Text("Total")),
                ft.DataColumn(ft.Text("")),
            ],
            rows=[], heading_row_color=ft.Colors.BLUE_GREY_800,
            heading_row_height=36, data_row_min_height=40,
            column_spacing=10,
        )

        self.sub_lbl = ft.Text("Package Cost: ₹0.00", size=12,
                               weight=ft.FontWeight.BOLD)
        self.disc_lbl = ft.Text("Discount: ₹0.00", size=12,
                                color="#c2185b",
                                weight=ft.FontWeight.BOLD)
        self.taxable_lbl = ft.Text("Taxable: ₹0.00", size=12,
                                   weight=ft.FontWeight.BOLD)
        self.total_lbl = ft.Text("★ Rounded Total: ₹0", size=14,
                                 weight=ft.FontWeight.BOLD,
                                 color="#e67e22")

        def add_item(e):
            bid = self.package_dd.value
            if not bid:
                self._snack("⚠️ Select a Package first")
                return
            try:
                batch = None
                for b in self.db.get_batches():
                    if str(b.get('id')) == str(bid):
                        batch = b
                        break
                if not batch:
                    return
                rate = float(batch.get('price', 0) or 0)
                self.item_rows.append({
                    'item': batch.get('batch_name', 'Package'),
                    'hsn': '998555',
                    'rate': rate,
                    'qty': 1,
                    'discount_percent': 0,
                })
                self.refresh_items()
            except Exception as ex:
                self._snack(f"❌ {ex}")

        add_btn = ft.Button(
            content=ft.Text("➕ Add Item"),
            on_click=add_item, height=42,
            bgcolor="#3498db", color=ft.Colors.WHITE)

        def generate(e):
            self.generate_invoice()

        gen_btn = ft.Button(
            content=ft.Text("💾 Generate Invoice"),
            on_click=generate, height=42,
            bgcolor="#27ae60", color=ft.Colors.WHITE)

        content = ft.Column(
            controls=[
                ft.Text("🧾 Manual Invoice Creator", size=16,
                        weight=ft.FontWeight.BOLD, color="#1e40af"),
                ft.Row([self.invoice_date, self.traveler_dd],
                       spacing=10),
                ft.Row([self.cust_name, self.cust_phone, self.cust_email],
                       spacing=10, wrap=True),
                ft.Divider(),
                ft.Row([self.package_dd, add_btn], spacing=10),
                ft.Container(
                    content=ft.Column([self.items_table],
                                      scroll=ft.ScrollMode.AUTO),
                    bgcolor=ft.Colors.GREY_50,
                    border=ft.Border.all(1, ft.Colors.GREY_300),
                    border_radius=8, padding=5, height=280),
                ft.Divider(),
                self.sub_lbl, self.disc_lbl,
                self.taxable_lbl, self.total_lbl,
            ],
            spacing=10, scroll=ft.ScrollMode.AUTO)

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("🧾 Manual Invoice",
                          weight=ft.FontWeight.BOLD),
            content=ft.Container(content=content,
                                 width=900, height=720, padding=10),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                gen_btn,
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    # -----------------------------------------------------------------------------
    # 14.5.2 — refresh_items
    # -----------------------------------------------------------------------------
    def refresh_items(self):
        self.items_table.rows.clear()
        for i, item in enumerate(self.item_rows):
            rate = item['rate']
            qty = item['qty']
            amount = rate * qty
            disc_amt = amount * (item['discount_percent'] / 100)
            taxable = amount - disc_amt
            tax = self.settings_manager.get_tax_settings()
            try:
                gst = float(tax.get('gst_percentage', 18))
            except Exception:
                gst = 18
            cgst = taxable * (gst / 200)
            sgst = taxable * (gst / 200)
            total = taxable + cgst + sgst

            def rm(idx=i):
                def handler(e):
                    self.item_rows.pop(idx)
                    self.refresh_items()
                return handler

            self.items_table.rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(str(i + 1))),
                    ft.DataCell(ft.Text(item['item'])),
                    ft.DataCell(ft.Text(f"₹{rate:,.0f}")),
                    ft.DataCell(ft.Text(str(qty))),
                    ft.DataCell(ft.Text(f"₹{amount:,.0f}")),
                    ft.DataCell(ft.Text(f"{item['discount_percent']:.1f}%")),
                    ft.DataCell(ft.Text(f"₹{taxable:,.0f}")),
                    ft.DataCell(ft.Text(f"₹{cgst:,.0f}")),
                    ft.DataCell(ft.Text(f"₹{sgst:,.0f}")),
                    ft.DataCell(ft.Text(f"₹{total:,.0f}")),
                    ft.DataCell(ft.IconButton(
                        icon=ft.Icons.DELETE, icon_size=16,
                        icon_color="#e74c3c",
                        on_click=rm())),
                ]))

        tax = self.settings_manager.get_tax_settings()
        try:
            gst = float(tax.get('gst_percentage', 18))
        except Exception:
            gst = 18

        sub = sum(i['rate'] * i['qty'] for i in self.item_rows)
        disc = sum(i['rate'] * i['qty'] * (i['discount_percent'] / 100)
                   for i in self.item_rows)
        taxable = sub - disc
        gst_amt = taxable * (gst / 100)
        total = taxable + gst_amt
        rounded = round_as_per_rules(total)

        self.sub_lbl.value = f"Package Cost: ₹{sub:,.2f}"
        self.disc_lbl.value = f"Discount: ₹{disc:,.2f}"
        self.taxable_lbl.value = f"Taxable: ₹{taxable:,.2f}"
        self.total_lbl.value = f"★ Rounded Total: ₹{rounded:,.0f}"
        try:
            self.page.update()
        except Exception:
            pass

    # -----------------------------------------------------------------------------
    # 14.5.3 — generate_invoice
    # -----------------------------------------------------------------------------
    def generate_invoice(self):
        if not self.item_rows:
            self._snack("⚠️ Add at least one item")
            return
        name = (self.cust_name.value or '').strip()
        phone = (self.cust_phone.value or '').strip()
        if not name or not phone:
            self._snack("⚠️ Customer name and phone required")
            return

        tid = self.traveler_dd.value
        bid = self.package_dd.value

        try:
            if not tid:
                parts = name.split()
                traveler_data = {
                    'first_name': parts[0] if parts else '',
                    'last_name': ' '.join(parts[1:]) if len(parts) > 1 else '',
                    'passport_name': name.upper(),
                    'mobile': phone,
                    'email': (self.cust_email.value or '').strip(),
                    'passport_no': 'N/A',
                    'status': 'Active',
                    'batch_id': bid}
                tid = self.db.add_traveler(traveler_data)

            tax = self.settings_manager.get_tax_settings()
            gst = float(tax.get('gst_percentage', 18))
            tcs = float(tax.get('tcs_percentage', 0.1))

            sub = sum(i['rate'] * i['qty'] for i in self.item_rows)
            disc = sum(i['rate'] * i['qty'] * (i['discount_percent'] / 100)
                       for i in self.item_rows)

            inv_id = self.db.generate_invoice(
                tid, bid, sub, gst, tcs,
                discount_percentage=0.0,
                discount_amount=disc)

            try:
                self.db.log_activity(
                    self.current_user['id'], "manual_invoice",
                    f"Created manual invoice for {name}")
            except Exception:
                pass

            self.page.pop_dialog()
            self._snack(f"✅ Invoice generated: {inv_id}")
            if self.on_save:
                self.on_save()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ {ex}")

    def show(self):
        self.page.show_dialog(self.dialog)

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass


# =================================================================================
# SECTION 14 END (FLET 1.0.0 VERSION)
# =================================================================================