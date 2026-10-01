# =================================================================================
# SECTION 11 (FLET 1.0.0 VERSION) — BATCHES TAB + DIALOGS (Mobile-Responsive)
# =================================================================================
# v1.2 — Mobile-friendly layout:
#   • Stat cards 2-per-row on mobile
#   • Toolbar buttons responsive
#   • Table wrapped in horizontal scroll
#   • Dialogs fit mobile screens
# =================================================================================

import flet as ft
import os
from datetime import datetime
from pathlib import Path
import pandas as pd

try:
    from core.settings_manager import SettingsManager
except ImportError:
    SettingsManager = None


def get_app_base_path():
    import sys
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


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


def _db_add_batch(db, data):
    if hasattr(db, "add_batch"):
        return db.add_batch(data)
    year = data.get("year")
    tour_name = data.get("tour_type_name", "HAJ")
    prefix = _get_prefix(tour_name)
    new_id = db._generate_id(prefix, "BCH", str(year))
    data["id"] = new_id
    data["available_seats"] = int(data.get("total_seats", 0) or 0)
    new_row = pd.DataFrame([data])
    db.batches = pd.concat([db.batches, new_row], ignore_index=True)
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
                tours.append({"id": tid, "tour_name": tname, "is_active": True})
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
            SettingsManager(db) if SettingsManager is not None else None
        )

        self.batches = []
        self.travelers = []
        self.filtered_batches = []
        self.tour_types = []
        self.available_years = []
        self.current_page = 1
        self.items_per_page = 10

        self.stats_labels = {}
        self.table = None
        self.pagination_label = None
        self.prev_btn = None
        self.next_btn = None
        self.year_filter = None
        self.tour_filter = None
        self.search_input = None
        self.root = None

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
            card = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Text(icon, size=14),
                                ft.Text(label, size=9,
                                        color=ft.Colors.WHITE,
                                        weight=ft.FontWeight.BOLD,
                                        no_wrap=False,
                                        max_lines=2),
                            ],
                            spacing=4,
                        ),
                        value_label,
                    ],
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=8,
                bgcolor=color,
                border_radius=10,
                height=72,
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
        self.search_input.on_change = self.apply_filters

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
            ],
            spacing=8, run_spacing=8,
        )

        self.table = ft.DataTable(
            columns=[
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
            ],
            rows=[],
            column_spacing=10,
            heading_row_color=ft.Colors.BLUE_GREY_800,
            heading_row_height=40,
            data_row_min_height=44,
            data_row_max_height=56,
            border=ft.Border.all(1, ft.Colors.GREY_300),
            border_radius=10,
        )

        self.pagination_label = ft.Text("0–0 of 0", size=11,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.BLUE_GREY_800)
        self.prev_btn = ft.Button(
            content=ft.Text("◀ Prev", size=11),
            on_click=self.prev_page, height=34,
            bgcolor=ft.Colors.BLUE_600, color=ft.Colors.WHITE,
            disabled=True,
        )
        self.next_btn = ft.Button(
            content=ft.Text("Next ▶", size=11),
            on_click=self.next_page, height=34,
            bgcolor=ft.Colors.BLUE_600, color=ft.Colors.WHITE,
            disabled=True,
        )
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
                                 bgcolor=ft.Colors.WHITE,
                                 border_radius=10),
                    ft.Container(
                        content=ft.Row([self.table],
                                       scroll=ft.ScrollMode.ADAPTIVE),
                        bgcolor=ft.Colors.WHITE,
                        border_radius=10,
                        padding=10,
                    ),
                    pagination_row,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=10, bgcolor="#f0f2f5", expand=True,
        )

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
        try:
            s = str(value)[:10]
            dt = datetime.strptime(s, "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return str(value)

    def load_tour_types_and_years(self):
        try:
            self.tour_types = _db_get_tour_types(self.db)
            current_year = datetime.now().year
            default_years = list(range(current_year - 2, current_year + 6))
            tour_years = _db_get_tour_years(self.db)
            all_years = list(set(default_years + tour_years))
            self.available_years = sorted(all_years, reverse=True)
            if not self.available_years:
                self.available_years = [current_year]

            year_opts = [ft.dropdown.Option(key="", text="All")]
            for y in self.available_years:
                year_opts.append(ft.dropdown.Option(key=str(y), text=str(y)))
            self.year_filter.options = year_opts

            tour_opts = [ft.dropdown.Option(key="", text="All")]
            for t in self.tour_types:
                if t.get("is_active", True):
                    tour_opts.append(ft.dropdown.Option(
                        key=str(t.get("id", "")),
                        text=str(t.get("tour_name", "")),
                    ))
            self.tour_filter.options = tour_opts
            try:
                self.page.update()
            except Exception:
                pass
        except Exception as ex:
            print(f"Error loading tour types/years: {ex}")

    def refresh(self):
        try:
            try:
                if hasattr(self.db, "reload"):
                    self.db.reload()
                elif hasattr(self.db, "_load_all"):
                    self.db._load_all()
            except Exception as _re:
                print(f"[BatchesTab.refresh] reload skipped: {_re}")

            self.load_tour_types_and_years()
            self.batches = self.db.get_batches()
            self.travelers = self.db.get_travelers()

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

            self.filtered_batches = self.batches[:]
            self.current_page = 1
            self.display_batches()
            self.update_statistics()
            try:
                self.page.update()
            except Exception:
                pass
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
            avail = total - booked
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
            status_lower = status.strip().lower()
            status_color = ("#27ae60" if status_lower == "open"
                            else "#e67e22" if status_lower == "closing soon"
                            else "#e74c3c" if status_lower == "full"
                            else "#95a5a6")

            occ_color = ("#e74c3c" if occ >= 90
                         else "#e67e22" if occ >= 70
                         else "#27ae60")

            b_id = b.get("id")

            def _make_actions(_bid=b_id):
                def _fresh():
                    return next(
                        (x for x in self.batches
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
                                      icon_color="#3498db", icon_size=16,
                                      tooltip="View",
                                      on_click=_wrap(self.view_batch)),
                        ft.IconButton(icon=ft.Icons.EDIT,
                                      icon_color="#f39c12", icon_size=16,
                                      tooltip="Edit",
                                      on_click=_wrap(self.open_edit_dialog)),
                        ft.IconButton(icon=ft.Icons.DELETE,
                                      icon_color="#e74c3c", icon_size=16,
                                      tooltip="Delete",
                                      on_click=_wrap(self.delete_batch)),
                    ], spacing=0)

            self.table.rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(str(bid or "")[:18], size=9)),
                    ft.DataCell(ft.Text(str(b.get("batch_name", "")),
                                        size=10,
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
                        f"₹{int(b.get('price', 0) or 0):,}", size=10)),
                    ft.DataCell(ft.Text(str(total), size=10)),
                    ft.DataCell(ft.Text(str(booked), size=10,
                                        color="#1e8449" if booked > 0 else "#95a5a6")),
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
            self.display_batches()
            try:
                self.page.update()
            except Exception:
                pass

    def next_page(self, e):
        if (self.current_page * self.items_per_page
                < len(self.filtered_batches)):
            self.current_page += 1
            self.display_batches()
            try:
                self.page.update()
            except Exception:
                pass

    def apply_filters(self, e=None):
        year = self.year_filter.value or ""
        tour_id = self.tour_filter.value or ""
        text = (self.search_input.value or "").strip().lower()

        result = self.batches[:]

        if year:
            result = [b for b in result
                      if str(b.get("year", "")) == str(year)]

        if tour_id:
            result = [b for b in result
                      if str(b.get("tour_type_id", "")) == str(tour_id)]

        if text:
            result = [
                b for b in result
                if (text in str(b.get("batch_name", "")).lower()
                    or text in str(b.get("departure_date", "")).lower()
                    or text in str(b.get("return_date", "")).lower()
                    or text in str(b.get("status", "")).lower()
                    or text in str(b.get("tour_type_name", "")).lower())
            ]

        self.filtered_batches = result
        self.current_page = 1
        self.display_batches()
        try:
            self.page.update()
        except Exception:
            pass

    def update_statistics(self):
        total = len(self.batches)

        open_batches = len([
            b for b in self.batches
            if str(b.get("status", "")).strip().lower()
               in ("open", "closing soon")
        ])

        total_seats = sum(int(b.get("total_seats", 0) or 0)
                          for b in self.batches)

        bookings = {}
        for t in self.travelers:
            bid = t.get("batch_id")
            if bid:
                bookings[bid] = bookings.get(bid, 0) + 1
        booked = sum(bookings.values())

        total_value = sum(
            int(b.get("price", 0) or 0) * bookings.get(b.get("id"), 0)
            for b in self.batches)

        with_return = len([b for b in self.batches
                           if b.get("return_date")])

        self.stats_labels["total"].value = str(total)
        self.stats_labels["open"].value = str(open_batches)
        self.stats_labels["seats"].value = str(total_seats)
        self.stats_labels["booked"].value = str(booked)
        self.stats_labels["value"].value = f"₹{total_value:,}"
        self.stats_labels["return_date"].value = str(with_return)

    def open_create_dialog(self, e):
        dlg = BatchFormDialog(
            self.page, self.db, self.current_user,
            batch=None,
            settings_manager=self.settings_manager,
            tour_types=self.tour_types,
            available_years=self.available_years,
            on_save=self._on_saved,
        )
        dlg.show()

    def open_edit_dialog(self, batch):
        dlg = BatchFormDialog(
            self.page, self.db, self.current_user,
            batch=batch,
            settings_manager=self.settings_manager,
            tour_types=self.tour_types,
            available_years=self.available_years,
            on_save=self._on_saved,
        )
        dlg.show()

    def _on_saved(self):
        self.refresh()

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
        linked_invoices = [
            i for i in invoices
            if str(i.get("batch_id", "")) == str(batch.get("id"))
        ]

        warn = f"Delete batch '{batch.get('batch_name', '')}'?"
        if linked_invoices:
            warn += (f"\n\n⚠️ {len(linked_invoices)} invoice(s) reference "
                     f"this batch.")

        def confirm(ev):
            try:
                if hasattr(self.db, "delete_batch"):
                    self.db.delete_batch(batch.get("id"))
                else:
                    self.db.batches = self.db.batches[
                        self.db.batches["id"] != batch.get("id")]
                    self.db._save_df(self.db.batches, "batches.csv")
                try:
                    self.db.log_activity(
                        self.current_user["id"], "delete_batch",
                        f"Deleted batch: {batch.get('batch_name', '')}")
                except Exception:
                    pass
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

    def export_to_excel(self, e):
        if not self.batches:
            self._snack("⚠️ No batches to export")
            return
        try:
            headers = ["ID", "Batch Name", "Tour Type", "Year",
                       "Departure Date", "Return Date", "Price",
                       "Total Seats", "Booked", "Available",
                       "Status", "Occupancy%", "Description"]
            bookings = {}
            for t in self.travelers:
                bid = t.get("batch_id")
                if bid:
                    bookings[bid] = bookings.get(bid, 0) + 1

            data = []
            for b in self.batches:
                bid = b.get("id")
                booked = bookings.get(bid, 0)
                total = int(b.get("total_seats", 0) or 0)
                avail = total - booked
                occ = (booked / total * 100) if total > 0 else 0
                data.append([
                    bid, b.get("batch_name", ""),
                    b.get("tour_type_name", ""), b.get("year", ""),
                    b.get("departure_date", ""), b.get("return_date", ""),
                    b.get("price", 0), total, booked, avail,
                    b.get("status", ""), f"{occ:.1f}",
                    b.get("description", ""),
                ])

            df = pd.DataFrame(data, columns=headers)
            base = get_app_base_path()
            exports = Path(base) / "exports"
            exports.mkdir(exist_ok=True)
            fname = (f"batches_export_"
                     f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            path = exports / fname
            df.to_csv(path, index=False, encoding="utf-8-sig")

            from core.helpers import send_file_to_user
            url = send_file_to_user(self.page, str(path),
                                    "Batches CSV")
            self._snack(f"✅ Exported {len(self.batches)} batches")
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
        self._snack("ℹ️ Use your browser's Ctrl+P to print this page")

    def _snack(self, msg):
        try:
            self.page.show_dialog(ft.SnackBar(content=ft.Text(msg)))
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass


class BatchFormDialog:

    def __init__(self, page, db, current_user, batch=None,
                 settings_manager=None, tour_types=None,
                 available_years=None, on_save=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.batch = batch
        self.is_edit = batch is not None
        self.settings_manager = settings_manager
        self.tour_types = tour_types or []
        self.available_years = available_years or []
        self.on_save = on_save

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

        self.setup_ui()
        if self.is_edit:
            self.load_batch()

    def setup_ui(self):
        year_opts = []
        for y in self.available_years:
            year_opts.append(ft.dropdown.Option(key=str(y), text=str(y)))
        if not year_opts:
            y = datetime.now().year
            year_opts = [ft.dropdown.Option(key=str(y), text=str(y))]

        tour_opts = [ft.dropdown.Option(key="", text="Select Tour Type")]
        for t in self.tour_types:
            if t.get("is_active", True):
                tour_opts.append(ft.dropdown.Option(
                    key=str(t.get("id", "")),
                    text=str(t.get("tour_name", "")),
                ))

        self.name_field = ft.TextField(
            label="Batch Name *",
            hint_text="e.g., Haj Silver 2026",
            height=48, text_size=12,
        )
        self.year_dropdown = ft.Dropdown(
            label="Year *",
            options=year_opts,
            value=str(datetime.now().year),
            width=120, height=48, text_size=12,
        )
        self.year_dropdown.on_change = self.on_year_change

        self.tour_dropdown = ft.Dropdown(
            label="Tour Type *",
            options=tour_opts,
            value="",
            width=180, height=48, text_size=12,
        )
        self.tour_dropdown.on_change = self.on_tour_change

        self.id_preview = ft.Text(
            "📋 Batch ID: Select Year and Tour Type",
            size=11, weight=ft.FontWeight.BOLD,
            color=ft.Colors.RED_600,
        )
        self.seats_field = ft.TextField(
            label="Seats", value="150", width=120,
            height=48, text_size=12,
        )
        self.price_field = ft.TextField(
            label="Price (₹)", hint_text="350000",
            width=180, height=48, text_size=12,
        )
        self.departure_field = ft.TextField(
            label="Departure (YYYY-MM-DD)",
            value=datetime.now().strftime("%Y-%m-%d"),
            height=48, text_size=12,
        )
        self.return_field = ft.TextField(
            label="Return (YYYY-MM-DD)",
            value=datetime.now().strftime("%Y-%m-%d"),
            height=48, text_size=12,
        )
        self.date_validation = ft.Text("", size=11,
                                       color=ft.Colors.GREEN_700)
        self.status_dropdown = ft.Dropdown(
            label="Status",
            options=[
                ft.dropdown.Option("Open"),
                ft.dropdown.Option("Closing Soon"),
                ft.dropdown.Option("Full"),
                ft.dropdown.Option("Closed"),
            ],
            value="Open",
            width=180, height=48, text_size=12,
        )
        self.description_field = ft.TextField(
            label="Description",
            hint_text="Package details...",
            multiline=True, min_lines=2, max_lines=3,
            text_size=12,
        )

        content = ft.Column(
            controls=[
                self.name_field,
                ft.Row([self.year_dropdown, self.tour_dropdown],
                       spacing=10, wrap=True),
                self.id_preview,
                ft.Row([self.seats_field, self.price_field],
                       spacing=10, wrap=True),
                self.departure_field,
                self.return_field,
                self.date_validation,
                self.status_dropdown,
                self.description_field,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

        title = "✏️ Edit Batch" if self.is_edit else "➕ Create New Batch"

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD, size=15),
            content=ft.Container(content=content,
                                 width=600, height=560, padding=10),
            actions=[
                ft.TextButton(
                    content=ft.Text("Cancel"),
                    on_click=lambda e: self.page.pop_dialog()),
                ft.Button(
                    content=ft.Text("💾 Save"),
                    on_click=self.save,
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
        self.update_id_preview()

    def on_tour_change(self, e):
        self.update_id_preview()

    def update_id_preview(self):
        year = self.year_dropdown.value
        tour_id = self.tour_dropdown.value
        if not year or not tour_id:
            self.id_preview.value = (
                "📋 Batch ID: Select Year and Tour Type")
            self.id_preview.color = ft.Colors.RED_600
            try:
                self.page.update()
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
        self.id_preview.value = f"📋 Batch ID: {bid}"
        self.id_preview.color = ft.Colors.GREEN_700
        try:
            self.page.update()
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
        self.price_field.value = str(int(b.get("price", 0) or 0))
        if b.get("departure_date"):
            self.departure_field.value = str(b.get("departure_date"))[:10]
        if b.get("return_date"):
            self.return_field.value = str(b.get("return_date"))[:10]
        self.status_dropdown.value = str(b.get("status", "Open"))
        self.description_field.value = str(b.get("description", ""))
        self.update_id_preview()

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
            price_text = (self.price_field.value or "").strip()
            if not price_text:
                self._snack("⚠️ Price is required")
                return
            try:
                price = int(float(price_text))
            except Exception:
                self._snack("⚠️ Price must be a number")
                return
            try:
                seats = int(float(self.seats_field.value or 150))
            except Exception:
                seats = 150

            dep = (self.departure_field.value or "").strip()
            ret = (self.return_field.value or "").strip()
            if not dep or not ret:
                self._snack("⚠️ Departure and Return dates required")
                return
            try:
                dep_dt = datetime.strptime(dep[:10], "%Y-%m-%d")
                ret_dt = datetime.strptime(ret[:10], "%Y-%m-%d")
                if ret_dt < dep_dt:
                    self._snack("⚠️ Return must be after departure")
                    return
            except Exception:
                self._snack("⚠️ Dates must be YYYY-MM-DD")
                return

            tour_name = ""
            for t in self.tour_types:
                if str(t.get("id", "")) == str(tour_id):
                    tour_name = t.get("tour_name", "")
                    break

            data = {
                "batch_name": name,
                "tour_type_id": tour_id,
                "tour_type_name": tour_name,
                "year": int(year),
                "total_seats": seats,
                "price": price,
                "departure_date": dep[:10],
                "return_date": ret[:10],
                "status": self.status_dropdown.value or "Open",
                "description": (self.description_field.value or "").strip(),
            }

            if self.is_edit:
                self.db.update_batch(self.batch.get("id"), data)
                self.db.log_activity(
                    self.current_user["id"], "edit_batch",
                    f"Updated batch: {name}")
                msg = "✅ Batch updated"
            else:
                bid = _db_add_batch(self.db, data)
                self.db.log_activity(
                    self.current_user["id"], "add_batch",
                    f"Added batch: {name}")
                msg = f"✅ Batch created: {bid}"

            self.page.pop_dialog()
            self._snack(msg)
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
                ft.Text(label, width=140,
                        weight=ft.FontWeight.BOLD, size=11),
                ft.Text(str(value) if value not in (None, "") else "-",
                        size=11, selectable=True, expand=True),
            ], spacing=8)

        travelers = self.db.get_travelers()
        assigned = [t for t in travelers
                    if str(t.get("batch_id")) == str(b.get("id"))]
        names = [(f"{t.get('first_name', '')} "
                  f"{t.get('last_name', '')}").strip() or "N/A"
                 for t in assigned]

        content = ft.Column(
            controls=[
                ft.Text("Batch Information", size=12,
                        weight=ft.FontWeight.BOLD, color="#1e40af"),
                ft.Divider(),
                row("ID", b.get("id", "")),
                row("Batch Name", b.get("batch_name", "")),
                row("Tour Type", b.get("tour_type_name", "N/A")),
                row("Year", b.get("year", "")),
                row("Departure", b.get("departure_date", "-")),
                row("Return", b.get("return_date", "-")),
                row("Price", f"₹{int(b.get('price', 0) or 0):,}"),
                row("Total Seats", b.get("total_seats", 0)),
                row("Status", b.get("status", "")),
                row("Description", b.get("description", "")),
                ft.Divider(),
                row("Travelers Booked", len(assigned)),
                row("Traveler List",
                    ", ".join(names[:5]) + ("..." if len(names) > 5 else "")),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"📦 {b.get('batch_name', 'Batch')}",
                          weight=ft.FontWeight.BOLD, size=15),
            content=ft.Container(content=content, width=480,
                                 height=500, padding=10),
            actions=[
                ft.Button(
                    content=ft.Text("Close"),
                    on_click=lambda e: self.page.pop_dialog(),
                    bgcolor=ft.Colors.BLUE_700,
                    color=ft.Colors.WHITE),
            ],
        )

    def show(self):
        self.page.show_dialog(self.dialog)


# =================================================================================
# END — core/batches_tab.py
# =================================================================================