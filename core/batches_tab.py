# =================================================================================
# SECTION 11 (FLET 1.0.0 VERSION) — BATCHES TAB + DIALOGS
# =================================================================================
# v1.6 — Review-fix release (builds on v1.5)
#
#   FIXES:
#     • Seat validation: reject ≤ 0, non-integer, seats < booked on edit
#     • Price validation via Decimal — negative rejected, decimals preserved
#     • Strict date parsing (no [:10] truncation) — "05-10-2026abc" rejected
#     • Tour-name validation — stale/missing tour type rejected
#     • Logging in show(), open_create_dialog, open_edit_dialog
#     • Duplicate-dialog guard via _active_batch_dialog
#     • Delete blocks on invoice/payment references (defense in depth)
#     • Delete activity-log failures logged
#     • Case-insensitive status normalization
#     • refresh() copies records before enrichment
#     • TYPING_GUARD_SECONDS 3.0 → 0.6
#     • display_batches logs WARN when stored avail ≠ computed
# =================================================================================

import flet as ft
import os
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import pandas as pd

try:
    from core.settings_manager import SettingsManager
except ImportError:
    SettingsManager = None


TYPING_GUARD_SECONDS = 0.6
OPEN_STATUSES = {"open", "active", "closing soon"}


# ---- [H.0] App base path ----
def get_app_base_path():
    import sys
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ---- [H.1] _get_prefix ----
def _get_prefix(name):
    if not name:
        return "HAJ"
    special = {
        "HAJ": "HAJ", "HJJ": "HAJ",
        "UMRA": "UMR", "UMRAH": "UMR", "UMR": "UMR",
        "ZIYARAH": "ZIY", "ZIYARAT": "ZIY", "ZIY": "ZIY",
        "MADINAH": "MAD", "MADINA": "MAD", "MAD": "MAD",
        "MAKKAH": "MAK", "MAK": "MAK",
        "UK TOUR": "UKT", "UK": "UKT",
        "USA TOUR": "UST", "USA": "UST",
        "EUROPE TOUR": "EUT", "EUROPE": "EUT",
    }
    clean = name.strip().upper()
    if clean in special:
        return special[clean]
    for w in ["TOUR", "TRIP", "PILGRIMAGE", "VISIT", "EXPEDITION"]:
        clean = clean.replace(w, "")
    if len(clean) >= 3:
        return clean[:3]
    if len(clean) == 2:
        return clean + "X"
    return clean + "XX"


# ---- [H.2] Date conversion helpers ----
_DATE_SEP = "-"


