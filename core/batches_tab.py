# =================================================================================
# SECTION 11 (FLET 1.0.0 VERSION) — BATCHES TAB + DIALOGS
# =================================================================================
# PATCHES APPLIED (v1.1):
#   11.2.A — refresh()        : force DB reload before reading (fresh cache)
#   11.2.B — display_batches(): action icons capture batch ID, re-fetch latest
#                               dict on click (no stale row data)
#   11.2.C — delete_batch()   : prefer db.delete_batch(); also guards against
#                               invoices referencing the batch; shows warning
#
# CASCADE NOTE (3rd leg):
#   This tab owns the "batch price" that drives "Pkg Pending" in both the
#   Invoices tab (Patch 14.1.A) and the Receipts tab (Patch 15.1.A). Because
#   both of those tabs now call db.reload() on every refresh, editing a
#   batch price here propagates to their pending columns without restart.
# =================================================================================

# =================================================================================
# 11.1 — IMPORTS & INLINE HELPERS
# =================================================================================
import flet as ft
import os
from datetime import datetime
from pathlib import Path
import pandas as pd

# ---- SettingsManager (safe import) ----
try:
    from core.settings_manager import SettingsManager
except ImportError:
    SettingsManager = None


# ---- Inline helpers ----
def get_app_base_path():
    import sys
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _get_prefix(name):
    """Derive a 3-char prefix from a tour name."""
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
    """Add a batch using db.add_batch if available, else inline fallback."""
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
    """Return tour types from settings_manager, or fall back to a built-in list."""
    if SettingsManager is not None:
        try:
            return SettingsManager(db).get_tour_types()
        except Exception:
            pass
    # Fallback: scan existing batches to derive tour types
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
    """Return years from settings_manager, or fall back to 2020..2099."""
    if SettingsManager is not None:
        try:
            return SettingsManager(db).get_tour_years()
        except Exception:
            pass
    return list(range(2020, 2100))


