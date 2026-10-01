# =================================================================================
# SECTION 15 (FLET 1.0.0 VERSION) — RECEIPTS TAB
# =================================================================================
# v1.3 — Row Selection + Data-Loading Safety
#   • ADDED: Tap any row → SELECTS (does not open Edit)
#   • ADDED: Toolbar 📄 PDF / 🖨️ Print act on selected row
#   • ADDED: "Sel" column with ✓ marker
#   • FIXED: on_select_change (correct Flet 1.0.0 param)
#   • FIXED: refresh() no longer calls db.reload() (was wiping cache)
#   • Action icons 16 → 18 for easier mobile tapping
#   • Preserved: 15.1.A (fresh reload), 15.1.B (lifetime Pkg-Pending),
#                15.1.C (action handlers re-fetch), 15.1.D (delete warns)
# =================================================================================

import flet as ft
import os
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

from core.helpers import (
    get_app_base_path,
    number_to_words_indian,
    format_currency_indian,
    send_file_to_user,
)


# =================================================================================
# 15.1 — CLASS: ReceiptsTab
# =================================================================================
class ReceiptsTab:

    def __init__(self, page: ft.Page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user

        self.receipts = []
        self.travelers = {}
        self.payments = {}
        self.invoices = {}
        self.batches = {}

        self.stat_labels = {}
        self.traveler_filter = None
        self.search_input = None
        self.date_from = None
        self.date_to = None
        self.table = None
        self.filtered_count_label = None
        self.selection_label = None
        self.root = None

        # Currently selected receipt (for toolbar PDF/Print)
        self._selected_receipt_id = None

        self.setup_ui()
        self.refresh()

    def build(self):
        return self.root

    # =============================================================================
    # 15.1.1 — setup_ui
    # =============================================================================
    def setup_ui(self):
        # ---- TOOLBAR ----
        def _tb(label, color, handler):
            return ft.Button(
                content=ft.Text(label, size=11,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE,
                                no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS),
                on_click=handler, height=38,
                bgcolor=color,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=8)),
            )

        toolbar = ft.Row(
            controls=[
                _tb("🔄 Refresh", "#3498db", self.refresh),
                _tb("📄 PDF (selected)", "#e74c3c",
                    self.export_pdf_selected),
                _tb("🖨️ Print (selected)", "#9b59b6",
                    self.print_receipt_selected),
            ],
            spacing=8, wrap=True,
        )

        # ---- FILTER BAR ----
        self.traveler_filter = ft.Dropdown(
            label="Traveler",
            options=[ft.dropdown.Option(key="", text="All Travelers")],
            value="", height=48, text_size=11)
        self.traveler_filter.on_change = self.apply_filters

        self.search_input = ft.TextField(
            hint_text="🔍 Search receipt no, amount, or invoice...",
            height=48, text_size=12,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8))
        self.search_input.on_change = self.apply_filters

        self.date_from = ft.TextField(
            label="From",
            value=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
            height=48, text_size=11)
        self.date_from.on_change = self.apply_filters

        self.date_to = ft.TextField(
            label="To",
            value=datetime.now().strftime("%Y-%m-%d"),
            height=48, text_size=11)
        self.date_to.on_change = self.apply_filters

        filter_bar = ft.ResponsiveRow(
            controls=[
                ft.Container(content=self.traveler_filter,
                             col={"xs": 12, "sm": 6, "md": 3}),
                ft.Container(content=self.search_input,
                             col={"xs": 12, "sm": 6, "md": 3}),
                ft.Container(content=self.date_from,
                             col={"xs": 6, "sm": 6, "md": 3}),
                ft.Container(content=self.date_to,
                             col={"xs": 6, "sm": 6, "md": 3}),
            ],
            spacing=8, run_spacing=8,
        )

        # ---- STAT CARDS ----
        stat_configs = [
            ("total_receipts",  "📊 Receipts",   "#3498db"),
            ("total_amount",    "💰 Amount",     "#27ae60"),
            ("today",           "📅 Today",      "#f39c12"),
            ("package_pending", "📦 Pkg Pend",   "#e74c3c"),
            ("invoice_pending", "📄 Inv Pend",   "#e67e22"),
        ]

        stat_cards = []
        for key, label, color in stat_configs:
            value_label = ft.Text("0", size=14,
                                  weight=ft.FontWeight.BOLD,
                                  color=ft.Colors.WHITE)
            self.stat_labels[key] = value_label
            card = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(label, size=9, color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD,
                                no_wrap=False, max_lines=2),
                        value_label,
                    ],
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=8,
                bgcolor=color,
                border_radius=10,
                height=64,
            )
            stat_cards.append(card)

        stats_row = ft.ResponsiveRow(
            controls=[
                ft.Container(content=c,
                             col={"xs": 6, "sm": 6, "md": 4, "lg": 2})
                for c in stat_cards
            ],
            spacing=6, run_spacing=6,
        )

        self.filtered_count_label = ft.Text(
            "🔍 Showing: 0 receipts", size=11,
            weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_800)

        self.selection_label = ft.Text("", size=10,
                                       color=ft.Colors.BLUE_700,
                                       weight=ft.FontWeight.BOLD,
                                       italic=True)

        # ---- TABLE ----
        self.table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Sel", size=11)),
                ft.DataColumn(ft.Text("Receipt", size=11)),
                ft.DataColumn(ft.Text("Date", size=11)),
                ft.DataColumn(ft.Text("Traveler", size=11)),
                ft.DataColumn(ft.Text("Passport", size=11)),
                ft.DataColumn(ft.Text("Method", size=11)),
                ft.DataColumn(ft.Text("Amount", size=11)),
                ft.DataColumn(ft.Text("Invoice", size=11)),
                ft.DataColumn(ft.Text("Status", size=11)),
                ft.DataColumn(ft.Text("Pkg Pend", size=11)),
                ft.DataColumn(ft.Text("Inv Pend", size=11)),
                ft.DataColumn(ft.Text("Actions", size=11)),
            ],
            rows=[], column_spacing=10,
            heading_row_color=ft.Colors.BLUE_GREY_800,
            heading_row_height=40,
            data_row_min_height=44,
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
                    ft.Container(content=toolbar, padding=8,
                                 bgcolor=ft.Colors.WHITE,
                                 border_radius=10),
                    ft.Container(content=filter_bar, padding=8,
                                 bgcolor=ft.Colors.WHITE,
                                 border_radius=10),
                    stats_row,
                    self.filtered_count_label,
                    ft.Container(
                        content=ft.Column([
                            ft.Text("💡 Tap a row to SELECT it, then use "
                                    "toolbar 📄 PDF / 🖨️ Print. "
                                    "Use icons in Actions column for "
                                    "per-row actions.",
                                    size=10,
                                    color=ft.Colors.GREY_600,
                                    italic=True),
                            self.selection_label,
                            ft.Row(
                                [self.table],
                                scroll=ft.ScrollMode.ADAPTIVE,
                            ),
                        ], spacing=6),
                        bgcolor=ft.Colors.WHITE,
                        border_radius=10, padding=10),
                ],
                spacing=10, scroll=ft.ScrollMode.AUTO,
            ),
            padding=10, bgcolor="#f0f2f5", expand=True,
        )

    def _darken(self, color):
        return {
            "#3498db": "#2471a3", "#27ae60": "#1e8449",
            "#f39c12": "#d68910", "#e74c3c": "#c0392b",
            "#e67e22": "#ca6f1e",
        }.get(color, color)

    def safe_str(self, value, default=''):
        if value is None:
            return default
        if isinstance(value, float):
            if value != value or str(value) == 'nan':
                return default
            if value.is_integer():
                return str(int(value))
        return str(value)

    def _f(self, v, d=0.0):
        try:
            f = float(v)
            return d if f != f else f
        except (ValueError, TypeError):
            return d

    # =============================================================================
    # 15.1.2 — refresh (reload removed to protect cache)
    # =============================================================================
    def refresh(self, e=None):
        """
        Load receipts + related data from the DB's in-memory cache.

        IMPORTANT: Do NOT call db.reload() here — on Railway the CSV path
        can differ from the volume mount path, which wipes the cache.
        """
        try:
            self.receipts = self.db.get_receipts()

            self.travelers = {}
            for t in self.db.get_travelers():
                tid = t.get('id', '')
                self.travelers[tid] = {
                    'name': (f"{t.get('first_name', '')} "
                             f"{t.get('last_name', '')}").strip() or "Unnamed",
                    'passport': t.get('passport_no', '') or '',
                    'batch_id': t.get('batch_id', '') or '',
                }

            self.payments = {p['id']: p for p in self.db.get_payments()}
            self.invoices = {i['id']: i for i in self.db.get_invoices()}
            self.batches = {b['id']: b for b in self.db.get_batches()}

            opts = [ft.dropdown.Option(key="", text="All Travelers")]
            for tid, info in self.travelers.items():
                label = (f"{info['name']} ({info['passport']})"
                         if info['passport'] else info['name'])
                opts.append(ft.dropdown.Option(key=tid, text=label[:60]))
            self.traveler_filter.options = opts

            print(f"[RECEIPTS] loaded {len(self.receipts)} receipts, "
                  f"{len(self.payments)} payments, "
                  f"{len(self.invoices)} invoices")

            self.display_receipts()
            self.update_summary_stats()
            try:
                self.page.update()
            except Exception:
                pass
        except Exception as ex:
            print(f"Receipts refresh error: {ex}")
            import traceback
            traceback.print_exc()

    # =============================================================================
    # 15.1.3 — display_receipts
    # =============================================================================
    def display_receipts(self, receipts=None):
        if receipts is None:
            receipts = self.receipts

        # PATCH 15.1.B — lifetime paid totals from ALL receipts
        traveler_paid = {}
        for r in self.receipts:
            p = self.payments.get(r.get('payment_id', ''), {})
            tid = p.get('traveler_id', '')
            if tid:
                traveler_paid[tid] = (traveler_paid.get(tid, 0)
                                      + self._f(r.get('amount', 0)))

        self.table.rows.clear()
        for r in receipts:
            p = self.payments.get(r.get('payment_id', ''), {})
            tid = p.get('traveler_id', '')
            info = self.travelers.get(tid, {
                'name': 'Unknown', 'passport': '', 'batch_id': ''})
            tname = info['name']
            tpassport = info['passport']
            bid = info['batch_id']

            batch_price = 0
            if bid and bid in self.batches:
                batch_price = self._f(self.batches[bid].get('price', 0))

            total_paid = traveler_paid.get(tid, 0)
            pkg_pending = batch_price - total_paid

            inv_id = r.get('invoice_id', '')
            inv_pending = 0
            inv_no = ''
            if inv_id and inv_id in self.invoices:
                inv = self.invoices[inv_id]
                inv_no = inv.get('invoice_no', '')
                if inv.get('status') == 'pending':
                    inv_pending = self._f(
                        inv.get('rounded_total', inv.get('total_amount', 0)))

            date_str = (str(r.get('receipt_date', ''))[:10]
                        if r.get('receipt_date') else '')
            amount = self._f(r.get('amount', 0))
            method = str(p.get('payment_method', 'N/A'))
            status = str(p.get('status', 'completed'))
            status_color = ("#27ae60" if status == "completed"
                            else "#f39c12" if status == "pending"
                            else "#e74c3c")

            if batch_price > 0:
                if pkg_pending <= 0:
                    pkg_txt = "✅ Paid"
                    pkg_color = "#27ae60"
                else:
                    pkg_txt = f"₹{pkg_pending:,.0f}"
                    pkg_color = ("#e67e22"
                                 if pkg_pending < batch_price * 0.5
                                 else "#e74c3c")
            else:
                pkg_txt = "N/A"
                pkg_color = "#95a5a6"

            if inv_pending > 0:
                inv_txt = f"₹{inv_pending:,.0f}"
                inv_color = "#f39c12"
            elif inv_id and inv_id in self.invoices:
                inv_txt = "✅ Paid"
                inv_color = "#27ae60"
            else:
                inv_txt = "N/A"
                inv_color = "#95a5a6"

            # PATCH 15.1.C — capture receipt ID, re-fetch on click
            r_id = r.get('id')

            def _make_actions(_rid=r_id):
                def _fresh():
                    return next(
                        (x for x in self.receipts
                         if x.get('id') == _rid), None)

                def _wrap(handler):
                    def h(e, _h=handler, _f=_fresh):
                        fresh = _f()
                        if fresh is None:
                            self._snack("⚠️ Receipt no longer exists — "
                                        "refreshing…")
                            self.refresh()
                            return
                        _h(fresh)
                    return h

                return ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.VISIBILITY,
                            icon_color="#3498db", icon_size=18,
                            tooltip="View",
                            on_click=_wrap(self.view_receipt_details)),
                        ft.IconButton(
                            icon=ft.Icons.PICTURE_AS_PDF,
                            icon_color="#e74c3c", icon_size=18,
                            tooltip="PDF",
                            on_click=_wrap(self.export_single_receipt_pdf)),
                        ft.IconButton(
                            icon=ft.Icons.PRINT,
                            icon_color="#9b59b6", icon_size=18,
                            tooltip="Print",
                            on_click=_wrap(self.print_single_receipt)),
                        ft.IconButton(
                            icon=ft.Icons.DELETE,
                            icon_color="#95a5a6", icon_size=18,
                            tooltip="Delete",
                            on_click=_wrap(self.delete_receipt)),
                    ], spacing=0,
                )

            is_selected = (self._selected_receipt_id == r_id)

            # -------- ROW TAP → SELECT (not edit) --------
            def _on_row_tap(e, _rid=r_id):
                try:
                    self._select_receipt(_rid)
                except Exception as ex:
                    print(f"[RECEIPTS] row tap error: {ex}")

            self.table.rows.append(
                ft.DataRow(
                    on_select_change=_on_row_tap,
                    selected=is_selected,
                    cells=[
                        # Selection indicator
                        ft.DataCell(
                            ft.Container(
                                content=ft.Text(
                                    "✓" if is_selected else "",
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color="#27ae60"),
                                width=24,
                                alignment=ft.Alignment.CENTER,
                                bgcolor=("#dcfce7" if is_selected
                                         else None),
                                border_radius=4,
                            )),
                        ft.DataCell(ft.Text(
                            self.safe_str(r.get('receipt_no', ''))[:16],
                            size=10, weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(date_str, size=10)),
                        ft.DataCell(ft.Text(tname[:18], size=10)),
                        ft.DataCell(ft.Text(tpassport, size=10)),
                        ft.DataCell(ft.Text(method[:12], size=10)),
                        ft.DataCell(ft.Text(
                            f"₹{amount:,.0f}", size=10,
                            weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(inv_no[:14], size=10)),
                        ft.DataCell(ft.Text(status, size=10,
                                            color=status_color,
                                            weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(pkg_txt, size=10,
                                            color=pkg_color)),
                        ft.DataCell(ft.Text(inv_txt, size=10,
                                            color=inv_color)),
                        ft.DataCell(_make_actions()),
                    ]))

        self.filtered_count_label.value = (
            f"🔍 Showing: {len(receipts)} receipts")

    # =============================================================================
    # 15.1.3b — _select_receipt / _get_selected_receipt
    # =============================================================================
    def _select_receipt(self, receipt_id):
        if self._selected_receipt_id == receipt_id:
            self._selected_receipt_id = None
        else:
            self._selected_receipt_id = receipt_id

        if self.selection_label:
            if self._selected_receipt_id:
                r = next((x for x in self.receipts
                          if x.get('id') == self._selected_receipt_id), None)
                if r:
                    p = self.payments.get(r.get('payment_id', ''), {})
                    tid = p.get('traveler_id', '')
                    info = self.travelers.get(tid, {'name': '?'})
                    self.selection_label.value = (
                        f"✅ Selected: Receipt "
                        f"{self.safe_str(r.get('receipt_no', ''))[:16]} | "
                        f"{info['name']} | "
                        f"₹{self._f(r.get('amount', 0)):,.0f}")
                else:
                    self.selection_label.value = ""
            else:
                self.selection_label.value = ""

        self.display_receipts()
        try:
            self.page.update()
        except Exception:
            pass

    def _get_selected_receipt(self):
        if not self._selected_receipt_id:
            return None
        return next((r for r in self.receipts
                     if r.get('id') == self._selected_receipt_id), None)

    # =============================================================================
    # 15.1.4 — Stats
    # =============================================================================
    def update_summary_stats(self):
        total = len(self.receipts)
        total_amount = sum(self._f(r.get('amount', 0))
                           for r in self.receipts)

        today = datetime.now().strftime('%Y-%m-%d')
        today_amount = sum(
            self._f(r.get('amount', 0)) for r in self.receipts
            if str(r.get('receipt_date', '')).startswith(today))

        traveler_paid = {}
        for r in self.receipts:
            p = self.payments.get(r.get('payment_id', ''), {})
            tid = p.get('traveler_id', '')
            if tid:
                traveler_paid[tid] = (traveler_paid.get(tid, 0)
                                      + self._f(r.get('amount', 0)))

        pkg_pending_total = 0
        for tid, paid in traveler_paid.items():
            info = self.travelers.get(tid, {})
            bid = info.get('batch_id', '')
            if bid and bid in self.batches:
                bp = self._f(self.batches[bid].get('price', 0))
                pending = bp - paid
                if pending > 0:
                    pkg_pending_total += pending

        inv_pending_total = 0
        for inv in self.invoices.values():
            if inv.get('status') == 'pending':
                inv_pending_total += self._f(
                    inv.get('rounded_total', inv.get('total_amount', 0)))

        def _short(v):
            try:
                n = float(v)
            except Exception:
                return "₹0"
            if n >= 10000000:
                return f"₹{n/10000000:.2f}Cr"
            if n >= 100000:
                return f"₹{n/100000:.2f}L"
            if n >= 1000:
                return f"₹{n/1000:.1f}K"
            return f"₹{n:,.0f}"

        if 'total_receipts' in self.stat_labels:
            self.stat_labels['total_receipts'].value = str(total)
        if 'total_amount' in self.stat_labels:
            self.stat_labels['total_amount'].value = _short(total_amount)
        if 'today' in self.stat_labels:
            self.stat_labels['today'].value = _short(today_amount)
        if 'package_pending' in self.stat_labels:
            self.stat_labels['package_pending'].value = _short(
                pkg_pending_total)
        if 'invoice_pending' in self.stat_labels:
            self.stat_labels['invoice_pending'].value = _short(
                inv_pending_total)

    # =============================================================================
    # 15.1.5 — Filter
    # =============================================================================
    def apply_filters(self, e=None):
        tid_filter = self.traveler_filter.value or ""
        search = (self.search_input.value or "").lower().strip()
        date_from = (self.date_from.value or "").strip()
        date_to = (self.date_to.value or "").strip()

        filtered = []
        for r in self.receipts:
            p = self.payments.get(r.get('payment_id', ''), {})
            p_tid = p.get('traveler_id', '')

            if tid_filter and str(p_tid) != str(tid_filter):
                continue

            info = self.travelers.get(p_tid,
                                      {'name': '', 'passport': ''})
            receipt_no = str(r.get('receipt_no', '')).lower()
            amount_str = f"{self._f(r.get('amount', 0)):.2f}"
            inv_id = r.get('invoice_id', '')
            inv_no = ''
            if inv_id and inv_id in self.invoices:
                inv_no = str(self.invoices[inv_id].get(
                    'invoice_no', '')).lower()

            if search:
                haystack = ' '.join([
                    receipt_no, info['name'].lower(),
                    info['passport'].lower(), amount_str, inv_no])
                if search not in haystack:
                    continue

            rdate = str(r.get('receipt_date', ''))[:10]
            if date_from and rdate and rdate < date_from:
                continue
            if date_to and rdate and rdate > date_to:
                continue

            filtered.append(r)

        self.display_receipts(filtered)
        try:
            self.page.update()
        except Exception:
            pass

    # =============================================================================
    # 15.1.6 — View details
    # =============================================================================
    def view_receipt_details(self, receipt):
        p = self.payments.get(receipt.get('payment_id', ''), {})
        tid = p.get('traveler_id', '')
        info = self.travelers.get(tid,
                                  {'name': 'Unknown', 'passport': '',
                                   'batch_id': ''})
        tname = info['name']
        tpassport = info['passport']
        bid = info['batch_id']

        batch_price = 0
        batch_name = 'No Batch'
        if bid and bid in self.batches:
            b = self.batches[bid]
            batch_price = self._f(b.get('price', 0))
            batch_name = b.get('batch_name', 'No Batch')

        total_paid = 0
        for r in self.receipts:
            pr = self.payments.get(r.get('payment_id', ''), {})
            if pr.get('traveler_id') == tid:
                total_paid += self._f(r.get('amount', 0))
        pkg_pending = batch_price - total_paid

        inv_id = receipt.get('invoice_id', '')
        inv_pending = 0
        inv_no = 'N/A'
        if inv_id and inv_id in self.invoices:
            inv = self.invoices[inv_id]
            inv_no = inv.get('invoice_no', 'N/A')
            if inv.get('status') == 'pending':
                inv_pending = self._f(
                    inv.get('rounded_total', inv.get('total_amount', 0)))

        company_name = "Alhudha Haj Travel"
        try:
            if not self.db.company_settings.empty:
                company_name = str(
                    self.db.company_settings.iloc[0].get(
                        'company_name', company_name))
        except Exception:
            pass

        try:
            words = number_to_words_indian(int(self._f(
                receipt.get('amount', 0))))
        except Exception:
            words = ''

        details = (
            f"Company: {company_name}\n"
            f"Receipt No: {receipt.get('receipt_no', '')}\n"
            f"Date: {str(receipt.get('receipt_date', ''))[:10]}\n"
            f"{'-' * 60}\n"
            f"Traveler: {tname}\n"
            f"Passport: {tpassport}\n"
            f"Batch: {batch_name}\n"
            f"{'-' * 60}\n"
            f"Amount: ₹{self._f(receipt.get('amount', 0)):,.2f}\n"
            f"Amount in Words: {words}\n"
            f"{'-' * 60}\n"
            f"Method: {p.get('payment_method', 'N/A')}\n"
            f"Transaction ID: {p.get('transaction_id', 'N/A')}\n"
            f"Invoice No: {inv_no}\n"
            f"Status: {p.get('status', 'completed')}\n"
            f"{'-' * 60}\n"
            f"PAYMENT SUMMARY\n"
            f"  Total Package:     ₹{batch_price:>14,.2f}\n"
            f"  Total Paid:        ₹{total_paid:>14,.2f}\n"
            f"  Package Pending:   ₹{pkg_pending:>14,.2f}  (without GST)\n"
            f"  Invoice Pending:   ₹{inv_pending:>14,.2f}  (with GST)"
        )

        dialog = ft.AlertDialog(
            title=ft.Text(f"🧾 Receipt: {receipt.get('receipt_no', '')}",
                          weight=ft.FontWeight.BOLD, size=14),
            content=ft.Container(
                content=ft.Text(details, size=11,
                                font_family="Consolas", selectable=True),
                width=520, height=460, padding=10),
            actions=[
                ft.Button(content=ft.Text("Close"),
                          on_click=lambda e: self.page.pop_dialog(),
                          bgcolor="#3498db", color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.show_dialog(dialog)

    # =============================================================================
    # 15.1.7 — PDF export (also used by toolbar + row icon)
    # =============================================================================
    def export_pdf_selected(self, e):
        r = self._get_selected_receipt()
        if not r:
            self._snack("⚠️ Tap a row first to select it, then tap 📄 PDF")
            return
        self.export_single_receipt_pdf(r)

    def export_single_receipt_pdf(self, receipt):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import (
                SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer)
            from reportlab.lib import colors as rl_colors
            from reportlab.lib.styles import (
                getSampleStyleSheet, ParagraphStyle)
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
            from reportlab.lib.units import cm

            p = self.payments.get(receipt.get('payment_id', ''), {})
            tid = p.get('traveler_id', '')
            info = self.travelers.get(tid, {'name': 'Unknown'})
            tname = info['name']

            company_name = "Alhudha Haj Travel"
            try:
                if not self.db.company_settings.empty:
                    company_name = str(
                        self.db.company_settings.iloc[0].get(
                            'company_name', company_name))
            except Exception:
                pass

            amount_in_words = number_to_words_indian(
                int(self._f(receipt.get('amount', 0))))

            base = get_app_base_path()
            out_dir = Path(base) / "receipts"
            out_dir.mkdir(exist_ok=True)
            fname = (f"receipt_{receipt.get('receipt_no', 'NA')}_"
                     f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            filepath = out_dir / fname

            doc = SimpleDocTemplate(
                str(filepath), pagesize=A4,
                topMargin=2 * cm, bottomMargin=2.5 * cm,
                leftMargin=1.5 * cm, rightMargin=1.5 * cm)
            elements = []
            styles = getSampleStyleSheet()

            title_style = ParagraphStyle(
                'T', parent=styles['Heading1'], fontSize=20,
                alignment=TA_CENTER, spaceAfter=10)
            subtitle_style = ParagraphStyle(
                'S', parent=styles['Heading2'], fontSize=14,
                alignment=TA_CENTER, spaceAfter=20)
            label_style = ParagraphStyle(
                'L', parent=styles['Normal'], fontSize=11,
                alignment=TA_LEFT, fontName='Helvetica-Bold')
            value_style = ParagraphStyle(
                'V', parent=styles['Normal'], fontSize=11,
                alignment=TA_LEFT)
            footer_style = ParagraphStyle(
                'F', parent=styles['Normal'], fontSize=10,
                alignment=TA_CENTER, fontName='Helvetica',
                italic=True, textColor=rl_colors.HexColor('#7f8c8d'),
                spaceBefore=20)

            elements.append(Paragraph(company_name, title_style))
            elements.append(Paragraph("PAYMENT RECEIPT", subtitle_style))
            elements.append(Spacer(1, 10))

            data = [
                ["Receipt No:", receipt.get('receipt_no', '')],
                ["Date:", str(receipt.get('receipt_date', ''))[:10]],
                ["Received from:", tname],
                ["Amount:",
                 f"₹{self._f(receipt.get('amount', 0)):,.2f}"],
                ["Amount in Words:", amount_in_words],
                ["Payment Method:", p.get('payment_method', 'N/A')],
                ["Transaction ID:", p.get('transaction_id', 'N/A')],
                ["Status:", p.get('status', 'completed')],
            ]

            tbl_data = []
            for label, val in data:
                tbl_data.append([
                    Paragraph(f"<b>{label}</b>", label_style),
                    Paragraph(str(val), value_style)])

            t = Table(tbl_data, colWidths=[4.5 * cm, 8 * cm])
            t.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))

            elements.append(t)
            elements.append(Spacer(1, 20))
            elements.append(Paragraph(
                "Thank you for your payment!", footer_style))
            doc.build(elements)

            url = send_file_to_user(self.page, str(filepath), "Receipt PDF")
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

    # =============================================================================
    # 15.1.8 — Print (also used by toolbar + row icon)
    # =============================================================================
    def print_receipt_selected(self, e):
        r = self._get_selected_receipt()
        if not r:
            self._snack("⚠️ Tap a row first to select it, then tap 🖨️ Print")
            return
        self.print_single_receipt(r)

    def print_single_receipt(self, receipt):
        self._snack("🖨️ Generating PDF — press Ctrl+P when it opens")
        self.export_single_receipt_pdf(receipt)

    # =============================================================================
    # 15.1.9 — Delete (PATCH 15.1.D preserved)
    # =============================================================================
    def delete_receipt(self, receipt):
        payment_id = receipt.get('payment_id', '')
        linked_payment = self.payments.get(payment_id) if payment_id else None

        warn_text = f"Delete receipt {receipt.get('receipt_no', '')}?"
        if linked_payment:
            try:
                amt = self._f(linked_payment.get('amount', 0))
            except Exception:
                amt = 0.0
            warn_text += (
                f"\n\n⚠️ This receipt is linked to a payment record "
                f"(₹{amt:,.2f}).\n"
                f"The payment will NOT be deleted automatically — "
                f"clean it up in the Payments tab if needed."
            )

        def confirm(ev):
            try:
                if hasattr(self.db, "delete_receipt"):
                    self.db.delete_receipt(receipt['id'])
                else:
                    self.db.receipts = self.db.receipts[
                        self.db.receipts['id'] != receipt['id']]
                    self.db._save_df(self.db.receipts, "receipts.csv")
                try:
                    self.db.log_activity(
                        self.current_user['id'], "delete_receipt",
                        f"Deleted receipt {receipt.get('receipt_no', '')}")
                except Exception:
                    pass
                self.page.pop_dialog()
                self.refresh()
                self._snack("✅ Receipt deleted")
            except Exception as ex:
                self._snack(f"❌ {ex}")

        dialog = ft.AlertDialog(
            title=ft.Text("Delete Receipt?", size=14),
            content=ft.Text(warn_text, size=12),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Delete"), on_click=confirm,
                          bgcolor=ft.Colors.RED_600,
                          color=ft.Colors.WHITE),
            ],
        )
        self.page.show_dialog(dialog)

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
# SECTION 15 END (FLET 1.0.0 VERSION)
# =================================================================================