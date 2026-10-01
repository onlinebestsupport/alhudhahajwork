# =================================================================================
# SECTION 7 (FLET 1.0.0 VERSION) — MAIN WINDOW
# =================================================================================
# UPDATED — 2026-10-01 (v2.2)
#   • Permission-based tab visibility
#   • 🔄 Reload Data button + 💾 Storage Info in settings menu
#   • Auto-refresh every 30s
#   • Dashboard Quick Actions navigate to tabs via _on_navigate()
#   • Al-Hudha logo image in the header (left side)
#   • NEW: "🌐 Front Page" tab (permission: manage_settings)
#          — opens the FrontPageSettingsTab for editing the marketing
#            front page (hero, alert, features, packages, about,
#            contact, social, footer)
# =================================================================================

import flet as ft
import asyncio
import json
from datetime import datetime

# ---- Existing sections (auto-detected) ----
try:
    from core.dashboard_tab import DashboardTab
except ImportError:
    DashboardTab = None

try:
    from core.travelers_tab import TravelersTab
except ImportError:
    TravelersTab = None

try:
    from core.batches_tab import BatchesTab
except ImportError:
    BatchesTab = None

try:
    from core.payments_tab import PaymentsTab
except ImportError:
    PaymentsTab = None

try:
    from core.receipts_tab import ReceiptsTab
except ImportError:
    ReceiptsTab = None

try:
    from core.invoices_tab import InvoicesTab
except ImportError:
    InvoicesTab = None

try:
    from core.reports_tab import ReportsTab
except ImportError:
    ReportsTab = None

try:
    from core.users_tab import UsersTab
except ImportError:
    UsersTab = None

try:
    from core.frontpage_settings_tab import FrontPageSettingsTab
except ImportError as _e:
    print(f"[IMPORT] frontpage_settings_tab failed: {_e}")
    FrontPageSettingsTab = None

# ---- Backup: try both filenames ----
BackupTab = None
try:
    from core.backups_tab import BackupTab
    print("[IMPORT] Loaded BackupTab from core.backups_tab")
except ImportError as e1:
    print(f"[IMPORT] core.backups_tab failed: {e1}")
    try:
        from core.backup_tab import BackupTab
        print("[IMPORT] Loaded BackupTab from core.backup_tab")
    except ImportError as e2:
        print(f"[IMPORT] core.backup_tab failed: {e2}")
        BackupTab = None

try:
    from core.company_settings_dialog import CompanySettingsDialog
except ImportError:
    CompanySettingsDialog = None


# =================================================================================
# PERMISSION HELPERS
# =================================================================================
ROLE_DEFAULT_PERMISSIONS = {
    "super_admin": {
        "view_dashboard", "manage_travelers", "manage_batches",
        "manage_payments", "manage_invoices", "manage_receipts",
        "view_reports", "manage_users", "manage_backups",
        "manage_settings",
    },
    "admin": {
        "view_dashboard", "manage_travelers", "manage_batches",
        "manage_payments", "manage_invoices", "manage_receipts",
        "view_reports", "manage_backups", "manage_settings",
    },
    "staff": {
        "view_dashboard", "manage_travelers", "manage_payments",
        "manage_receipts", "view_reports",
    },
    "viewer": {"view_dashboard", "view_reports"},
}


def _user_has_permission(user, perm_key):
    """Return True if `user` has the given permission key."""
    if not user:
        return False

    role = str(user.get("role", "")).strip().lower()
    if role == "super_admin":
        return True

    raw = user.get("permissions", "")

    if isinstance(raw, (list, set, tuple, frozenset)):
        return perm_key in raw

    s = str(raw).strip() if raw else ""

    if not s:
        defaults = ROLE_DEFAULT_PERMISSIONS.get(
            role, ROLE_DEFAULT_PERMISSIONS["viewer"])
        return perm_key in defaults

    if s.startswith("["):
        try:
            return perm_key in set(json.loads(s))
        except Exception:
            pass

    return perm_key in {x.strip() for x in s.split("|") if x.strip()}