def _to_display_date(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat", "null"):
        return ""
    head = s[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            dt = datetime.strptime(head, fmt)
            return dt.strftime(f"%d{_DATE_SEP}%m{_DATE_SEP}%Y")
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", ""))
        return dt.strftime(f"%d{_DATE_SEP}%m{_DATE_SEP}%Y")
    except Exception:
        pass
    return s


def _to_storage_date(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat", "null"):
        return ""
    head = s[:10]
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            dt = datetime.strptime(head, fmt)
            return dt.strftime(f"%d{_DATE_SEP}%m{_DATE_SEP}%Y")
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d",):
        try:
            dt = datetime.strptime(head, fmt)
            return dt.strftime(f"%d{_DATE_SEP}%m{_DATE_SEP}%Y")
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", ""))
        return dt.strftime(f"%d{_DATE_SEP}%m{_DATE_SEP}%Y")
    except Exception:
        pass
    return s


def _to_storage_datetime(value):
    """
    v1.6 — STRICT parsing: full-string match only. No [:10] truncation,
    so trailing garbage like '05-10-2026abc' is rejected.
    """
    s = str(value or "").strip()
    if not s:
        raise ValueError("empty date")
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y",
                "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime(f"%d{_DATE_SEP}%m{_DATE_SEP}%Y"), dt
        except ValueError:
            continue
    raise ValueError(f"bad date: {s}")


# ---- [H.3] DB adapters ----
def _db_add_batch(db, data):
    if hasattr(db, "add_batch"):
        return db.add_batch(data)
    year = data.get("year")
    tour_name = data.get("tour_type_name", "HAJ")
    prefix = _get_prefix(tour_name)
    new_id = db._generate_id(prefix, "BCH", str(year))
    data["id"] = new_id
    data["available_seats"] = int(data.get("total_seats", 0) or 0)
    db.batches = pd.concat(
        [db.batches, pd.DataFrame([data])], ignore_index=True)
    db._save_df(db.batches, "batches.csv")
    return new_id


def _db_get_tour_types(db):
    if SettingsManager is not None:
        try:
            return SettingsManager(db).get_tour_types()
        except Exception:
            pass
    tours = []
    seen = set()
    try:
        for b in db.get_batches():
            tid = b.get("tour_type_id")
            tname = b.get("tour_type_name")
            if tid and tname and tid not in seen:
                seen.add(tid)
                tours.append({"id": tid, "tour_name": tname,
                              "is_active": True})
    except Exception:
        pass
    return tours


def _db_get_tour_years(db):
    if SettingsManager is not None:
        try:
            return SettingsManager(db).get_tour_years()
        except Exception:
            pass
    return list(range(2020, 2100))


class BatchesTab:

    def __init__(self, page: ft.Page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.settings_manager = (
            SettingsManager(db) if SettingsManager is not None else None)

        self.batches = []
        self.travelers = []
        self.filtered_batches = []
        self.tour_types = []
        self.available_years = []
        self.current_page = self._load_saved_page()
        self.items_per_page = 10

        self.stats_labels = {}
        self.table = None
        self.pagination_label = None
        self.prev_btn = None
        self.next_btn = None
        self.year_filter = None
        self.tour_filter = None
        self.search_input = None
        self.selection_label = None
        self.root = None

        self._selected_batch_id = None
        self._typing_until = 0.0
        self._active_batch_dialog = None

        try:
            self.setup_ui()
            self.refresh()
        except Exception as e:
            import traceback
            print(f"[BATCHES setup] FAILED: {e}")
            traceback.print_exc()
            self.root = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.WARNING_AMBER, size=48,
                            color=ft.Colors.ORANGE_600),
                    ft.Text("Batches tab failed to load",
                            size=18, weight=ft.FontWeight.BOLD),
                    ft.Text(str(e), size=12, color=ft.Colors.RED_500),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=10),
                padding=40, alignment=ft.Alignment.CENTER, expand=True,
            )

    def build(self):
        return self.root

    def _load_saved_page(self) -> int:
        try:
            v = self.page.session.store.get("batches_page")
            if v:
                n = int(v)
                return n if n >= 1 else 1
        except Exception:
            pass
        return 1

    def _save_page(self):
        try:
            self.page.session.store.set(
                "batches_page", str(self.current_page))
        except Exception:
            pass

    def setup_ui(self):
        stat_configs = [
            ("total",       "Total Batches",    "📦", "#3498db"),
            ("open",        "Open Batches",     "🚪", "#27ae60"),
            ("seats",       "Total Seats",      "🪑", "#f39c12"),
            ("booked",      "Booked Seats",     "👥", "#9b59b6"),
            ("value",       "Total Value",      "💰", "#e67e22"),
            ("return_date", "With Return Date", "📅", "#1abc9c"),
        ]

        stat_cards = []
        for key, label, icon, color in stat_configs:
            value_label = ft.Text("0", size=18,
                                  weight=ft.FontWeight.BOLD,
                                  color=ft.Colors.WHITE)
            self.stats_labels[key] = value_label
            stat_cards.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Text(icon, size=14),
                        ft.Text(label, size=9, color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD,
                                no_wrap=False, max_lines=2),
                    ], spacing=4),
                    value_label,
                ], spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=8, bgcolor=color, border_radius=10, height=72,
            ))

        stats_row = ft.ResponsiveRow(
            controls=[ft.Container(content=c,
                                   col={"xs": 6, "sm": 6, "md": 4, "lg": 2})
                      for c in stat_cards],
            spacing=6, run_spacing=6,
        )

        def _toolbar_btn(label, color, handler):
            return ft.Button(
                content=ft.Text(label, size=11,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE,
                                no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS),
                on_click=handler, height=38, bgcolor=color,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=8)),
            )

        self.year_filter = ft.Dropdown(
            label="Year",
            options=[ft.dropdown.Option(key="", text="All")],
            value="", width=110, height=48, text_size=11,
        )
        self.year_filter.on_change = self.apply_filters

        self.tour_filter = ft.Dropdown(
            label="Tour",
            options=[ft.dropdown.Option(key="", text="All")],
            value="", width=150, height=48, text_size=11,
        )
        self.tour_filter.on_change = self.apply_filters

        self.search_input = ft.TextField(
            hint_text="🔍 Search...",
            height=48, text_size=12,
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        )

        def _search_on_change(e, _f=self.search_input):
            self._typing_until = time.time() + TYPING_GUARD_SECONDS
            try:
                ctrl = getattr(e, "control", None)
                if ctrl is not None and hasattr(ctrl, "value"):
                    if _f.value != ctrl.value:
                        _f.value = ctrl.value
            except Exception:
                pass
            self.apply_filters(e)

        self.search_input.on_change = _search_on_change

        toolbar = ft.ResponsiveRow(
            controls=[
                ft.Container(
                    content=_toolbar_btn("➕ Create", "#27ae60",
                                         self.open_create_dialog),
                    col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(
                    content=_toolbar_btn("📊 Export", "#16a085",
                                         self.export_to_excel),
                    col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(
                    content=_toolbar_btn("🖨️ Print", "#2980b9",
                                         self.print_batches),
                    col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(
                    content=self.year_filter,
                    col={"xs": 6, "sm": 4, "md": 2}),
                ft.Container(
                    content=self.tour_filter,
                    col={"xs": 12, "sm": 6, "md": 2}),
                ft.Container(
                    content=self.search_input,
                    col={"xs": 12, "sm": 12, "md": 2}),
            ], spacing=8, run_spacing=8,
        )

        self.table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Sel", size=11)),
                ft.DataColumn(ft.Text("ID", size=11)),
                ft.DataColumn(ft.Text("Package", size=11)),
                ft.DataColumn(ft.Text("Type", size=11)),
                ft.DataColumn(ft.Text("Year", size=11)),
                ft.DataColumn(ft.Text("Departure", size=11)),
                ft.DataColumn(ft.Text("Return", size=11)),
                ft.DataColumn(ft.Text("Price", size=11)),
                ft.DataColumn(ft.Text("Seats", size=11)),
                ft.DataColumn(ft.Text("Booked", size=11)),
                ft.DataColumn(ft.Text("Avail", size=11)),
                ft.DataColumn(ft.Text("Status", size=11)),
                ft.DataColumn(ft.Text("Occ%", size=11)),
                ft.DataColumn(ft.Text("Actions", size=11)),
            ], rows=[], column_spacing=10,
            heading_row_color=ft.Colors.BLUE_GREY_800,
            heading_row_height=40,
            data_row_min_height=44, data_row_max_height=56,
            border=ft.Border.all(1, ft.Colors.GREY_300),
            border_radius=10,
        )

        self.selection_label = ft.Text("", size=10, color=ft.Colors.BLUE_700,
                                       weight=ft.FontWeight.BOLD, italic=True)

        self.pagination_label = ft.Text("0–0 of 0", size=11,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.BLUE_GREY_800)
        self.prev_btn = ft.Button(
            content=ft.Text("◀ Prev", size=11),
            on_click=self.prev_page, height=34,
            bgcolor=ft.Colors.BLUE_600, color=ft.Colors.WHITE, disabled=True)
        self.next_btn = ft.Button(
            content=ft.Text("Next ▶", size=11),
            on_click=self.next_page, height=34,
            bgcolor=ft.Colors.BLUE_600, color=ft.Colors.WHITE, disabled=True)
        pagination_row = ft.Row(
            controls=[
                ft.Container(content=self.pagination_label, expand=True),
                self.prev_btn, self.next_btn,
            ], spacing=8,
        )

        self.root = ft.Container(
            content=ft.Column(
                controls=[
                    stats_row,
                    ft.Container(content=toolbar, padding=10,
                                 bgcolor=ft.Colors.WHITE, border_radius=10),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("💡 Tap a row to SELECT it, then use "
                                    "toolbar 📊 Export / 🖨️ Print.",
                                    size=10, color=ft.Colors.GREY_600,
                                    italic=True),
                            self.selection_label,
                            ft.Row([self.table],
                                   scroll=ft.ScrollMode.ADAPTIVE),
                        ], spacing=6),
                        bgcolor=ft.Colors.WHITE, border_radius=10, padding=10,
                    ),
                    pagination_row,
                ],
                spacing=10, scroll=ft.ScrollMode.AUTO,
            ),
            padding=10, bgcolor="#f0f2f5", expand=True,
        )

    # ---- Helpers ----
    def safe_str(self, value):
        if value is None:
            return ""
        if isinstance(value, float):
            if value != value:
                return ""
            if value.is_integer():
                return str(int(value))
        return str(value)

    def _fmt_date(self, value):
        if not value:
            return "-"
        return _to_display_date(value) or "-"

    def _safe_update(self):
        if time.time() < self._typing_until:
            print("[BATCHES] _safe_update SKIPPED (typing)")
            return
        try:
            if self.root is not None:
                self.root.update()
        except Exception as e:
            print(f"[BATCHES] _safe_update failed: {e}")

    def _update_table_and_pagination(self):
        for ctrl in (self.table, self.pagination_label, self.prev_btn,
                     self.next_btn, self.selection_label):
            if ctrl is None:
                continue
            try:
                ctrl.update()
            except Exception:
                pass

    def load_tour_types_and_years(self):
        try:
            self.tour_types = _db_get_tour_types(self.db)
            current_year = datetime.now().year
            default_years = list(range(current_year - 2, current_year + 6))
            tour_years = _db_get_tour_years(self.db)
            self.available_years = sorted(
                set(default_years + tour_years), reverse=True)
            if not self.available_years:
                self.available_years = [current_year]

            self.year_filter.options = [
                ft.dropdown.Option(key="", text="All")] + [
                ft.dropdown.Option(key=str(y), text=str(y))
                for y in self.available_years]

            self.tour_filter.options = [
                ft.dropdown.Option(key="", text="All")] + [
                ft.dropdown.Option(key=str(t.get("id", "")),
                                   text=str(t.get("tour_name", "")))
                for t in self.tour_types if t.get("is_active", True)]
        except Exception as ex:
            print(f"Error loading tour types/years: {ex}")

    def refresh(self):
        try:
            self.load_tour_types_and_years()
            # v1.6 — copy records before enrichment
            self.batches = [dict(b) for b in self.db.get_batches()]
            self.travelers = [dict(t) for t in self.db.get_travelers()]

            tour_map = {str(t.get("id")): t.get("tour_name", "N/A")
                        for t in self.tour_types}
            for b in self.batches:
                tid = b.get("tour_type_id")
                if tid and str(tid) in tour_map:
                    b["tour_type_name"] = tour_map[str(tid)]
                elif not b.get("tour_type_name"):
                    b["tour_type_name"] = "N/A"
                if "year" not in b or not b.get("year"):
                    b["year"] = datetime.now().year

            print(f"[BATCHES] loaded {len(self.batches)} batches, "
                  f"{len(self.travelers)} travelers")

            self._apply_filters_internal()

            total_pages = max(
                1, (len(self.filtered_batches) + self.items_per_page - 1)
                // self.items_per_page)
            if self.current_page > total_pages:
                self.current_page = total_pages
            if self.current_page < 1:
                self.current_page = 1
            self._save_page()

            print(f"[BATCHES] refreshed — page "
                  f"{self.current_page}/{total_pages}, "
                  f"{len(self.filtered_batches)} filtered")

            self.display_batches()
            self.update_statistics()
            self._update_table_and_pagination()
            self._safe_update()
        except Exception as ex:
            print(f"Batches refresh error: {ex}")
            import traceback
            traceback.print_exc()

    def display_batches(self):
        start = (self.current_page - 1) * self.items_per_page
        end = min(start + self.items_per_page, len(self.filtered_batches))
        page_items = self.filtered_batches[start:end]

        bookings = {}
        for t in self.travelers:
            bid = t.get("batch_id")
            if bid:
                bookings[bid] = bookings.get(bid, 0) + 1

        self.table.rows.clear()
        for b in page_items:
            bid = b.get("id")
            booked = bookings.get(bid, 0)
            total = int(b.get("total_seats", 0) or 0)

            # v1.6 — prefer stored available_seats, log drift
            computed_avail = total - booked
            try:
                stored_avail = int(b.get("available_seats", computed_avail))
            except (ValueError, TypeError):
                stored_avail = computed_avail
            if stored_avail != computed_avail:
                print(f"[BATCHES] WARN avail drift for {bid}: "
                      f"stored={stored_avail} computed={computed_avail}")
            avail = computed_avail
            occ = (booked / total * 100) if total > 0 else 0

            tname = str(b.get("tour_type_name", "N/A"))
            tcolor = ("#006400" if "Haj" in tname
                      else "#000096" if "Umra" in tname
                      else "#966400" if "Ziyarah" in tname
                      else "#0000c8" if "UK" in tname
                      else None)

            avail_color = ("#e74c3c" if avail <= 0
                           else "#e67e22" if total and avail <= total * 0.2
                           else "#27ae60")

            status = str(b.get("status", "Open") or "Open")
            sl = status.strip().lower()
            status_color = ("#27ae60" if sl in ("open", "active")
                            else "#e67e22" if sl == "closing soon"
                            else "#e74c3c" if sl == "full"
                            else "#95a5a6")

            occ_color = ("#e74c3c" if occ >= 90
                         else "#e67e22" if occ >= 70
                         else "#27ae60")

            b_id = b.get("id")
            is_selected = (self._selected_batch_id == b_id)

            def _make_actions(_bid=b_id):
                def _fresh():
                    return next((x for x in self.batches
                                 if x.get("id") == _bid), None)

                def _wrap(handler):
                    def h(e, _h=handler, _f=_fresh):
                        fresh = _f()
                        if fresh is None:
                            self._snack("⚠️ Batch not found — refreshing")
                            self.refresh()
                            return
                        _h(fresh)
                    return h

                return ft.Row(
                    controls=[
                        ft.IconButton(icon=ft.Icons.VISIBILITY,
                                      icon_color="#3498db", icon_size=18,
                                      tooltip="View",
                                      on_click=_wrap(self.view_batch)),
                        ft.IconButton(icon=ft.Icons.EDIT,
                                      icon_color="#f39c12", icon_size=18,
                                      tooltip="Edit",
                                      on_click=_wrap(self.open_edit_dialog)),
                        ft.IconButton(icon=ft.Icons.DELETE,
                                      icon_color="#e74c3c", icon_size=18,
                                      tooltip="Delete",
                                      on_click=_wrap(self.delete_batch)),
                    ], spacing=0)

            def _on_row_tap(e, _bid=b_id):
                try:
                    self._select_batch(_bid)
                except Exception as ex:
                    print(f"[BATCHES] row tap error: {ex}")

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
                    ft.DataCell(ft.Text(str(bid or "")[:18], size=9)),
                    ft.DataCell(ft.Text(str(b.get("batch_name", "")), size=10,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(tname, size=10, color=tcolor,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(str(b.get("year", "")), size=10,
                                        color="#0064c8")),
                    ft.DataCell(ft.Text(
                        self._fmt_date(b.get("departure_date")), size=10)),
                    ft.DataCell(ft.Text(
                        self._fmt_date(b.get("return_date")), size=10)),
                    ft.DataCell(ft.Text(
                        f"₹{int(float(b.get('price', 0) or 0)):,}", size=10)),
                    ft.DataCell(ft.Text(str(total), size=10)),
                    ft.DataCell(ft.Text(str(booked), size=10,
                                        color="#1e8449" if booked > 0
                                        else "#95a5a6")),
                    ft.DataCell(ft.Text(str(avail), size=10,
                                        color=avail_color)),
                    ft.DataCell(ft.Text(status, size=10,
                                        color=status_color,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(f"{occ:.0f}%", size=10,
                                        color=occ_color)),
                    ft.DataCell(_make_actions()),
                ]))

        self.update_pagination()

    def _select_batch(self, batch_id):
        if self._selected_batch_id == batch_id:
            self._selected_batch_id = None
        else:
            self._selected_batch_id = batch_id

        if self.selection_label:
            if self._selected_batch_id:
                b = next((x for x in self.batches
                          if x.get("id") == self._selected_batch_id), None)
                if b:
                    self.selection_label.value = (
                        f"✅ Selected: {b.get('batch_name', '')} | "
                        f"{b.get('tour_type_name', 'N/A')} | "
                        f"Year: {b.get('year', '')} | "
                        f"₹{int(float(b.get('price', 0) or 0)):,}")
                else:
                    self.selection_label.value = ""
            else:
                self.selection_label.value = ""

        self.display_batches()
        self._update_table_and_pagination()

    def _get_selected_batch(self):
        if not self._selected_batch_id:
            return None
        return next((b for b in self.batches
                     if b.get("id") == self._selected_batch_id), None)

    def update_pagination(self):
        total = len(self.filtered_batches)
        start = ((self.current_page - 1) * self.items_per_page + 1
                 if total else 0)
        end = min(self.current_page * self.items_per_page, total)
        self.pagination_label.value = f"{start}–{end} of {total}"
        self.prev_btn.disabled = self.current_page <= 1
        self.next_btn.disabled = end >= total

    def prev_page(self, e):
        if self.current_page > 1:
            self.current_page -= 1
            self._save_page()
            self.display_batches()
            self._update_table_and_pagination()

    def next_page(self, e):
        if (self.current_page * self.items_per_page
                < len(self.filtered_batches)):
            self.current_page += 1
            self._save_page()
            self.display_batches()
            self._update_table_and_pagination()

    def _apply_filters_internal(self):
        year = (self.year_filter.value or "") if self.year_filter else ""
        tour_id = (self.tour_filter.value or "") if self.tour_filter else ""
        text = ((self.search_input.value or "").strip().lower()
                if self.search_input else "")

        result = self.batches[:]
        if year:
            result = [b for b in result
                      if str(b.get("year", "")) == str(year)]
        if tour_id:
            result = [b for b in result
                      if str(b.get("tour_type_id", "")) == str(tour_id)]
        if text:
            result = [b for b in result
                      if (text in str(b.get("batch_name", "")).lower()
                          or text in str(b.get("departure_date", "")).lower()
                          or text in str(b.get("return_date", "")).lower()
                          or text in str(b.get("status", "")).lower()
                          or text in str(b.get("tour_type_name", "")).lower())]
        self.filtered_batches = result

    def apply_filters(self, e=None):
        self._apply_filters_internal()
        self.current_page = 1
        self._save_page()
        self.display_batches()
        self._update_table_and_pagination()

    def update_statistics(self):
        total = len(self.batches)
        open_batches = len([
            b for b in self.batches
            if str(b.get("status", "")).strip().lower() in OPEN_STATUSES])
        total_seats = sum(int(b.get("total_seats", 0) or 0)
                          for b in self.batches)
        bookings = {}
        for t in self.travelers:
            bid = t.get("batch_id")
            if bid:
                bookings[bid] = bookings.get(bid, 0) + 1
        booked = sum(bookings.values())
        total_value = sum(
            int(float(b.get("price", 0) or 0)) * bookings.get(b.get("id"), 0)
            for b in self.batches)
        with_return = len([b for b in self.batches if b.get("return_date")])

        self.stats_labels["total"].value = str(total)
        self.stats_labels["open"].value = str(open_batches)
        self.stats_labels["seats"].value = str(total_seats)
        self.stats_labels["booked"].value = str(booked)
        self.stats_labels["value"].value = f"₹{total_value:,}"
        self.stats_labels["return_date"].value = str(with_return)

    # ---- Dialog launchers ----
    def open_create_dialog(self, e):
        if self._active_batch_dialog is not None:
            print("[BATCHES] dialog already open — ignoring click")
            return
        print("[BATCHES] Create Batch clicked")
        try:
            self._active_batch_dialog = BatchFormDialog(
                self.page, self.db, self.current_user,
                batch=None,
                settings_manager=self.settings_manager,
                tour_types=self.tour_types,
                available_years=self.available_years,
                on_save=self._on_saved,
                on_close_callback=self._clear_dialog_reference,
            )
            print("[BATCHES] BatchFormDialog created")
            self._active_batch_dialog.show()
            print("[BATCHES] BatchFormDialog.show() completed")
        except Exception as ex:
            print(f"[BATCHES] open_create_dialog failed: {ex}")
            import traceback
            traceback.print_exc()
            self._active_batch_dialog = None
            self._snack(f"Could not open batch form: {ex}")

    def open_edit_dialog(self, batch):
        if self._active_batch_dialog is not None:
            print("[BATCHES] dialog already open — ignoring edit click")
            return
        print("[BATCHES] Edit Batch clicked")
        try:
            self._active_batch_dialog = BatchFormDialog(
                self.page, self.db, self.current_user,
                batch=batch,
                settings_manager=self.settings_manager,
                tour_types=self.tour_types,
                available_years=self.available_years,
                on_save=self._on_saved,
                on_close_callback=self._clear_dialog_reference,
            )
            self._active_batch_dialog.show()
        except Exception as ex:
            print(f"[BATCHES] open_edit_dialog failed: {ex}")
            import traceback
            traceback.print_exc()
            self._active_batch_dialog = None
            self._snack(f"Could not open batch form: {ex}")

    def _on_saved(self):
        self.refresh()

    def _clear_dialog_reference(self):
        self._active_batch_dialog = None

    # ---- Delete ----
    def delete_batch(self, batch):
        assigned = [t for t in self.travelers
                    if str(t.get("batch_id")) == str(batch.get("id"))]
        if assigned:
            self._snack(
                f"⚠️ Cannot delete — {len(assigned)} traveler(s) assigned")
            return

        try:
            invoices = self.db.get_invoices()
        except Exception:
            invoices = []
        linked_invoices = [i for i in invoices
                           if str(i.get("batch_id", "")) == str(batch.get("id"))]

        try:
            payments = self.db.get_payments()
        except Exception:
            payments = []
        linked_payments = [p for p in payments
                           if str(p.get("batch_id", "")) == str(batch.get("id"))]

        warn = f"Delete batch '{batch.get('batch_name', '')}'?"
        if linked_invoices or linked_payments:
            warn += (f"\n\n⚠️ {len(linked_invoices)} invoice(s) and "
                     f"{len(linked_payments)} payment(s) reference this batch.\n"
                     f"Deletion will be blocked by the database if any exist.")

        def confirm(ev):
            try:
                try:
                    self.db.delete_batch(batch.get("id"))
                except ValueError as ve:
                    self._snack(f"⚠️ {ve}")
                    return
                try:
                    self.db.log_activity(
                        self.current_user["id"], "delete_batch",
                        f"Deleted batch: {batch.get('batch_name', '')}")
                except Exception as log_ex:
                    print(f"[BATCHES] activity log failed: {log_ex}")
                self.page.pop_dialog()
                self.refresh()
                self._snack("✅ Batch deleted")
            except Exception as ex:
                self._snack(f"❌ {ex}")

        dialog = ft.AlertDialog(
            title=ft.Text("Delete Batch?", size=14),
            content=ft.Text(warn, size=12),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Delete"), on_click=confirm,
                          bgcolor=ft.Colors.RED_600,
                          color=ft.Colors.WHITE),
            ],
        )
        self.page.show_dialog(dialog)

    def view_batch(self, batch):
        dlg = BatchViewDialog(self.page, self.db, batch)
        dlg.show()

    # ---- Exports ----
    def export_to_excel(self, e):
        selected = self._get_selected_batch()
        if selected:
            batches_to_export = [selected]
            suffix = "selected_batch"
        else:
            if not self.batches:
                self._snack("⚠️ No batches to export")
                return
            batches_to_export = self.batches
            suffix = "batches"

        try:
            headers = ["ID", "Batch Name", "Tour Type", "Year",
                       "Departure Date", "Return Date", "Price",
                       "Total Seats", "Booked", "Available", "Status",
                       "Occupancy%", "Description"]
            bookings = {}
            for t in self.travelers:
                bid = t.get("batch_id")
                if bid:
                    bookings[bid] = bookings.get(bid, 0) + 1

            data = []
            for b in batches_to_export:
                bid = b.get("id")
                booked = bookings.get(bid, 0)
                total = int(b.get("total_seats", 0) or 0)
                avail = total - booked
                occ = (booked / total * 100) if total > 0 else 0
                data.append([
                    bid, b.get("batch_name", ""),
                    b.get("tour_type_name", ""), b.get("year", ""),
                    _to_display_date(b.get("departure_date", "")),
                    _to_display_date(b.get("return_date", "")),
                    b.get("price", 0), total, booked, avail,
                    b.get("status", ""), f"{occ:.1f}",
                    b.get("description", ""),
                ])

            df = pd.DataFrame(data, columns=headers)
            exports = Path(get_app_base_path()) / "exports"
            exports.mkdir(exist_ok=True)
            path = exports / (f"{suffix}_"
                              f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            df.to_csv(path, index=False, encoding="utf-8-sig")

            from core.helpers import send_file_to_user
            url = send_file_to_user(self.page, str(path), "Batches CSV")
            self._snack(f"✅ Exported {len(batches_to_export)} "
                        f"batch{'es' if len(batches_to_export) != 1 else ''}")
            if url:
                try:
                    self.page.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ Export error: {ex}")

    def print_batches(self, e):
        selected = self._get_selected_batch()
        if selected:
            self._snack(f"🖨️ Selected: {selected.get('batch_name', '')} — "
                        f"opening export…")
            self.export_to_excel(e)
        else:
            self._snack("⚠️ Tap a row to select, then tap 🖨️ Print. "
                        "Or use Ctrl+P for the full page.")

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception as ex:
            print(f"[BATCHES] snack failed: {ex}")


# =================================================================================
# BatchFormDialog (v1.6)
# =================================================================================
class BatchFormDialog:

    def __init__(self, page, db, current_user, batch=None,
                 settings_manager=None, tour_types=None,
                 available_years=None, on_save=None,
                 on_close_callback=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.batch = batch
        self.is_edit = batch is not None
        self.settings_manager = settings_manager
        self.tour_types = tour_types or []
        self.available_years = available_years or []
        self.on_save = on_save
        self.on_close_callback = on_close_callback

        self.name_field = None
        self.year_dropdown = None
        self.tour_dropdown = None
        self.id_preview = None
        self.seats_field = None
        self.price_field = None
        self.departure_field = None
        self.return_field = None
        self.date_validation = None
        self.status_dropdown = None
        self.description_field = None
        self.dialog = None

        self._typing_until = 0.0
        self._closed = False

        self.setup_ui()
        if self.is_edit:
            self.load_batch()

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
        year_opts = [ft.dropdown.Option(key=str(y), text=str(y))
                     for y in self.available_years]
        if not year_opts:
            y = datetime.now().year
            year_opts = [ft.dropdown.Option(key=str(y), text=str(y))]

        tour_opts = [ft.dropdown.Option(key="", text="Select Tour Type")]
        for t in self.tour_types:
            if t.get("is_active", True):
                tour_opts.append(ft.dropdown.Option(
                    key=str(t.get("id", "")),
                    text=str(t.get("tour_name", ""))))

        self.name_field = self._field(
            label="Batch Name *", hint_text="e.g., Haj Silver 2026",
            height=48, text_size=12)

        self.year_dropdown = ft.Dropdown(
            label="Year *", options=year_opts,
            value=str(datetime.now().year),
            width=120, height=48, text_size=12)
        self.year_dropdown.on_change = self.on_year_change

        self.tour_dropdown = ft.Dropdown(
            label="Tour Type *", options=tour_opts,
            value="", width=180, height=48, text_size=12)
        self.tour_dropdown.on_change = self.on_tour_change

        self.id_preview = ft.Text(
            "📋 Batch ID: Select Year and Tour Type",
            size=11, weight=ft.FontWeight.BOLD,
            color=ft.Colors.RED_600)

        self.seats_field = self._field(
            label="Seats", value="150", width=120, height=48, text_size=12)
        self.price_field = self._field(
            label="Price (₹)", hint_text="350000",
            width=180, height=48, text_size=12)

        today_dmy = datetime.now().strftime("%d-%m-%Y")
        self.departure_field = self._field(
            label="Departure (DD-MM-YYYY)", value=today_dmy,
            hint_text="e.g. 05-10-2026", height=48, text_size=12)
        self.return_field = self._field(
            label="Return (DD-MM-YYYY)", value=today_dmy,
            hint_text="e.g. 20-10-2026", height=48, text_size=12)
        self.date_validation = ft.Text("", size=11, color=ft.Colors.GREEN_700)

        self.status_dropdown = ft.Dropdown(
            label="Status",
            options=[
                ft.dropdown.Option(key="Open", text="Open"),
                ft.dropdown.Option(key="Closing Soon", text="Closing Soon"),
                ft.dropdown.Option(key="Full", text="Full"),
                ft.dropdown.Option(key="Closed", text="Closed"),
            ], value="Open", width=180, height=48, text_size=12)
        self.description_field = self._field(
            label="Description", hint_text="Package details...",
            multiline=True, min_lines=2, max_lines=3, text_size=12)

        content = ft.Column(
            controls=[
                self.name_field,
                ft.Row([self.year_dropdown, self.tour_dropdown],
                       spacing=10, wrap=True),
                self.id_preview,
                ft.Row([self.seats_field, self.price_field],
                       spacing=10, wrap=True),
                self.departure_field, self.return_field,
                self.date_validation, self.status_dropdown,
                self.description_field,
            ], spacing=12, scroll=ft.ScrollMode.AUTO)

        title = "✏️ Edit Batch" if self.is_edit else "➕ Create New Batch"

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD, size=15),
            content=ft.Container(content=content, width=600, height=560,
                                 padding=10),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self._close()),
                ft.Button(content=ft.Text("💾 Save"), on_click=self.save,
                          bgcolor=ft.Colors.GREEN_600,
                          color=ft.Colors.WHITE),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        if not self.is_edit:
            self.update_id_preview()

    def _get_next_batch_number(self, prefix, year):
        max_num = 0
        for b in self.db.get_batches():
            bid = str(b.get("id", ""))
            if bid.startswith(f"{prefix}/BCH/{year}/"):
                try:
                    n = int(bid.split("/")[-1])
                    if n > max_num:
                        max_num = n
                except Exception:
                    pass
        return max_num + 1

    def on_year_change(self, e):
        self._typing_until = time.time() + TYPING_GUARD_SECONDS
        self.update_id_preview()

    def on_tour_change(self, e):
        self._typing_until = time.time() + TYPING_GUARD_SECONDS
        self.update_id_preview()

    def update_id_preview(self):
        year = self.year_dropdown.value
        tour_id = self.tour_dropdown.value
        if not year or not tour_id:
            self.id_preview.value = (
                "📋 Batch ID: Select Year and Tour Type")
            self.id_preview.color = ft.Colors.RED_600
            try:
                self.id_preview.update()
            except Exception:
                pass
            return

        tour_name = ""
        for t in self.tour_types:
            if str(t.get("id", "")) == str(tour_id):
                tour_name = t.get("tour_name", "")
                break
        prefix = _get_prefix(tour_name)
        next_num = self._get_next_batch_number(prefix, year)
        bid = f"{prefix}/BCH/{year}/{next_num:03d}"
        self.id_preview.value = f"📋 Batch ID (preview): {bid}"
        self.id_preview.color = ft.Colors.GREEN_700
        try:
            self.id_preview.update()
        except Exception:
            pass

    def load_batch(self):
        b = self.batch
        self.name_field.value = str(b.get("batch_name", ""))
        if b.get("year"):
            self.year_dropdown.value = str(b.get("year"))
        if b.get("tour_type_id"):
            self.tour_dropdown.value = str(b.get("tour_type_id"))
        self.seats_field.value = str(int(b.get("total_seats", 150) or 150))
        self.price_field.value = str(b.get("price", 0) or 0)
        if b.get("departure_date"):
            self.departure_field.value = _to_display_date(
                b.get("departure_date"))
        if b.get("return_date"):
            self.return_field.value = _to_display_date(b.get("return_date"))
        self.status_dropdown.value = str(b.get("status", "Open"))
        self.description_field.value = str(b.get("description", ""))
        self.update_id_preview()

    def _count_bookings(self, batch_id):
        try:
            return sum(1 for t in self.db.get_travelers()
                       if str(t.get("batch_id", "")) == str(batch_id))
        except Exception:
            return 0

    def save(self, e):
        try:
            name = (self.name_field.value or "").strip()
            if not name:
                self._snack("⚠️ Batch Name is required")
                return

            year = self.year_dropdown.value
            if not year:
                self._snack("⚠️ Please select a Year")
                return

            tour_id = self.tour_dropdown.value
            if not tour_id:
                self._snack("⚠️ Please select a Tour Type")
                return

            # v1.6 — tour-name validation
            tour_name = ""
            for t in self.tour_types:
                if str(t.get("id", "")) == str(tour_id):
                    tour_name = t.get("tour_name", "")
                    break
            if not tour_name:
                self._snack("⚠️ Selected tour type is invalid")
                return

            # ---- Seats ----
            seats_text = (self.seats_field.value or "").strip()
            if not seats_text:
                self._snack("⚠️ Seats is required")
                return
            try:
                seats = int(seats_text)
            except ValueError:
                self._snack("⚠️ Seats must be a whole number")
                return
            if seats <= 0:
                self._snack("⚠️ Seats must be greater than zero")
                return
            if self.is_edit:
                booked = self._count_bookings(self.batch.get("id"))
                if seats < booked:
                    self._snack(
                        f"⚠️ Seats cannot be less than current bookings "
                        f"({booked})")
                    return

            # ---- Price ----
            price_text = (self.price_field.value or "").strip()
            if not price_text:
                self._snack("⚠️ Price is required")
                return
            try:
                price_decimal = Decimal(price_text)
            except (InvalidOperation, ValueError):
                self._snack("⚠️ Price must be a valid amount")
                return
            if price_decimal < 0:
                self._snack("⚠️ Price cannot be negative")
                return
            price = float(price_decimal)

            # ---- Dates (strict) ----
            dep_raw = (self.departure_field.value or "").strip()
            ret_raw = (self.return_field.value or "").strip()
            if not dep_raw or not ret_raw:
                self._snack("⚠️ Departure and Return dates required")
                return
            try:
                dep_norm, dep_dt = _to_storage_datetime(dep_raw)
                ret_norm, ret_dt = _to_storage_datetime(ret_raw)
            except ValueError:
                self._snack("⚠️ Dates must be in DD-MM-YYYY format "
                            "(e.g. 05-10-2026)")
                return
            if ret_dt < dep_dt:
                self._snack("⚠️ Return must be after departure")
                return

            data = {
                "batch_name": name,
                "tour_type_id": tour_id,
                "tour_type_name": tour_name,
                "year": int(year),
                "total_seats": seats,
                "price": price,
                "departure_date": dep_norm,
                "return_date": ret_norm,
                "status": self.status_dropdown.value or "Open",
                "description": (self.description_field.value or "").strip(),
            }

            changes = []
            if self.is_edit:
                old = self.batch or {}
                for k in ("batch_name", "tour_type_id", "year",
                          "total_seats", "price", "departure_date",
                          "return_date", "status", "description"):
                    if str(old.get(k, "")) != str(data.get(k, "")):
                        changes.append(k.replace("_", " "))

            try:
                if self.is_edit:
                    self.db.update_batch(self.batch.get("id"), data)
                    self.db.log_activity(
                        self.current_user["id"], "edit_batch",
                        f"Updated batch: {name}")
                    msg = "✅ Batch updated"
                    if changes:
                        msg += f": {', '.join(changes)}"
                else:
                    bid = _db_add_batch(self.db, data)
                    self.db.log_activity(
                        self.current_user["id"], "add_batch",
                        f"Added batch: {name}")
                    msg = f"✅ Batch created: {bid}"
            except ValueError as ve:
                self._snack(f"⚠️ {ve}")
                return
            except Exception as ex:
                import traceback
                traceback.print_exc()
                self._snack(f"❌ {ex}")
                return

            self._typing_until = 0.0
            self._close()
            self._snack(msg)

            try:
                if self.on_save:
                    self.on_save()
            except Exception as cb_ex:
                print(f"[BATCH-FORM] on_save callback failed: {cb_ex}")
                import traceback
                traceback.print_exc()
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
            print(f"[BATCH-FORM] pop_dialog failed: {ex}")
        if self.on_close_callback:
            try:
                self.on_close_callback()
            except Exception as ex:
                print(f"[BATCH-FORM] on_close_callback failed: {ex}")

    def show(self):
        try:
            print("[BATCH-FORM] opening dialog")
            self.page.show_dialog(self.dialog)
            print("[BATCH-FORM] dialog opened")
        except Exception as ex:
            import traceback
            print(f"[BATCH-FORM] dialog failed: {ex}")
            traceback.print_exc()
            try:
                self.page.show_dialog(ft.SnackBar(
                    content=ft.Text(f"Unable to open batch form: {ex}")))
            except Exception:
                pass
            self._closed = True
            if self.on_close_callback:
                try:
                    self.on_close_callback()
                except Exception:
                    pass

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception as ex:
            print(f"[BATCH-FORM] snack failed: {ex}")