# =================================================================================
# 11.2 — CLASS: BatchesTab
# =================================================================================
class BatchesTab:

    # -----------------------------------------------------------------------------
    # 11.2.1 — __init__
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # 11.2.2 — setup_ui
    # -----------------------------------------------------------------------------
    def setup_ui(self):
        # ---- STAT CARDS ----
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
                                        weight=ft.FontWeight.BOLD),
                            ],
                            spacing=4,
                        ),
                        value_label,
                    ],
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=10,
                bgcolor=color,   # ← solid color instead of gradient (safer)
                border_radius=10,
                expand=True,
                height=80,
            )
            stat_cards.append(card)

        stats_row = ft.Row(controls=stat_cards, spacing=10)

        # ---- TOOLBAR ----
        def _toolbar_btn(label, color, handler):
            return ft.Button(
                content=ft.Text(label, size=11,
                                weight=ft.FontWeight.BOLD),
                on_click=handler, height=38,
                bgcolor=color, color=ft.Colors.WHITE,
            )

        self.year_filter = ft.Dropdown(
            label="Year",
            options=[ft.dropdown.Option(key="", text="All")],
            value="",
            width=120, height=48, text_size=12,
        )
        self.year_filter.on_change = self.apply_filters

        self.tour_filter = ft.Dropdown(
            label="Tour Type",
            options=[ft.dropdown.Option(key="", text="All")],
            value="",
            width=180, height=48, text_size=12,
        )
        self.tour_filter.on_change = self.apply_filters

        self.search_input = ft.TextField(
            hint_text="🔍 Search...",
            width=220, height=48,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        )
        self.search_input.on_change = self.apply_filters

        toolbar = ft.Row(
            controls=[
                _toolbar_btn("➕ Create New Batch", "#27ae60",
                             self.open_create_dialog),
                _toolbar_btn("📊 Export", "#16a085",
                             self.export_to_excel),
                _toolbar_btn("🖨️ Print", "#2980b9", self.print_batches),
                self.year_filter,
                self.tour_filter,
                self.search_input,
            ],
            spacing=8,
            wrap=True,
        )

        # ---- TABLE ----
        self.table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("ID")),
                ft.DataColumn(ft.Text("Package")),
                ft.DataColumn(ft.Text("Tour Type")),
                ft.DataColumn(ft.Text("Year")),
                ft.DataColumn(ft.Text("Departure")),
                ft.DataColumn(ft.Text("Return")),
                ft.DataColumn(ft.Text("Price (₹)")),
                ft.DataColumn(ft.Text("Seats")),
                ft.DataColumn(ft.Text("Booked")),
                ft.DataColumn(ft.Text("Avail")),
                ft.DataColumn(ft.Text("Status")),
                ft.DataColumn(ft.Text("Occ%")),
                ft.DataColumn(ft.Text("Actions")),
            ],
            rows=[],
            column_spacing=12,
            heading_row_color=ft.Colors.BLUE_GREY_800,
            heading_row_height=42,
            data_row_min_height=48,
            data_row_max_height=60,
            border=ft.Border.all(1, ft.Colors.GREY_300),
            border_radius=10,
            vertical_lines=ft.BorderSide(1, ft.Colors.GREY_200),
            horizontal_lines=ft.BorderSide(1, ft.Colors.GREY_200),
        )

        # ---- PAGINATION ----
        self.pagination_label = ft.Text("Showing 0 to 0 of 0 batches",
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.BLUE_GREY_800)
        self.prev_btn = ft.Button(
            content=ft.Text("◀ Previous"),
            on_click=self.prev_page, height=36,
            bgcolor=ft.Colors.BLUE_600, color=ft.Colors.WHITE,
            disabled=True,
        )
        self.next_btn = ft.Button(
            content=ft.Text("Next ▶"),
            on_click=self.next_page, height=36,
            bgcolor=ft.Colors.BLUE_600, color=ft.Colors.WHITE,
            disabled=True,
        )
        pagination_row = ft.Row(
            controls=[
                self.pagination_label,
                ft.Container(expand=True),
                self.prev_btn, self.next_btn,
            ], spacing=10,
        )

        # ---- ROOT ----
        self.root = ft.Container(
            content=ft.Column(
                controls=[
                    stats_row,
                    ft.Container(content=toolbar, padding=10,
                                 bgcolor=ft.Colors.WHITE,
                                 border_radius=10),
                    ft.Container(
                        content=ft.Column(
                            controls=[self.table],
                            scroll=ft.ScrollMode.ADAPTIVE,
                        ),
                        bgcolor=ft.Colors.WHITE,
                        border_radius=10,
                        padding=10,
                    ),
                    pagination_row,
                ],
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=15,
            bgcolor="#f0f2f5",
            expand=True,
        )

    # -----------------------------------------------------------------------------
    # 11.2.3 — Helpers
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # 11.2.4 — load_tour_types_and_years
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # 11.2.5 — refresh  (PATCH 11.2.A: force DB reload before reading)
    # -----------------------------------------------------------------------------
    def refresh(self):
        try:
            # ---- PATCH 11.2.A: fresh cache reload ----
            # Travelers tab, Invoices tab, or Receipts tab may have written
            # to disk since our last read. Re-hydrate so get_* returns
            # current data, not a stale in-memory snapshot.
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

    # -----------------------------------------------------------------------------
    # 11.2.6 — display_batches
    #   PATCH 11.2.B: action icons capture batch ID, re-fetch on every click
    # -----------------------------------------------------------------------------
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

            # ------------------------------------------------------------
            # PATCH 11.2.B — capture ID (not dict), re-fetch before dispatch
            # ------------------------------------------------------------
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
                            self._snack("⚠️ Batch no longer exists — "
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
                            on_click=_wrap(self.view_batch)),
                        ft.IconButton(
                            icon=ft.Icons.EDIT,
                            icon_color="#f39c12", icon_size=18,
                            tooltip="Edit",
                            on_click=_wrap(self.open_edit_dialog)),
                        ft.IconButton(
                            icon=ft.Icons.DELETE,
                            icon_color="#e74c3c", icon_size=18,
                            tooltip="Delete",
                            on_click=_wrap(self.delete_batch)),
                    ], spacing=0,
                )

            self.table.rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(str(bid or ""), size=10)),
                    ft.DataCell(ft.Text(str(b.get("batch_name", "")),
                                        size=11,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(tname, size=11, color=tcolor,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(
                        str(b.get("year", "")), size=11,
                        color="#0064c8", weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(
                        self._fmt_date(b.get("departure_date")), size=11)),
                    ft.DataCell(ft.Text(
                        self._fmt_date(b.get("return_date")), size=11)),
                    ft.DataCell(ft.Text(
                        f"₹{int(b.get('price', 0) or 0):,}", size=11)),
                    ft.DataCell(ft.Text(str(total), size=11)),
                    ft.DataCell(ft.Text(
                        str(booked), size=11,
                        color="#1e8449" if booked > 0 else "#95a5a6")),
                    ft.DataCell(ft.Text(
                        str(avail), size=11, color=avail_color)),
                    ft.DataCell(ft.Text(
                        status, size=11, color=status_color,
                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(
                        f"{occ:.1f}%", size=11, color=occ_color)),
                    ft.DataCell(_make_actions()),
                ]))

        self.update_pagination()

    # -----------------------------------------------------------------------------
    # 11.2.7 — Pagination
    # -----------------------------------------------------------------------------
    def update_pagination(self):
        total = len(self.filtered_batches)
        start = ((self.current_page - 1) * self.items_per_page + 1
                 if total else 0)
        end = min(self.current_page * self.items_per_page, total)
        self.pagination_label.value = (
            f"Showing {start} to {end} of {total} batches")
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

    # -----------------------------------------------------------------------------
    # 11.2.8 — Filters
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # 11.2.9 — Statistics (case-insensitive)
    # -----------------------------------------------------------------------------
    def update_statistics(self):
        total = len(self.batches)

        # Case-insensitive: "Open", "open", "OPEN" all count
        open_batches = len([
            b for b in self.batches
            if str(b.get("status", "")).strip().lower() in ("open", "closing soon")
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

    # -----------------------------------------------------------------------------
    # 11.2.10 — Dialog launchers
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # 11.2.11 — delete_batch
    #   PATCH 11.2.C — prefer db.delete_batch(); also guard against invoices
    #                  referencing the batch; warn the user.
    # -----------------------------------------------------------------------------
    def delete_batch(self, batch):
        # ---- Guard 1: travelers assigned? ----
        assigned = [t for t in self.travelers
                    if str(t.get("batch_id")) == str(batch.get("id"))]
        if assigned:
            self._snack(
                f"⚠️ Cannot delete — {len(assigned)} traveler(s) assigned")
            return

        # ---- Guard 2: invoices referencing this batch? ----
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
                     f"this batch.\nTheir batch_id will point to a "
                     f"deleted record.\nConsider re-assigning travelers "
                     f"first.")

        def confirm(ev):
            try:
                # PATCH 11.2.C — prefer DB method
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
            title=ft.Text("Delete Batch?"),
            content=ft.Text(warn),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Delete"), on_click=confirm,
                          bgcolor=ft.Colors.RED_600,
                          color=ft.Colors.WHITE),
            ],
        )
        self.page.show_dialog(dialog)

    # -----------------------------------------------------------------------------
    # 11.2.12 — View
    # -----------------------------------------------------------------------------
    def view_batch(self, batch):
        dlg = BatchViewDialog(self.page, self.db, batch)
        dlg.show()

    # -----------------------------------------------------------------------------
    # 11.2.13 — Export
    # -----------------------------------------------------------------------------
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

            self._snack(f"✅ Exported {len(self.batches)} batches to {path}")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self._snack(f"❌ Export error: {ex}")

    # -----------------------------------------------------------------------------
    # 11.2.14 — Print + snack
    # -----------------------------------------------------------------------------
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


