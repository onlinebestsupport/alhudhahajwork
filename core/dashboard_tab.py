# =================================================================================
# core/dashboard_tab.py — DashboardTab (Flet 1.0, mobile-responsive)
# =================================================================================
# v1.3 — Mobile-friendly layout:
#   • Header stacks cleanly on narrow screens
#   • Stat cards use ResponsiveRow (2 per row mobile, 4 per row desktop)
#   • Quick action buttons stack full-width on mobile
#   • Removed problematic gradients that broke on some mobile browsers
# =================================================================================

import asyncio
import math
import threading
import time
import pandas as pd
from datetime import datetime, timedelta

import flet as ft

try:
    import flet_charts as fch
    _CHART_ENGINE = "flet_charts"
except Exception:
    _CHART_ENGINE = None
    fch = None

_MPL_AVAILABLE = False
try:
    from matplotlib.figure import Figure
    from flet.matplotlib_chart import MatplotlibChart
    _MPL_AVAILABLE = True
except Exception:
    MatplotlibChart = None


def format_currency_indian(amount):
    if amount is None or (isinstance(amount, float) and math.isnan(amount)):
        return "₹ 0.00"
    try:
        amount = float(amount)
    except Exception:
        return "₹ 0.00"
    is_negative = amount < 0
    amount = abs(amount)
    amount_str = f"{amount:.2f}"
    integer_part, fractional_part = amount_str.split(".")
    if len(integer_part) > 3:
        last_three = integer_part[-3:]
        remaining = integer_part[:-3]
        remaining = ",".join(
            [remaining[max(i - 2, 0):i]
             for i in range(len(remaining), 0, -2)][::-1])
        integer_part = f"{remaining},{last_three}"
    formatted = f"₹ {integer_part}.{fractional_part}"
    return f"-{formatted}" if is_negative else formatted


