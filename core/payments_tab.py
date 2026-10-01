# =================================================================================
# SECTION 12 + 13 (FLET 1.0.0 VERSION) — PAYMENTS TAB + DIALOGS
# =================================================================================
# v1.4 — Row Tap Selection (based on working v1.2)
#   • ONLY CHANGE: Each table row is now tappable → opens Edit dialog
#   • Data loading untouched (your working v1.2 logic preserved)
#   • Table layout untouched
#   • Action icons slightly larger (16 → 18) for easier tap
# =================================================================================

import flet as ft
import os
import uuid
from pathlib import Path
from datetime import datetime
import pandas as pd

from core.helpers import (
    get_app_base_path,
    number_to_words_indian,
    format_currency_indian,
    send_file_to_user,
)
from core.settings_manager import SettingsManager


# =================================================================================
# 12.2 — CLASS: PaymentEditDialog
# =================================================================================
class PaymentEditDialog:

    def __init__(self, page, db, current_user, payment_data,
                 on_save=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.payment_data = dict(payment_data)
        self.on_save = on_save

        self.amount_field = None
        self.date_field = None
        self.method_dropdown = None
        self.trans_field = None
        self.status_dropdown = None
        self.notes_field = None
        self.dialog = None

        self.setup_ui()

    def setup_ui(self):
        traveler_id = self.payment_data.get('traveler_id', '')
        traveler_name = "Unknown"
        if traveler_id:
            try:
                t = self.db.get_traveler_by_id(traveler_id)
                if t:
                    traveler_name = (
                        f"{t.get('first_name', '')} "
                        f"{t.get('last_name', '')}").strip() or "Unnamed"
            except Exception:
                pass

        invoice_id = self.payment_data.get('invoice_id', '')
        invoice_text = "No invoice linked"
        if invoice_id:
            try:
                invs = self.db.get_invoices()
                for inv in invs:
                    if str(inv.get('id')) == str(invoice_id):
                        invoice_text = (
                            f"{inv.get('invoice_no', 'N/A')} "
                            f"(ID: {invoice_id})")
                        break
                else:
                    invoice_text = f"ID: {invoice_id}"
            except Exception:
                invoice_text = f"ID: {invoice_id}"

        self.amount_field = ft.TextField(
            label="Amount (₹) *",
            value=str(self.payment_data.get('amount', 0)),
            height=48, text_size=12)
        self.date_field = ft.TextField(
            label="Payment Date (YYYY-MM-DD)",
            value=str(self.payment_data.get('payment_date', ''))[:10],
            height=48, text_size=12)
        self.method_dropdown = ft.Dropdown(
            label="Payment Method",
            options=[
                ft.dropdown.Option("Cash"),
                ft.dropdown.Option("Bank Transfer"),
                ft.dropdown.Option("Credit Card"),
                ft.dropdown.Option("Cheque"),
                ft.dropdown.Option("Online"),
                ft.dropdown.Option("UPI"),
            ],
            value=str(self.payment_data.get('payment_method', 'Cash')),
            height=48, text_size=12)
        self.trans_field = ft.TextField(
            label="Transaction ID",
            value=str(self.payment_data.get('transaction_id', '')),
            height=48, text_size=12)
        self.status_dropdown = ft.Dropdown(
            label="Status",
            options=[
                ft.dropdown.Option("completed"),
                ft.dropdown.Option("pending"),
                ft.dropdown.Option("failed"),
                ft.dropdown.Option("refunded"),
            ],
            value=str(self.payment_data.get('status', 'pending')),
            height=48, text_size=12)
        self.notes_field = ft.TextField(
            label="Notes",
            value=str(self.payment_data.get('notes', '')),
            multiline=True, min_lines=2, max_lines=3,
            text_size=12)

        def info_row(label, value):
            return ft.Row([
                ft.Text(label, width=140,
                        weight=ft.FontWeight.BOLD, size=11),
                ft.Text(str(value), size=11, selectable=True, expand=True),
            ], spacing=8)

        content = ft.Column(
            controls=[
                info_row("Payment ID", self.payment_data.get('id', 'N/A')),
                info_row("Traveler", traveler_name),
                ft.Divider(height=10),
                self.amount_field,
                self.date_field,
                self.method_dropdown,
                self.trans_field,
                self.status_dropdown,
                ft.Divider(height=10),
                info_row("Invoice", invoice_text),
                self.notes_field,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("✏️ Edit Payment",
                          weight=ft.FontWeight.BOLD, size=15),
            content=ft.Container(content=content,
                                 width=520, height=560, padding=10),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content=ft.Text("💾 Save Changes"),
                          on_click=self.save,
                          bgcolor=ft.Colors.GREEN_600,
                          color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def save(self, e):
        try:
            amount_text = (self.amount_field.value or '').strip()
            if not amount_text:
                self._snack("⚠️ Please enter the payment amount")
                return
            try:
                amount = float(amount_text)
                if amount <= 0:
                    self._snack("⚠️ Amount must be greater than 0")
                    return
            except ValueError:
                self._snack("⚠️ Invalid amount — must be numeric")
                return

            updated = {
                'amount': amount,
                'payment_date': (self.date_field.value or '')[:10],
                'payment_method': self.method_dropdown.value or 'Cash',
                'transaction_id': (self.trans_field.value or '').strip(),
                'status': self.status_dropdown.value or 'pending',
                'notes': (self.notes_field.value or '').strip(),
            }

            success = self.db.update_payment(
                self.payment_data['id'], updated)
            if success:
                self.payment_data.update(updated)
                try:
                    self.db.log_activity(
                        self.current_user['id'], "edit_payment",
                        f"Edited payment #{self.payment_data['id']} - "
                        f"Amount: ₹{amount:,.2f}")
                except Exception:
                    pass

                try:
                    if hasattr(self.db, "reload_payments"):
                        self.db.reload_payments()
                    if hasattr(self.db, "reload_receipts"):
                        self.db.reload_receipts()
                    if hasattr(self.db, "reload_invoices"):
                        self.db.reload_invoices()
                except Exception:
                    pass

                self.page.pop_dialog()
                self._snack("✅ Payment updated successfully!")
                if self.on_save:
                    self.on_save()
            else:
                self._snack("❌ Failed to update payment")
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
# 12.3 — CLASS: PaymentsTab
# =================================================================================
class PaymentsTab:

    def __init__(self, page: ft.Page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user

        self.payments = []
        self.travelers = {}
        self.receipts = {}
        self.invoices = {}
        self.batches = {}
        self.traveler_details = {}

        self.stat_labels = {}
        self.status_filter = None
        self.method_filter = None
        self.search_input = None
        self.table = None
        self.root = None

        # Track currently highlighted row
        self._selected_payment_id = None

        self.setup_ui()
        self.refresh()

    def build(self):
        return self.root

    def setup_ui(self):
        stat_configs = [
            ("total",           "💰 Total",       "#3498db"),
            ("completed",       "✅ Completed",   "#27ae60"),
            ("pending",         "⏳ Pending",     "#f39c12"),
            ("receipts",        "🧾 Receipts",    "#9b59b6"),
            ("package_pending", "📦 Pkg Pend",    "#e74c3c"),
            ("invoice_pending", "📄 Inv Pend",    "#e67e22"),
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
                        ft.Text(label, size=9,
                                color=ft.Colors.WHITE,
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

        def _tb(label, color, handler):
            return ft.Button(
                content=ft.Text(label, size=11,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE,
                                no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS),
                on_click=handler, height=40,
                bgcolor=color,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=8)),
            )

        self.status_filter = ft.Dropdown(
            label="Status",
            options=[
                ft.dropdown.Option(key="All", text="All"),
                ft.dropdown.Option(key="completed", text="Completed"),
                ft.dropdown.Option(key="pending", text="Pending"),
                ft.dropdown.Option(key="failed", text="Failed"),
                ft.dropdown.Option(key="refunded", text="Refunded"),
            ],
            value="All", height=48, text_size=11)
        self.status_filter.on_change = self.filter_payments

        self.method_filter = ft.Dropdown(
            label="Method",
            options=[
                ft.dropdown.Option(key="All", text="All"),
                ft.dropdown.Option(key="Cash", text="Cash"),
                ft.dropdown.Option(key="Bank Transfer", text="Bank Transfer"),
                ft.dropdown.Option(key="Credit Card", text="Credit Card"),
                ft.dropdown.Option(key="Cheque", text="Cheque"),
                ft.dropdown.Option(key="Online", text="Online"),
                ft.dropdown.Option(key="UPI", text="UPI"),
            ],
            value="All", height=48, text_size=11)
        self.method_filter.on_change = self.filter_payments

        self.search_input = ft.TextField(
            hint_text="🔍 Search traveler or txn ID...",
            height=48, text_size=12,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8))
        self.search_input.on_change = self.filter_payments

        toolbar = ft.ResponsiveRow(
            controls=[
                ft.Container(
                    content=_tb("➕ Record Payment", "#27ae60",
                                self.add_payment),
                    col={"xs": 6, "sm": 4, "md": 3}),
                ft.Container(
                    content=_tb("📄 PDF", "#e74c3c",
                                self.export_pdf_selected),
                    col={"xs": 6, "sm": 4, "md": 3}),
                ft.Container(
                    content=_tb("🖨️ Print", "#9b59b6",
                                self.print_receipt_selected),
                    col={"xs": 6, "sm": 4, "md": 3}),
            ],
            spacing=8, run_spacing=8,
        )

        filter_row = ft.ResponsiveRow(
            controls=[
                ft.Container(content=self.status_filter,
                             col={"xs": 6, "sm": 4, "md": 3}),
                ft.Container(content=self.method_filter,
                             col={"xs": 6, "sm": 4, "md": 4}),
                ft.Container(content=self.search_input,
                             col={"xs": 12, "sm": 12, "md": 5}),
            ], spacing=8, run_spacing=8,
        )

        self.table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Date", size=11)),
                ft.DataColumn(ft.Text("Traveler", size=11)),
                ft.DataColumn(ft.Text("Amount", size=11)),
                ft.DataColumn(ft.Text("Method", size=11)),
                ft.DataColumn(ft.Text("Status", size=11)),
                ft.DataColumn(ft.Text("Txn ID", size=11)),
                ft.DataColumn(ft.Text("Receipt", size=11)),
                ft.DataColumn(ft.Text("Invoice", size=11)),
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
        )

        self.root = ft.Container(
            content=ft.Column(
                controls=[
                    stats_row,
                    ft.Container(content=toolbar, padding=8,
                                 bgcolor=ft.Colors.WHITE, border_radius=10),
                    ft.Container(content=filter_row, padding=8,
                                 bgcolor=ft.Colors.WHITE, border_radius=10),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("💡 Tap any row to edit that payment",
                                    size=10,
                                    color=ft.Colors.GREY_600,
                                    italic=True),
                            ft.Row([self.table],
                                   scroll=ft.ScrollMode.ADAPTIVE),
                        ], spacing=6),
                        bgcolor=ft.Colors.WHITE,
                        border_radius=10, padding=10),
                ],
                spacing=10, scroll=ft.ScrollMode.AUTO,
            ),
            padding=10, bgcolor="#f0f2f5", expand=True,
        )

    def refresh(self):
        try:
            for mn in ("reload_payments", "reload_receipts",
                       "reload_invoices", "reload_travelers",
                       "reload_batches"):
                if hasattr(self.db, mn):
                    try:
                        getattr(self.db, mn)()
                    except Exception as ex:
                        print(f"[PAYMENTS] {mn} failed: {ex}")

            self.payments = self.db.get_payments()
            self.travelers = {
                t['id']: (f"{t.get('first_name', '')} "
                          f"{t.get('last_name', '')}").strip() or "Unnamed"
                for t in self.db.get_travelers()
            }
            self.receipts = {r['payment_id']: r
                             for r in self.db.get_receipts()}
            self.invoices = {i['id']: i for i in self.db.get_invoices()}
            self.batches = {b['id']: b for b in self.db.get_batches()}

            self.traveler_details = {}
            for t in self.db.get_travelers():
                tid = t['id']
                bid = t.get('batch_id')
                if bid and bid in self.batches:
                    b = self.batches[bid]
                    self.traveler_details[tid] = {
                        'batch_price': float(b.get('price', 0) or 0),
                        'batch_name': b.get('batch_name', 'Unknown'),
                        'batch_id': bid,
                    }
                else:
                    self.traveler_details[tid] = {
                        'batch_price': 0, 'batch_name': 'No Batch',
                        'batch_id': None,
                    }

            self.display_payments()
            self.update_summary_stats()
            try:
                self.page.update()
            except Exception:
                pass
        except Exception as ex:
            print(f"Payments refresh error: {ex}")
            import traceback
            traceback.print_exc()

    def display_payments(self, payments=None):
        if payments is None:
            payments = self.payments

        traveler_paid = {}
        for p in payments:
            tid = p.get('traveler_id')
            if tid:
                traveler_paid[tid] = (traveler_paid.get(tid, 0)
                                      + float(p.get('amount', 0) or 0))

        self.table.rows.clear()
        for p in payments:
            tid = p.get('traveler_id', '')
            pid = p.get('id')
            date_str = (str(p.get('payment_date', ''))[:10]
                        if p.get('payment_date') else '')
            traveler_name = self.travelers.get(tid, 'Unknown')
            amount_text = f"₹{float(p.get('amount', 0) or 0):,.0f}"
            method = str(p.get('payment_method', ''))
            status = str(p.get('status', 'pending'))
            status_color = ("#27ae60" if status == "completed"
                            else "#f39c12" if status == "pending"
                            else "#e74c3c" if status == "failed"
                            else "#95a5a6")
            txn = str(p.get('transaction_id', '') or '')[:12]
            receipt = self.receipts.get(pid)
            receipt_no = (receipt.get('receipt_no', '—')
                          if receipt else '—')
            inv_id = p.get('invoice_id', '')
            inv_no = ''
            if inv_id and inv_id in self.invoices:
                inv_no = self.invoices[inv_id].get('invoice_no', '')[:14]

            traveler_info = self.traveler_details.get(
                tid, {'batch_price': 0, 'batch_name': 'No Batch'})
            batch_price = traveler_info['batch_price']
            total_paid = traveler_paid.get(tid, 0)
            package_pending = batch_price - total_paid

            if batch_price > 0:
                if package_pending <= 0:
                    pkg_txt = "✅ Paid"
                    pkg_color = "#27ae60"
                else:
                    pkg_txt = f"₹{package_pending:,.0f}"
                    pkg_color = ("#e67e22"
                                 if package_pending < batch_price * 0.5
                                 else "#e74c3c")
            else:
                pkg_txt = "N/A"
                pkg_color = "#95a5a6"

            inv_pending = 0
            if inv_id and inv_id in self.invoices:
                inv = self.invoices[inv_id]
                if inv.get('status') == 'pending':
                    inv_pending = float(
                        inv.get('rounded_total',
                                inv.get('total_amount', 0)) or 0)

            if inv_pending > 0:
                inv_txt = f"₹{inv_pending:,.0f}"
                inv_color = "#f39c12"
            elif inv_id and inv_id in self.invoices:
                inv_txt = "✅ Paid"
                inv_color = "#27ae60"
            else:
                inv_txt = "N/A"
                inv_color = "#95a5a6"

            actions = ft.Row(
                controls=[
                    ft.IconButton(icon=ft.Icons.EDIT,
                                  icon_color="#f39c12", icon_size=18,
                                  tooltip="Edit",
                                  on_click=lambda e, pp=p:
                                      self.edit_payment(pp)),
                    ft.IconButton(icon=ft.Icons.RECEIPT_LONG,
                                  icon_color="#3498db", icon_size=18,
                                  tooltip="View Receipt",
                                  on_click=lambda e, pp=p:
                                      self.view_specific_receipt(pp)),
                    ft.IconButton(icon=ft.Icons.PICTURE_AS_PDF,
                                  icon_color="#e74c3c", icon_size=18,
                                  tooltip="PDF",
                                  on_click=lambda e, pp=p:
                                      self.export_single_receipt_pdf(pp)),
                    ft.IconButton(icon=ft.Icons.PRINT,
                                  icon_color="#9b59b6", icon_size=18,
                                  tooltip="Print",
                                  on_click=lambda e, pp=p:
                                      self.print_single_receipt(pp)),
                ], spacing=0,
            )

            # -------- ROW TAP → open Edit dialog --------
            def _on_row_tap(e, pp=p):
                try:
                    print(f"[PAYMENTS] Row tapped: {pp.get('id')}")
                    self._selected_payment_id = pp.get('id')
                    # Small visual feedback
                    self._snack(
                        f"✏️ Opening payment "
                        f"{str(pp.get('transaction_id', ''))[:12]}...")
                    self.edit_payment(pp)
                except Exception as ex:
                    print(f"[PAYMENTS] row tap error: {ex}")

            row = ft.DataRow(
                on_select_changed=_on_row_tap,
                cells=[
                    ft.DataCell(ft.Text(date_str, size=10)),
                    ft.DataCell(ft.Text(traveler_name[:18], size=10,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(amount_text, size=10,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(method[:12], size=10)),
                    ft.DataCell(ft.Text(status, size=10,
                                        color=status_color,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(txn, size=10)),
                    ft.DataCell(ft.Text(str(receipt_no)[:14], size=10)),
                    ft.DataCell(ft.Text(str(inv_no), size=10)),
                    ft.DataCell(ft.Text(pkg_txt, size=10, color=pkg_color)),
                    ft.DataCell(ft.Text(inv_txt, size=10, color=inv_color)),
                    ft.DataCell(actions),
                ])

            self.table.rows.append(row)

    def edit_payment(self, payment):
        dlg = PaymentEditDialog(
            self.page, self.db, self.current_user, payment,
            on_save=self.refresh)
        dlg.show()

    def filter_payments(self, e=None):
        search = (self.search_input.value or "").strip().lower()
        status = self.status_filter.value or "All"
        method = self.method_filter.value or "All"
        filtered = self.payments

        if status != "All":
            filtered = [p for p in filtered
                        if str(p.get('status', '')) == status]
        if method != "All":
            filtered = [p for p in filtered
                        if str(p.get('payment_method', '')) == method]
        if search:
            def match(p):
                tname = self.travelers.get(
                    p.get('traveler_id', ''), '').lower()
                txn = str(p.get('transaction_id', '') or '').lower()
                return search in tname or search in txn
            filtered = [p for p in filtered if match(p)]

        self.display_payments(filtered)
        try:
            self.page.update()
        except Exception:
            pass

    def add_payment(self, e):
        dlg = PaymentDialog(self.page, self.db, self.current_user,
                            on_save=self.refresh)
        dlg.show()

    def view_specific_receipt(self, payment):
        receipts = self.db.get_receipts(payment.get('id'))
        if not receipts:
            self._snack("ℹ️ No receipt — generating one now")
            self.generate_receipt_for_payment(payment)
            return

        receipt = receipts[0]
        traveler_name = self.travelers.get(
            payment.get('traveler_id', ''), 'Unknown')

        company_name = "Alhudha Haj Travel"
        try:
            if not self.db.company_settings.empty:
                company_name = str(
                    self.db.company_settings.iloc[0].get(
                        'company_name', company_name))
        except Exception:
            pass

        amount_in_words = number_to_words_indian(
            int(receipt.get('amount', 0) or 0))
        tid = payment.get('traveler_id', '')
        traveler_info = self.traveler_details.get(
            tid, {'batch_price': 0, 'batch_name': 'No Batch'})
        batch_price = traveler_info['batch_price']
        total_paid = sum(
            float(p.get('amount', 0) or 0) for p in self.payments
            if p.get('traveler_id') == tid)
        package_pending = batch_price - total_paid

        inv_id = payment.get('invoice_id', '')
        inv_pending = 0
        inv_no = 'N/A'
        if inv_id and inv_id in self.invoices:
            inv = self.invoices[inv_id]
            inv_no = inv.get('invoice_no', 'N/A')
            if inv.get('status') == 'pending':
                inv_pending = float(
                    inv.get('rounded_total',
                            inv.get('total_amount', 0)) or 0)

        details = (
            f"Company:  {company_name}\n"
            f"Receipt No:  {receipt.get('receipt_no', '')}\n"
            f"Date:  {str(receipt.get('receipt_date', ''))[:10]}\n"
            f"Received From:  {traveler_name}\n"
            f"Amount:  ₹{float(receipt.get('amount', 0) or 0):,.2f}\n"
            f"Amount in Words:  {amount_in_words}\n"
            f"Method:  {payment.get('payment_method', 'N/A')}\n"
            f"Transaction ID:  {payment.get('transaction_id', 'N/A')}\n"
            f"Invoice No:  {inv_no}\n"
            f"Status:  {payment.get('status', 'completed')}\n"
            f"\nPAYMENT SUMMARY\n"
            f"  Total Package:  ₹{batch_price:,.2f}\n"
            f"  Total Paid:  ₹{total_paid:,.2f}\n"
            f"  Package Pending:  ₹{package_pending:,.2f}  (without GST)\n"
            f"  Invoice Pending:  ₹{inv_pending:,.2f}  (with GST)"
        )

        dialog = ft.AlertDialog(
            title=ft.Text(f"🧾 Receipt: {receipt.get('receipt_no', '')}",
                          weight=ft.FontWeight.BOLD, size=14),
            content=ft.Container(
                content=ft.Text(details, size=11,
                                font_family="Consolas", selectable=True),
                width=520, height=440, padding=10),
            actions=[
                ft.Button(content=ft.Text("Close"),
                          on_click=lambda e: self.page.pop_dialog(),
                          bgcolor=ft.Colors.BLUE_700,
                          color=ft.Colors.WHITE),
            ],
        )
        self.page.show_dialog(dialog)

    def export_pdf_selected(self, e):
        self._snack("ℹ️ Click 📄 in a row to export that receipt")

    def export_single_receipt_pdf(self, payment):
        receipts = self.db.get_receipts(payment.get('id'))
        if not receipts:
            self._snack("⚠️ No receipt found for this payment")
            return
        receipt = receipts[0]

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import (
                SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer)
            from reportlab.lib import colors as rl_colors
            from reportlab.lib.styles import (
                getSampleStyleSheet, ParagraphStyle)
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
            from reportlab.lib.units import cm

            company_name = "Alhudha Haj Travel"
            try:
                if not self.db.company_settings.empty:
                    company_name = str(
                        self.db.company_settings.iloc[0].get(
                            'company_name', company_name))
            except Exception:
                pass

            tid = payment.get('traveler_id', '')
            traveler = self.db.get_traveler_by_id(tid)
            traveler_name = (
                f"{traveler.get('first_name', '')} "
                f"{traveler.get('last_name', '')}").strip() or "Unknown"
            bid = payment.get('batch_id', '')
            batch = self.db.get_batch_by_id(bid) if bid else None
            batch_price = float(batch.get('price', 0) or 0) if batch else 0
            batch_name = (batch.get('batch_name', 'No Batch')
                          if batch else 'No Batch')

            total_paid = sum(
                float(p.get('amount', 0) or 0) for p in self.payments
                if p.get('traveler_id') == tid)
            package_pending = batch_price - total_paid

            inv_id = payment.get('invoice_id', '')
            inv_pending = 0
            inv_no = 'N/A'
            if inv_id and inv_id in self.invoices:
                inv = self.invoices[inv_id]
                inv_no = inv.get('invoice_no', 'N/A')
                if inv.get('status') == 'pending':
                    inv_pending = float(
                        inv.get('rounded_total',
                                inv.get('total_amount', 0)) or 0)

            amount_in_words = number_to_words_indian(
                int(receipt.get('amount', 0) or 0))

            base = get_app_base_path()
            receipts_dir = Path(base) / "receipts"
            receipts_dir.mkdir(exist_ok=True)
            filename = (f"receipt_{receipt.get('receipt_no', 'NA')}_"
                        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            filepath = receipts_dir / filename

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

            receipt_data = [
                ["Receipt No:", receipt.get('receipt_no', '')],
                ["Date:", str(receipt.get('receipt_date', ''))[:10]],
                ["Received from:", traveler_name],
                ["Batch:", batch_name],
                ["Amount:", f"₹{float(receipt.get('amount', 0) or 0):,.2f}"],
                ["Amount in Words:", amount_in_words],
                ["Payment Method:", payment.get('payment_method', 'N/A')],
                ["Transaction ID:", payment.get('transaction_id', 'N/A')],
                ["Invoice No:", inv_no],
                ["Status:", payment.get('status', 'completed')],
                ["", ""],
                ["📊 PAYMENT SUMMARY", ""],
                ["Total Package:", f"₹{batch_price:,.2f}"],
                ["Total Paid:", f"₹{total_paid:,.2f}"],
                ["Package Pending:",
                 f"₹{package_pending:,.2f} (without GST)"],
                ["Invoice Pending:",
                 f"₹{inv_pending:,.2f} (with GST)"],
            ]

            table_data = []
            for label, value in receipt_data:
                table_data.append([
                    Paragraph(f"<b>{label}</b>", label_style),
                    Paragraph(str(value), value_style)])

            table = Table(table_data, colWidths=[4.5 * cm, 8 * cm])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BACKGROUND', (0, 11), (-1, 11),
                 rl_colors.HexColor('#f0f0f0')),
                ('SPAN', (0, 11), (1, 11)),
            ]))

            elements.append(table)
            elements.append(Spacer(1, 20))
            elements.append(Paragraph("Thank you for your payment!",
                                      footer_style))
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

    def print_receipt_selected(self, e):
        self._snack("ℹ️ Click 🖨️ in a row, then use browser Ctrl+P")

    def print_single_receipt(self, payment):
        self._snack(
            "ℹ️ Generate PDF first (📄), then press Ctrl+P in the browser")

    def generate_receipt_for_payment(self, payment):
        receipts = self.db.get_receipts(payment.get('id'))
        if receipts:
            self._snack(f"ℹ️ Receipt exists: "
                        f"{receipts[0].get('receipt_no', '')}")
            return
        try:
            self.db._generate_receipt(payment)
            try:
                self.db.log_activity(
                    self.current_user['id'], "generate_receipt",
                    f"Generated receipt for payment {payment.get('id')}")
            except Exception:
                pass
            self.refresh()
            self._snack("✅ Receipt generated")
        except Exception as ex:
            self._snack(f"❌ {ex}")

    def update_summary_stats(self):
        total = sum(float(p.get('amount', 0) or 0) for p in self.payments)
        completed = sum(float(p.get('amount', 0) or 0)
                        for p in self.payments
                        if p.get('status') == 'completed')
        pending = sum(float(p.get('amount', 0) or 0)
                      for p in self.payments
                      if p.get('status') == 'pending')
        receipt_count = len(self.receipts)

        traveler_paid = {}
        for p in self.payments:
            tid = p.get('traveler_id')
            if tid:
                traveler_paid[tid] = (traveler_paid.get(tid, 0)
                                      + float(p.get('amount', 0) or 0))

        total_package_pending = 0
        for tid, info in self.traveler_details.items():
            bp = info['batch_price']
            paid = traveler_paid.get(tid, 0)
            if bp - paid > 0:
                total_package_pending += (bp - paid)

        total_invoice_pending = 0
        for inv in self.invoices.values():
            if inv.get('status') == 'pending':
                total_invoice_pending += float(
                    inv.get('rounded_total',
                            inv.get('total_amount', 0)) or 0)

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

        self.stat_labels['total'].value = _short(total)
        self.stat_labels['completed'].value = _short(completed)
        self.stat_labels['pending'].value = _short(pending)
        self.stat_labels['receipts'].value = str(receipt_count)
        self.stat_labels['package_pending'].value = _short(
            total_package_pending)
        self.stat_labels['invoice_pending'].value = _short(
            total_invoice_pending)

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
# 13.1 — CLASS: PaymentDialog (Record new payment)
# =================================================================================
class PaymentDialog:

    def __init__(self, page, db, current_user, traveler=None,
                 on_save=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.selected_traveler = traveler
        self.on_save = on_save
        self.settings_manager = SettingsManager(db)
        self.payment_data = {}

        self.traveler_dropdown = None
        self.batch_label = None
        self.total_amount_label = None
        self.total_paid_label = None
        self.pending_amount_label = None
        self.amount_field = None
        self.remaining_label = None
        self.method_dropdown = None
        self.trans_field = None
        self.generate_invoice_check = None
        self.notes_field = None
        self.save_btn = None
        self.dialog = None

        self._current_traveler_id = None
        self._batch_price = 0.0
        self._total_paid = 0.0

        self.setup_ui()
        if traveler:
            self.select_traveler(traveler.get('id'))

    def setup_ui(self):
        traveler_options = []
        try:
            for t in self.db.get_travelers():
                name = (f"{t.get('first_name', '')} "
                        f"{t.get('last_name', '')}").strip()
                passport = t.get('passport_no', '')
                label = f"{name} ({passport})" if passport else name
                traveler_options.append(
                    ft.dropdown.Option(key=str(t['id']), text=label[:60]))
        except Exception:
            pass

        self.traveler_dropdown = ft.Dropdown(
            label="Traveler *",
            options=traveler_options or [ft.dropdown.Option(
                key="", text="No travelers available")],
            value="", height=48, text_size=12)
        self.traveler_dropdown.on_change = self.on_traveler_change

        self.batch_label = ft.Text("Not assigned", size=11,
                                   color="#2c3e50")
        self.total_amount_label = ft.Text("₹0", size=12,
                                          weight=ft.FontWeight.BOLD,
                                          color="#2c3e50")
        self.total_paid_label = ft.Text("₹0", size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color="#27ae60")
        self.pending_amount_label = ft.Text("₹0", size=13,
                                            weight=ft.FontWeight.BOLD,
                                            color="#e74c3c")

        def info_row(label, control):
            return ft.Row([
                ft.Text(label, width=150,
                        weight=ft.FontWeight.BOLD, size=11),
                control,
            ], spacing=8)

        self.amount_field = ft.TextField(
            label="💵 Payment Amount (₹) *",
            value="0", height=48, text_size=13)
        self.amount_field.on_change = self.on_amount_changed

        self.remaining_label = ft.Text("₹0", size=12,
                                       weight=ft.FontWeight.BOLD,
                                       color="#3498db")

        self.method_dropdown = ft.Dropdown(
            label="Payment Method",
            options=[
                ft.dropdown.Option("Cash"),
                ft.dropdown.Option("Bank Transfer"),
                ft.dropdown.Option("Credit Card"),
                ft.dropdown.Option("Cheque"),
                ft.dropdown.Option("Online"),
                ft.dropdown.Option("UPI"),
            ],
            value="Cash", height=48, text_size=12)

        self.trans_field = ft.TextField(
            label="Transaction ID (optional)",
            hint_text="Leave blank to auto-generate",
            height=48, text_size=12)

        self.generate_invoice_check = ft.Checkbox(
            label="Generate Invoice (GST/TCS applied)",
            value=False)

        self.notes_field = ft.TextField(
            label="Notes", multiline=True,
            min_lines=2, max_lines=3, text_size=12)

        self.save_btn = ft.Button(
            content=ft.Text("💾 Record Payment"),
            on_click=self.save_payment,
            bgcolor=ft.Colors.GREEN_600,
            color=ft.Colors.WHITE, height=45)

        content = ft.Column(
            controls=[
                self.traveler_dropdown,
                info_row("Batch:", self.batch_label),
                info_row("💰 Total Package:", self.total_amount_label),
                info_row("✅ Total Paid:", self.total_paid_label),
                info_row("⚠️ Pending:", self.pending_amount_label),
                ft.Divider(height=10),
                self.amount_field,
                info_row("📊 Remaining:", self.remaining_label),
                self.method_dropdown,
                self.trans_field,
                self.generate_invoice_check,
                self.notes_field,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("💰 Record Payment",
                          weight=ft.FontWeight.BOLD, size=15),
            content=ft.Container(content=content,
                                 width=540, height=640, padding=10),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                self.save_btn,
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def select_traveler(self, traveler_id):
        try:
            self.traveler_dropdown.value = str(traveler_id)
        except Exception:
            pass
        self.update_traveler_info()

    def on_traveler_change(self, e):
        self.update_traveler_info()

    def update_traveler_info(self):
        tid = self.traveler_dropdown.value
        if not tid:
            self.batch_label.value = "Not assigned"
            self.total_amount_label.value = "₹0"
            self.total_paid_label.value = "₹0"
            self.pending_amount_label.value = "₹0"
            self._batch_price = 0
            self._total_paid = 0
            self._current_traveler_id = None
            try:
                self.page.update()
            except Exception:
                pass
            return

        try:
            traveler = self.db.get_traveler_by_id(tid)
        except Exception:
            traveler = None

        if not traveler:
            self.batch_label.value = "Traveler not found"
            return

        self._current_traveler_id = tid
        batch_id = traveler.get('batch_id')

        if not batch_id:
            self.batch_label.value = "No batch assigned"
            self.total_amount_label.value = "₹0"
            self.total_paid_label.value = "₹0"
            self.pending_amount_label.value = "₹0"
            self._batch_price = 0
            self._total_paid = 0
            try:
                self.page.update()
            except Exception:
                pass
            return

        batch = None
        try:
            for b in self.db.get_batches():
                if b.get('id') == batch_id:
                    batch = b
                    break
        except Exception:
            pass

        if not batch:
            self.batch_label.value = "Batch not found"
            return

        batch_price = float(batch.get('price', 0) or 0)
        batch_name = batch.get('batch_name', 'Unknown')
        self._batch_price = batch_price

        try:
            payments = self.db.get_payments(traveler_id=tid)
            total_paid = sum(float(p.get('amount', 0) or 0)
                             for p in payments)
        except Exception:
            total_paid = 0
        self._total_paid = total_paid

        pending = batch_price - total_paid
        if pending < 0:
            pending = 0

        self.batch_label.value = f"{batch_name} (₹{batch_price:,.0f})"
        self.total_amount_label.value = f"₹{batch_price:,.2f}"
        self.total_paid_label.value = f"₹{total_paid:,.2f}"
        self.pending_amount_label.value = f"₹{pending:,.2f}"
        self.pending_amount_label.color = (
            "#27ae60" if pending <= 0 else "#e74c3c")

        if pending <= 0:
            self.save_btn.disabled = True
            self.amount_field.disabled = True
            self.amount_field.value = "0"
        else:
            self.save_btn.disabled = False
            self.amount_field.disabled = False
            self.amount_field.value = f"{pending:.2f}"

        self.on_amount_changed(None)

        try:
            self.page.update()
        except Exception:
            pass

    def on_amount_changed(self, e):
        pending = self._batch_price - self._total_paid
        if pending < 0:
            pending = 0

        try:
            amount = float(self.amount_field.value or 0)
        except (ValueError, TypeError):
            amount = 0.0

        remaining = pending - amount
        if remaining < 0:
            remaining = 0

        self.remaining_label.value = f"₹{remaining:,.2f}"
        if remaining == 0:
            self.remaining_label.color = "#27ae60"
        else:
            self.remaining_label.color = "#3498db"

        try:
            self.page.update()
        except Exception:
            pass

    def save_payment(self, e):
        try:
            tid = self.traveler_dropdown.value
            if not tid:
                self._snack("⚠️ Please select a traveler")
                return

            try:
                amount = float(self.amount_field.value or 0)
            except (ValueError, TypeError):
                amount = 0
            if amount <= 0:
                self._snack("⚠️ Please enter a valid amount")
                return

            traveler = self.db.get_traveler_by_id(tid)
            batch_id = traveler.get('batch_id') if traveler else None

            batch_price = 0.0
            if batch_id:
                try:
                    for b in self.db.get_batches():
                        if b.get('id') == batch_id:
                            batch_price = float(b.get('price', 0) or 0)
                            break
                except Exception:
                    pass

            try:
                payments = self.db.get_payments(traveler_id=tid)
                total_paid = sum(float(p.get('amount', 0) or 0)
                                 for p in payments)
            except Exception:
                total_paid = 0

            pending_before = batch_price - total_paid
            if amount > pending_before + 0.01:
                self._snack(
                    f"⚠️ Payment (₹{amount:,.2f}) exceeds pending "
                    f"(₹{pending_before:,.2f})")
                return

            invoice_id = ''
            if self.generate_invoice_check.value and batch_id:
                tax = self.settings_manager.get_tax_settings()
                try:
                    gst_rate = float(tax.get('gst_percentage', 18))
                    tcs_rate = float(tax.get('tcs_percentage', 0.1))
                except Exception:
                    gst_rate = 18.0
                    tcs_rate = 0.1
                try:
                    invoice_id = self.db.generate_invoice(
                        tid, batch_id, amount, gst_rate, tcs_rate)
                except Exception as inv_ex:
                    print(f"[INVOICE] failed: {inv_ex}")

            trans_id = (self.trans_field.value or '').strip()
            if not trans_id:
                trans_id = str(uuid.uuid4())[:8]

            self.payment_data = {
                'traveler_id': tid,
                'batch_id': batch_id,
                'amount': amount,
                'payment_method': self.method_dropdown.value or 'Cash',
                'status': 'completed',
                'transaction_id': trans_id,
                'invoice_id': invoice_id,
                'notes': (self.notes_field.value or '').strip(),
            }

            pid = self.db.add_payment(self.payment_data)
            try:
                self.db.log_activity(
                    self.current_user['id'], "add_payment",
                    f"Recorded payment of ₹{amount:,.2f}")
            except Exception:
                pass

            try:
                if hasattr(self.db, "reload_payments"):
                    self.db.reload_payments()
                if hasattr(self.db, "reload_receipts"):
                    self.db.reload_receipts()
                if hasattr(self.db, "reload_invoices"):
                    self.db.reload_invoices()
            except Exception:
                pass

            new_total = total_paid + amount
            new_pending = batch_price - new_total
            if new_pending < 0:
                new_pending = 0

            print(f"[PAYMENT] Recorded: ₹{amount:,.2f}, "
                  f"Total: ₹{new_total:,.2f}, Pending: ₹{new_pending:,.2f}")

            self.page.pop_dialog()
            self._snack("✅ Payment recorded successfully!")

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
# SECTION 12 + 13 END (FLET 1.0.0 VERSION)
# =================================================================================