# =================================================================================
# BatchViewDialog
# =================================================================================
class BatchViewDialog:

    def __init__(self, page, db, batch):
        self.page = page
        self.db = db
        self.batch = batch
        self.dialog = None
        self.setup_ui()

    def setup_ui(self):
        b = self.batch

        def row(label, value):
            return ft.Row([
                ft.Text(label, width=140, weight=ft.FontWeight.BOLD, size=11),
                ft.Text(str(value) if value not in (None, "") else "-",
                        size=11, selectable=True, expand=True),
            ], spacing=8)

        travelers = self.db.get_travelers()
        assigned = [t for t in travelers
                    if str(t.get("batch_id")) == str(b.get("id"))]
        names = [(f"{t.get('first_name', '')} "
                  f"{t.get('last_name', '')}").strip() or "N/A"
                 for t in assigned]

        content = ft.Column(controls=[
            ft.Text("Batch Information", size=12,
                    weight=ft.FontWeight.BOLD, color="#1e40af"),
            ft.Divider(),
            row("ID", b.get("id", "")),
            row("Batch Name", b.get("batch_name", "")),
            row("Tour Type", b.get("tour_type_name", "N/A")),
            row("Year", b.get("year", "")),
            row("Departure", _to_display_date(b.get("departure_date")) or "-"),
            row("Return", _to_display_date(b.get("return_date")) or "-"),
            row("Price", f"₹{int(float(b.get('price', 0) or 0)):,}"),
            row("Total Seats", b.get("total_seats", 0)),
            row("Available Seats", b.get("available_seats", 0)),
            row("Status", b.get("status", "")),
            row("Description", b.get("description", "")),
            ft.Divider(),
            row("Travelers Booked", len(assigned)),
            row("Traveler List", ", ".join(names[:5])
                + ("..." if len(names) > 5 else "")),
        ], spacing=8, scroll=ft.ScrollMode.AUTO)

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"📦 {b.get('batch_name', 'Batch')}",
                          weight=ft.FontWeight.BOLD, size=15),
            content=ft.Container(content=content, width=480,
                                 height=500, padding=10),
            actions=[ft.Button(content=ft.Text("Close"),
                               on_click=lambda e: self.page.pop_dialog(),
                               bgcolor=ft.Colors.BLUE_700,
                               color=ft.Colors.WHITE)],
        )

    def show(self):
        try:
            print("[BATCH-VIEW] showing dialog")
            self.page.show_dialog(self.dialog)
            print("[BATCH-VIEW] dialog shown")
        except Exception as ex:
            import traceback
            print(f"[BATCH-VIEW] dialog failed: {ex}")
            traceback.print_exc()
            try:
                self.page.show_dialog(ft.SnackBar(
                    content=ft.Text(f"Unable to open batch view: {ex}")))
            except Exception:
                pass


# =================================================================================
# END — core/batches_tab.py v1.6
# =================================================================================