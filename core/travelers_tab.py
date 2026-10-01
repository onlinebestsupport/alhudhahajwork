# =================================================================================
# SECTION 8 + 9 + 10 (FLET 1.0.0 VERSION) — TRAVELERS TAB + DIALOGS
# =================================================================================
# v1.3 — Row Selection + Data-Loading Safety
#   • Row tap SELECTS (does not open edit)
#   • Toolbar PDF / Print act on selected row
#   • on_select_change (correct Flet 1.0.0 param)
#   • Icons 16 → 18 for easier tap
#   • refresh() no longer calls db.reload_travelers() / reload_batches()
#   • Dialogs no longer call reload_travelers() on save
#   • All original features preserved
# =================================================================================

import flet as ft
import base64
import os
import shutil
from pathlib import Path
from datetime import datetime
import pandas as pd

from core.helpers import get_app_base_path, send_file_to_user


# =================================================================================
# Helper — strip trailing ".0" from numeric-looking strings
# =================================================================================
_NUMERIC_STRING_FIELDS = {
    "pin",
    "mobile",
    "emergency_phone",
    "aadhaar",
    "passport_no",
}


def _clean_number_string(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value != value:
            return ""
        if value.is_integer():
            return str(int(value))
        return str(value)
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat", "null"):
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    return s


# =================================================================================
# 8.1 — CLASS: TravelersTab
# =================================================================================
class TravelersTab:

    def __init__(self, page: ft.Page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user

        self.travelers = []
        self.batches = []
        self.filtered_travelers = []
        self.current_page = 1
        self.items_per_page = 10

        self.stats_labels = {}
        self.search_input = None
        self.table = None
        self.pagination_label = None
        self.prev_btn = None
        self.next_btn = None
        self.root = None
        self.selection_label = None

        # Currently selected traveler (for toolbar PDF/Print)
        self._selected_traveler_id = None

        self.setup_ui()
        self.refresh()

    def build(self):
        return self.root

    # =============================================================================
    # 8.2 — setup_ui
    # =============================================================================
    def setup_ui(self):
        # ---- STAT CARDS ----
        stat_configs = [
            ("total",         "Total Travelers",   "👥", "#3498db"),
            ("active",        "Active Passports",  "✅", "#27ae60"),
            ("vaccinated",    "Fully Vaccinated",  "💉", "#f39c12"),
            ("docs_complete", "Docs Complete",     "📄", "#9b59b6"),
        ]

        stat_cards = []
        for key, label, icon, color in stat_configs:
            value_label = ft.Text("0", size=20,
                                  weight=ft.FontWeight.BOLD,
                                  color=ft.Colors.WHITE)
            self.stats_labels[key] = value_label
            card = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text(icon, size=16),
                                ft.Text(label, size=10,
                                        color=ft.Colors.WHITE,
                                        weight=ft.FontWeight.BOLD,
                                        no_wrap=False,
                                        max_lines=2),
                            ],
                            spacing=6,
                        ),
                        value_label,
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=10,
                bgcolor=color,
                border_radius=12,
                height=80,
            )
            stat_cards.append(card)

        stats_row = ft.ResponsiveRow(
            controls=[
                ft.Container(content=c,
                             col={"xs": 6, "sm": 6, "md": 3, "lg": 3})
                for c in stat_cards
            ],
            spacing=8, run_spacing=8,
        )

        # ---- TOOLBAR ----
        def _toolbar_btn(label, color, handler):
            return ft.Button(
                content=ft.Text(label, size=11,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE,
                                no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS),
                on_click=handler,
                height=40,
                bgcolor=color,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=8)),
            )

        self.search_input = ft.TextField(
            hint_text="🔍 Search travelers...",
            height=42,
            on_change=self.search_travelers,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            text_size=12,
        )

        toolbar = ft.ResponsiveRow(
            controls=[
                ft.Container(
                    content=_toolbar_btn("➕ Add Traveler", "#27ae60",
                                         self.open_add_dialog),
                    col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(
                    content=_toolbar_btn("📊 Excel", "#16a085",
                                         self.export_to_excel),
                    col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(
                    content=_toolbar_btn("📄 PDF", "#c0392b",
                                         self.export_to_pdf),
                    col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(
                    content=_toolbar_btn("🖨️ Print", "#2980b9",
                                         self.print_table),
                    col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(
                    content=_toolbar_btn("📂 Bulk Upload", "#8e44ad",
                                         self.bulk_upload_csv),
                    col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(
                    content=_toolbar_btn("📥 Template", "#16a085",
                                         self.download_csv_template),
                    col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(
                    content=self.search_input,
                    col={"xs": 12, "sm": 12, "md": 12}),
            ],
            spacing=8, run_spacing=8,
        )

        # ---- TABLE ----
        self.table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Sel", size=11)),
                ft.DataColumn(ft.Text("#", size=11)),
                ft.DataColumn(ft.Text("Name", size=11)),
                ft.DataColumn(ft.Text("Passport", size=11)),
                ft.DataColumn(ft.Text("Mobile", size=11)),
                ft.DataColumn(ft.Text("Batch", size=11)),
                ft.DataColumn(ft.Text("Return", size=11)),
                ft.DataColumn(ft.Text("Status", size=11)),
                ft.DataColumn(ft.Text("Docs", size=11)),
                ft.DataColumn(ft.Text("Actions", size=11)),
            ],
            rows=[],
            column_spacing=12,
            heading_row_color=ft.Colors.BLUE_GREY_800,
            heading_row_height=40,
            data_row_min_height=48,
            data_row_max_height=64,
            border=ft.Border.all(1, ft.Colors.GREY_300),
            border_radius=10,
            vertical_lines=ft.BorderSide(1, ft.Colors.GREY_200),
            horizontal_lines=ft.BorderSide(1, ft.Colors.GREY_200),
        )

        # ---- PAGINATION ----
        self.pagination_label = ft.Text("Showing 0 to 0 of 0",
                                        size=11,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.BLUE_GREY_800,
                                        no_wrap=True,
                                        overflow=ft.TextOverflow.ELLIPSIS)
        self.prev_btn = ft.Button(
            content=ft.Text("◀ Prev", size=11),
            on_click=self.prev_page,
            bgcolor=ft.Colors.BLUE_600,
            color=ft.Colors.WHITE,
            disabled=True,
            height=34,
        )
        self.next_btn = ft.Button(
            content=ft.Text("Next ▶", size=11),
            on_click=self.next_page,
            bgcolor=ft.Colors.BLUE_600,
            color=ft.Colors.WHITE,
            disabled=True,
            height=34,
        )

        pagination_row = ft.Row(
            controls=[
                ft.Container(content=self.pagination_label, expand=True),
                self.prev_btn,
                self.next_btn,
            ],
            spacing=8,
        )

        self.selection_label = ft.Text("", size=10,
                                       color=ft.Colors.BLUE_700,
                                       weight=ft.FontWeight.BOLD,
                                       italic=True)

        # ---- ROOT ----
        self.root = ft.Container(
            content=ft.Column(
                controls=[
                    stats_row,
                    ft.Container(content=toolbar, padding=10,
                                 bgcolor=ft.Colors.WHITE,
                                 border_radius=10),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("💡 Tap a row to SELECT it, then use "
                                    "toolbar 📄 PDF / 🖨️ Print. "
                                    "Use ✏️ icon in Actions column to edit.",
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
                        border_radius=10,
                        padding=10,
                    ),
                    pagination_row,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=10,
            bgcolor="#f0f2f5",
            expand=True,
        )

    # =============================================================================
    # 8.3 — Helpers
    # =============================================================================
    def safe_str(self, value):
        if value is None:
            return ""
        if isinstance(value, float):
            if value != value:
                return ""
            if value.is_integer():
                return str(int(value))
        return str(value)

    def _get_photo_path(self, traveler):
        base = get_app_base_path()
        photo = traveler.get('photo', '')
        if photo:
            abs_path = os.path.join(base, photo)
            if os.path.exists(abs_path):
                return abs_path
        traveler_id = traveler.get('id')
        if traveler_id:
            folder = traveler_id.replace('/', '_').replace('\\', '_')
            docs = os.path.join(base, "documents", folder, "photos")
            if os.path.exists(docs):
                for f in os.listdir(docs):
                    if f.lower().endswith(('.jpg', '.jpeg', '.png',
                                           '.bmp', '.gif')):
                        return os.path.join(docs, f)
        return None

    # =============================================================================
    # 8.4 — refresh  (no destructive reloads)
    # =============================================================================
    def refresh(self):
        """
        Load travelers from the in-memory DB cache.

        IMPORTANT: Do NOT call db.reload_travelers() here.
        On Railway, reload_*() reads from a fixed CSV path that may differ
        from the volume mount → cache gets wiped → tab shows zeros.
        The DB layer's get_travelers() already returns live data.
        """
        try:
            self.batches = self.db.get_batches()
            self.travelers = self.db.get_travelers()

            for t in self.travelers:
                for k in _NUMERIC_STRING_FIELDS:
                    if k in t:
                        t[k] = _clean_number_string(t.get(k, ""))

            batch_map = {str(b['id']): b.get('batch_name', 'Unknown')
                         for b in self.batches}
            for t in self.travelers:
                bid = t.get('batch_id')
                t['batch_name'] = (
                    batch_map.get(str(bid), 'Not Assigned') if bid
                    else 'Not Assigned')

            self.filtered_travelers = self.travelers[:]
            self.current_page = 1
            print(f"[TRAVELERS] loaded {len(self.travelers)} travelers, "
                  f"{len(self.batches)} batches")

            self.display_travelers()
            self.update_stats()
            try:
                self.page.update()
            except Exception:
                pass
        except Exception as ex:
            print(f"Travelers refresh error: {ex}")
            import traceback
            traceback.print_exc()

    # =============================================================================
    # 8.5 — display_travelers
    # =============================================================================
    def display_travelers(self):
        start = (self.current_page - 1) * self.items_per_page
        end = min(start + self.items_per_page, len(self.filtered_travelers))
        page_items = self.filtered_travelers[start:end]

        self.table.rows.clear()
        for i, t in enumerate(page_items):
            tid = t.get('id')
            passport = _clean_number_string(t.get('passport_no', '-'))
            expiry = t.get('passport_expiry_date', '')
            try:
                if expiry:
                    dt = datetime.strptime(str(expiry)[:10], "%Y-%m-%d")
                    exp_disp = dt.strftime("%d/%m/%Y")
                else:
                    exp_disp = ""
            except Exception:
                exp_disp = str(expiry)

            return_date = t.get('expected_return_date', '')
            try:
                if return_date:
                    rd = datetime.strptime(str(return_date)[:10],
                                           "%Y-%m-%d")
                    ret_disp = rd.strftime("%d/%m/%Y")
                else:
                    ret_disp = "-"
            except Exception:
                ret_disp = str(return_date) if return_date else "-"

            status = t.get('passport_status', 'Active')
            status_color = ("#27ae60" if status == "Active"
                            else "#f39c12"
                            if status in ["Submitted", "Processing"]
                            else "#e74c3c")

            doc_keys = ['passport_scan', 'aadhaar_scan', 'pan_scan',
                        'vaccine_scan', 'photo']
            icons = ['📄', '🆔', '💳', '💉', '📸']
            doc_controls = []
            for k, ic in zip(doc_keys, icons):
                has = bool(t.get(k))
                doc_controls.append(
                    ft.Container(
                        content=ft.Text(ic, size=12,
                                        color=None if has else "#e0e0e0"),
                        width=20, height=20,
                        alignment=ft.Alignment.CENTER,
                        tooltip=(k.replace('_', ' ').title()
                                 if has else "Missing"),
                        on_click=((lambda e, tt=t, kk=k:
                                   self.open_document(tt, kk))
                                  if has else None),
                    ))

            actions = ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.VISIBILITY,
                        icon_color="#3498db", icon_size=18,
                        tooltip="View",
                        on_click=lambda e, tt=t: self.view_traveler(tt)),
                    ft.IconButton(
                        icon=ft.Icons.EDIT,
                        icon_color="#f39c12", icon_size=18,
                        tooltip="Edit",
                        on_click=lambda e, tt=t: self.open_edit_dialog(tt)),
                    ft.IconButton(
                        icon=ft.Icons.DELETE,
                        icon_color="#e74c3c", icon_size=18,
                        tooltip="Delete",
                        on_click=lambda e, tt=t: self.delete_traveler(tt)),
                ],
                spacing=0,
            )

            is_selected = (self._selected_traveler_id == tid)

            # -------- ROW TAP → SELECT (not edit) --------
            def _on_row_tap(e, tt=t, tid=tid):
                try:
                    self._select_traveler(tid)
                except Exception as ex:
                    print(f"[TRAVELERS] row tap error: {ex}")

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
                        ft.DataCell(ft.Text(str(start + i + 1), size=10)),
                        ft.DataCell(ft.Text(
                            f"{t.get('first_name', '')} "
                            f"{t.get('last_name', '')}".strip() or 'N/A',
                            size=11, weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(
                            f"{passport}\nExp: {exp_disp}", size=10)),
                        ft.DataCell(ft.Text(
                            _clean_number_string(t.get('mobile', '-')) or '-',
                            size=10)),
                        ft.DataCell(ft.Text(
                            str(t.get('batch_name', 'Not Assigned')),
                            size=10, color="#0064c8",
                            weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Text(ret_disp, size=10)),
                        ft.DataCell(ft.Text(
                            status, size=10, color=status_color,
                            weight=ft.FontWeight.BOLD)),
                        ft.DataCell(ft.Row(controls=doc_controls, spacing=1)),
                        ft.DataCell(actions),
                    ]))

        self.update_pagination()

    # =============================================================================
    # 8.5b — _select_traveler
    # =============================================================================
    def _select_traveler(self, traveler_id):
        if self._selected_traveler_id == traveler_id:
            self._selected_traveler_id = None
        else:
            self._selected_traveler_id = traveler_id

        # Update selection label
        if self.selection_label:
            if self._selected_traveler_id:
                t = next((x for x in self.travelers
                          if x.get('id') == self._selected_traveler_id), None)
                if t:
                    self.selection_label.value = (
                        f"✅ Selected: "
                        f"{t.get('first_name','')} "
                        f"{t.get('last_name','')} | "
                        f"Passport: {_clean_number_string(t.get('passport_no',''))} | "
                        f"Batch: {t.get('batch_name','')}")
                else:
                    self.selection_label.value = ""
            else:
                self.selection_label.value = ""

        self.display_travelers()
        try:
            self.page.update()
        except Exception:
            pass

    # =============================================================================
    # 8.5c — _get_selected_traveler
    # =============================================================================
    def _get_selected_traveler(self):
        if not self._selected_traveler_id:
            return None
        return next((t for t in self.travelers
                     if t.get('id') == self._selected_traveler_id), None)

    # =============================================================================
    # 8.6 — Pagination
    # =============================================================================
    def update_pagination(self):
        total = len(self.filtered_travelers)
        start = ((self.current_page - 1) * self.items_per_page + 1
                 if total else 0)
        end = min(self.current_page * self.items_per_page, total)
        self.pagination_label.value = (
            f"{start}–{end} of {total}")
        self.prev_btn.disabled = self.current_page <= 1
        self.next_btn.disabled = end >= total

    def prev_page(self, e):
        if self.current_page > 1:
            self.current_page -= 1
            self.display_travelers()
            self.page.update()

    def next_page(self, e):
        if (self.current_page * self.items_per_page
                < len(self.filtered_travelers)):
            self.current_page += 1
            self.display_travelers()
            self.page.update()

    # =============================================================================
    # 8.7 — Search
    # =============================================================================
    def search_travelers(self, e):
        text = (self.search_input.value or "").strip().lower()
        if not text:
            self.filtered_travelers = self.travelers[:]
        else:
            self.filtered_travelers = [
                t for t in self.travelers
                if (text in (f"{t.get('first_name', '')} "
                             f"{t.get('last_name', '')}").lower()
                    or text in str(t.get('passport_no', '')).lower()
                    or text in str(t.get('mobile', '')).lower()
                    or text in str(t.get('email', '')).lower()
                    or text in str(t.get('batch_name', '')).lower())
            ]
        self.current_page = 1
        self.display_travelers()
        self.page.update()

    # =============================================================================
    # 8.8 — Stats
    # =============================================================================
    def update_stats(self):
        total = len(self.travelers)
        active = len([t for t in self.travelers
                      if t.get('passport_status') == 'Active'])
        vaccinated = len([t for t in self.travelers
                          if t.get('vaccine_status') == 'Fully Vaccinated'])
        docs_complete = 0
        base = get_app_base_path()
        for t in self.travelers:
            ok = True
            for k in ['passport_scan', 'aadhaar_scan', 'pan_scan',
                      'vaccine_scan', 'photo']:
                rp = t.get(k, '')
                if rp and os.path.exists(os.path.join(base, rp)):
                    continue
                ok = False
                break
            if ok:
                docs_complete += 1

        self.stats_labels['total'].value = str(total)
        self.stats_labels['active'].value = str(active)
        self.stats_labels['vaccinated'].value = str(vaccinated)
        self.stats_labels['docs_complete'].value = str(docs_complete)

    # =============================================================================
    # 8.9 — Dialog launchers
    # =============================================================================
    def open_add_dialog(self, e):
        dlg = TravelerDialog(self.page, self.db, self.current_user,
                             traveler=None,
                             on_save_callback=self._on_saved)
        dlg.show()

    def open_edit_dialog(self, traveler):
        dlg = TravelerDialog(self.page, self.db, self.current_user,
                             traveler=traveler,
                             on_save_callback=self._on_saved)
        dlg.show()

    def _on_saved(self):
        self.refresh()

    # =============================================================================
    # 8.10 — View / Delete / Open doc
    # =============================================================================
    def view_traveler(self, traveler):
        dlg = TravelerViewDialog(self.page, traveler, self.db)
        dlg.show()

    def delete_traveler(self, traveler):
        def confirm(ev):
            try:
                self.db.delete_traveler(traveler['id'])
                self.db.log_activity(
                    self.current_user['id'], "delete_traveler",
                    f"Deleted traveler: {traveler.get('first_name','')} "
                    f"{traveler.get('last_name','')}")
                self.page.pop_dialog()

                self.refresh()
                self._snack(
                    f"✅ Deleted {traveler.get('first_name','')} "
                    f"{traveler.get('last_name','')}")
            except Exception as ex:
                self._snack(f"❌ Error: {ex}")

        confirm_dialog = ft.AlertDialog(
            title=ft.Text("Delete Traveler?"),
            content=ft.Text(
                f"Delete {traveler.get('first_name','')} "
                f"{traveler.get('last_name','')}?\n\n"
                f"Passport: {traveler.get('passport_no','N/A')}"),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda ev: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Delete"), on_click=confirm,
                          bgcolor=ft.Colors.RED_600,
                          color=ft.Colors.WHITE),
            ],
        )
        self.page.show_dialog(confirm_dialog)

    def open_document(self, traveler, key):
        rel = traveler.get(key, '')
        if not rel:
            self._snack(f"⚠️ No document for {key.replace('_', ' ')}")
            return
        base = get_app_base_path()
        abs_path = os.path.join(base, rel)
        if not os.path.exists(abs_path):
            self._snack(f"⚠️ File not found: {rel}")
            return
        try:
            url = send_file_to_user(self.page, abs_path,
                                    key.replace('_', ' ').title())
            if url:
                try:
                    self.page.launch_url(url)
                except Exception:
                    pass
                self._snack(f"📎 Opened: {os.path.basename(abs_path)}")
            else:
                self._snack(f"⚠️ Could not serve file")
        except Exception as ex:
            print(f"[TRAVELERS] open_document error: {ex}")
            self._snack(f"⚠️ Could not open: {ex}")

    # =============================================================================
    # 8.11 — Exports (toolbar actions now act on selection when applicable)
    # =============================================================================
    def export_to_excel(self, e):
        if not self.travelers:
            self._snack("⚠️ No travelers to export")
            return
        try:
            headers = [
                '#', 'ID', 'First Name', 'Last Name', 'Passport Name',
                'Gender', 'Date of Birth', 'Batch ID', 'Batch Name',
                'Passport Number', 'Passport Issue Date',
                'Passport Expiry Date', 'Passport Status', 'Mobile',
                'Email', 'Aadhaar', 'PAN', 'Aadhaar-PAN Linked',
                'Vaccine Status', 'Wheelchair', 'Place of Birth',
                'Place of Issue', 'Passport Address', 'Mailing Address',
                'Father Name', 'Mother Name', 'Spouse Name',
                'Expected Return Date', 'File Reference', 'PIN',
                'Emergency Contact', 'Emergency Phone', 'Medical Notes'
            ]
            data = []
            for i, t in enumerate(self.travelers, 1):
                data.append([
                    i, t.get('id', ''), t.get('first_name', ''),
                    t.get('last_name', ''), t.get('passport_name', ''),
                    t.get('gender', ''), t.get('dob', ''),
                    t.get('batch_id', ''), t.get('batch_name', ''),
                    _clean_number_string(t.get('passport_no', '')),
                    t.get('passport_issue_date', ''),
                    t.get('passport_expiry_date', ''),
                    t.get('passport_status', ''),
                    _clean_number_string(t.get('mobile', '')),
                    t.get('email', ''),
                    _clean_number_string(t.get('aadhaar', '')),
                    t.get('pan', ''), t.get('aadhaar_pan_linked', ''),
                    t.get('vaccine_status', ''), t.get('wheelchair', ''),
                    t.get('place_of_birth', ''),
                    t.get('place_of_issue', ''),
                    t.get('passport_address', ''),
                    t.get('mailing_address', ''),
                    t.get('father_name', ''),
                    t.get('mother_name', ''),
                    t.get('spouse_name', ''),
                    t.get('expected_return_date', ''),
                    t.get('file_reference', ''),
                    _clean_number_string(t.get('pin', '')),
                    t.get('emergency_contact', ''),
                    _clean_number_string(t.get('emergency_phone', '')),
                    t.get('medical_notes', '')
                ])
            df = pd.DataFrame(data, columns=headers)
            base = get_app_base_path()
            exports_dir = Path(base) / "exports"
            exports_dir.mkdir(exist_ok=True)
            filename = (f"travelers_export_"
                        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            file_path = exports_dir / filename
            df.to_csv(file_path, index=False, encoding='utf-8-sig')

            url = send_file_to_user(self.page, str(file_path),
                                    "Travelers CSV")
            self._snack(f"✅ Exported {len(self.travelers)} travelers")
            if url:
                try:
                    self.page.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ Export error: {ex}")

    def export_to_pdf(self, e):
        # If a row is selected, export only that traveler
        selected = self._get_selected_traveler()
        if selected:
            travelers_to_export = [selected]
            suffix = "selected_traveler"
        else:
            if not self.travelers:
                self._snack("⚠️ No travelers to export")
                return
            travelers_to_export = self.travelers
            suffix = "travelers"

        try:
            from reportlab.lib.pagesizes import landscape, A4
            from reportlab.platypus import (
                SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer)
            from reportlab.lib import colors as rl_colors
            from reportlab.lib.styles import (
                getSampleStyleSheet, ParagraphStyle)
            from reportlab.lib.enums import TA_CENTER, TA_LEFT

            base = get_app_base_path()
            exports_dir = Path(base) / "exports"
            exports_dir.mkdir(exist_ok=True)
            filename = (f"{suffix}_"
                        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            file_path = exports_dir / filename

            company_name = "Alhudha Haj Travel"
            try:
                if not self.db.company_settings.empty:
                    company_name = str(
                        self.db.company_settings.iloc[0].get(
                            'company_name', company_name))
            except Exception:
                pass

            doc = SimpleDocTemplate(
                str(file_path), pagesize=landscape(A4),
                leftMargin=20, rightMargin=20,
                topMargin=30, bottomMargin=30)
            elements = []
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'T', parent=styles['Heading1'], fontSize=16,
                alignment=TA_CENTER,
                textColor=rl_colors.HexColor("#1e40af"))
            cell_style = ParagraphStyle(
                'C', parent=styles['Normal'], fontSize=7, leading=9,
                alignment=TA_LEFT)

            fields = ['ID', 'Name', 'Passport', 'Mobile', 'Email',
                      'Batch', 'Return', 'Status', 'Vaccine']
            header = [Paragraph(f"<b>{f}</b>", cell_style) for f in fields]
            data = [header]
            for t in travelers_to_export:
                row = [
                    t.get('id', ''),
                    f"{t.get('first_name','')} "
                    f"{t.get('last_name','')}".strip(),
                    _clean_number_string(t.get('passport_no', '')),
                    _clean_number_string(t.get('mobile', '')),
                    t.get('email', ''),
                    t.get('batch_name', ''),
                    str(t.get('expected_return_date', ''))[:10],
                    t.get('passport_status', ''),
                    t.get('vaccine_status', ''),
                ]
                data.append([Paragraph(str(v or ''), cell_style)
                             for v in row])

            table = Table(data, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0),
                 rl_colors.HexColor('#1e40af')),
                ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 0.4, rl_colors.grey),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                 [rl_colors.white, rl_colors.HexColor('#f5f5f5')]),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
            ]))

            elements.append(Paragraph(company_name, title_style))
            elements.append(Paragraph(
                ("Selected Traveler" if selected else "Travelers List"),
                title_style))
            elements.append(Spacer(1, 15))
            elements.append(table)
            doc.build(elements)

            url = send_file_to_user(self.page, str(file_path),
                                    "Travelers PDF")
            self._snack(f"✅ PDF exported "
                        f"({len(travelers_to_export)} traveler"
                        f"{'s' if len(travelers_to_export) != 1 else ''})")
            if url:
                try:
                    self.page.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ PDF error: {ex}")

    def print_table(self, e):
        selected = self._get_selected_traveler()
        if selected:
            self._snack(
                f"🖨️ Selected: {selected.get('first_name','')} "
                f"{selected.get('last_name','')} — "
                f"opening PDF to print…")
            # Reuse PDF export → user prints from browser
            self.export_to_pdf(e)
        else:
            self._snack("⚠️ Tap a row to select, then tap 🖨️ Print. "
                        "Or use Ctrl+P for the full page.")

    def bulk_upload_csv(self, e):
        self._snack("ℹ️ Bulk upload — coming soon")

    def download_csv_template(self, e):
        try:
            base = get_app_base_path()
            exports_dir = Path(base) / "exports"
            exports_dir.mkdir(exist_ok=True)
            file_path = exports_dir / "travelers_template.csv"
            headers = ["First Name", "Last Name", "Passport Number",
                       "Mobile", "Email", "Gender", "Date of Birth",
                       "Batch ID", "Passport Issue Date",
                       "Passport Expiry Date", "Aadhaar", "PAN",
                       "Vaccine Status", "Place of Birth",
                       "Place of Issue", "Father Name", "Mother Name",
                       "File Reference", "PIN"]
            pd.DataFrame(columns=headers).to_csv(
                file_path, index=False, encoding='utf-8-sig')
            url = send_file_to_user(self.page, str(file_path), "Template")
            self._snack("✅ Template downloaded")
            if url:
                try:
                    self.page.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            self._snack(f"❌ {ex}")

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
# 9.1 — CLASS: TravelerDialog (Add/Edit)
# =================================================================================
class TravelerDialog:

    def __init__(self, page, db, current_user, traveler=None,
                 on_save_callback=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.traveler = traveler
        self.on_save_callback = on_save_callback
        self.is_edit = traveler is not None

        self.fields = {}
        self.doc_paths = {}
        self.doc_status_labels = {}
        self.file_picker = None
        self._current_doc_key = None
        self.dialog = None

        self.setup_ui()
        if self.is_edit:
            self.load_traveler(traveler)

    def setup_ui(self):
        self.file_picker = ft.FilePicker()

        def field(key, hint="", width=None, required=False):
            f = ft.TextField(
                label=hint + (" *" if required else ""),
                width=width,
                height=48,
                content_padding=ft.Padding.symmetric(horizontal=10,
                                                     vertical=10),
                text_size=12,
            )
            self.fields[key] = f
            return f

        def dropdown(key, options):
            d = ft.Dropdown(
                options=[ft.dropdown.Option(o) for o in options],
                height=48, text_size=12,
            )
            self.fields[key] = d
            return d

        def section_header(title):
            return ft.Container(
                content=ft.Text(title, size=12,
                                weight=ft.FontWeight.BOLD,
                                color="#1e40af"),
                padding=8,
                bgcolor="#eaf2f8",
                border_radius=6,
                border=ft.Border(left=ft.BorderSide(4, "#3498db")),
            )

        passport_name_field = field("passport_name", "Passport Name")
        passport_name_field.read_only = True

        sec1 = ft.Column(
            controls=[
                section_header("1. PERSONAL INFORMATION"),
                ft.Row([
                    field("first_name", "First Name", 180, True),
                    field("last_name", "Last Name", 180, True),
                    passport_name_field,
                ], spacing=10, wrap=True),
                ft.Row([
                    dropdown("gender",
                             ["", "Male", "Female", "Other"]),
                    field("dob", "Date of Birth (YYYY-MM-DD)", 180),
                    dropdown("passport_status",
                             ["Active", "Expired", "Submitted",
                              "Processing"]),
                ], spacing=10, wrap=True),
                ft.Row([
                    field("passport_no", "Passport Number", 180, True),
                    field("passport_issue_date",
                          "Issue Date (YYYY-MM-DD)", 180),
                    field("passport_expiry_date",
                          "Expiry Date (YYYY-MM-DD)", 180),
                ], spacing=10, wrap=True),
            ],
            spacing=10,
        )

        sec2 = ft.Column(
            controls=[
                section_header("2. CONTACT INFORMATION"),
                ft.Row([
                    field("mobile", "Mobile", 180, True),
                    field("email", "Email", 220),
                    field("aadhaar", "Aadhaar", 180),
                ], spacing=10, wrap=True),
                ft.Row([
                    field("pan", "PAN", 180),
                    dropdown("aadhaar_pan_linked",
                             ["No", "Yes", "Pending"]),
                    dropdown("vaccine_status",
                             ["Not Vaccinated", "Partially Vaccinated",
                              "Fully Vaccinated", "Booster"]),
                    dropdown("wheelchair", ["No", "Yes"]),
                ], spacing=10, wrap=True),
            ],
            spacing=10,
        )

        passport_addr = ft.TextField(
            label="Passport Address", multiline=True,
            min_lines=2, max_lines=3, text_size=12)
        self.fields['passport_address'] = passport_addr
        mailing_addr = ft.TextField(
            label="Mailing Address", multiline=True,
            min_lines=2, max_lines=3, text_size=12)
        self.fields['mailing_address'] = mailing_addr

        sec3 = ft.Column(
            controls=[
                section_header("3. ADDRESS & FAMILY"),
                ft.Row([
                    field("place_of_birth", "Place of Birth", 200),
                    field("place_of_issue", "Place of Issue", 200),
                ], spacing=10, wrap=True),
                passport_addr,
                mailing_addr,
                ft.Row([
                    field("father_name", "Father's Name", 200),
                    field("mother_name", "Mother's Name", 200),
                    field("spouse_name", "Spouse Name", 200),
                ], spacing=10, wrap=True),
            ],
            spacing=10,
        )

        batch_dropdown = ft.Dropdown(height=48, text_size=12)
        self.fields['batch_id'] = batch_dropdown
        try:
            batch_dropdown.options = [
                ft.dropdown.Option(key="", text="Select Batch")]
            for b in self.db.get_batches():
                batch_dropdown.options.append(
                    ft.dropdown.Option(
                        key=str(b['id']),
                        text=(f"{b.get('batch_name','Batch')} "
                              f"({b.get('year','')})")))
        except Exception:
            pass

        sec4 = ft.Column(
            controls=[
                section_header("4. TRAVEL & BATCH"),
                ft.Row([
                    batch_dropdown,
                    field("expected_return_date",
                          "Expected Return (YYYY-MM-DD)", 220),
                    field("file_reference", "File Reference", 180),
                ], spacing=10, wrap=True),
            ],
            spacing=10,
        )

        doc_fields = [
            ("passport_scan", "Passport Scan", "📄"),
            ("aadhaar_scan", "Aadhaar Scan", "🆔"),
            ("pan_scan", "PAN Scan", "💳"),
            ("vaccine_scan", "Vaccine Certificate", "💉"),
            ("photo", "Photo", "📸"),
        ]

        doc_rows = []
        for key, lbl, icon in doc_fields:
            status_lbl = ft.Text("No file", size=11, color="#95a5a6")
            self.doc_status_labels[key] = status_lbl

            btn = ft.Button(
                content=ft.Text("📎 Choose"),
                on_click=lambda e, k=key: self.choose_document(k),
                height=34, bgcolor="#16a085", color=ft.Colors.WHITE,
            )
            doc_rows.append(
                ft.Row([
                    ft.Text(f"{icon} {lbl}", size=11, width=160),
                    btn,
                    status_lbl,
                ], spacing=10, wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER))

        sec5 = ft.Column(
            controls=[section_header("5. DOCUMENT UPLOADS")] + doc_rows,
            spacing=10,
        )

        med = ft.TextField(label="Medical Notes", multiline=True,
                           min_lines=2, max_lines=3, text_size=12)
        self.fields['medical_notes'] = med

        pin_field = ft.TextField(
            label="PIN (4 digits) — for Traveler Portal",
            width=280, height=48, text_size=14,
            max_length=8,
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.InputFilter(allow=True,
                                        regex_string=r"[0-9]*"),
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=10),
        )
        self.fields['pin'] = pin_field

        sec6 = ft.Column(
            controls=[
                section_header("6. ADDITIONAL INFORMATION"),
                ft.Row([
                    pin_field,
                    field("emergency_contact", "Emergency Contact", 200),
                    field("emergency_phone", "Emergency Phone", 180),
                ], spacing=10, wrap=True),
                med,
            ],
            spacing=10,
        )

        self.fields['first_name'].on_change = self._update_passport_name
        self.fields['last_name'].on_change = self._update_passport_name

        content = ft.Column(
            controls=[sec1, sec2, sec3, sec4, sec5, sec6],
            spacing=15,
            scroll=ft.ScrollMode.AUTO,
        )

        title = "✏️ Edit Traveler" if self.is_edit else "➕ Add Traveler"

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD, size=15),
            content=ft.Container(
                content=content,
                width=850, height=580,
                padding=10,
            ),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content=ft.Text("💾 Save"),
                          on_click=self.save,
                          bgcolor="#27ae60", color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _update_passport_name(self, e):
        first = (self.fields['first_name'].value or "").strip()
        last = (self.fields['last_name'].value or "").strip()
        name = f"{first} {last}".strip().upper()
        self.fields['passport_name'].value = name
        self.page.update()

    def choose_document(self, key):
        self._current_doc_key = key
        try:
            self.page.run_task(self._pick_doc_async)
        except Exception as ex:
            print(f"run_task failed: {ex}")

    async def _pick_doc_async(self):
        try:
            files = await self.file_picker.pick_files(
                allow_multiple=False, with_data=True)
            if not files:
                return
            f = files[0]
            data = getattr(f, 'bytes', None)
            name = getattr(f, 'name', 'file')

            if not data:
                src_path = getattr(f, 'path', None)
                if src_path and os.path.exists(src_path):
                    with open(src_path, 'rb') as fh:
                        data = fh.read()

            if not data:
                return

            base = get_app_base_path()
            folder_name = "new_traveler"
            if self.is_edit and self.traveler:
                folder_name = (str(self.traveler['id'])
                               .replace('/', '_').replace('\\', '_'))

            subfolder_map = {
                'passport_scan': 'passports',
                'aadhaar_scan': 'aadhaar',
                'pan_scan': 'pan',
                'vaccine_scan': 'vaccine',
                'photo': 'photos',
            }
            sub = subfolder_map.get(self._current_doc_key, 'other')
            dest_dir = Path(base) / "documents" / folder_name / sub
            dest_dir.mkdir(parents=True, exist_ok=True)

            ext = Path(name).suffix or ".dat"
            fname = (f"{self._current_doc_key}_"
                     f"{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}")
            dest = dest_dir / fname
            with open(dest, "wb") as fh:
                fh.write(data)

            rel = os.path.relpath(str(dest), base)
            self.doc_paths[self._current_doc_key] = rel.replace(os.sep, "/")

            lbl = self.doc_status_labels.get(self._current_doc_key)
            if lbl:
                lbl.value = f"✅ {name}"
                lbl.color = "#27ae60"
            self.page.update()
        except Exception as ex:
            import traceback
            traceback.print_exc()

    def load_traveler(self, traveler):
        for key, field in self.fields.items():
            val = traveler.get(key, '')
            if key in _NUMERIC_STRING_FIELDS:
                val = _clean_number_string(val)
            if field.__class__.__name__ == "Dropdown":
                field.value = str(val) if val else None
            else:
                field.value = str(val) if val is not None else ''
        for key in ['passport_scan', 'aadhaar_scan', 'pan_scan',
                    'vaccine_scan', 'photo']:
            if traveler.get(key):
                self.doc_paths[key] = traveler[key]
                lbl = self.doc_status_labels.get(key)
                if lbl:
                    lbl.value = (f"✅ "
                                 f"{os.path.basename(str(traveler[key]))}")
                    lbl.color = "#27ae60"

    def save(self, e):
        try:
            data = {}
            for key, field in self.fields.items():
                val = field.value
                if field.__class__.__name__ == "Dropdown":
                    data[key] = str(val) if val else ''
                else:
                    cleaned = (val or '').strip()
                    if key in _NUMERIC_STRING_FIELDS:
                        cleaned = _clean_number_string(cleaned)
                    data[key] = cleaned

            if not data.get('first_name') or not data.get('last_name'):
                self._snack("⚠️ First and Last Name are required")
                return
            if not data.get('passport_no'):
                self._snack("⚠️ Passport Number is required")
                return
            if not data.get('mobile'):
                self._snack("⚠️ Mobile is required")
                return
            if not data.get('batch_id'):
                self._snack("⚠️ Please select a Batch")
                return

            pin = data.get('pin', '')
            if pin and not pin.isdigit():
                self._snack("⚠️ PIN must be digits only")
                return
            if pin and len(pin) > 8:
                self._snack("⚠️ PIN must be 4–8 digits")
                return

            for key, rel in self.doc_paths.items():
                data[key] = rel

            if 'status' not in data or not data.get('status'):
                data['status'] = 'Active'

            if self.is_edit:
                self.db.update_traveler(self.traveler['id'], data)
                action = "edit_traveler"
                msg = "Traveler updated"
                tid = self.traveler['id']
            else:
                tid = self.db.add_traveler(data)
                action = "add_traveler"
                msg = "Traveler added"

                base = get_app_base_path()
                src = Path(base) / "documents" / "new_traveler"
                dst = Path(base) / "documents" / (
                    str(tid).replace('/', '_').replace('\\', '_'))
                if src.exists() and not dst.exists():
                    shutil.move(str(src), str(dst))
                    for key in list(self.doc_paths.keys()):
                        old = self.doc_paths[key]
                        new = old.replace(
                            "documents/new_traveler/",
                            f"documents/{str(tid).replace('/', '_')}/")
                        self.doc_paths[key] = new
                    try:
                        self.db.update_traveler(tid, self.doc_paths)
                    except Exception:
                        pass

            try:
                self.db.log_activity(
                    self.current_user['id'], action,
                    f"{msg}: {data.get('first_name','')} "
                    f"{data.get('last_name','')}")
            except Exception:
                pass

            # NOTE: Do NOT call reload_travelers() here.
            # add_traveler() / update_traveler() already update the cache.

            self.page.pop_dialog()
            self._snack(f"✅ {msg} successfully")
            if self.on_save_callback:
                self.on_save_callback()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ Error: {ex}")

    def show(self):
        try:
            if hasattr(self.page, 'services'):
                if self.file_picker not in self.page.services:
                    self.page.services.append(self.file_picker)
        except Exception:
            pass
        self.page.show_dialog(self.dialog)

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception:
            pass