class DashboardTab:

    def __init__(self, page: ft.Page, db, current_user, on_navigate=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.on_navigate = on_navigate

        self.date_label = None
        self.time_label = None
        self.stats_values = {}
        self.top_batches_table = None
        self.batch_summary_table = None
        self.activity_table = None
        self.sales_chart = None
        self.chart_container = None
        self.root = None
        self._clock_task_running = False
        self._clock_thread = None

        try:
            self.setup_ui()
        except Exception as e:
            import traceback
            print(f"[DASHBOARD setup_ui] FAILED: {e}")
            traceback.print_exc()
            self.root = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.WARNING_AMBER, size=48,
                            color=ft.Colors.ORANGE_600),
                    ft.Text("Dashboard failed to load",
                            size=18, weight=ft.FontWeight.BOLD),
                    ft.Text(str(e), size=12, color=ft.Colors.RED_500),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=10),
                padding=40, alignment=ft.Alignment.CENTER, expand=True,
            )

        try:
            self.refresh()
        except Exception as e:
            print(f"[DASHBOARD refresh] FAILED: {e}")

    def build(self):
        return self.root

    def safe_str(self, value):
        if value is None:
            return ""
        try:
            if isinstance(value, float):
                if value != value:
                    return ""
                if value.is_integer():
                    return str(int(value))
            return str(value)
        except Exception:
            return ""

    # =============================================================================
    # setup_ui
    # =============================================================================
    def setup_ui(self):
        company_name = "Alhudha Haj Travel"
        try:
            if not self.db.company_settings.empty:
                raw = self.db.company_settings.iloc[0].get("company_name", "")
                if raw:
                    company_name = str(raw)
        except Exception:
            pass

        gst_rate, tcs_rate = 18.0, 0.1
        try:
            tax_file = self.db.data_dir / "tax_settings.csv"
            if tax_file.exists():
                tdf = pd.read_csv(tax_file)
                if not tdf.empty:
                    gst_rate = float(tdf.iloc[0].get("gst_percentage", 18) or 18)
                    tcs_rate = float(tdf.iloc[0].get("tcs_percentage", 0.1) or 0.1)
        except Exception:
            pass

        self.date_label = ft.Text("", size=10, weight=ft.FontWeight.BOLD,
                                  color=ft.Colors.YELLOW_300)
        self.time_label = ft.Text("", size=16, weight=ft.FontWeight.BOLD,
                                  color=ft.Colors.WHITE)
        self.update_time()

        # ---- Mobile-aware header ----
        header = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("🕋", size=28),
                            ft.Column(
                                controls=[
                                    ft.Text(company_name, size=14,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.Colors.WHITE,
                                            no_wrap=True,
                                            overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text("Pilgrimage & Travel System",
                                            size=9,
                                            color=ft.Colors.BLUE_100),
                                ],
                                spacing=2, expand=True,
                            ),
                            ft.Container(
                                content=ft.Column(
                                    controls=[self.date_label,
                                              self.time_label],
                                    spacing=0,
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                                padding=ft.Padding.symmetric(
                                    horizontal=10, vertical=4),
                                bgcolor=ft.Colors.with_opacity(0.25,
                                                               ft.Colors.BLACK),
                                border_radius=10,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Text(f"GST {gst_rate}%", size=10,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.WHITE),
                                ft.Container(width=8),
                                ft.Text(f"TCS {tcs_rate}%", size=10,
                                        color=ft.Colors.BLUE_100),
                            ],
                            spacing=4,
                        ),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                        bgcolor=ft.Colors.with_opacity(0.25,
                                                       ft.Colors.BLACK),
                        border_radius=10,
                    ),
                ],
                spacing=8,
            ),
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            bgcolor="#1a252f",
            border_radius=15,
        )

        # ---- Stat cards ----
        card_configs = [
            ("total_travelers",        "👥", "Total Travelers",   "#3498db"),
            ("active_batches",         "📦", "Active Batches",    "#2ecc71"),
            ("total_seats",            "🪑", "Total Seats",       "#e67e22"),
            ("available_seats",        "✅", "Available Seats",   "#27ae60"),
            ("total_payments",         "💰", "Total Collections", "#9b59b6"),
            ("pending_amount_package", "📦", "Pending (Package)", "#e74c3c"),
            ("pending_amount_invoice", "📄", "Pending (Invoice)", "#f39c12"),
            ("total_receipts",         "🧾", "Total Receipts",    "#1abc9c"),
        ]

        cards_row1, cards_row2 = [], []
        for i, (key, icon, title, color) in enumerate(card_configs):
            card = self._create_card(icon, title, color, key)
            (cards_row1 if i < 4 else cards_row2).append(card)

        # ---- Mobile-friendly: 2 per row on xs, 4 per row on md+ ----
        cards_section = ft.Column(
            controls=[
                ft.ResponsiveRow(
                    controls=[self._wrap_card(c) for c in cards_row1],
                    spacing=8, run_spacing=8),
                ft.ResponsiveRow(
                    controls=[self._wrap_card(c) for c in cards_row2],
                    spacing=8, run_spacing=8),
            ],
            spacing=10,
        )

        # ---- Quick Actions ----
        def _action_btn(label, color, handler):
            return ft.Button(
                content=ft.Text(label, size=12,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE,
                                no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS),
                on_click=handler,
                height=44,
                bgcolor=color,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=10)),
            )

        actions_container = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("⚡ Quick Actions", size=14,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLUE_GREY_800),
                    ft.ResponsiveRow(
                        controls=[
                            ft.Container(
                                content=_action_btn("➕ Add Traveler",
                                                    "#3498db",
                                                    self.add_traveler),
                                col={"xs": 12, "sm": 6, "md": 3}),
                            ft.Container(
                                content=_action_btn("💰 Record Payment",
                                                    "#27ae60",
                                                    self.record_payment),
                                col={"xs": 12, "sm": 6, "md": 3}),
                            ft.Container(
                                content=_action_btn("📄 Create Invoice",
                                                    "#f39c12",
                                                    self.create_invoice),
                                col={"xs": 12, "sm": 6, "md": 3}),
                            ft.Container(
                                content=_action_btn("📊 Generate Report",
                                                    "#9b59b6",
                                                    self.generate_report),
                                col={"xs": 12, "sm": 6, "md": 3}),
                        ],
                        spacing=8, run_spacing=8,
                    ),
                ],
                spacing=10,
            ),
            padding=14, bgcolor=ft.Colors.WHITE, border_radius=12,
        )

        chart_section = self._build_chart_section()

        # ---- Top Batches ----
        self.top_batches_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Rank", size=11)),
                ft.DataColumn(ft.Text("Batch Name", size=11)),
                ft.DataColumn(ft.Text("Type", size=11)),
                ft.DataColumn(ft.Text("Booked", size=11)),
                ft.DataColumn(ft.Text("Available", size=11)),
            ],
            rows=[], heading_row_color=ft.Colors.BLUE_GREY_800,
            heading_row_height=38, data_row_min_height=38,
            column_spacing=12,
        )
        top_batches_section = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("🏆 Top Batches by Bookings", size=13,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLUE_GREY_800),
                    ft.Container(
                        content=ft.Row(
                            [self.top_batches_table],
                            scroll=ft.ScrollMode.ADAPTIVE,
                        ),
                        bgcolor=ft.Colors.GREY_50, border_radius=10,
                        border=ft.Border.all(1, ft.Colors.GREY_300),
                        padding=8,
                    ),
                ],
                spacing=10,
            ),
            padding=14, bgcolor=ft.Colors.WHITE, border_radius=12,
        )

        # ---- Batch Summary ----
        self.batch_summary_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Batch", size=11)),
                ft.DataColumn(ft.Text("Type", size=11)),
                ft.DataColumn(ft.Text("Year", size=11)),
                ft.DataColumn(ft.Text("Seats", size=11)),
                ft.DataColumn(ft.Text("Booked", size=11)),
                ft.DataColumn(ft.Text("Available", size=11)),
            ],
            rows=[], heading_row_color=ft.Colors.BLUE_GREY_800,
            heading_row_height=38, data_row_min_height=36,
            column_spacing=12,
        )
        batch_summary_section = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("📊 Batch Summary", size=13,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLUE_GREY_800),
                    ft.Container(
                        content=ft.Row(
                            [self.batch_summary_table],
                            scroll=ft.ScrollMode.ADAPTIVE,
                        ),
                        bgcolor=ft.Colors.GREY_50, border_radius=10,
                        border=ft.Border.all(1, ft.Colors.GREY_300),
                        padding=8,
                    ),
                ],
                spacing=10,
            ),
            padding=14, bgcolor=ft.Colors.WHITE, border_radius=12,
        )

        # ---- Activity Log ----
        self.activity_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Time", size=11)),
                ft.DataColumn(ft.Text("User", size=11)),
                ft.DataColumn(ft.Text("Action", size=11)),
                ft.DataColumn(ft.Text("Details", size=11)),
            ],
            rows=[], heading_row_color=ft.Colors.BLUE_GREY_700,
            heading_row_height=36, data_row_min_height=34,
            column_spacing=12,
        )
        activity_section = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("📋 Recent Activity", size=13,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLUE_GREY_800),
                    ft.Container(
                        content=ft.Row(
                            [self.activity_table],
                            scroll=ft.ScrollMode.ADAPTIVE,
                        ),
                        bgcolor=ft.Colors.GREY_50, border_radius=10,
                        border=ft.Border.all(1, ft.Colors.GREY_300),
                        padding=8,
                    ),
                ],
                spacing=10,
            ),
            padding=14, bgcolor=ft.Colors.WHITE, border_radius=12,
        )

        # ---- Root ----
        self.root = ft.Container(
            content=ft.Column(
                controls=[
                    header, cards_section, actions_container,
                    chart_section, top_batches_section,
                    batch_summary_section, activity_section,
                ],
                spacing=12, scroll=ft.ScrollMode.AUTO,
            ),
            padding=10, bgcolor="#f0f2f5", expand=True,
        )

        self._start_clock()

    # -----------------------------------------------------------------------------
    # Helper — wrap a stat card for ResponsiveRow
    # -----------------------------------------------------------------------------
    def _wrap_card(self, card):
        """Wrap a stat card for ResponsiveRow — 2 per row mobile,
        4 per row desktop."""
        try:
            card.expand = False
        except Exception:
            pass
        return ft.Container(
            content=card,
            col={"xs": 6, "sm": 6, "md": 3, "lg": 3, "xl": 3},
        )

    # -----------------------------------------------------------------------------
    # Clock
    # -----------------------------------------------------------------------------
    def _start_clock(self):
        try:
            if hasattr(self.page, "run_task") and self.page.run_task:
                self.page.run_task(self._clock_loop)
                return
        except Exception as e:
            print(f"[CLOCK] page.run_task failed: {e}")

        try:
            t = threading.Thread(target=self._clock_thread_loop, daemon=True)
            t.start()
            self._clock_thread = t
        except Exception as e:
            print(f"[CLOCK] threading fallback failed: {e}")

    async def _clock_loop(self):
        if self._clock_task_running:
            return
        self._clock_task_running = True
        try:
            while True:
                self.update_time()
                try:
                    self.page.update()
                except Exception:
                    break
                await asyncio.sleep(1)
        except Exception as ex:
            print(f"[CLOCK] stopped: {ex}")
        finally:
            self._clock_task_running = False

    def _clock_thread_loop(self):
        try:
            while True:
                self.update_time()
                try:
                    self.page.update()
                except Exception:
                    break
                time.sleep(1)
        except Exception as ex:
            print(f"[CLOCK-THREAD] stopped: {ex}")

    def update_time(self):
        try:
            now = datetime.now()
            if self.date_label:
                self.date_label.value = now.strftime("%a, %b %d")
            if self.time_label:
                self.time_label.value = now.strftime("%I:%M %p")
        except Exception:
            pass

    # -----------------------------------------------------------------------------
    # Chart section
    # -----------------------------------------------------------------------------
    def _build_chart_section(self):
        chart_content = None

        if _CHART_ENGINE == "flet_charts":
            try:
                self.sales_chart = fch.BarChart(
                    groups=[],
                    border=ft.Border.only(
                        bottom=ft.BorderSide(1, ft.Colors.GREY_300),
                        left=ft.BorderSide(1, ft.Colors.GREY_300),
                    ),
                    horizontal_grid_lines=fch.ChartGridLines(
                        color=ft.Colors.GREY_300, width=1,
                        dash_pattern=[3, 3]),
                    tooltip=fch.BarChartTooltip(
                        bgcolor=ft.Colors.with_opacity(0.85,
                                                       ft.Colors.BLUE_GREY_800),
                        border_radius=ft.BorderRadius.all(6),
                    ),
                    max_y=100, interactive=True, expand=True, height=240,
                )
                chart_content = self.sales_chart
            except Exception as e:
                print(f"[CHART] flet_charts init failed: {e}")
                chart_content = None

        if chart_content is None and _MPL_AVAILABLE:
            try:
                self.chart_container = ft.Container(height=240)
                chart_content = self.chart_container
            except Exception as e:
                print(f"[CHART] matplotlib init failed: {e}")
                chart_content = None

        if chart_content is None:
            chart_content = ft.Container(
                height=200,
                content=ft.Text(
                    "Charts unavailable — install flet-charts.",
                    color=ft.Colors.GREY_500, size=12,
                    text_align=ft.TextAlign.CENTER),
                alignment=ft.Alignment.CENTER,
            )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(controls=[
                        ft.Text("📈", size=18),
                        ft.Text("Sales Overview (Last 7 Days)",
                                size=13, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.BLUE_GREY_800),
                    ], spacing=8),
                    chart_content,
                ],
                spacing=10,
            ),
            padding=14, bgcolor=ft.Colors.WHITE, border_radius=12,
        )

    # -----------------------------------------------------------------------------
    # Card factory
    # -----------------------------------------------------------------------------
    def _create_card(self, icon, title, color, key):
        value_label = ft.Text("0", size=18,
                              weight=ft.FontWeight.BOLD, color=color)
        self.stats_values[key] = value_label

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Text(icon, size=20),
                        width=40, height=40,
                        alignment=ft.Alignment.CENTER,
                        bgcolor=ft.Colors.with_opacity(0.15, color),
                        border_radius=10,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(title, size=10,
                                    color=ft.Colors.GREY_600,
                                    no_wrap=False,
                                    max_lines=2),
                            value_label,
                        ],
                        spacing=1, expand=True,
                    ),
                ],
                spacing=8,
            ),
            padding=10, bgcolor=ft.Colors.WHITE, border_radius=12,
            border=ft.Border.only(left=ft.BorderSide(4, color)),
            height=80,
        )

    # -----------------------------------------------------------------------------
    # Refresh
    # -----------------------------------------------------------------------------
    def refresh(self):
        try:
            try:
                if hasattr(self.db, "reload"):
                    self.db.reload()
                elif hasattr(self.db, "_load_all"):
                    self.db._load_all()
            except Exception as _re:
                print(f"[DashboardTab.refresh] reload skipped: {_re}")

            travelers = self.db.get_travelers()
            batches = self.db.get_batches()
            payments = self.db.get_payments()
            invoices = self.db.get_invoices()
            receipts = self.db.get_receipts()

            total_seats = sum(int(float(b.get("total_seats", 0) or 0))
                              for b in batches)
            available_seats = sum(int(float(b.get("available_seats", 0) or 0))
                                  for b in batches)
            total_payments = sum(float(p.get("amount", 0) or 0)
                                 for p in payments)

            batch_prices = {b["id"]: float(b.get("price", 0) or 0)
                            for b in batches}
            traveler_batch_map = {}
            for t in travelers:
                bid = t.get("batch_id")
                if bid and bid in batch_prices:
                    traveler_batch_map[t["id"]] = {
                        "batch_id": bid, "price": batch_prices[bid]}

            traveler_paid = {}
            for p in payments:
                tid = p.get("traveler_id")
                if tid:
                    traveler_paid[tid] = (
                        traveler_paid.get(tid, 0)
                        + float(p.get("amount", 0) or 0))

            total_package_pending = 0
            for tid, info in traveler_batch_map.items():
                paid = traveler_paid.get(tid, 0)
                pending = info["price"] - paid
                if pending > 0:
                    total_package_pending += pending

            total_invoice_pending = 0
            for inv in invoices:
                if inv.get("status") == "pending":
                    total_invoice_pending += float(
                        inv.get("rounded_total",
                                inv.get("total_amount", 0)) or 0)

            self._set_stat("total_travelers", f"{len(travelers):,}")

            _active_statuses = {"open", "closing soon"}
            active_count = len([
                b for b in batches
                if str(b.get("status", "")).strip().lower() in _active_statuses
            ])
            self._set_stat("active_batches", str(active_count))
            self._set_stat("total_seats", f"{total_seats:,}")
            self._set_stat("available_seats", f"{available_seats:,}")
            self._set_stat("total_payments",
                           format_currency_indian(total_payments))
            self._set_stat("pending_amount_package",
                           format_currency_indian(total_package_pending))
            self._set_stat("pending_amount_invoice",
                           format_currency_indian(total_invoice_pending))
            self._set_stat("total_receipts", f"{len(receipts):,}")

            try:
                self.update_batch_summary(batches, travelers)
            except Exception as e:
                print(f"[DASHBOARD batch_summary] {e}")

            try:
                self.update_top_batches(batches, travelers)
            except Exception as e:
                print(f"[DASHBOARD top_batches] {e}")

            try:
                self.update_activity_log()
            except Exception as e:
                print(f"[DASHBOARD activity] {e}")

            try:
                self.update_charts()
            except Exception as e:
                print(f"[DASHBOARD chart update] {e}")

            try:
                self.page.update()
            except Exception:
                pass
        except Exception as ex:
            print(f"Dashboard refresh error: {ex}")
            import traceback
            traceback.print_exc()

    def _set_stat(self, key, value):
        ctrl = self.stats_values.get(key)
        if ctrl:
            ctrl.value = str(value)

    def update_top_batches(self, batches, travelers):
        counts = {}
        for t in travelers:
            bid = t.get("batch_id")
            if bid:
                counts[bid] = counts.get(bid, 0) + 1

        batch_list = []
        for b in batches:
            bid = b.get("id")
            booked = counts.get(bid, 0)
            if booked > 0:
                batch_list.append({
                    "name": b.get("batch_name", "Unknown"),
                    "type": b.get("tour_type_name", ""),
                    "booked": booked,
                    "available": int(float(b.get("total_seats", 0) or 0))
                                  - booked,
                })
        batch_list.sort(key=lambda x: x["booked"], reverse=True)
        batch_list = batch_list[:10]

        self.top_batches_table.rows.clear()
        for i, item in enumerate(batch_list):
            if i == 0:
                rank_txt, rank_color = "🥇 1", "#FFD700"
            elif i == 1:
                rank_txt, rank_color = "🥈 2", "#C0C0C0"
            elif i == 2:
                rank_txt, rank_color = "🥉 3", "#CD7F32"
            else:
                rank_txt, rank_color = f"#{i+1}", "#2c3e50"

            booked_color = ("#27ae60" if item["booked"] >= 20
                            else "#f39c12" if item["booked"] >= 10
                            else "#e74c3c")
            avail = item["available"]
            avail_color = ("#e74c3c" if avail <= 0
                           else "#f39c12" if avail <= 10
                           else "#27ae60")

            self.top_batches_table.rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(rank_txt, color=rank_color,
                                        size=11,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(item["name"], size=11,
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(item["type"], size=11)),
                    ft.DataCell(ft.Text(str(item["booked"]), size=11,
                                        color=booked_color)),
                    ft.DataCell(ft.Text(str(avail), size=11,
                                        color=avail_color)),
                ]))

    def update_batch_summary(self, batches, travelers):
        counts = {}
        for t in travelers:
            bid = t.get("batch_id")
            if bid:
                counts[bid] = counts.get(bid, 0) + 1

        self.batch_summary_table.rows.clear()
        for b in batches:
            bid = b.get("id")
            booked = counts.get(bid, 0)
            total = int(float(b.get("total_seats", 0) or 0))
            avail = total - booked

            avail_color = ("#e74c3c" if avail <= 0
                           else "#e67e22" if total and avail <= total * 0.2
                           else "#27ae60")

            self.batch_summary_table.rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(self.safe_str(
                        b.get("batch_name", "N/A")), size=11,
                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(self.safe_str(
                        b.get("tour_type_name", "N/A")), size=11)),
                    ft.DataCell(ft.Text(self.safe_str(
                        b.get("year", "-")), size=11)),
                    ft.DataCell(ft.Text(self.safe_str(total), size=11)),
                    ft.DataCell(ft.Text(self.safe_str(booked), size=11,
                                        color="#1e8449" if booked > 0 else None)),
                    ft.DataCell(ft.Text(self.safe_str(avail), size=11,
                                        color=avail_color)),
                ]))

    def update_activity_log(self):
        try:
            log_df = None
            if hasattr(self.db, "get_activity_log"):
                try:
                    res = self.db.get_activity_log()
                    if isinstance(res, pd.DataFrame):
                        log_df = res
                except Exception as _e:
                    print(f"[DashboardTab.activity] failed: {_e}")

            if log_df is None:
                log_df = getattr(self.db, "activity_log", None)

            if log_df is None or log_df.empty:
                self.activity_table.rows.clear()
                return

            recent = log_df.tail(15).iloc[::-1]
            self.activity_table.rows.clear()

            users_df = getattr(self.db, "users", None)
            user_map = {}
            if users_df is not None and not users_df.empty:
                user_map = dict(zip(users_df["id"], users_df["username"]))

            for _, a in recent.iterrows():
                uid = a.get("user_id")
                username = user_map.get(uid, "Unknown")

                try:
                    dt = datetime.fromisoformat(str(a.get("timestamp", "")))
                    ts = dt.strftime("%m/%d %H:%M")
                except Exception:
                    ts = str(a.get("timestamp", ""))[:10]

                details = self.safe_str(a.get("details", ""))
                if len(details) > 30:
                    details = details[:30] + "..."

                self.activity_table.rows.append(
                    ft.DataRow(cells=[
                        ft.DataCell(ft.Text(ts, size=10)),
                        ft.DataCell(ft.Text(str(username)[:12], size=10)),
                        ft.DataCell(ft.Text(str(a.get("action", ""))[:15],
                                            size=10)),
                        ft.DataCell(ft.Text(details, size=10)),
                    ]))
        except Exception as ex:
            print(f"Error updating activity log: {ex}")

    def update_charts(self):
        if _CHART_ENGINE == "flet_charts":
            self._update_chart_flet_charts()
        elif _MPL_AVAILABLE and self.chart_container is not None:
            self._update_chart_matplotlib()

    def _update_chart_flet_charts(self):
        try:
            df_sales = self._get_sales_last_days(7)
            self.sales_chart.groups.clear()

            if df_sales.empty:
                self.sales_chart.max_y = 100
                self.sales_chart.bottom_axis = fch.ChartAxis(
                    labels=[], label_size=40)
                self.sales_chart.left_axis = fch.ChartAxis(
                    labels=[], label_size=50)
                return

            values = list(df_sales.values)
            dates = list(df_sales.index)
            max_val = max(values) if values else 1
            self.sales_chart.max_y = max(max_val * 1.25, 100)

            groups = []
            for i, (d, v) in enumerate(zip(dates, values)):
                groups.append(
                    fch.BarChartGroup(
                        x=i,
                        rods=[
                            fch.BarChartRod(
                                from_y=0, to_y=float(v),
                                width=22, color="#3498db",
                                tooltip=fch.BarChartRodTooltip(
                                    f"{d.strftime('%d/%m')}\n₹{int(v):,}"),
                                border_radius=4,
                            ),
                        ],
                    ))
            self.sales_chart.groups = groups

            self.sales_chart.bottom_axis = fch.ChartAxis(
                labels=[
                    fch.ChartAxisLabel(
                        value=i,
                        label=ft.Text(d.strftime("%d/%m"), size=9),
                    )
                    for i, d in enumerate(dates)
                ],
                label_size=28,
            )
            self.sales_chart.left_axis = fch.ChartAxis(label_size=50)
        except Exception as ex:
            print(f"flet_charts update error: {ex}")

    def _update_chart_matplotlib(self):
        try:
            if self.chart_container is None:
                return
            df_sales = self._get_sales_last_days(7)
            fig = Figure(figsize=(7.5, 3.0), tight_layout=True)
            ax = fig.add_subplot(111)

            if not df_sales.empty:
                values = list(df_sales.values)
                dates = list(df_sales.index)
                ax.bar(range(len(values)), values, color="#3498db",
                       alpha=0.85)
                ax.set_xticks(range(len(values)))
                ax.set_xticklabels([d.strftime("%d/%m") for d in dates],
                                   rotation=45, fontsize=8)
                ax.grid(True, alpha=0.25, linestyle="--")
                ax.set_ylabel("Amount (₹)", fontsize=9)
            else:
                ax.text(0.5, 0.5, "No sales data available",
                        ha="center", va="center", color="#888")
                ax.set_xticks([]); ax.set_yticks([])

            self.chart_container.content = MatplotlibChart(fig, expand=True)
        except Exception as ex:
            print(f"matplotlib chart error: {ex}")

    def _get_sales_last_days(self, days):
        payments = None
        if hasattr(self.db, "get_payments"):
            try:
                rows = self.db.get_payments()
                if rows:
                    payments = pd.DataFrame(rows)
                else:
                    payments = pd.DataFrame()
            except Exception as _e:
                print(f"[DashboardTab.chart] get_payments failed: {_e}")

        if payments is None or payments.empty:
            payments = getattr(self.db, "payments", None)
            if payments is None or payments.empty:
                return pd.DataFrame()
            payments = payments.copy()

        if "payment_date" not in payments.columns:
            return pd.DataFrame()

        df = payments.copy()
        df["payment_date"] = pd.to_datetime(df["payment_date"],
                                            errors="coerce")
        cutoff = datetime.now() - timedelta(days=days)
        recent = df[df["payment_date"] >= cutoff]
        if recent.empty:
            return pd.DataFrame()

        daily = recent.groupby(recent["payment_date"].dt.date)["amount"].sum()
        return daily

    # -----------------------------------------------------------------------------
    # Quick actions
    # -----------------------------------------------------------------------------
    def _goto_tab(self, tab_name, action=None):
        print(f"[DASHBOARD] QuickAction → tab='{tab_name}' action={action}")

        if self.on_navigate is None:
            self.page.show_dialog(ft.SnackBar(
                content=ft.Text(
                    f"⚠️ Please open the '{tab_name}' tab from the top menu."
                ),
                bgcolor=ft.Colors.ORANGE_700,
            ))
            return

        try:
            self.on_navigate(tab_name, action)
        except TypeError:
            try:
                self.on_navigate(tab_name)
            except Exception as ex:
                print(f"[DASHBOARD] on_navigate failed: {ex}")
        except Exception as ex:
            print(f"[DASHBOARD] on_navigate failed: {ex}")
            self.page.show_dialog(ft.SnackBar(
                content=ft.Text(f"⚠️ Navigation error: {ex}"),
                bgcolor=ft.Colors.RED_600,
            ))

    def add_traveler(self, e):
        self._goto_tab("Travelers", "add")

    def record_payment(self, e):
        self._goto_tab("Payments", "add")

    def create_invoice(self, e):
        self._goto_tab("Invoices", "add")

    def generate_report(self, e):
        self._goto_tab("Reports")


# =================================================================================
# END — core/dashboard_tab.py
# =================================================================================