# =================================================================================
# 7.1 — CLASS: MainWindowView
# =================================================================================
class MainWindowView:

    # -----------------------------------------------------------------------------
    # 7.1.1 — __init__
    # -----------------------------------------------------------------------------
    def __init__(self, page: ft.Page, db, current_user, on_logout=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.on_logout = on_logout

        self.dashboard_tab = None
        self.travelers_tab = None
        self.batches_tab = None
        self.payments_tab = None
        self.receipts_tab = None
        self.invoices_tab = None
        self.reports_tab = None
        self.users_tab = None
        self.frontpage_tab = None       # ← NEW
        self.backup_tab = None

        # Registry keyed by plain tab name
        self.tab_instances = {}

        self.tabs_control = None
        self.status_time_label = None
        self._clock_running = False
        self._refresh_running = False
        self.root = None

    # =============================================================================
    # 7.1.2 — Navigation callback
    # =============================================================================
    def _on_navigate(self, tab_name, action=None):
        print(f"[NAV] _on_navigate(tab_name='{tab_name}', action={action})")

        try:
            if self.tabs_control is None:
                self._show_snack("⚠️ Tabs not initialized yet")
                return

            idx = None
            try:
                tab_bar = self.tabs_control.content.controls[0]
                visible_labels = [t.label for t in tab_bar.tabs]
            except Exception:
                visible_labels = []

            for i, lbl in enumerate(visible_labels):
                plain = lbl.split(" ", 1)[-1] if " " in lbl else lbl
                if plain == tab_name:
                    idx = i
                    break

            if idx is None:
                print(f"[NAV] '{tab_name}' not in visible tabs: "
                      f"{visible_labels}")
                self._show_snack(
                    f"⚠️ '{tab_name}' tab is not visible to you")
                return

            self.tabs_control.selected_index = idx
            try:
                self.page.update()
            except Exception:
                pass
            print(f"[NAV] Switched to '{tab_name}' (index {idx})")

            if action == "add":
                tab_inst = self.tab_instances.get(tab_name)
                if tab_inst is None:
                    print(f"[NAV] No instance registered for '{tab_name}'")
                    return

                for method_name in (
                    "open_add_dialog",
                    "open_create_dialog",
                    "add_record",
                    "add_new",
                    "open_manual_invoice",
                ):
                    fn = getattr(tab_inst, method_name, None)
                    if callable(fn):
                        try:
                            fn(None)
                            print(f"[NAV] Called {tab_name}."
                                  f"{method_name}()")
                        except Exception as ex:
                            print(f"[NAV] {tab_name}.{method_name} "
                                  f"failed: {ex}")
                        break
                else:
                    print(f"[NAV] No add-method found on '{tab_name}'")

        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f"[NAV] _on_navigate failed: {ex}")
            self._show_snack(f"⚠️ Navigation error: {ex}")

    # =============================================================================
    # 7.1.3 — build()
    # =============================================================================
    def build(self):
        company_name = "Alhudha Haj Travel"
        try:
            if not self.db.company_settings.empty:
                company_name = str(
                    self.db.company_settings.iloc[0].get(
                        'company_name', '')
                ) or company_name
        except Exception:
            pass

        user_name = self.current_user.get('full_name', 'User')
        user_role = self.current_user.get('role', 'user')

        # =====================================================================
        # HEADER
        # =====================================================================
        def open_settings(e):
            if CompanySettingsDialog is None:
                self._show_snack("⚠️ Settings dialog not available")
                return
            def on_save():
                self.refresh_all()
            dlg = CompanySettingsDialog(
                self.page, self.db, self.current_user,
                on_save_callback=on_save)
            dlg.show()

        def refresh_click(e):
            self.refresh_all()
            self._show_snack("🔄 Refreshed")

        def reload_click(e):
            try:
                if hasattr(self.db, "reload_all"):
                    self.db.reload_all()
                self.refresh_all()
                self._show_snack("✅ Data reloaded from disk")
            except Exception as ex:
                print(f"[RELOAD] failed: {ex}")
                self._show_snack(f"❌ Reload failed: {ex}")

        def storage_info_click(e):
            try:
                if hasattr(self.db, "get_data_folder_info"):
                    info = self.db.get_data_folder_info()
                else:
                    info = {
                        "data_path": str(getattr(self.db, "data_dir", "?")),
                        "note": "get_data_folder_info() not available",
                    }
                lines = [f"{k}: {v}" for k, v in info.items()
                         if k != "files"]
                files = info.get("files", [])
                if files:
                    lines.append("")
                    lines.append("CSV files:")
                    for f in files:
                        lines.append(
                            f"  • {f['name']} — {f['size_bytes']} bytes — "
                            f"{f['modified'][:19]}")

                d = ft.AlertDialog(
                    title=ft.Row([
                        ft.Icon(ft.Icons.FOLDER, color="#0ea5e9"),
                        ft.Text("Storage Diagnostics",
                                weight=ft.FontWeight.BOLD),
                    ], spacing=8),
                    content=ft.Container(
                        content=ft.Text("\n".join(lines),
                                        size=11,
                                        selectable=True,
                                        font_family="Consolas"),
                        width=600,
                        padding=10),
                    actions=[
                        ft.TextButton(
                            content=ft.Text("Close"),
                            on_click=lambda ev: self.page.pop_dialog()),
                    ])
                self.page.show_dialog(d)
            except Exception as ex:
                self._show_snack(f"❌ {ex}")

        def about_click(e):
            self.show_about()

        settings_menu = ft.PopupMenuButton(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.SETTINGS, color=ft.Colors.WHITE),
                    ft.Text("Settings", color=ft.Colors.WHITE, size=12),
                ], spacing=4),
            items=[
                ft.PopupMenuItem(
                    content=ft.Text("🏢 Company"),
                    on_click=open_settings),
                ft.PopupMenuItem(
                    content=ft.Text("💰 Tax"),
                    on_click=open_settings),
                ft.PopupMenuItem(
                    content=ft.Text("🎯 Tours"),
                    on_click=open_settings),
                ft.PopupMenuItem(),
                ft.PopupMenuItem(
                    content=ft.Text("🔄 Reload Data"),
                    on_click=reload_click),
                ft.PopupMenuItem(
                    content=ft.Text("💾 Storage Info"),
                    on_click=storage_info_click),
                ft.PopupMenuItem(),
                ft.PopupMenuItem(
                    content=ft.Text("ℹ️ About"),
                    on_click=about_click),
            ])

        def logout_click(e):
            def confirm(ev):
                self.page.pop_dialog()
                if self.on_logout:
                    self.on_logout()

            d = ft.AlertDialog(
                title=ft.Text("Logout"),
                content=ft.Text("Are you sure you want to log out?"),
                actions=[
                    ft.TextButton(
                        content=ft.Text("No"),
                        on_click=lambda ev: self.page.pop_dialog()),
                    ft.Button(
                        content=ft.Text("Yes, Logout"),
                        on_click=confirm,
                        bgcolor=ft.Colors.RED_600,
                        color=ft.Colors.WHITE),
                ])
            self.page.show_dialog(d)

        # ---- Logo image with emoji fallback ----
        logo_image = ft.Image(
            src="/static/logo.png",
            width=42, height=42,
            fit=ft.BoxFit.CONTAIN,
            error_content=ft.Icon(ft.Icons.TRAVEL_EXPLORE,
                                  color=ft.Colors.WHITE, size=28),
        )

        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=logo_image,
                        width=42, height=42,
                        alignment=ft.Alignment.CENTER,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text("Alhudha Haj Travel System",
                                    size=16, weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE),
                            ft.Text(company_name[:50], size=10,
                                    color=ft.Colors.BLUE_100),
                        ], spacing=0),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        icon_color=ft.Colors.WHITE,
                        tooltip="Refresh (F5)",
                        on_click=refresh_click),
                    ft.IconButton(
                        icon=ft.Icons.CLOUD_DOWNLOAD,
                        icon_color=ft.Colors.WHITE,
                        tooltip="Reload Data from Disk",
                        on_click=reload_click),
                    settings_menu,
                    ft.Container(width=10),
                    ft.Text(f"👤 {user_name} ({user_role})",
                            color=ft.Colors.WHITE, size=12),
                    ft.IconButton(
                        icon=ft.Icons.LOGOUT,
                        icon_color=ft.Colors.WHITE,
                        tooltip="Logout",
                        on_click=logout_click),
                ], spacing=12),
            padding=ft.Padding.symmetric(horizontal=15, vertical=8),
            bgcolor=ft.Colors.BLUE_800)

        # =====================================================================
        # TABS
        # =====================================================================
        def make_placeholder(label, icon):
            return ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Icon(icon, size=64, color=ft.Colors.GREY_400),
                        ft.Text(label, size=22,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.GREY_700),
                        ft.Text("This section will be migrated soon.",
                                size=13, color=ft.Colors.GREY_500),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=10),
                alignment=ft.Alignment.CENTER,
                expand=True,
                padding=50)

        def build_tab_content(cls, plain_label, icon, attr_name):
            """Instantiate a tab class; register in tab_instances."""
            if cls is None:
                print(f"[TAB] {plain_label}: no module (placeholder shown)")
                return make_placeholder(plain_label, icon)
            try:
                print(f"[TAB] {plain_label}: building...")

                if cls is DashboardTab:
                    instance = cls(
                        self.page, self.db, self.current_user,
                        on_navigate=self._on_navigate)
                else:
                    instance = cls(
                        self.page, self.db, self.current_user)

                setattr(self, attr_name, instance)
                self.tab_instances[plain_label] = instance

                content = instance.build()
                print(f"[TAB] {plain_label}: ✅ SUCCESS "
                      f"({type(content).__name__})")
                return content
            except Exception as ex:
                import traceback
                print(f"[TAB] {plain_label}: ❌ FAILED: {ex}")
                traceback.print_exc()
                return make_placeholder(f"{plain_label} (error)", icon)

        # ---- Tab definitions (order matters!) ----
        # ★ NEW: "🌐 Front Page" tab inserted before "💾 Backup"
        TAB_DEFINITIONS = [
            ("📊 Dashboard", ft.Icons.DASHBOARD, "dashboard_tab",
             "view_dashboard",   DashboardTab),
            ("👥 Travelers", ft.Icons.PEOPLE,    "travelers_tab",
             "manage_travelers", TravelersTab),
            ("📦 Batches",   ft.Icons.INVENTORY, "batches_tab",
             "manage_batches",   BatchesTab),
            ("💰 Payments",  ft.Icons.PAYMENTS,  "payments_tab",
             "manage_payments",  PaymentsTab),
            ("🧾 Receipts",  ft.Icons.RECEIPT,   "receipts_tab",
             "manage_receipts",  ReceiptsTab),
            ("📄 Invoices",  ft.Icons.DESCRIPTION, "invoices_tab",
             "manage_invoices",  InvoicesTab),
            ("📈 Reports",   ft.Icons.ANALYTICS, "reports_tab",
             "view_reports",     ReportsTab),
            ("👤 Users",     ft.Icons.PERSON,    "users_tab",
             "manage_users",     UsersTab),
            ("🌐 Front Page", ft.Icons.PUBLIC,   "frontpage_tab",
             "manage_settings",  FrontPageSettingsTab),   # ← NEW
            ("💾 Backup",    ft.Icons.BACKUP,    "backup_tab",
             "manage_backups",   BackupTab),
        ]

        print(f"[MAIN] user='{user_name}' role='{user_role}' "
              f"permissions_raw='{self.current_user.get('permissions', '')}'")

        tab_labels = []
        for label, icon, attr_name, perm_key, cls in TAB_DEFINITIONS:
            if not _user_has_permission(self.current_user, perm_key):
                print(f"[TAB] {label.strip()}: ⛔ denied "
                      f"(missing '{perm_key}' permission)")
                continue
            plain_label = label.split(" ", 1)[-1]
            content = build_tab_content(cls, plain_label, icon, attr_name)
            tab_labels.append((label, icon, content))

        if not tab_labels:
            print("[MAIN] ⚠️ user has no visible tabs — "
                  "showing access-denied screen")
            tab_labels.append((
                "⛔ No Access",
                ft.Icons.LOCK,
                make_placeholder("No Access", ft.Icons.LOCK)))

        print(f"[MAIN] showing {len(tab_labels)} tab(s): "
              f"{[lbl for lbl, _, _ in tab_labels]}")

        tab_bar_items = [ft.Tab(label=label)
                         for label, _, _ in tab_labels]
        tab_views = [view for _, _, view in tab_labels]

        self.tabs_control = ft.Tabs(
            selected_index=0,
            animation_duration=200,
            length=len(tab_labels),
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(tabs=tab_bar_items),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            ft.Container(content=v, expand=True, padding=0)
                            for v in tab_views
                        ]),
                ]))

        # =====================================================================
        # STATUS BAR
        # =====================================================================
        self.status_time_label = ft.Text(
            datetime.now().strftime("%H:%M:%S"),
            size=11, color=ft.Colors.GREY_700)

        status_bar = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Text("Ready", size=11, color=ft.Colors.GREY_700),
                    ft.Container(expand=True),
                    self.status_time_label,
                ], spacing=10),
            padding=ft.Padding.symmetric(horizontal=15, vertical=5),
            bgcolor=ft.Colors.GREY_100,
            border=ft.Border(top=ft.BorderSide(1, ft.Colors.GREY_300)))

        # =====================================================================
        # ROOT
        # =====================================================================
        self.root = ft.Column(
            controls=[header, self.tabs_control, status_bar],
            spacing=0,
            expand=True)

        self.page.run_task(self._clock_loop)
        self.page.run_task(self._auto_refresh_loop)

        return self.root

    # =============================================================================
    # Live clock
    # =============================================================================
    async def _clock_loop(self):
        if self._clock_running:
            return
        self._clock_running = True
        try:
            while True:
                try:
                    if self.status_time_label:
                        self.status_time_label.value = (
                            datetime.now().strftime("%H:%M:%S"))
                        self.page.update()
                except Exception:
                    break
                await asyncio.sleep(1)
        except Exception as ex:
            print(f"[CLOCK] stopped: {ex}")
        finally:
            self._clock_running = False

    # =============================================================================
    # Auto-refresh every 30s
    # =============================================================================
    async def _auto_refresh_loop(self):
        if self._refresh_running:
            return
        self._refresh_running = True
        try:
            while True:
                await asyncio.sleep(30)
                try:
                    self.refresh_all()
                except Exception as ex:
                    print(f"[AUTO REFRESH] {ex}")
        except Exception as ex:
            print(f"[AUTO REFRESH] stopped: {ex}")
        finally:
            self._refresh_running = False

    # =============================================================================
    # Refresh all tabs
    # =============================================================================
    def refresh_all(self):
        for name in ('dashboard_tab', 'travelers_tab', 'batches_tab',
                     'payments_tab', 'receipts_tab', 'invoices_tab',
                     'reports_tab', 'users_tab',
                     'frontpage_tab',       # ← NEW
                     'backup_tab'):
            tab = getattr(self, name, None)
            if tab is not None and hasattr(tab, 'refresh'):
                try:
                    tab.refresh()
                except Exception as ex:
                    print(f"[REFRESH {name}] {ex}")

    def refresh_dashboard(self):
        self.refresh_all()

    # =============================================================================
    # About
    # =============================================================================
    def show_about(self):
        def close(ev):
            self.page.pop_dialog()

        dialog = ft.AlertDialog(
            title=ft.Text("About"),
            content=ft.Column(
                controls=[
                    ft.Text("Alhudha Haj Travel System",
                            size=16, weight=ft.FontWeight.BOLD),
                    ft.Text("Version 3.0.0 (Web)"),
                    ft.Text("© Alhudha Travel"),
                    ft.Divider(),
                    ft.Text(
                        f"User: {self.current_user.get('full_name','')}",
                        size=12),
                    ft.Text(
                        f"Role: {self.current_user.get('role','')}",
                        size=12),
                ],
                tight=True,
                spacing=8),
            actions=[
                ft.Button(content=ft.Text("Close"), on_click=close),
            ])
        self.page.show_dialog(dialog)

    # =============================================================================
    # SnackBar helper
    # =============================================================================
    def _show_snack(self, message):
        try:
            self.page.show_dialog(
                ft.SnackBar(content=ft.Text(message)))
        except Exception:
            try:
                self.page.snack_bar = ft.SnackBar(
                    content=ft.Text(message))
                self.page.snack_bar.open = True
                self.page.update()
            except Exception as ex:
                print(f"[SNACK] {message} ({ex})")


# =================================================================================
# SECTION 7 END (FLET 1.0.0 VERSION)
# =================================================================================