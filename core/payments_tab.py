# =================================================================================
# SECTION 12 + 13 (FLET 1.0.0 VERSION) — PAYMENTS TAB + DIALOGS
# =================================================================================
# v1.9 — Financial-consistency review-fix release
#
#   REVIEW FIXES:
#     §1  Balances use COMPLETED-only amounts (_completed_amount helper)
#     §2  Financial-field edit triggers a confirmation dialog
#     §3  Invoice rollback if payment creation fails
#     §4  Invoice failure aborts payment (surfaced)
#     §5  PaymentDialog has status dropdown (default: completed)
#     §8  Strict payment-date parsing (YYYY-MM-DD or DD-MM-YYYY)
#     §9  Decimal used for amount validation & 2-decimal quantize
#     §10 Full UUID for auto trans IDs + uniqueness check on manual
#     §11 pending_before clamped at 0; based on completed-only
#     §12 Payments blocked when traveler has no assigned batch
#     §13 view_specific_receipt no longer auto-generates
#     §14 self.receipts is dict-of-lists (multiple receipts supported)
#     §15 Receipt/payment amount mismatch warned in receipt viewer
#     §17 Responsive dialog sizing
#     §18 show() logging on PaymentDialog / PaymentEditDialog
#     §19 Silent except blocks replaced with logged catches
#
#   PRESERVED FROM v1.8:
#     • Typing-wipe guard (_typing_until) on all three classes
#     • Leaf-only updates for search/amount/traveler-info
#     • Filter preservation across refresh
#     • Row tap = select, toolbar PDF/Print act on selected
#
#   COMPANION DB CHANGES (must be applied to database.py):
#     1. _generate_receipt() is called only when status == "completed"
#     2. add_payment() validates traveler exists and has a batch_id
#     3. update_payment() recalculates linked invoice status from all
#        completed payments referencing that invoice (fixes §16)
# =================================================================================

import flet as ft
import os
import time
import uuid
from decimal import Decimal, InvalidOperation
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


TYPING_GUARD_SECONDS = 0.6
FINANCIAL_FIELDS = {"amount", "status", "transaction_id", "invoice_id"}


# =================================================================================
# MODULE-LEVEL HELPERS
# =================================================================================

def _completed_amount(payments):
    """Sum of amounts for payments whose status is 'completed'."""
    total = 0.0
    for p in payments:
        if str(p.get("status", "")).strip().lower() == "completed":
            try:
                total += float(p.get("amount", 0) or 0)
            except (ValueError, TypeError):
                pass
    return total


def _pending_amount(payments):
    """Sum of amounts for payments whose status is 'pending'."""
    total = 0.0
    for p in payments:
        if str(p.get("status", "")).strip().lower() == "pending":
            try:
                total += float(p.get("amount", 0) or 0)
            except (ValueError, TypeError):
                pass
    return total


def _parse_payment_date(value):
    """
    Strict parse — accepts YYYY-MM-DD or DD-MM-YYYY, returns YYYY-MM-DD.
    Raises ValueError on empty or malformed input.
    """
    s = str(value or "").strip()
    if not s:
        raise ValueError("Payment date is required")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError("Payment date must be YYYY-MM-DD or DD-MM-YYYY")


def _parse_amount(value):
    """Parse amount strictly; return float quantized to 2 decimals or raise."""
    s = str(value or "").strip()
    if not s:
        raise ValueError("Amount is required")
    try:
        dec = Decimal(s)
    except InvalidOperation:
        raise ValueError("Amount must be a valid number")
    if dec <= 0:
        raise ValueError("Amount must be greater than zero")
    return float(dec.quantize(Decimal("0.01")))


def _check_unique_trans_id(new_id, all_payments, exclude_payment_id=None):
    """Return True if transaction id is unique (ignoring exclude)."""
    needle = str(new_id or "").strip().lower()
    if not needle:
        return True
    for p in all_payments:
        pid = p.get("id")
        if exclude_payment_id and str(pid) == str(exclude_payment_id):
            continue
        if str(p.get("transaction_id", "")).strip().lower() == needle:
            return False
    return True


