# =================================================================================
# SECTION 16 — REPORTS TAB (FLET 1.0, Mobile-Responsive)
# =================================================================================
# v1.2 — Mobile-Responsive
#   • Banner stacks on narrow screens
#   • Stat cards 2-per-row mobile, 5 desktop
#   • Report category cards stack on mobile
#   • Single Traveler: sidebar stacks ABOVE right column on mobile
#   • Standard Reports toolbar wraps
#   • Photo Viewer dropdown + display stack
#   • All original patches preserved:
#       16.1.A — refresh() reload
#       16.1.B — _rebuild_traveler_lists()
#       16.1.C — _generate_standard() reload
#       16.1.D — Flet 1.0 web-safe SnackBar
# =================================================================================

import os
import sys
import base64
import traceback
from datetime import datetime, timedelta

import flet as ft
import pandas as pd

try:
    from core.settings_manager import SettingsManager
except ImportError:
    SettingsManager = None


# =================================================================================
# 16.1b — MODULE HELPER: _app_base
# =================================================================================
def _app_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    here = os.path.dirname(os.path.abspath(__file__))
    cur = here
    for _ in range(6):
        if (os.path.exists(os.path.join(cur, "main.py"))
                or os.path.exists(os.path.join(cur, "documents"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return here


# =================================================================================
# 16.1c — _fmt_inr_
# =================================================================================
def _fmt_inr_(value):
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
# 16.1d — _fmt_date_ddmmyyyy
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
                "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d",
                "%d-%m-%Y", "%d/%m/%Y",
                "%d-%m-%y", "%d/%m/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:19], fmt).strftime("%d/%m/%Y")
        except Exception:
            continue
    return s[:10]


# =================================================================================
# 16.1e — _parse_ui_date
# =================================================================================
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
    if len(s) >= 10 and s[2] == "-" and s[5] == "-":
        try:
            return datetime.strptime(s, "%d-%m-%Y")
        except Exception:
            return None
    return None


# =================================================================================
# 16.1f — _photo_data_uri
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
    except Exception as e:
        print(f"[REPORTS] _photo_data_uri: {e}")
        return None


# =================================================================================
# 16.1g — _find_photo_path
# =================================================================================
def _find_photo_path(traveler):
    base = _app_base()
    rel = (traveler.get("photo", "") or "").strip()
    if rel:
        p = os.path.join(base, rel)
        if os.path.exists(p):
            return p
    tid = str(traveler.get("id", "") or "").strip()
    if not tid:
        return None
    folder_variants = list(dict.fromkeys([
        tid.replace("/", "_").replace("\\", "_"),
        tid.replace("/", "_").replace("\\", "_").upper(),
        tid.replace("/", "_").replace("\\", "_").lower(),
    ]))
    sub_variants = ["photos", "photo", "images", "img", ""]
    for folder in folder_variants:
        for sub in sub_variants:
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
# 16.1h — _collect_traveler_documents
# =================================================================================
def _collect_traveler_documents(traveler):
    base = _app_base()
    tid = traveler.get("id", "")
    folder = tid.replace("/", "_").replace("\\", "_")
    t_folder = os.path.join(base, "documents", folder)
    specs = [
        ("photo", "📸 Photo", "photos",
         (".jpg", ".jpeg", ".png", ".bmp", ".gif")),
        ("passport_scan", "📄 Passport", "passports",
         (".jpg", ".jpeg", ".png", ".pdf")),
        ("aadhaar_scan", "🆔 Aadhaar", "aadhaar",
         (".jpg", ".jpeg", ".png", ".pdf")),
        ("pan_scan", "💳 PAN", "pan", (".jpg", ".jpeg", ".png", ".pdf")),
        ("vaccine_scan", "💉 Vaccine", "vaccine",
         (".jpg", ".jpeg", ".png", ".pdf")),
    ]
    docs = []
    for key, label, sub, exts in specs:
        rel = traveler.get(key, "") or ""
        path = ""
        if rel:
            p = os.path.join(base, rel)
            if os.path.exists(p):
                path = p
        if not path and tid:
            sub_dir = os.path.join(t_folder, sub)
            if os.path.exists(sub_dir):
                for f in os.listdir(sub_dir):
                    if f.lower().endswith(exts):
                        path = os.path.join(sub_dir, f)
                        break
        docs.append({
            "key": key, "label": label, "path": path,
            "exists": bool(path),
            "filename": os.path.basename(path) if path else "",
        })
    return docs


# =================================================================================
# 16.2 — CLASS: ReportsTab
# =================================================================================
class ReportsTab(ft.Column):

    # -----------------------------------------------------------------------------
    # 16.2.1 — __init__
    # -----------------------------------------------------------------------------
    def __init__(self, page, db, current_user):
        super().__init__()
        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}

        self.expand = True
        self.spacing = 0

        self._gst_rate = 0.0
        self._tcs_rate = 0.0
        self._load_tax_rates()

        self._hub_stat_labels = {}
        self._hub_badge_labels = {}
        self._hub_last_refresh = None

        self.tabs = None

        self._single_search = None
        self._single_photo_circle = None
        self._single_name = None
        self._single_id = None
        self._single_status_badge = None
        self._single_info = {}
        self._single_docs_grid = None
        self._single_invoice_label = None
        self._single_kpi = {}
        self._single_payment_table = None
        self._single_status = None
        self._single_map = {}

        self._photo_search = None
        self._photo_display = None
        self._photo_map = {}

        self._std_type = None
        self._std_from = None
        self._std_to = None
        self._std_output = None

        try:
            self._build()
        except Exception as e:
            print(f"[REPORTS] build failed: {e}")
            traceback.print_exc()
            self.controls = [self._build_error_ui(e)]

    # -----------------------------------------------------------------------------
    # 16.2.1b — _build_error_ui
    # -----------------------------------------------------------------------------
    def _build_error_ui(self, exc):
        return ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.WARNING_AMBER, size=48,
                        color=ft.Colors.ORANGE_600),
                ft.Text("Reports failed to load", size=18,
                        weight=ft.FontWeight.BOLD),
                ft.Text(str(exc), size=12, color=ft.Colors.RED_500,
                        selectable=True),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=10),
            padding=40, alignment=ft.Alignment.CENTER, expand=True)

    # -----------------------------------------------------------------------------
    # 16.2.2 — _load_tax_rates
    # -----------------------------------------------------------------------------
    def _load_tax_rates(self):
        try:
            if SettingsManager is not None:
                tax = SettingsManager(self.db).get_tax_settings()
                self._gst_rate = float(tax.get("gst_percentage", 18) or 0)
                self._tcs_rate = float(tax.get("tcs_percentage", 0.1) or 0)
        except Exception as e:
            print(f"[REPORTS] tax rates: {e}")

    # -----------------------------------------------------------------------------
    # 16.2.3 — build
    # -----------------------------------------------------------------------------
    def build(self):
        return self

    # -----------------------------------------------------------------------------
    # 16.2.4 — _build
    # -----------------------------------------------------------------------------
    def _build(self):
        labels = ["🏠 Hub", "🎯 Custom", "🔎 Traveler",
                  "📈 Standard", "📸 Photos"]
        views = [
            self._build_reports_hub_tab(),
            self._build_custom_report_tab(),
            self._build_single_traveler_tab(),
            self._build_standard_reports_tab(),
            self._build_photo_viewer_tab(),
        ]
        # Scrollable tab bar for mobile
        self.tabs = ft.Tabs(
            selected_index=0,
            animation_duration=200,
            length=len(labels),
            expand=True,
            content=ft.Column(
                expand=True, spacing=0,
                controls=[
                    ft.TabBar(
                        tabs=[ft.Tab(label=l) for l in labels],
                        scrollable=True),
                    ft.TabBarView(
                        expand=True,
                        controls=[ft.Container(content=v, expand=True,
                                               padding=0)
                                  for v in views]),
                ]))
        self.controls = [self.tabs]

    # -----------------------------------------------------------------------------
    # 16.2.5 — refresh  (PATCH 16.1.A + 16.1.B preserved)
    # -----------------------------------------------------------------------------
    def refresh(self, e=None):
        try:
            try:
                if hasattr(self.db, "reload"):
                    self.db.reload()
                elif hasattr(self.db, "_load_all"):
                    self.db._load_all()
            except Exception as _re:
                print(f"[ReportsTab.refresh] reload skipped: {_re}")

            self._load_tax_rates()
            self._rebuild_traveler_lists()
            self._refresh_hub_stats()
        except Exception as ex:
            print(f"[REPORTS] refresh: {ex}")
            traceback.print_exc()

    # -----------------------------------------------------------------------------
    # 16.2.5b — _rebuild_traveler_lists  (PATCH 16.1.B)
    # -----------------------------------------------------------------------------
    def _rebuild_traveler_lists(self):
        try:
            travelers = self.db.get_travelers()
            travelers.sort(key=lambda t: (
                f"{t.get('first_name','')} {t.get('last_name','')}".lower()))

            # Single Traveler dropdown
            if self._single_search is not None:
                self._single_map = {}
                opts = [ft.dropdown.Option("", "— Select a traveler —")]
                for t in travelers:
                    name = (f"{t.get('first_name','')} "
                            f"{t.get('last_name','')}").strip() or "Unknown"
                    passport = t.get("passport_no", "") or ""
                    label = f"{name}  ·  {passport}"
                    tid = t.get("id", "")
                    opts.append(ft.dropdown.Option(tid, label))
                    self._single_map[tid] = t
                self._single_search.options = opts
                cur = self._single_search.value
                if cur and cur in self._single_map:
                    try:
                        self._render_single_traveler(self._single_map[cur])
                    except Exception as _e:
                        print(f"[REPORTS] re-render single: {_e}")

            # Photo Viewer dropdown
            if self._photo_search is not None:
                self._photo_map = {}
                opts = [ft.dropdown.Option("", "— Select a traveler —")]
                for t in travelers:
                    name = (f"{t.get('first_name','')} "
                            f"{t.get('last_name','')}").strip() or "Unknown"
                    has = "📸" if _find_photo_path(t) else "📷"
                    label = f"{has}  {name} · {t.get('passport_no','')}"
                    tid = t.get("id", "")
                    opts.append(ft.dropdown.Option(tid, label))
                    self._photo_map[tid] = t
                self._photo_search.options = opts
        except Exception as ex:
            print(f"[REPORTS] _rebuild_traveler_lists: {ex}")

    # =============================================================================
    # 16.2.6 — Reports Hub tab  (MOBILE-RESPONSIVE)
    # =============================================================================
    def _build_reports_hub_tab(self):
        user_name = (self.current_user.get("full_name")
                     or self.current_user.get("username") or "User")

        banner = ft.Container(
            content=ft.Row([
                ft.Text("📊", size=32),
                ft.Column([
                    ft.Text(f"Welcome, {user_name}! 👋", size=15,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE,
                            no_wrap=False, max_lines=2),
                    ft.Text("Your unified reports dashboard",
                            size=10, color=ft.Colors.BLUE_100),
                ], spacing=4, expand=True),
            ], spacing=12),
            padding=ft.Padding.symmetric(horizontal=16, vertical=14),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#1e3a8a", "#2563eb", "#7c3aed"]),
            border_radius=14)

        specs = [
            ("travelers", "👥", "Travelers", "#2563eb"),
            ("batches", "📦", "Batches", "#059669"),
            ("payments", "💰", "Payments", "#7c3aed"),
            ("invoices", "🧾", "Invoices", "#d97706"),
            ("revenue", "💵", "Revenue", "#0891b2"),
        ]
        stat_cols = []
        for key, icon, label, color in specs:
            val = ft.Text("—", size=16, weight=ft.FontWeight.BOLD,
                          color=color)
            self._hub_stat_labels[key] = val
            stat_cols.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(icon, size=14, color=color),
                        val,
                        ft.Text(label, size=9,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.GREY_600),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                       spacing=2),
                    padding=8,
                    col={"xs": 4, "sm": 4, "md": 2}))

        stats_bar = ft.Container(
            content=ft.ResponsiveRow(stat_cols, spacing=4, run_spacing=6),
            bgcolor=ft.Colors.WHITE, border_radius=14,
            padding=ft.Padding.symmetric(horizontal=6, vertical=8),
            border=ft.Border.all(1, ft.Colors.GREY_300))

        def _card(icon, title, desc, color, key, on_click):
            badge = ft.Text("—", size=10, weight=ft.FontWeight.BOLD,
                            color=color)
            self._hub_badge_labels[key] = badge
            return ft.Container(
                content=ft.Column([
                    ft.Container(
                        content=ft.Text(icon, size=22),
                        width=48, height=48,
                        bgcolor=ft.Colors.with_opacity(0.12, color),
                        border_radius=24,
                        alignment=ft.Alignment.CENTER),
                    ft.Text(title, size=12, weight=ft.FontWeight.BOLD),
                    ft.Text(desc, size=10, color=ft.Colors.GREY_600,
                            max_lines=3),
                    ft.Container(height=4),
                    ft.Container(content=badge,
                                 padding=ft.Padding.symmetric(
                                     horizontal=8, vertical=4),
                                 bgcolor=ft.Colors.with_opacity(
                                     0.08, color),
                                 border_radius=10),
                    ft.Container(height=4),
                    ft.Button(content=ft.Text("Open  →", size=11),
                              on_click=on_click, bgcolor=color,
                              color=ft.Colors.WHITE, height=36,
                              expand=True),
                ], spacing=6),
                padding=14, bgcolor=ft.Colors.WHITE,
                border=ft.Border.all(1, ft.Colors.GREY_200),
                border_radius=14, col={"xs": 12, "sm": 6, "md": 6})

        cards = ft.ResponsiveRow([
            _card("🎯", "Custom Report Generator",
                  "39+ traveler fields, batch data, dynamic payments.",
                  "#2563eb", "custom", lambda e: self._goto_tab(1)),
            _card("🔎", "Single Traveler Report",
                  "Full traveler profile with photo, payments, docs.",
                  "#7c3aed", "single", lambda e: self._goto_tab(2)),
            _card("📈", "Standard Reports",
                  "Financial · Travelers · Batches · Payments.",
                  "#059669", "standard", lambda e: self._goto_tab(3)),
            _card("📸", "Photo Viewer",
                  "Browse traveler photos and documents.",
                  "#dc2626", "photo", lambda e: self._goto_tab(4)),
        ], spacing=10, run_spacing=10)

        self._hub_last_refresh = ft.Text("", size=9,
                                         color=ft.Colors.GREY_500)

        content = ft.Column([
            banner,
            ft.Container(height=8),
            stats_bar,
            ft.Container(height=10),
            ft.Text("📊  Report Categories", size=13,
                    weight=ft.FontWeight.BOLD),
            cards,
            ft.Container(height=10),
            ft.Row([
                self._hub_last_refresh,
                ft.Container(expand=True),
                ft.Button(content=ft.Text("🔄 Refresh", size=11),
                          on_click=self._refresh_hub_stats,
                          bgcolor="#1e40af", color=ft.Colors.WHITE,
                          height=36),
            ]),
        ], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)

        container = ft.Container(content=content, padding=14, expand=True)
        try:
            self.page_ref.run_task(self._refresh_hub_async)
        except Exception:
            pass
        return container

    async def _refresh_hub_async(self):
        import asyncio
        await asyncio.sleep(0.1)
        self._refresh_hub_stats()

    # -----------------------------------------------------------------------------
    # 16.2.7 — _refresh_hub_stats  (PATCH 16.1.A preserved)
    # -----------------------------------------------------------------------------
    def _refresh_hub_stats(self, e=None):
        try:
            try:
                if hasattr(self.db, "reload"):
                    self.db.reload()
                elif hasattr(self.db, "_load_all"):
                    self.db._load_all()
            except Exception as _re:
                print(f"[REPORTS] hub reload skipped: {_re}")

            travelers = self.db.get_travelers()
            batches = self.db.get_batches()
            payments = self.db.get_payments()
            invoices = self.db.get_invoices()

            total_rev = 0.0
            for inv in invoices:
                try:
                    total_rev += float(inv.get("total_amount", 0) or 0)
                except (TypeError, ValueError):
                    pass

            n_photos = sum(1 for t in travelers if _find_photo_path(t))

            if "travelers" in self._hub_stat_labels:
                self._hub_stat_labels["travelers"].value = str(len(travelers))
            if "batches" in self._hub_stat_labels:
                self._hub_stat_labels["batches"].value = str(len(batches))
            if "payments" in self._hub_stat_labels:
                self._hub_stat_labels["payments"].value = str(len(payments))
            if "invoices" in self._hub_stat_labels:
                self._hub_stat_labels["invoices"].value = str(len(invoices))
            if "revenue" in self._hub_stat_labels:
                if total_rev >= 10000000:
                    r = f"₹{total_rev/10000000:.1f}Cr"
                elif total_rev >= 100000:
                    r = f"₹{total_rev/100000:.1f}L"
                elif total_rev >= 1000:
                    r = f"₹{total_rev/1000:.1f}K"
                else:
                    r = f"₹{_fmt_inr_(total_rev)}"
                self._hub_stat_labels["revenue"].value = r

            if "custom" in self._hub_badge_labels:
                self._hub_badge_labels["custom"].value = "📊 39 fields"
            if "single" in self._hub_badge_labels:
                self._hub_badge_labels["single"].value = (
                    f"👥 {len(travelers)}")
            if "standard" in self._hub_badge_labels:
                self._hub_badge_labels["standard"].value = "📋 4 types"
            if "photo" in self._hub_badge_labels:
                self._hub_badge_labels["photo"].value = f"📷 {n_photos}"
            if self._hub_last_refresh:
                self._hub_last_refresh.value = (
                    f"🔄 {datetime.now().strftime('%H:%M:%S')}")
            self._safe_update()
        except Exception as e:
            print(f"[REPORTS] hub stats: {e}")

    # -----------------------------------------------------------------------------
    # 16.2.8 — _goto_tab
    # -----------------------------------------------------------------------------
    def _goto_tab(self, idx):
        try:
            if self.tabs:
                self.tabs.selected_index = idx
                self.page_ref.update()
        except Exception as e:
            print(f"[REPORTS] goto_tab: {e}")

    # =============================================================================
    # 16.2.9 — Custom Reports launcher tab
    # =============================================================================
    def _build_custom_report_tab(self):
        hero = ft.Container(
            content=ft.Column([
                ft.Text("🎯", size=36),
                ft.Text("Custom Report Generator", size=17,
                        weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.Text(
                    "39+ fields · dynamic payment slots · Excel, CSV & "
                    "PDF exports.",
                    size=11, color=ft.Colors.BLUE_100,
                    text_align=ft.TextAlign.CENTER),
                ft.Container(height=8),
                ft.Button(
                    content=ft.Text("🚀  Launch Generator", size=13,
                                    weight=ft.FontWeight.BOLD),
                    on_click=self._launch_custom_report,
                    height=48, bgcolor=ft.Colors.WHITE, color="#1e40af"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=10),
            padding=24,
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#1e40af", "#2563eb"]),
            border_radius=16)

        return ft.Container(
            content=ft.Column([hero], scroll=ft.ScrollMode.AUTO,
                              expand=True),
            padding=14, expand=True)

    def _launch_custom_report(self, e=None):
        try:
            from core.custom_report_dialog import CustomReportDialog
            dlg = CustomReportDialog(self.page_ref, self.db,
                                     self.current_user)
            dlg.show()
        except Exception as ex:
            traceback.print_exc()
            self._snack(f"❌ {ex}", ft.Colors.RED_500)

    # =============================================================================
    # 16.2.10 — Single Traveler tab  (MOBILE-RESPONSIVE)
    # =============================================================================
    def _build_single_traveler_tab(self):
        travelers = self.db.get_travelers()
        travelers.sort(key=lambda t: (
            f"{t.get('first_name','')} {t.get('last_name','')}".lower()))

        self._single_map = {}
        opts = [ft.dropdown.Option("", "— Select a traveler —")]
        for t in travelers:
            name = (f"{t.get('first_name','')} "
                    f"{t.get('last_name','')}").strip() or "Unknown"
            passport = t.get("passport_no", "") or ""
            label = f"{name}  ·  {passport}"
            tid = t.get("id", "")
            opts.append(ft.dropdown.Option(tid, label))
            self._single_map[tid] = t

        self._single_search = ft.Dropdown(
            label="Search traveler",
            options=opts, value="",
            enable_filter=True, enable_search=True, editable=True)
        self._single_search.on_change = self._on_single_changed
        self._single_search.on_select = self._on_single_changed

        self._single_photo_circle = ft.Container(
            content=ft.Text("📷", size=36, color=ft.Colors.GREY_400),
            width=130, height=130,
            bgcolor="#f8fafc", border_radius=65,
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            border=ft.Border.all(3, "#7c3aed"))

        self._single_name = ft.Text("No traveler selected", size=13,
                                    weight=ft.FontWeight.BOLD,
                                    text_align=ft.TextAlign.CENTER)
        self._single_id = ft.Text("—", size=10,
                                  color=ft.Colors.GREY_600,
                                  text_align=ft.TextAlign.CENTER)
        self._single_status_badge = ft.Container(
            content=ft.Text("—", size=10, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREY_700),
            padding=ft.Padding.symmetric(horizontal=12, vertical=4),
            bgcolor="#f3f4f6", border_radius=13)

        self._single_info = {}
        info_rows = []
        for key, lbl in [("mobile", "📱 Mobile"),
                         ("passport", "🛂 Passport"),
                         ("file_ref", "📄 File Ref"),
                         ("batch", "📦 Batch"),
                         ("dob", "🎂 DOB")]:
            val = ft.Text("—", size=10, weight=ft.FontWeight.BOLD,
                          text_align=ft.TextAlign.RIGHT)
            self._single_info[key] = val
            info_rows.append(ft.Row([
                ft.Text(lbl, width=80, size=10,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.GREY_600),
                ft.Container(expand=True), val]))

        self._single_docs_grid = ft.GridView(
            expand=True, runs_count=2, spacing=6, run_spacing=6,
            child_aspect_ratio=1.4, height=150)

        left_card = ft.Container(
            content=ft.Column([
                ft.Container(content=self._single_photo_circle,
                             alignment=ft.Alignment.CENTER),
                self._single_name,
                self._single_id,
                ft.Container(content=self._single_status_badge,
                             alignment=ft.Alignment.CENTER),
                ft.Divider(height=1),
                *info_rows,
                ft.Divider(height=1),
                ft.Text("📎 Documents", size=10,
                        weight=ft.FontWeight.BOLD, color="#6d28d9"),
                self._single_docs_grid,
            ], spacing=8, scroll=ft.ScrollMode.AUTO),
            padding=14, bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1.5, ft.Colors.GREY_300),
            border_radius=14,
            # Desktop fixed width, mobile full-width
            col={"xs": 12, "sm": 12, "md": 4})

        def _kpi(key, icon, title, color):
            val = ft.Text("—", size=14, weight=ft.FontWeight.BOLD,
                          color=color)
            self._single_kpi[key] = val
            return ft.Container(
                content=ft.Column([
                    ft.Row([ft.Text(icon, size=12, color=color),
                            ft.Text(title.upper(), size=9,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.GREY_600,
                                    no_wrap=False, max_lines=2)],
                           spacing=4),
                    val,
                ], spacing=3),
                padding=10, bgcolor=ft.Colors.WHITE,
                border=ft.Border.only(
                    left=ft.BorderSide(4, color),
                    top=ft.BorderSide(1, ft.Colors.GREY_200),
                    right=ft.BorderSide(1, ft.Colors.GREY_200),
                    bottom=ft.BorderSide(1, ft.Colors.GREY_200)),
                border_radius=10,
                col={"xs": 6, "sm": 6, "md": 3})

        kpi_row = ft.ResponsiveRow([
            _kpi("invoiced", "📄", "Invoiced", "#1e40af"),
            _kpi("received", "💰", "Paid", "#059669"),
            _kpi("discount", "🎁", "Discount", "#c2185b"),
            _kpi("outstanding", "⚠️", "Outstanding", "#dc2626"),
        ], spacing=8, run_spacing=8)

        self._single_invoice_label = ft.Text(
            "No invoice recorded for this traveler yet.",
            size=11, selectable=True, font_family="Consolas")

        inv_card = ft.Container(
            content=ft.Column([
                ft.Text("🧾  Invoice Breakdown", size=12,
                        weight=ft.FontWeight.BOLD, color="#1e40af"),
                ft.Container(content=self._single_invoice_label,
                             padding=10, bgcolor="#f8fafc",
                             border=ft.Border.all(1, ft.Colors.GREY_200),
                             border_radius=10),
            ], spacing=8),
            padding=12, bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1.5, ft.Colors.GREY_300),
            border_radius=14)

        self._single_payment_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Date", size=10)),
                ft.DataColumn(ft.Text("Method", size=10)),
                ft.DataColumn(ft.Text("Receipt", size=10)),
                ft.DataColumn(ft.Text("Amount", size=10)),
            ],
            rows=[], heading_row_color="#f1f5f9", column_spacing=10)

        pay_card = ft.Container(
            content=ft.Column([
                ft.Text("💵  Payment Received", size=12,
                        weight=ft.FontWeight.BOLD, color="#059669"),
                ft.Container(
                    content=ft.Row([self._single_payment_table],
                                   scroll=ft.ScrollMode.ADAPTIVE),
                    height=170, padding=4, bgcolor=ft.Colors.WHITE,
                    border=ft.Border.all(1, ft.Colors.GREY_200),
                    border_radius=10),
            ], spacing=8),
            padding=12, bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1.5, ft.Colors.GREY_300),
            border_radius=14)

        self._single_status = ft.Text(
            "🔍  No traveler selected.", size=11,
            color=ft.Colors.GREY_600, italic=True)

        right_col = ft.Container(
            content=ft.Column([kpi_row, inv_card, pay_card],
                              spacing=12),
            col={"xs": 12, "sm": 12, "md": 8})

        body = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Text("🔎", size=26),
                        ft.Column([
                            ft.Text("Single Traveler", size=15,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE),
                            ft.Text("Search by name, passport, file ref",
                                    size=9, color=ft.Colors.BLUE_100),
                        ], spacing=2, expand=True),
                    ], spacing=10),
                    padding=ft.Padding.symmetric(horizontal=16,
                                                 vertical=12),
                    gradient=ft.LinearGradient(
                        begin=ft.Alignment.CENTER_LEFT,
                        end=ft.Alignment.CENTER_RIGHT,
                        colors=["#6d28d9", "#7c3aed", "#a855f7"]),
                    border_radius=14),
                ft.Container(height=10),
                self._single_search,
                ft.Container(height=4),
                self._single_status,
                ft.Container(height=6),
                ft.ResponsiveRow(
                    controls=[left_card, right_col],
                    spacing=12, run_spacing=12),
            ], spacing=6, scroll=ft.ScrollMode.AUTO, expand=True),
            padding=14, expand=True, bgcolor="#f3f4f6")

        return body

    # -----------------------------------------------------------------------------
    # 16.2.11 — _on_single_changed
    # -----------------------------------------------------------------------------
    def _on_single_changed(self, e=None):
        try:
            raw = self._single_search.value
            if not raw:
                return
            t = self._single_map.get(raw)
            if t is None:
                self._rebuild_traveler_lists()
                t = self._single_map.get(raw)
                if t is None:
                    return
            self._render_single_traveler(t)
            self._safe_update()
        except Exception as ex:
            print(f"[REPORTS] single changed: {ex}")
            traceback.print_exc()

    # -----------------------------------------------------------------------------
    # 16.2.12 — _render_single_traveler
    # -----------------------------------------------------------------------------
    def _render_single_traveler(self, t):
        photo_path = _find_photo_path(t)
        uri = _photo_data_uri(photo_path) if photo_path else None
        if uri:
            self._single_photo_circle.content = ft.Image(
                src=uri, width=130, height=130, fit=ft.BoxFit.COVER)
        else:
            self._single_photo_circle.content = ft.Text(
                "📷", size=36, color=ft.Colors.GREY_400)

        name = (f"{t.get('first_name','')} "
                f"{t.get('last_name','')}").strip() or "Unknown"
        self._single_name.value = name
        self._single_id.value = str(t.get("id", "—") or "—")
        status_val = str(t.get("status", "—") or "—")
        sl = status_val.lower()
        if sl == "active":
            bg, fg = "#dcfce7", "#166534"
        elif sl == "completed":
            bg, fg = "#dbeafe", "#1e40af"
        else:
            bg, fg = "#fef3c7", "#92400e"
        self._single_status_badge.content = ft.Text(
            status_val.upper(), size=10, weight=ft.FontWeight.BOLD,
            color=fg)
        self._single_status_badge.bgcolor = bg

        batch_id = t.get("batch_id")
        batch = self.db.get_batch_by_id(batch_id) if batch_id else None
        batch_name = batch.get("batch_name", "—") if batch else "—"
        self._single_info["mobile"].value = str(t.get("mobile", "—") or "—")
        self._single_info["passport"].value = str(
            t.get("passport_no", "—") or "—")
        self._single_info["file_ref"].value = str(
            t.get("file_reference", "—") or "—")
        self._single_info["batch"].value = batch_name[:18]
        self._single_info["dob"].value = (
            _fmt_date_ddmmyyyy(str(t.get("dob", "") or "")) or "—")

        tid = t.get("id", "")
        payments = self.db.get_payments(tid) if tid else []
        invoices = self.db.get_invoices(tid) if tid else []

        def _f(v):
            try:
                return float(v or 0)
            except (TypeError, ValueError):
                return 0.0

        total_paid = sum(_f(p.get("amount", 0)) for p in payments)
        inv_base = 0.0
        inv_disc = 0.0
        inv_taxable = 0.0
        inv_gst = 0.0
        inv_tcs = 0.0
        inv_total = 0.0
        has_paid = False
        for inv in invoices:
            inv_base += _f(inv.get("amount", 0))
            inv_disc += _f(inv.get("discount_amount", 0))
            inv_taxable += _f(inv.get("taxable_value", 0))
            inv_gst += _f(inv.get("gst_amount", 0))
            inv_tcs += _f(inv.get("tcs_amount", 0))
            inv_total += _f(inv.get("total_amount",
                                    inv.get("rounded_total", 0)))
            if str(inv.get("status", "")).lower() == "paid":
                has_paid = True

        batch_price = _f(batch.get("price", 0)) if batch else 0.0
        package = inv_total if inv_total > 0 else batch_price
        pending = 0.0 if has_paid else max(0.0, package - total_paid)

        if invoices:
            lines = [
                f"📦 Base     : ₹{_fmt_inr_(inv_base):>15}",
                f"🎁 Discount : -₹{_fmt_inr_(inv_disc):>14}",
                f"📊 Taxable  : ₹{_fmt_inr_(inv_taxable):>15}",
                f"🧾 GST      : +₹{_fmt_inr_(inv_gst):>14}",
                f"💰 TCS      : +₹{_fmt_inr_(inv_tcs):>14}",
                "─" * 44,
                f"⭐ TOTAL    : ₹{_fmt_inr_(inv_total):>15}",
                "",
                f"Invoices: {len(invoices)}  ·  Payments: {len(payments)}",
            ]
            self._single_invoice_label.value = "\n".join(lines)
        else:
            self._single_invoice_label.value = "ℹ️  No invoice recorded yet."

        self._single_payment_table.rows.clear()
        for p in payments:
            dt = _fmt_date_ddmmyyyy(str(p.get("payment_date", "")))
            amt = _f(p.get("amount", 0))
            self._single_payment_table.rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(dt, size=10)),
                ft.DataCell(ft.Text(
                    str(p.get("payment_method", "—") or "—")[:12],
                    size=10)),
                ft.DataCell(ft.Text(str(p.get("id", "—"))[:14], size=10)),
                ft.DataCell(ft.Text(f"₹{_fmt_inr_(amt)}", size=10,
                                    weight=ft.FontWeight.BOLD,
                                    color="#059669",
                                    text_align=ft.TextAlign.RIGHT)),
            ]))

        self._single_kpi["invoiced"].value = f"₹{_fmt_inr_(package)}"
        self._single_kpi["received"].value = f"₹{_fmt_inr_(total_paid)}"
        self._single_kpi["discount"].value = f"₹{_fmt_inr_(inv_disc)}"
        if pending <= 0:
            self._single_kpi["outstanding"].value = "₹0 ✅"
            self._single_kpi["outstanding"].color = "#059669"
        else:
            self._single_kpi["outstanding"].value = f"₹{_fmt_inr_(pending)}"
            self._single_kpi["outstanding"].color = "#dc2626"

        if has_paid:
            self._single_status.value = (
                f"✅ {name} — Invoice PAID. Outstanding ₹0.00.")
            self._single_status.color = "#059669"
        else:
            self._single_status.value = f"✅ {name}"
            self._single_status.color = "#059669"

        docs = _collect_traveler_documents(t)
        self._single_docs_grid.controls.clear()
        for d in docs:
            thumb = ft.Text("✕", size=16, color="#d1d5db")
            if d["exists"] and d["path"].lower().endswith(
                    (".jpg", ".jpeg", ".png", ".bmp", ".gif")):
                uri = _photo_data_uri(d["path"])
                thumb = ft.Image(src=uri or "", width=50, height=34,
                                 fit=ft.BoxFit.COVER, border_radius=4)
            elif d["exists"]:
                thumb = ft.Text("📄", size=18, color="#dc2626")
            self._single_docs_grid.controls.append(ft.Container(
                content=ft.Column([
                    thumb,
                    ft.Text(d["label"], size=8,
                            weight=ft.FontWeight.BOLD,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text("●" if d["exists"] else "○", size=7,
                            color="#059669" if d["exists"] else "#dc2626"),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=2),
                padding=5, bgcolor="#f8fafc",
                border=ft.Border.all(1, ft.Colors.GREY_200),
                border_radius=8))

    # =============================================================================
    # 16.2.13 — Standard Reports tab  (MOBILE-RESPONSIVE)
    # =============================================================================
    def _build_standard_reports_tab(self):
        self._std_type = ft.Dropdown(
            label="Report Type",
            options=[ft.dropdown.Option(x) for x in
                     ["Financial Summary", "Traveler Statistics",
                      "Batch Utilization", "Payment Analysis"]],
            value="Financial Summary")

        self._std_from = ft.TextField(
            label="From (dd/mm/yyyy)",
            value=(datetime.now() - timedelta(days=30)
                   ).strftime("%d/%m/%Y"))
        self._std_to = ft.TextField(
            label="To (dd/mm/yyyy)",
            value=datetime.now().strftime("%d/%m/%Y"))

        self._std_output = ft.TextField(
            multiline=True, min_lines=15, read_only=True,
            text_style=ft.TextStyle(font_family="Consolas", size=11))

        def _quick(days):
            def _h(e):
                self._std_from.value = (
                    datetime.now() - timedelta(days=days)
                ).strftime("%d/%m/%Y")
                self._std_to.value = datetime.now().strftime("%d/%m/%Y")
                self._generate_standard(None)
            return _h

        def _qbtn(label, days):
            return ft.Button(
                content=ft.Text(label, size=10),
                on_click=_quick(days), height=36,
                bgcolor="#0ea5e9", color=ft.Colors.WHITE)

        return ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Text("📈", size=22),
                        ft.Column([
                            ft.Text("Standard Reports", size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE),
                            ft.Text("4 ready-to-use reports",
                                    size=9, color=ft.Colors.BLUE_100),
                        ], spacing=0, expand=True),
                    ], spacing=10),
                    padding=ft.Padding.symmetric(horizontal=16,
                                                 vertical=12),
                    gradient=ft.LinearGradient(
                        begin=ft.Alignment.CENTER_LEFT,
                        end=ft.Alignment.CENTER_RIGHT,
                        colors=["#065f46", "#059669"]),
                    border_radius=14),
                ft.Container(height=12),
                ft.ResponsiveRow(
                    controls=[
                        ft.Container(content=self._std_type,
                                     col={"xs": 12, "sm": 6, "md": 3}),
                        ft.Container(content=self._std_from,
                                     col={"xs": 6, "sm": 6, "md": 2}),
                        ft.Container(content=self._std_to,
                                     col={"xs": 6, "sm": 6, "md": 2}),
                    ], spacing=8, run_spacing=8),
                ft.Container(height=8),
                ft.Row([
                    _qbtn("Today", 0),
                    _qbtn("Week", 7),
                    _qbtn("Month", 30),
                    _qbtn("3M", 90),
                    ft.Button(content=ft.Text("🔄 Generate", size=11),
                              on_click=self._generate_standard,
                              bgcolor="#059669",
                              color=ft.Colors.WHITE, height=36),
                ], spacing=6, wrap=True),
                ft.Divider(height=1),
                self._std_output,
            ], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True),
            padding=14, expand=True)

    # -----------------------------------------------------------------------------
    # 16.2.13.0 — _generate_standard  (PATCH 16.1.C preserved)
    # -----------------------------------------------------------------------------
    def _generate_standard(self, e=None):
        try:
            try:
                if hasattr(self.db, "reload"):
                    self.db.reload()
                elif hasattr(self.db, "_load_all"):
                    self.db._load_all()
            except Exception as _re:
                print(f"[REPORTS] std reload skipped: {_re}")

            sd = self._std_from.value.strip()
            ed = self._std_to.value.strip()
            rt = self._std_type.value
            if rt == "Financial Summary":
                txt = self._report_financial(sd, ed)
            elif rt == "Traveler Statistics":
                txt = self._report_travelers(sd, ed)
            elif rt == "Batch Utilization":
                txt = self._report_batches(sd, ed)
            else:
                txt = self._report_payments(sd, ed)
            self._std_output.value = txt
            self._safe_update()
        except Exception as ex:
            traceback.print_exc()
            self._std_output.value = f"❌ {ex}"
            self._safe_update()

    def _report_financial(self, sd, ed):
        from_dt = _parse_ui_date(sd)
        to_dt = _parse_ui_date(ed)
        payments = self.db.get_payments()
        filtered = [p for p in payments
                    if self._in_range(p.get("payment_date"),
                                      from_dt, to_dt)]
        total = sum(float(p.get("amount", 0) or 0) for p in filtered)
        by_method = {}
        for p in filtered:
            m = p.get("payment_method", "Other")
            by_method[m] = by_method.get(m, 0) + float(
                p.get("amount", 0) or 0)
        lines = [f"FINANCIAL SUMMARY — {sd} to {ed}", "=" * 60, ""]
        lines.append(f"Total Collections : ₹{_fmt_inr_(total)}")
        lines.append(f"Number of Payments: {len(filtered)}")
        avg = total / len(filtered) if filtered else 0
        lines.append(f"Average Payment   : ₹{_fmt_inr_(avg)}")
        lines.append("")
        lines.append("Payment by Method:")
        for m, amt in by_method.items():
            lines.append(f"  • {m}: ₹{_fmt_inr_(amt)}")
        return "\n".join(lines)

    def _report_travelers(self, sd, ed):
        from_dt = _parse_ui_date(sd)
        to_dt = _parse_ui_date(ed)
        travelers = self.db.get_travelers()
        filtered = [t for t in travelers
                    if self._in_range(t.get("registration_date"),
                                      from_dt, to_dt)]
        sc = {}
        for t in filtered:
            s = t.get("status", "Unknown")
            sc[s] = sc.get(s, 0) + 1
        lines = [f"TRAVELER STATISTICS — {sd} to {ed}", "=" * 60, ""]
        lines.append(f"Total Travelers: {len(filtered)}")
        lines.append("")
        lines.append("Status Distribution:")
        for s, c in sc.items():
            p = (c / len(filtered) * 100) if filtered else 0
            lines.append(f"  • {s}: {c} ({p:.1f}%)")
        return "\n".join(lines)

    def _report_batches(self, sd, ed):
        batches = self.db.get_batches()
        travelers = self.db.get_travelers()
        counts = {}
        for t in travelers:
            bid = t.get("batch_id")
            if bid:
                counts[bid] = counts.get(bid, 0) + 1
        lines = [f"BATCH UTILIZATION — {sd} to {ed}", "=" * 60, ""]
        ts = tb = 0
        tr = 0.0
        for b in batches:
            bid = b.get("id")
            booked = counts.get(bid, 0)
            total = int(b.get("total_seats", 0) or 0)
            price = float(b.get("price", 0) or 0)
            rev = booked * price
            ts += total
            tb += booked
            tr += rev
            pct = (booked / total * 100) if total > 0 else 0
            lines.append(f"📌 {b.get('batch_name','Unknown')}: "
                         f"{booked}/{total} ({pct:.1f}%) — ₹{_fmt_inr_(rev)}")
        lines.append("")
        lines.append("=" * 60)
        lines.append(f"Total Seats  : {ts}")
        lines.append(f"Total Booked : {tb}")
        if ts > 0:
            lines.append(f"Occupancy    : {tb/ts*100:.1f}%")
        lines.append(f"Total Revenue: ₹{_fmt_inr_(tr)}")
        return "\n".join(lines)

    def _report_payments(self, sd, ed):
        from_dt = _parse_ui_date(sd)
        to_dt = _parse_ui_date(ed)
        payments = self.db.get_payments()
        filtered = [p for p in payments
                    if self._in_range(p.get("payment_date"),
                                      from_dt, to_dt)]
        daily = {}
        methods = {}
        for p in filtered:
            d = str(p.get("payment_date", ""))[:10]
            daily[d] = daily.get(d, 0) + float(p.get("amount", 0) or 0)
            m = p.get("payment_method", "Other")
            methods[m] = methods.get(m, 0) + float(
                p.get("amount", 0) or 0)
        lines = [f"PAYMENT ANALYSIS — {sd} to {ed}", "=" * 60, ""]
        lines.append("Daily Collections:")
        for d in sorted(daily):
            lines.append(f"  • {_fmt_date_ddmmyyyy(d)}: "
                         f"₹{_fmt_inr_(daily[d])}")
        lines.append("")
        lines.append("By Method:")
        for m, amt in methods.items():
            lines.append(f"  • {m}: ₹{_fmt_inr_(amt)}")
        return "\n".join(lines)

    def _in_range(self, value, d_from, d_to):
        if value is None:
            return True
        dt = _parse_ui_date(str(value))
        if dt is None:
            return True
        if d_from is not None and dt < d_from:
            return False
        if d_to is not None and dt > d_to:
            return False
        return True

    # =============================================================================
    # 16.2.14 — Photo Viewer tab  (MOBILE-RESPONSIVE)
    # =============================================================================
    def _build_photo_viewer_tab(self):
        travelers = self.db.get_travelers()
        travelers.sort(key=lambda t: (
            f"{t.get('first_name','')} {t.get('last_name','')}".lower()))

        self._photo_map = {}
        opts = [ft.dropdown.Option("", "— Select a traveler —")]
        for t in travelers:
            name = (f"{t.get('first_name','')} "
                    f"{t.get('last_name','')}").strip() or "Unknown"
            has = "📸" if _find_photo_path(t) else "📷"
            label = f"{has}  {name} · {t.get('passport_no','')}"
            tid = t.get("id", "")
            opts.append(ft.dropdown.Option(tid, label))
            self._photo_map[tid] = t

        self._photo_search = ft.Dropdown(
            label="Search traveler", options=opts, value="",
            enable_filter=True, enable_search=True, editable=True)
        self._photo_search.on_change = self._on_photo_change
        self._photo_search.on_select = self._on_photo_change

        self._photo_display = ft.Container(
            content=ft.Column([
                ft.Text("📷", size=60, color=ft.Colors.GREY_400),
                ft.Text("Select a traveler to view photo", size=12,
                        color=ft.Colors.GREY_500),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=8),
            alignment=ft.Alignment.CENTER, bgcolor="#f9fafb",
            border_radius=12, padding=20, height=420, expand=True)

        return ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Text("📸", size=22),
                        ft.Text("Photo Viewer", size=14,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE),
                    ], spacing=10),
                    padding=ft.Padding.symmetric(horizontal=14,
                                                 vertical=10),
                    gradient=ft.LinearGradient(
                        begin=ft.Alignment.CENTER_LEFT,
                        end=ft.Alignment.CENTER_RIGHT,
                        colors=["#dc2626", "#f43f5e"]),
                    border_radius=12),
                ft.Container(height=10),
                self._photo_search,
                ft.Divider(height=1),
                self._photo_display,
            ], spacing=10, expand=True),
            padding=14, expand=True)

    def _on_photo_change(self, e=None):
        try:
            raw = self._photo_search.value
            if not raw:
                return
            t = self._photo_map.get(raw)
            if not t:
                self._rebuild_traveler_lists()
                t = self._photo_map.get(raw)
                if not t:
                    return
            name = (f"{t.get('first_name','')} "
                    f"{t.get('last_name','')}").strip() or "Unknown"
            pp = _find_photo_path(t)
            uri = _photo_data_uri(pp) if pp else None
            if uri:
                self._photo_display.content = ft.Column([
                    ft.Image(src=uri, height=340, fit=ft.BoxFit.CONTAIN),
                    ft.Text(name, size=14, weight=ft.FontWeight.BOLD),
                    ft.Text(f"ID: {t.get('id','')} · "
                            f"Passport: {t.get('passport_no','')}",
                            size=10, color=ft.Colors.GREY_600),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=8, scroll=ft.ScrollMode.AUTO)
            else:
                self._photo_display.content = ft.Column([
                    ft.Text("📷", size=60, color=ft.Colors.GREY_400),
                    ft.Text(f"No photo for {name}", size=12,
                            color=ft.Colors.GREY_500),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=10)
            self._safe_update()
        except Exception as ex:
            print(f"[REPORTS] photo change: {ex}")

    # =============================================================================
    # 16.2.15 — Helpers
    # =============================================================================
    def _safe_update(self):
        try:
            self.update()
        except Exception:
            pass

    # -----------------------------------------------------------------------------
    # 16.2.15b — _snack  (PATCH 16.1.D preserved)
    # -----------------------------------------------------------------------------
    def _snack(self, msg, color=ft.Colors.GREEN_700):
        try:
            self.page_ref.show_dialog(
                ft.SnackBar(content=ft.Text(msg), bgcolor=color))
            return
        except Exception:
            pass
        try:
            self.page_ref.snack_bar = ft.SnackBar(
                content=ft.Text(msg), bgcolor=color)
            self.page_ref.snack_bar.open = True
            self.page_ref.update()
        except Exception:
            pass


# =================================================================================
# SECTION 16 END — REPORTS TAB (FLET 1.0.0 VERSION)
# =================================================================================