# =================================================================================
# 11.3 — CLASS: BatchFormDialog
# =================================================================================
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

    # -----------------------------------------------------------------------------
    # 11.3.1 — setup_ui
    # -----------------------------------------------------------------------------
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
            width=200, height=48, text_size=12,
        )
        self.return_field = ft.TextField(
            label="Return (YYYY-MM-DD)",
            value=datetime.now().strftime("%Y-%m-%d"),
            width=200, height=48, text_size=12,
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
                       spacing=10),
                self.id_preview,
                ft.Row([self.seats_field, self.price_field],
                       spacing=10),
                ft.Row([self.departure_field, self.return_field],
                       spacing=10),
                self.date_validation,
                self.status_dropdown,
                self.description_field,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

        title = ("✏️ Edit Batch" if self.is_edit
                 else "➕ Create New Batch")

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD),
            content=ft.Container(content=content,
                                 width=650, height=520, padding=10),
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

    # -----------------------------------------------------------------------------
    # 11.3.2 — ID preview helpers
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # 11.3.3 — load_batch (edit mode)
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # 11.3.4 — save
    # -----------------------------------------------------------------------------
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


# =================================================================================
# 11.4 — CLASS: BatchViewDialog
# =================================================================================
class BatchViewDialog:

    def __init__(self, page, db, batch):
        self.page = page
        self.db = db
        self.batch = batch
        self.dialog = None
        self.setup_ui()

    # -----------------------------------------------------------------------------
    # 11.4.1 — setup_ui
    # -----------------------------------------------------------------------------
    def setup_ui(self):
        b = self.batch

        def row(label, value):
            return ft.Row([
                ft.Text(label, width=160,
                        weight=ft.FontWeight.BOLD, size=12),
                ft.Text(str(value) if value not in (None, "") else "-",
                        size=12, selectable=True, expand=True),
            ], spacing=8)

        travelers = self.db.get_travelers()
        assigned = [t for t in travelers
                    if str(t.get("batch_id")) == str(b.get("id"))]
        names = [(f"{t.get('first_name', '')} "
                  f"{t.get('last_name', '')}").strip() or "N/A"
                 for t in assigned]

        content = ft.Column(
            controls=[
                ft.Text("Batch Information", size=13,
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
                          weight=ft.FontWeight.BOLD, size=16),
            content=ft.Container(content=content, width=500,
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
# SECTION 11 END (FLET 1.0.0 VERSION)
# =================================================================================