# =================================================================================
# CLASS: PaymentEditDialog  (v1.9)
# =================================================================================
class PaymentEditDialog:

    def __init__(self, page, db, current_user, payment_data, on_save=None):
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

        self._typing_until = 0.0
        self._closed = False

        self.setup_ui()

    def _field(self, **kwargs):
        if "content_padding" not in kwargs:
            kwargs["content_padding"] = ft.Padding.symmetric(
                horizontal=10, vertical=10)
        field = ft.TextField(**kwargs)

        def _on_change(e, _f=field):
            self._typing_until = time.time() + TYPING_GUARD_SECONDS
            try:
                ctrl = getattr(e, "control", None)
                if ctrl is not None and hasattr(ctrl, "value"):
                    if _f.value != ctrl.value:
                        _f.value = ctrl.value
            except Exception:
                pass

        field.on_change = _on_change
        return field

    def setup_ui(self):
        traveler_id = self.payment_data.get('traveler_id', '')
        traveler_name = "Unknown"
        if traveler_id:
            try:
                t = self.db.get_traveler_by_id(traveler_id)
                if t:
                    traveler_name = (f"{t.get('first_name', '')} "
                                     f"{t.get('last_name', '')}").strip() or "Unnamed"
            except Exception as ex:
                print(f"[PAY-EDIT] traveler lookup failed: {ex}")

        invoice_id = self.payment_data.get('invoice_id', '')
        invoice_text = "No invoice linked"
        if invoice_id:
            try:
                for inv in self.db.get_invoices():
                    if str(inv.get('id')) == str(invoice_id):
                        invoice_text = (f"{inv.get('invoice_no', 'N/A')} "
                                        f"(ID: {invoice_id})")
                        break
                else:
                    invoice_text = f"ID: {invoice_id}"
            except Exception as ex:
                print(f"[PAY-EDIT] invoice lookup failed: {ex}")
                invoice_text = f"ID: {invoice_id}"

        self.amount_field = self._field(
            label="Amount (₹) *",
            value=str(self.payment_data.get('amount', 0)),
            height=48, text_size=12)

        # Normalize current date to YYYY-MM-DD for the field
        current_date = str(self.payment_data.get('payment_date', ''))[:10]
        self.date_field = self._field(
            label="Payment Date (YYYY-MM-DD) *",
            value=current_date,
            hint_text="e.g. 2026-10-05",
            height=48, text_size=12)

        self.method_dropdown = ft.Dropdown(
            label="Payment Method",
            options=[
                ft.dropdown.Option(key="Cash", text="Cash"),
                ft.dropdown.Option(key="Bank Transfer", text="Bank Transfer"),
                ft.dropdown.Option(key="Credit Card", text="Credit Card"),
                ft.dropdown.Option(key="Cheque", text="Cheque"),
                ft.dropdown.Option(key="Online", text="Online"),
                ft.dropdown.Option(key="UPI", text="UPI"),
            ],
            value=str(self.payment_data.get('payment_method', 'Cash')),
            height=48, text_size=12)

        self.trans_field = self._field(
            label="Transaction ID",
            value=str(self.payment_data.get('transaction_id', '')),
            height=48, text_size=12)

        self.status_dropdown = ft.Dropdown(
            label="Status",
            options=[
                ft.dropdown.Option(key="completed", text="completed"),
                ft.dropdown.Option(key="pending", text="pending"),
                ft.dropdown.Option(key="failed", text="failed"),
                ft.dropdown.Option(key="refunded", text="refunded"),
            ],
            value=str(self.payment_data.get('status', 'pending')),
            height=48, text_size=12)

        self.notes_field = self._field(
            label="Notes",
            value=str(self.payment_data.get('notes', '')),
            multiline=True, min_lines=2, max_lines=3, text_size=12)

        def info_row(label, value):
            return ft.Row([
                ft.Text(label, width=140, weight=ft.FontWeight.BOLD, size=11),
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
            spacing=12, scroll=ft.ScrollMode.AUTO)

        # §17 — responsive sizing
        page_w = getattr(self.page, "width", None) or 900
        page_h = getattr(self.page, "height", None) or 700
        dialog_w = min(520, max(320, int(page_w) - 32))
        dialog_h = min(560, max(280, int(page_h) - 120))

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("✏️ Edit Payment",
                          weight=ft.FontWeight.BOLD, size=15),
            content=ft.Container(content=content, width=dialog_w,
                                 height=dialog_h, padding=10),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self._close()),
                ft.Button(content=ft.Text("💾 Save Changes"),
                          on_click=self.save,
                          bgcolor=ft.Colors.GREEN_600,
                          color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END)

    def _build_updated(self):
        amount = _parse_amount(self.amount_field.value)
        payment_date = _parse_payment_date(self.date_field.value)
        trans_id = (self.trans_field.value or '').strip()

        # §10 — uniqueness check
        if trans_id:
            try:
                all_payments = self.db.get_payments()
                if not _check_unique_trans_id(
                        trans_id, all_payments,
                        exclude_payment_id=self.payment_data.get('id')):
                    raise ValueError(
                        f"Transaction ID '{trans_id}' already exists")
            except ValueError:
                raise
            except Exception as ex:
                print(f"[PAY-EDIT] trans-id check failed: {ex}")

        return {
            'amount': amount,
            'payment_date': payment_date,
            'payment_method': self.method_dropdown.value or 'Cash',
            'transaction_id': trans_id,
            'status': self.status_dropdown.value or 'pending',
            'notes': (self.notes_field.value or '').strip(),
        }

    def save(self, e, _confirmed=False):
        try:
            try:
                updated = self._build_updated()
            except ValueError as ve:
                self._snack(f"⚠️ {ve}")
                return

            # §2 — detect financial-field changes
            if not _confirmed:
                changed = []
                for f in FINANCIAL_FIELDS:
                    if f not in updated:
                        continue
                    old_val = self.payment_data.get(f, '')
                    new_val = updated.get(f, '')
                    if f == 'amount':
                        try:
                            old_val = float(old_val or 0)
                            new_val = float(new_val or 0)
                        except (ValueError, TypeError):
                            pass
                        if abs(old_val - new_val) > 0.005:
                            changed.append(f)
                    else:
                        if str(old_val or "") != str(new_val or ""):
                            changed.append(f)

                if changed:
                    self._show_financial_warning(changed, updated)
                    return

            self._apply_update(updated)

        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ {ex}")

    def _show_financial_warning(self, changed, updated):
        labels = {"amount": "Amount", "status": "Status",
                  "transaction_id": "Transaction ID",
                  "invoice_id": "Invoice reference"}
        human = ", ".join(labels.get(f, f) for f in changed)

        def on_confirm(ev):
            self.page.pop_dialog()
            self._apply_update(updated)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("⚠️ Confirm Financial Edit",
                          weight=ft.FontWeight.BOLD, size=14),
            content=ft.Text(
                f"You are about to modify: {human}.\n\n"
                "This affects the financial record. The linked "
                "receipt/invoice may become inconsistent. "
                "Continue?", size=12),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Continue"),
                          on_click=on_confirm,
                          bgcolor=ft.Colors.ORANGE_600,
                          color=ft.Colors.WHITE),
            ])
        self.page.show_dialog(dialog)

    def _apply_update(self, updated):
        try:
            success = self.db.update_payment(
                self.payment_data['id'], updated)
            if not success:
                self._snack("❌ Failed to update payment")
                return

            self.payment_data.update(updated)

            try:
                self.db.log_activity(
                    self.current_user['id'], "edit_payment",
                    f"Edited payment #{self.payment_data['id']} - "
                    f"Amount: ₹{updated['amount']:,.2f}, "
                    f"Status: {updated['status']}")
            except Exception as log_ex:
                print(f"[PAY-EDIT] activity log failed: {log_ex}")

            self._typing_until = 0.0
            self._close()
            self._snack("✅ Payment updated successfully!")

            if self.on_save:
                try:
                    self.on_save()
                except Exception as cb_ex:
                    print(f"[PAY-EDIT] on_save callback failed: {cb_ex}")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ {ex}")

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self._typing_until = 0.0
        try:
            self.page.pop_dialog()
        except Exception as ex:
            print(f"[PAY-EDIT] pop_dialog failed: {ex}")

    def show(self):
        try:
            print("[PAY-EDIT] opening edit dialog")
            self.page.show_dialog(self.dialog)
            print("[PAY-EDIT] dialog opened")
        except Exception as ex:
            import traceback
            print(f"[PAY-EDIT] dialog failed: {ex}")
            traceback.print_exc()
            try:
                self.page.show_dialog(ft.SnackBar(
                    content=ft.Text(f"Unable to open edit form: {ex}")))
            except Exception:
                pass
            self._closed = True

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception as ex:
            print(f"[PAY-EDIT] snack failed: {ex}")