# =================================================================================
# 10.1 — CLASS: TravelerViewDialog
# =================================================================================
class TravelerViewDialog:

    def __init__(self, page, traveler, db=None):
        self.page = page
        self.traveler = traveler
        self.db = db
        self.dialog = None
        self.tabs_control = None
        self.setup_ui()

    def setup_ui(self):
        t = self.traveler
        full_name = (f"{t.get('first_name', '')} "
                     f"{t.get('last_name', '')}").strip() or "Traveler"

        def info_row(label, value):
            if value is not None:
                value = (_clean_number_string(value)
                         if isinstance(value, float)
                         or (isinstance(value, str) and value.endswith(".0"))
                         else value)
            return ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Text(label, size=11,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.BLUE_GREY_800),
                        width=140,
                    ),
                    ft.Text(str(value) if value not in (None, '') else '-',
                            size=11, selectable=True, expand=True),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )

        def section_card(title, rows):
            return ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(title, size=12,
                                weight=ft.FontWeight.BOLD,
                                color="#1e40af"),
                        ft.Divider(height=8),
                        *rows,
                    ],
                    spacing=6,
                ),
                padding=14, bgcolor=ft.Colors.WHITE,
                border_radius=8,
                border=ft.Border.all(1, ft.Colors.GREY_300),
            )

        batch_name = t.get('batch_name', '')
        if not batch_name and t.get('batch_id') and self.db:
            try:
                for b in self.db.get_batches():
                    if str(b.get('id')) == str(t.get('batch_id')):
                        batch_name = b.get('batch_name', 'Unknown')
                        break
            except Exception:
                pass
        if not batch_name:
            batch_name = 'Not Assigned'

        personal_tab = ft.Column(
            controls=[section_card("👤 Personal Information", [
                info_row("Full Name", full_name),
                info_row("Passport Name", t.get('passport_name', '')),
                info_row("Gender", t.get('gender', '')),
                info_row("Date of Birth", self._fmt_date(t.get('dob'))),
                info_row("Batch", batch_name),
                info_row("Passport No",
                         _clean_number_string(t.get('passport_no', ''))),
                info_row("Passport Issue",
                         self._fmt_date(t.get('passport_issue_date'))),
                info_row("Passport Expiry",
                         self._fmt_date(t.get('passport_expiry_date'))),
                info_row("Passport Status", t.get('passport_status', '')),
            ])],
            spacing=12, scroll=ft.ScrollMode.AUTO,
        )

        contact_tab = ft.Column(
            controls=[section_card("📞 Contact Information", [
                info_row("Mobile",
                         _clean_number_string(t.get('mobile', ''))),
                info_row("Email", t.get('email', '')),
                info_row("Aadhaar",
                         _clean_number_string(t.get('aadhaar', ''))),
                info_row("PAN", t.get('pan', '')),
                info_row("Aadhaar-PAN Linked",
                         t.get('aadhaar_pan_linked', '')),
                info_row("Vaccine Status", t.get('vaccine_status', '')),
                info_row("Wheelchair", t.get('wheelchair', '')),
            ])],
            spacing=12, scroll=ft.ScrollMode.AUTO,
        )

        address_tab = ft.Column(
            controls=[section_card("🏠 Address & Family", [
                info_row("Place of Birth", t.get('place_of_birth', '')),
                info_row("Place of Issue", t.get('place_of_issue', '')),
                info_row("Passport Address", t.get('passport_address', '')),
                info_row("Mailing Address", t.get('mailing_address', '')),
                info_row("Father's Name", t.get('father_name', '')),
                info_row("Mother's Name", t.get('mother_name', '')),
                info_row("Spouse Name", t.get('spouse_name', '')),
            ])],
            spacing=12, scroll=ft.ScrollMode.AUTO,
        )

        travel_tab = ft.Column(
            controls=[section_card("✈️ Travel Information", [
                info_row("Expected Return",
                         self._fmt_date(t.get('expected_return_date'))),
                info_row("File Reference", t.get('file_reference', '')),
                info_row("Registration Date",
                         self._fmt_date(t.get('registration_date'))),
            ])],
            spacing=12, scroll=ft.ScrollMode.AUTO,
        )

        doc_fields = [
            ("passport_scan", "📄 Passport Scan"),
            ("aadhaar_scan", "🆔 Aadhaar Scan"),
            ("pan_scan", "💳 PAN Scan"),
            ("vaccine_scan", "💉 Vaccine Certificate"),
            ("photo", "📸 Photo"),
        ]
        doc_rows = []
        for key, label in doc_fields:
            rel = t.get(key, '')
            if rel:
                base = get_app_base_path()
                abs_path = os.path.join(base, rel)
                exists = os.path.exists(abs_path)
                if exists:
                    link = ft.Container(
                        content=ft.Text(
                            f"📎 {os.path.basename(str(rel))}",
                            size=11, color="#2980b9",
                            weight=ft.FontWeight.BOLD),
                        on_click=(lambda e, p=abs_path:
                                  self._open_document(p)),
                        padding=ft.Padding.symmetric(
                            horizontal=6, vertical=3),
                    )
                    doc_rows.append(ft.Row([
                        ft.Container(
                            content=ft.Text(
                                label, size=11,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLUE_GREY_800),
                            width=160),
                        link,
                    ], spacing=8))
                else:
                    doc_rows.append(ft.Row([
                        ft.Container(
                            content=ft.Text(
                                label, size=11,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLUE_GREY_800),
                            width=160),
                        ft.Text(f"⚠️ {os.path.basename(str(rel))}",
                                size=11, color="#e74c3c"),
                    ], spacing=8))
            else:
                doc_rows.append(ft.Row([
                    ft.Container(
                        content=ft.Text(
                            label, size=11,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLUE_GREY_800),
                        width=160),
                    ft.Text("❌ Missing", size=11, color="#95a5a6"),
                ], spacing=8))

        documents_tab = ft.Column(
            controls=[section_card("📎 Documents", doc_rows)],
            spacing=12, scroll=ft.ScrollMode.AUTO,
        )

        additional_tab = ft.Column(
            controls=[section_card("🔒 Additional", [
                info_row("PIN",
                         _clean_number_string(t.get('pin', '')) or '—'),
                info_row("Emergency Contact",
                         t.get('emergency_contact', '')),
                info_row("Emergency Phone",
                         _clean_number_string(t.get('emergency_phone', ''))),
                info_row("Medical Notes", t.get('medical_notes', '')),
                info_row("Created At",
                         self._fmt_date(t.get('created_at'))),
            ])],
            spacing=12, scroll=ft.ScrollMode.AUTO,
        )

        self.tabs_control = ft.Tabs(
            selected_index=0,
            animation_duration=200,
            length=6,
            expand=True,
            content=ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    ft.TabBar(
                        tabs=[
                            ft.Tab(label="👤 Personal"),
                            ft.Tab(label="📞 Contact"),
                            ft.Tab(label="🏠 Address"),
                            ft.Tab(label="✈️ Travel"),
                            ft.Tab(label="📎 Docs"),
                            ft.Tab(label="🔒 More"),
                        ],
                        scrollable=True,
                    ),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            ft.Container(content=personal_tab, padding=10),
                            ft.Container(content=contact_tab, padding=10),
                            ft.Container(content=address_tab, padding=10),
                            ft.Container(content=travel_tab, padding=10),
                            ft.Container(content=documents_tab, padding=10),
                            ft.Container(content=additional_tab, padding=10),
                        ],
                    ),
                ]))

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"👤 {full_name}",
                          weight=ft.FontWeight.BOLD, size=15),
            content=ft.Container(
                content=self.tabs_control,
                width=800, height=580, padding=5,
            ),
            actions=[
                ft.Button(
                    content=ft.Text("Close"),
                    on_click=lambda e: self.page.pop_dialog(),
                    bgcolor=ft.Colors.BLUE_700,
                    color=ft.Colors.WHITE,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _fmt_date(self, value):
        if not value:
            return ''
        try:
            s = str(value)[:10]
            dt = datetime.strptime(s, "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return str(value)

    def _open_document(self, abs_path):
        try:
            if not os.path.exists(abs_path):
                self._snack(f"⚠️ File not found: {abs_path}")
                return
            url = send_file_to_user(self.page, abs_path, "Document")
            if url:
                self.page.launch_url(url)
                self._snack(f"📎 Opened: {os.path.basename(abs_path)}")
            else:
                self._snack("⚠️ Could not serve file")
        except Exception as ex:
            self._snack(f"⚠️ Could not open: {ex}")

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    def show(self):
        self.page.show_dialog(self.dialog)


# =================================================================================
# SECTION 8 + 9 + 10 END (FLET 1.0.0 VERSION)
# =================================================================================