# =================================================================================
# CLASS: PaymentsTab  (v1.9)
# =================================================================================
class PaymentsTab:

    def __init__(self, page: ft.Page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user

        self.payments = []
        self.travelers = {}
        self.receipts = {}          # payment_id -> list[receipt]
        self.invoices = {}
        self.batches = {}
        self.traveler_details = {}

        self.stat_labels = {}
        self.status_filter = None
        self.method_filter = None
        self.search_input = None
        self.table = None
        self.root = None
        self.selection_label = None

        self._selected_payment_id = None
        self._typing_until = 0.0

        self.setup_ui()
        self.refresh()

    def build(self):
        return self.root

    def _safe_update(self):
        if time.time() < self._typing_until:
            print("[PAYMENTS] _safe_update SKIPPED (typing)")
            return
        try:
            if self.root is not None:
                self.root.update()
        except Exception as e:
            print(f"[PAYMENTS] _safe_update failed: {e}")

    def _update_table_only(self):
        for ctrl in (self.table, self.selection_label):
            if ctrl is None:
                continue
            try:
                ctrl.update()
            except Exception:
                pass

    def setup_ui(self):
        stat_configs = [
            ("total",           "💰 Recorded",    "#3498db"),
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
            stat_cards.append(ft.Container(
                content=ft.Column([
                    ft.Text(label, size=9, color=ft.Colors.WHITE,
                            weight=ft.FontWeight.BOLD,
                            no_wrap=False, max_lines=2),
                    value_label,
                ], spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=8, bgcolor=color, border_radius=10, height=64,
            ))

        stats_row = ft.ResponsiveRow(
            controls=[ft.Container(content=c,
                                   col={"xs": 6, "sm": 6, "md": 4, "lg": 2})
                      for c in stat_cards],
            spacing=6, run_spacing=6,
        )

        def _tb(label, color, handler):
            return ft.Button(
                content=ft.Text(label, size=11,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE,
                                no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS),
                on_click=handler, height=40, bgcolor=color,
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
            content_padding=ft.Padding.symmetric(
                horizontal=10, vertical=8))

        def _search_on_change(e, _f=self.search_input):
            self._typing_until = time.time() + TYPING_GUARD_SECONDS
            try:
                ctrl = getattr(e, "control", None)
                if ctrl is not None and hasattr(ctrl, "value"):
                    if _f.value != ctrl.value:
                        _f.value = ctrl.value
            except Exception:
                pass
            self.filter_payments(e)

        self.search_input.on_change = _search_on_change

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
                ft.DataColumn(ft.Text("Sel", size=11)),
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
            data_row_min_height=44, data_row_max_height=58,
            border=ft.Border.all(1, ft.Colors.GREY_300),
            border_radius=10,
        )

        self.selection_label = ft.Text("", size=10, color=ft.Colors.BLUE_700,
                                       weight=ft.FontWeight.BOLD, italic=True)

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
                            ft.Text("💡 Tap a row to SELECT it, then use "
                                    "toolbar 📄 PDF / 🖨️ Print.",
                                    size=10, color=ft.Colors.GREY_600,
                                    italic=True),
                            self.selection_label,
                            ft.Row([self.table],
                                   scroll=ft.ScrollMode.ADAPTIVE),
                        ], spacing=6),
                        bgcolor=ft.Colors.WHITE, border_radius=10, padding=10),
                ],
                spacing=10, scroll=ft.ScrollMode.AUTO,
            ),
            padding=10, bgcolor="#f0f2f5", expand=True,
        )

    def refresh(self):
        try:
            self.payments = self.db.get_payments()
            self.travelers = {
                t['id']: (f"{t.get('first_name', '')} "
                          f"{t.get('last_name', '')}").strip() or "Unnamed"
                for t in self.db.get_travelers()
            }

            # §14 — dict of lists
            self.receipts = {}
            for r in self.db.get_receipts():
                self.receipts.setdefault(r.get('payment_id'), []).append(r)

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

            print(f"[PAYMENTS] loaded {len(self.payments)} payments, "
                  f"{len(self.travelers)} travelers, "
                  f"{sum(len(v) for v in self.receipts.values())} receipts, "
                  f"{len(self.invoices)} invoices")

            self._apply_filters_internal()
            self.update_summary_stats()
            self._safe_update()
        except Exception as ex:
            print(f"Payments refresh error: {ex}")
            import traceback
            traceback.print_exc()

    def _apply_filters_internal(self):
        search = (self.search_input.value or "").strip().lower() \
            if self.search_input else ""
        status = (self.status_filter.value or "All") \
            if self.status_filter else "All"
        method = (self.method_filter.value or "All") \
            if self.method_filter else "All"

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

    def display_payments(self, payments=None):
        if payments is None:
            payments = self.payments

        # §1 — completed-only for balances
        traveler_completed = {}
        for p in payments:
            tid = p.get('traveler_id')
            if tid and str(p.get('status', '')).lower() == 'completed':
                try:
                    traveler_completed[tid] = (
                        traveler_completed.get(tid, 0)
                        + float(p.get('amount', 0) or 0))
                except (ValueError, TypeError):
                    pass

        self.table.rows.clear()
        for p in payments:
            tid = p.get('traveler_id', '')
            pid = p.get('id')
            date_str = (str(p.get('payment_date', ''))[:10]
                        if p.get('payment_date') else '')
            traveler_name = self.travelers.get(tid, 'Unknown')
            try:
                amount_val = float(p.get('amount', 0) or 0)
            except (ValueError, TypeError):
                amount_val = 0.0
            amount_text = f"₹{amount_val:,.0f}"
            method = str(p.get('payment_method', ''))
            status = str(p.get('status', 'pending'))
            status_color = ("#27ae60" if status == "completed"
                            else "#f39c12" if status == "pending"
                            else "#e74c3c" if status == "failed"
                            else "#95a5a6")
            txn = str(p.get('transaction_id', '') or '')[:12]

            # §14 — list of receipts
            receipt_list = self.receipts.get(pid, [])
            receipt_no = receipt_list[0].get('receipt_no', '—') \
                if receipt_list else '—'

            inv_id = p.get('invoice_id', '')
            inv_no = ''
            if inv_id and inv_id in self.invoices:
                inv_no = str(self.invoices[inv_id].get('invoice_no', ''))[:14]

            traveler_info = self.traveler_details.get(
                tid, {'batch_price': 0, 'batch_name': 'No Batch'})
            batch_price = traveler_info['batch_price']
            completed_paid = traveler_completed.get(tid, 0)
            package_pending = max(0.0, batch_price - completed_paid)

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
                if str(inv.get('status', '')).lower() == 'pending':
                    try:
                        inv_pending = float(
                            inv.get('rounded_total',
                                    inv.get('total_amount', 0)) or 0)
                    except (ValueError, TypeError):
                        inv_pending = 0

            if inv_pending > 0:
                inv_txt = f"₹{inv_pending:,.0f}"
                inv_color = "#f39c12"
            elif inv_id and inv_id in self.invoices:
                inv_txt = "✅ Paid"
                inv_color = "#27ae60"
            else:
                inv_txt = "N/A"
                inv_color = "#95a5a6"

            is_selected = (self._selected_payment_id == pid)

            # §13 — receipt action reflects whether a receipt exists
            if receipt_list:
                receipt_action = ft.IconButton(
                    icon=ft.Icons.RECEIPT_LONG,
                    icon_color="#3498db", icon_size=18,
                    tooltip="View Receipt",
                    on_click=lambda e, pp=p: self.view_specific_receipt(pp))
            else:
                receipt_action = ft.IconButton(
                    icon=ft.Icons.ADD_BOX,
                    icon_color="#f39c12", icon_size=18,
                    tooltip="Generate Receipt (status: completed only)",
                    on_click=lambda e, pp=p:
                        self.generate_receipt_for_payment(pp))

            actions = ft.Row(
                controls=[
                    ft.IconButton(icon=ft.Icons.EDIT,
                                  icon_color="#f39c12", icon_size=18,
                                  tooltip="Edit",
                                  on_click=lambda e, pp=p:
                                      self.edit_payment(pp)),
                    receipt_action,
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
                ], spacing=0)

            def _on_row_tap(e, pid=pid):
                try:
                    self._select_payment(pid)
                except Exception as ex:
                    print(f"[PAYMENTS] row tap error: {ex}")

            self.table.rows.append(ft.DataRow(
                on_select_change=_on_row_tap,
                selected=is_selected,
                cells=[
                    ft.DataCell(ft.Container(
                        content=ft.Text("✓" if is_selected else "",
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                        color="#27ae60"),
                        width=24, alignment=ft.Alignment.CENTER,
                        bgcolor=("#dcfce7" if is_selected else None),
                        border_radius=4)),
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
                ]))

    def _select_payment(self, payment_id):
        if self._selected_payment_id == payment_id:
            self._selected_payment_id = None
        else:
            self._selected_payment_id = payment_id

        if self.selection_label:
            if self._selected_payment_id:
                p = next((x for x in self.payments
                          if x.get('id') == self._selected_payment_id), None)
                if p:
                    try:
                        amt = float(p.get('amount', 0) or 0)
                    except (ValueError, TypeError):
                        amt = 0.0
                    self.selection_label.value = (
                        f"✅ Selected: "
                        f"{self.travelers.get(p.get('traveler_id',''),'?')} "
                        f"| ₹{amt:,.0f} | "
                        f"Txn: {str(p.get('transaction_id',''))[:12]}")
                else:
                    self.selection_label.value = ""
            else:
                self.selection_label.value = ""

        self.display_payments()
        self._update_table_only()

    def _get_selected_payment(self):
        if not self._selected_payment_id:
            return None
        return next((p for p in self.payments
                     if p.get('id') == self._selected_payment_id), None)

    def edit_payment(self, payment):
        dlg = PaymentEditDialog(
            self.page, self.db, self.current_user, payment,
            on_save=self.refresh)
        dlg.show()

    def filter_payments(self, e=None):
        self._apply_filters_internal()
        self._update_table_only()

    def add_payment(self, e):
        dlg = PaymentDialog(self.page, self.db, self.current_user,
                            on_save=self.refresh)
        dlg.show()

    # §13 — read-only; no auto-generate
    def view_specific_receipt(self, payment):
        receipts = self.db.get_receipts(payment.get('id'))
        if not receipts:
            self._snack("⚠️ No receipt exists for this payment. "
                        "Use the 🧾 Generate action (completed "
                        "payments only).")
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
        except Exception as ex:
            print(f"[PAYMENTS] company settings read failed: {ex}")

        try:
            receipt_amount = float(receipt.get('amount', 0) or 0)
        except (ValueError, TypeError):
            receipt_amount = 0.0
        try:
            payment_amount = float(payment.get('amount', 0) or 0)
        except (ValueError, TypeError):
            payment_amount = 0.0

        # §15 — mismatch warning
        mismatch_note = ""
        if abs(receipt_amount - payment_amount) > 0.01:
            mismatch_note = (
                f"\n⚠️ WARNING: Receipt (₹{receipt_amount:,.2f}) "
                f"differs from payment (₹{payment_amount:,.2f})")

        amount_in_words = number_to_words_indian(int(receipt_amount))
        tid = payment.get('traveler_id', '')
        traveler_info = self.traveler_details.get(
            tid, {'batch_price': 0, 'batch_name': 'No Batch'})
        batch_price = traveler_info['batch_price']

        # §1 — completed-only
        traveler_payments = [
            p for p in self.payments if p.get('traveler_id') == tid]
        total_paid = _completed_amount(traveler_payments)
        package_pending = max(0.0, batch_price - total_paid)

        inv_id = payment.get('invoice_id', '')
        inv_pending = 0
        inv_no = 'N/A'
        if inv_id and inv_id in self.invoices:
            inv = self.invoices[inv_id]
            inv_no = inv.get('invoice_no', 'N/A')
            if str(inv.get('status', '')).lower() == 'pending':
                try:
                    inv_pending = float(
                        inv.get('rounded_total',
                                inv.get('total_amount', 0)) or 0)
                except (ValueError, TypeError):
                    inv_pending = 0

        details = (
            f"Company:  {company_name}\n"
            f"Receipt No:  {receipt.get('receipt_no', '')}\n"
            f"Date:  {str(receipt.get('receipt_date', ''))[:10]}\n"
            f"Received From:  {traveler_name}\n"
            f"Amount:  ₹{receipt_amount:,.2f}\n"
            f"Amount in Words:  {amount_in_words}\n"
            f"Method:  {payment.get('payment_method', 'N/A')}\n"
            f"Transaction ID:  {payment.get('transaction_id', 'N/A')}\n"
            f"Invoice No:  {inv_no}\n"
            f"Status:  {payment.get('status', 'completed')}"
            f"{mismatch_note}\n"
            f"\nPAYMENT SUMMARY (completed only)\n"
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
            actions=[ft.Button(content=ft.Text("Close"),
                               on_click=lambda e: self.page.pop_dialog(),
                               bgcolor=ft.Colors.BLUE_700,
                               color=ft.Colors.WHITE)],
        )
        self.page.show_dialog(dialog)

    def export_pdf_selected(self, e):
        p = self._get_selected_payment()
        if not p:
            self._snack("⚠️ Tap a row first to select it, then tap 📄 PDF")
            return
        self.export_single_receipt_pdf(p)

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
            except Exception as ex:
                print(f"[PAYMENTS] company settings read failed: {ex}")

            tid = payment.get('traveler_id', '')
            traveler = self.db.get_traveler_by_id(tid)
            traveler_name = (
                f"{traveler.get('first_name', '')} "
                f"{traveler.get('last_name', '')}").strip() or "Unknown"
            bid = payment.get('batch_id', '')
            batch = self.db.get_batch_by_id(bid) if bid else None
            try:
                batch_price = float(batch.get('price', 0) or 0) if batch else 0
            except (ValueError, TypeError):
                batch_price = 0
            batch_name = (batch.get('batch_name', 'No Batch')
                          if batch else 'No Batch')

            # §1 — completed-only
            traveler_payments = [
                p for p in self.payments if p.get('traveler_id') == tid]
            total_paid = _completed_amount(traveler_payments)
            package_pending = max(0.0, batch_price - total_paid)

            inv_id = payment.get('invoice_id', '')
            inv_pending = 0
            inv_no = 'N/A'
            if inv_id and inv_id in self.invoices:
                inv = self.invoices[inv_id]
                inv_no = inv.get('invoice_no', 'N/A')
                if str(inv.get('status', '')).lower() == 'pending':
                    try:
                        inv_pending = float(
                            inv.get('rounded_total',
                                    inv.get('total_amount', 0)) or 0)
                    except (ValueError, TypeError):
                        inv_pending = 0

            try:
                receipt_amount = float(receipt.get('amount', 0) or 0)
            except (ValueError, TypeError):
                receipt_amount = 0
            amount_in_words = number_to_words_indian(int(receipt_amount))

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
                ["Amount:", f"₹{receipt_amount:,.2f}"],
                ["Amount in Words:", amount_in_words],
                ["Payment Method:", payment.get('payment_method', 'N/A')],
                ["Transaction ID:", payment.get('transaction_id', 'N/A')],
                ["Invoice No:", inv_no],
                ["Status:", payment.get('status', 'completed')],
                ["", ""],
                ["📊 PAYMENT SUMMARY (completed only)", ""],
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
                except Exception as ex:
                    print(f"[PAYMENTS] launch_url failed: {ex}")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ PDF error: {ex}")

    def print_receipt_selected(self, e):
        p = self._get_selected_payment()
        if not p:
            self._snack("⚠️ Tap a row first to select it, then tap 🖨️ Print")
            return
        self.print_single_receipt(p)

    def print_single_receipt(self, payment):
        self._snack("🖨️ Generating PDF — press Ctrl+P when it opens")
        self.export_single_receipt_pdf(payment)

    def generate_receipt_for_payment(self, payment):
        # §5 / §6 — only completed payments generate receipts
        if str(payment.get('status', '')).lower() != 'completed':
            self._snack(
                f"⚠️ Cannot generate receipt for a "
                f"'{payment.get('status', 'unknown')}' payment. "
                f"Only completed payments have receipts.")
            return

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
            except Exception as log_ex:
                print(f"[PAYMENTS] activity log failed: {log_ex}")
            self.refresh()
            self._snack("✅ Receipt generated")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ {ex}")

    def update_summary_stats(self):
        # §1 — all = recorded (for context), completed/pending for finance
        total_recorded = 0.0
        for p in self.payments:
            try:
                total_recorded += float(p.get('amount', 0) or 0)
            except (ValueError, TypeError):
                pass

        completed = _completed_amount(self.payments)
        pending = _pending_amount(self.payments)
        receipt_count = sum(len(v) for v in self.receipts.values())

        # §1 — completed-only balances
        traveler_completed = {}
        for p in self.payments:
            tid = p.get('traveler_id')
            if tid and str(p.get('status', '')).lower() == 'completed':
                try:
                    traveler_completed[tid] = (
                        traveler_completed.get(tid, 0)
                        + float(p.get('amount', 0) or 0))
                except (ValueError, TypeError):
                    pass

        total_package_pending = 0.0
        for tid, info in self.traveler_details.items():
            bp = info['batch_price']
            if bp <= 0:
                continue
            paid = traveler_completed.get(tid, 0)
            delta = bp - paid
            if delta > 0:
                total_package_pending += delta

        total_invoice_pending = 0.0
        for inv in self.invoices.values():
            if str(inv.get('status', '')).lower() == 'pending':
                try:
                    total_invoice_pending += float(
                        inv.get('rounded_total',
                                inv.get('total_amount', 0)) or 0)
                except (ValueError, TypeError):
                    pass

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

        self.stat_labels['total'].value = _short(total_recorded)
        self.stat_labels['completed'].value = _short(completed)
        self.stat_labels['pending'].value = _short(pending)
        self.stat_labels['receipts'].value = str(receipt_count)
        self.stat_labels['package_pending'].value = _short(total_package_pending)
        self.stat_labels['invoice_pending'].value = _short(total_invoice_pending)

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception as ex:
            print(f"[PAYMENTS] snack failed: {ex}")


# =================================================================================
# CLASS: PaymentDialog  (v1.9 — record new payment)
# =================================================================================
class PaymentDialog:

    def __init__(self, page, db, current_user, traveler=None, on_save=None):
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
        self.status_dropdown = None
        self.generate_invoice_check = None
        self.notes_field = None
        self.save_btn = None
        self.dialog = None

        self._current_traveler_id = None
        self._batch_price = 0.0
        self._total_paid_completed = 0.0
        self._typing_until = 0.0
        self._closed = False

        self.setup_ui()
        if traveler:
            self.select_traveler(traveler.get('id'))

    def _field(self, **kwargs):
        if "content_padding" not in kwargs:
            kwargs["content_padding"] = ft.Padding.symmetric(
                horizontal=10, vertical=10)
        field = ft.TextField(**kwargs)

        def _on_change(e, _f=field):
            self._typing_until = time.time() + TYPING_GUARD_SECONDS
            try:
                ctrl = getattr(e, "control", None)
                if ctrl is not None and hasattr(ctrl, "value"):
                    if _f.value != ctrl.value:
                        _f.value = ctrl.value
            except Exception:
                pass

        field.on_change = _on_change
        return field

    def _update_traveler_labels(self):
        for c in (self.batch_label, self.total_amount_label,
                  self.total_paid_label, self.pending_amount_label):
            if c is None:
                continue
            try:
                c.update()
            except Exception:
                pass

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
        except Exception as ex:
            print(f"[PAY-DIALOG] traveler list load failed: {ex}")

        self.traveler_dropdown = ft.Dropdown(
            label="Traveler *",
            options=traveler_options or [
                ft.dropdown.Option(key="", text="No travelers available")],
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
                ft.Text(label, width=150, weight=ft.FontWeight.BOLD, size=11),
                control,
            ], spacing=8)

        self.amount_field = self._field(
            label="💵 Payment Amount (₹) *",
            value="0", height=48, text_size=13)

        def _amount_on_change(e, _f=self.amount_field):
            self._typing_until = time.time() + TYPING_GUARD_SECONDS
            try:
                ctrl = getattr(e, "control", None)
                if ctrl is not None and hasattr(ctrl, "value"):
                    if _f.value != ctrl.value:
                        _f.value = ctrl.value
            except Exception:
                pass
            self.on_amount_changed(e)

        self.amount_field.on_change = _amount_on_change

        self.remaining_label = ft.Text("₹0", size=12,
                                       weight=ft.FontWeight.BOLD,
                                       color="#3498db")

        self.method_dropdown = ft.Dropdown(
            label="Payment Method",
            options=[
                ft.dropdown.Option(key="Cash", text="Cash"),
                ft.dropdown.Option(key="Bank Transfer", text="Bank Transfer"),
                ft.dropdown.Option(key="Credit Card", text="Credit Card"),
                ft.dropdown.Option(key="Cheque", text="Cheque"),
                ft.dropdown.Option(key="Online", text="Online"),
                ft.dropdown.Option(key="UPI", text="UPI"),
            ],
            value="Cash", height=48, text_size=12)

        self.trans_field = self._field(
            label="Transaction ID (optional)",
            hint_text="Leave blank to auto-generate",
            height=48, text_size=12)

        # §5 — status selector (default: completed)
        self.status_dropdown = ft.Dropdown(
            label="Payment Status",
            options=[
                ft.dropdown.Option(key="completed", text="Completed"),
                ft.dropdown.Option(key="pending", text="Pending"),
            ],
            value="completed", height=48, text_size=12)

        self.generate_invoice_check = ft.Checkbox(
            label="Generate Invoice (GST/TCS applied)", value=False)

        self.notes_field = self._field(
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
                info_row("✅ Completed Paid:", self.total_paid_label),
                info_row("⚠️ Pending:", self.pending_amount_label),
                ft.Divider(height=10),
                self.amount_field,
                info_row("📊 Remaining:", self.remaining_label),
                self.method_dropdown,
                self.trans_field,
                self.status_dropdown,
                self.generate_invoice_check,
                self.notes_field,
            ],
            spacing=12, scroll=ft.ScrollMode.AUTO)

        # §17 — responsive
        page_w = getattr(self.page, "width", None) or 900
        page_h = getattr(self.page, "height", None) or 700
        dialog_w = min(540, max(320, int(page_w) - 32))
        dialog_h = min(680, max(280, int(page_h) - 120))

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("💰 Record Payment",
                          weight=ft.FontWeight.BOLD, size=15),
            content=ft.Container(content=content, width=dialog_w,
                                 height=dialog_h, padding=10),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self._close()),
                self.save_btn,
            ],
            actions_alignment=ft.MainAxisAlignment.END)

    def select_traveler(self, traveler_id):
        try:
            self.traveler_dropdown.value = str(traveler_id)
        except Exception:
            pass
        self.update_traveler_info()

    def on_traveler_change(self, e):
        self._typing_until = time.time() + TYPING_GUARD_SECONDS
        self.update_traveler_info()

    def update_traveler_info(self):
        tid = self.traveler_dropdown.value
        if not tid:
            self.batch_label.value = "Not assigned"
            self.total_amount_label.value = "₹0"
            self.total_paid_label.value = "₹0"
            self.pending_amount_label.value = "₹0"
            self._batch_price = 0
            self._total_paid_completed = 0
            self._current_traveler_id = None
            self._update_traveler_labels()
            return

        try:
            traveler = self.db.get_traveler_by_id(tid)
        except Exception as ex:
            print(f"[PAY-DIALOG] traveler lookup failed: {ex}")
            traveler = None

        if not traveler:
            self.batch_label.value = "Traveler not found"
            self._update_traveler_labels()
            return

        self._current_traveler_id = tid
        batch_id = traveler.get('batch_id')

        if not batch_id:
            self.batch_label.value = "⚠️ No batch assigned"
            self.total_amount_label.value = "₹0"
            self.total_paid_label.value = "₹0"
            self.pending_amount_label.value = "₹0"
            self._batch_price = 0
            self._total_paid_completed = 0
            self.save_btn.disabled = True
            self.amount_field.disabled = True
            self._update_traveler_labels()
            return

        batch = None
        try:
            for b in self.db.get_batches():
                if b.get('id') == batch_id:
                    batch = b
                    break
        except Exception as ex:
            print(f"[PAY-DIALOG] batch lookup failed: {ex}")

        if not batch:
            self.batch_label.value = "Batch not found"
            self._update_traveler_labels()
            return

        try:
            batch_price = float(batch.get('price', 0) or 0)
        except (ValueError, TypeError):
            batch_price = 0.0
        batch_name = batch.get('batch_name', 'Unknown')
        self._batch_price = batch_price

        # §1 — completed-only for paid total
        try:
            payments = self.db.get_payments(traveler_id=tid)
            total_paid = _completed_amount(payments)
        except Exception as ex:
            print(f"[PAY-DIALOG] payments lookup failed: {ex}")
            total_paid = 0.0
        self._total_paid_completed = total_paid

        pending = max(0.0, batch_price - total_paid)

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
        self._update_traveler_labels()

    def on_amount_changed(self, e):
        pending = max(0.0, self._batch_price - self._total_paid_completed)

        try:
            amount = float(self.amount_field.value or 0)
        except (ValueError, TypeError):
            amount = 0.0

        remaining = max(0.0, pending - amount)
        self.remaining_label.value = f"₹{remaining:,.2f}"
        self.remaining_label.color = ("#27ae60" if remaining == 0
                                      else "#3498db")

        try:
            self.remaining_label.update()
        except Exception:
            pass
        try:
            self.save_btn.update()
        except Exception:
            pass

    def save_payment(self, e):
        try:
            tid = self.traveler_dropdown.value
            if not tid:
                self._snack("⚠️ Please select a traveler")
                return

            # §12 — block traveler without batch
            try:
                traveler = self.db.get_traveler_by_id(tid)
            except Exception as ex:
                print(f"[PAY-DIALOG] traveler lookup failed: {ex}")
                self._snack(f"❌ Traveler lookup failed: {ex}")
                return
            if not traveler:
                self._snack("❌ Traveler not found")
                return
            batch_id = traveler.get('batch_id')
            if not batch_id:
                self._snack("⚠️ Traveler has no assigned batch")
                return

            # §9 — strict amount parsing
            try:
                amount = _parse_amount(self.amount_field.value)
            except ValueError as ve:
                self._snack(f"⚠️ {ve}")
                return

            # Batch price lookup
            batch_price = 0.0
            try:
                for b in self.db.get_batches():
                    if b.get('id') == batch_id:
                        batch_price = float(b.get('price', 0) or 0)
                        break
            except Exception as ex:
                print(f"[PAY-DIALOG] batch lookup failed: {ex}")

            # §1 / §11 — pending based on completed-only
            try:
                payments = self.db.get_payments(traveler_id=tid)
                total_paid_completed = _completed_amount(payments)
            except Exception as ex:
                print(f"[PAY-DIALOG] payments lookup failed: {ex}")
                total_paid_completed = 0.0

            pending_before = max(0.0, batch_price - total_paid_completed)
            if amount > pending_before + 0.01:
                self._snack(
                    f"⚠️ Payment (₹{amount:,.2f}) exceeds pending "
                    f"(₹{pending_before:,.2f})")
                return

            # §10 — transaction ID uniqueness
            trans_id = (self.trans_field.value or '').strip()
            if not trans_id:
                trans_id = str(uuid.uuid4())
            else:
                try:
                    if not _check_unique_trans_id(
                            trans_id, self.db.get_payments()):
                        self._snack(
                            f"⚠️ Transaction ID '{trans_id}' already exists")
                        return
                except Exception as ex:
                    print(f"[PAY-DIALOG] trans-id check failed: {ex}")

            # §5 — status from dropdown
            status = self.status_dropdown.value or "completed"

            # §3 — generate invoice BEFORE payment (so we can rollback)
            invoice_id = ''
            if self.generate_invoice_check.value:
                try:
                    tax = self.settings_manager.get_tax_settings()
                    try:
                        gst_rate = float(tax.get('gst_percentage', 18))
                    except (ValueError, TypeError):
                        gst_rate = 18.0
                    try:
                        tcs_rate = float(tax.get('tcs_percentage', 0.1))
                    except (ValueError, TypeError):
                        tcs_rate = 0.1
                except Exception:
                    gst_rate = 18.0
                    tcs_rate = 0.1

                try:
                    invoice_id = self.db.generate_invoice(
                        tid, batch_id, amount, gst_rate, tcs_rate)
                    print(f"[PAY-DIALOG] invoice created: {invoice_id}")
                except Exception as inv_ex:
                    # §4 — abort if invoice creation fails
                    print(f"[PAY-DIALOG] invoice creation failed: {inv_ex}")
                    import traceback
                    traceback.print_exc()
                    self._snack(
                        f"❌ Invoice creation failed: {inv_ex}\n"
                        f"Payment was NOT recorded.")
                    return

            # §3 — create payment; rollback invoice on failure
            self.payment_data = {
                'traveler_id': tid,
                'batch_id': batch_id,
                'amount': amount,
                'payment_method': self.method_dropdown.value or 'Cash',
                'status': status,
                'transaction_id': trans_id,
                'invoice_id': invoice_id,
                'notes': (self.notes_field.value or '').strip(),
            }

            try:
                pid = self.db.add_payment(self.payment_data)
                print(f"[PAY-DIALOG] payment created: {pid}")
            except Exception as pay_ex:
                print(f"[PAY-DIALOG] payment creation failed: {pay_ex}")
                import traceback
                traceback.print_exc()
                if invoice_id:
                    try:
                        self.db.delete_invoice(invoice_id)
                        print(f"[PAY-DIALOG] rolled back invoice: "
                              f"{invoice_id}")
                    except Exception as rb_ex:
                        print(f"[PAY-DIALOG] invoice rollback failed: "
                              f"{rb_ex}")
                self._snack(f"❌ Payment creation failed: {pay_ex}")
                return

            try:
                self.db.log_activity(
                    self.current_user['id'], "add_payment",
                    f"Recorded payment of ₹{amount:,.2f} "
                    f"(status: {status})")
            except Exception as log_ex:
                print(f"[PAY-DIALOG] activity log failed: {log_ex}")

            new_total = total_paid_completed + (
                amount if status == 'completed' else 0.0)
            new_pending = max(0.0, batch_price - new_total)

            print(f"[PAY-DIALOG] Recorded: ₹{amount:,.2f}, "
                  f"Status: {status}, "
                  f"Completed-paid total: ₹{new_total:,.2f}, "
                  f"Pending: ₹{new_pending:,.2f}")

            self._typing_until = 0.0
            self._close()
            self._snack("✅ Payment recorded successfully!")

            if self.on_save:
                try:
                    self.on_save()
                except Exception as cb_ex:
                    print(f"[PAY-DIALOG] on_save callback failed: {cb_ex}")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ {ex}")

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self._typing_until = 0.0
        try:
            self.page.pop_dialog()
        except Exception as ex:
            print(f"[PAY-DIALOG] pop_dialog failed: {ex}")

    def show(self):
        try:
            print("[PAY-DIALOG] opening payment dialog")
            self.page.show_dialog(self.dialog)
            print("[PAY-DIALOG] payment dialog opened")
        except Exception as ex:
            import traceback
            print(f"[PAY-DIALOG] dialog failed: {ex}")
            traceback.print_exc()
            try:
                self.page.show_dialog(ft.SnackBar(
                    content=ft.Text(f"Unable to open payment form: {ex}")))
            except Exception:
                pass
            self._closed = True

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception as ex:
            print(f"[PAY-DIALOG] snack failed: {ex}")


# =================================================================================
# SECTION 12 + 13 END (FLET 1.0.0 VERSION) — v1.9
# =================================================================================