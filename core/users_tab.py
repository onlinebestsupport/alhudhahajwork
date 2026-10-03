# =================================================================================
# SECTION 18 — USERS TAB (FLET 1.0) — v1.7
# =================================================================================
# Restored from original + mobile fixes:
#   • Full Add / Edit dialog with permission checkboxes, validation, role defaults
#   • Full Delete with super_admin protection & self-delete prevention
#   • Container built once; content re-mounted on every refresh
#   • Platform-first narrow detection
#   • Extensive diagnostics
# =================================================================================

import flet as ft
import hashlib
import json
import traceback
from datetime import datetime

try:
    import pandas as pd
except ImportError:
    pd = None


# =================================================================================
# PERMISSION CATALOG
# =================================================================================
PERMISSION_CATALOG = [
    ("view_dashboard",   "📊", "View Dashboard"),
    ("manage_travelers", "👥", "Manage Travelers"),
    ("manage_batches",   "📦", "Manage Batches"),
    ("manage_payments",  "💰", "Manage Payments"),
    ("manage_invoices",  "📄", "Manage Invoices"),
    ("manage_receipts",  "🧾", "Manage Receipts"),
    ("view_reports",     "📈", "View Reports"),
    ("manage_users",     "👤", "Manage Users"),
    ("manage_backups",   "💾", "Manage Backups"),
    ("manage_settings",  "⚙️", "Manage Settings"),
]

ROLE_DEFAULT_PERMISSIONS = {
    "super_admin": {p[0] for p in PERMISSION_CATALOG},
    "admin":       {p[0] for p in PERMISSION_CATALOG
                    if p[0] != "manage_users"},
    "staff":       {"view_dashboard", "manage_travelers",
                    "manage_payments", "manage_receipts",
                    "view_reports"},
    "viewer":      {"view_dashboard", "view_reports"},
}

ROLE_OPTIONS = ["super_admin", "admin", "staff", "viewer"]
MOBILE_BREAKPOINT = 700


# =================================================================================
# HELPERS
# =================================================================================
def _safe_str(v):
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    try:
        s = str(v).strip()
    except Exception:
        return ""
    if s.lower() in ("nan", "none", "nat", "null"):
        return ""
    return s


def _parse_permissions(value, role):
    s = _safe_str(value)
    if not s:
        return set(ROLE_DEFAULT_PERMISSIONS.get(
            _safe_str(role).lower(),
            ROLE_DEFAULT_PERMISSIONS["viewer"]))
    try:
        if s.startswith("["):
            return set(json.loads(s))
        return set(x.strip() for x in s.split("|") if x.strip())
    except Exception:
        return set(ROLE_DEFAULT_PERMISSIONS.get(
            _safe_str(role).lower(),
            ROLE_DEFAULT_PERMISSIONS["viewer"]))


def _serialize_permissions(perms):
    return json.dumps(sorted(perms))


def _hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def _user_has_permission(user, perm_key):
    if not user:
        return False
    role = _safe_str(user.get("role", "")).lower()
    if role == "super_admin":
        return True
    raw = user.get("permissions", "")
    if isinstance(raw, (list, set, tuple, frozenset)):
        return perm_key in raw
    s = _safe_str(raw)
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
# UsersTab
# =================================================================================
class UsersTab(ft.Column):

    def __init__(self, page, db, current_user):
        super().__init__()

        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}
        self.users = []

        self.scroll = ft.ScrollMode.AUTO
        self.expand = True
        self.spacing = 12

        self.table = None
        self.mobile_list = None
        self.stats_labels = {}
        self.status_label = None
        self._content_container = None
        self._ui_built = False
        self._mobile_mode = False

        # 🔒 Permission gate
        if not _user_has_permission(self.current_user, "manage_users"):
            print(f"[USERS] ⛔ Access denied for user "
                  f"'{self.current_user.get('username', '?')}'")
            self._build_access_denied_ui()
            return

        try:
            self.setup_ui()
            self._ui_built = True
        except Exception as e:
            print(f"[USERS] setup_ui FAILED: {e}")
            traceback.print_exc()
            self._build_error_ui(e)
            return

        try:
            self.refresh()
        except Exception as e:
            print(f"[USERS] refresh FAILED: {e}")
            traceback.print_exc()
            self._show_status(f"❌ Load failed: {e}", ft.Colors.RED_500)

    # -----------------------------------------------------------------------------
    def _is_narrow(self):
        try:
            plat = getattr(self.page_ref, "platform", None)
            if plat is not None:
                try:
                    if plat in (ft.PagePlatform.ANDROID,
                                ft.PagePlatform.IOS):
                        return True
                except Exception:
                    pstr = str(plat).lower()
                    if "android" in pstr or "ios" in pstr:
                        return True
        except Exception:
            pass
        try:
            w = self.page_ref.width
            if w is not None and w > 0:
                return w < MOBILE_BREAKPOINT
        except Exception:
            pass
        try:
            w = self.page_ref.window.width
            if w is not None and w > 0:
                return w < MOBILE_BREAKPOINT
        except Exception:
            pass
        return True

    # -----------------------------------------------------------------------------
    def _build_access_denied_ui(self):
        try:
            self.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.LOCK, size=64,
                                color=ft.Colors.RED_400),
                        ft.Text("Access Denied", size=22,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.RED_700),
                        ft.Text(
                            "You do not have permission to manage users.",
                            size=12, color=ft.Colors.GREY_600,
                            text_align=ft.TextAlign.CENTER),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                       spacing=12),
                    padding=60, alignment=ft.Alignment.CENTER, expand=True,
                    bgcolor="#fef2f2", border_radius=12,
                    border=ft.Border.all(1, "#fecaca"))
            ]
        except Exception:
            pass

    def _build_error_ui(self, exc):
        try:
            self.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.WARNING_AMBER, size=48,
                                color=ft.Colors.ORANGE_600),
                        ft.Text("Users tab failed to load", size=18,
                                weight=ft.FontWeight.BOLD),
                        ft.Text(str(exc), size=12,
                                color=ft.Colors.RED_500, selectable=True),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                       spacing=10),
                    padding=40, bgcolor="#fef3c7", border_radius=12,
                    alignment=ft.Alignment.CENTER, expand=True)
            ]
        except Exception:
            pass

    # =============================================================================
    # setup_ui
    # =============================================================================
    def setup_ui(self):
        narrow = self._is_narrow()
        self._mobile_mode = narrow
        print(f"[USERS] setup_ui narrow={narrow} "
              f"platform={getattr(self.page_ref, 'platform', '?')} "
              f"width={getattr(self.page_ref, 'width', '?')}")

        # ---- Header ----
        header = ft.Container(
            content=ft.Row([
                ft.Text("👤", size=22 if narrow else 26),
                ft.Column([
                    ft.Text("User Management",
                            size=14 if narrow else 16,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                    ft.Text("Manage users, roles and permissions",
                            size=9 if narrow else 10,
                            color=ft.Colors.BLUE_100,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=2, expand=True),
            ], spacing=8 if narrow else 12),
            padding=ft.Padding.symmetric(
                horizontal=12 if narrow else 22,
                vertical=10 if narrow else 14),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#1e3a8a", "#2563eb", "#7c3aed"]),
            border_radius=12)

        # ---- Stats cards ----
        stat_specs = [
            ("total",  "👥", "Total",         "#2563eb"),
            ("supers", "👑", "Super Admins",  "#d97706"),
            ("admins", "🛡️", "Admins",        "#7c3aed"),
            ("staff",  "🧑", "Staff/Viewers", "#059669"),
        ]
        stat_cards = []
        for key, icon, label, color in stat_specs:
            value = ft.Text("0", size=18 if narrow else 20,
                            weight=ft.FontWeight.BOLD,
                            color=color)
            self.stats_labels[key] = value
            stat_cards.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Text(icon, size=14 if narrow else 16),
                        ft.Text(label, size=10 if narrow else 11,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.GREY_600,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=4),
                    value,
                ], spacing=2),
                padding=10 if narrow else 12,
                bgcolor=ft.Colors.WHITE, border_radius=10,
                border=ft.Border.only(left=ft.BorderSide(4, color)),
                col={"xs": 6, "sm": 6, "md": 3}))

        stats_row = ft.ResponsiveRow(stat_cards, spacing=8, run_spacing=8)

        # ---- Toolbar ----
        add_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.ADD, size=16, color=ft.Colors.WHITE),
                ft.Text("Add User", size=12,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE),
            ], spacing=6, tight=True,
               alignment=ft.MainAxisAlignment.CENTER),
            on_click=self.open_add_dialog,
            height=42, bgcolor="#059669",
            expand=narrow)

        toolbar = ft.Container(
            content=ft.Row([
                add_btn,
                ft.Container(expand=not narrow),
                ft.IconButton(icon=ft.Icons.REFRESH,
                              icon_color="#2563eb",
                              tooltip="Refresh list",
                              on_click=self.refresh),
            ], spacing=8, wrap=True),
            padding=ft.Padding.symmetric(
                horizontal=10 if narrow else 14,
                vertical=8 if narrow else 10),
            bgcolor=ft.Colors.WHITE, border_radius=12,
            border=ft.Border.all(1, "#e2e8f0"))

        # ---- Prepare the correct view object ----
        if narrow:
            self.mobile_list = ft.Column(spacing=8)
            self.table = None
            hint = "💡 Tap Edit/Delete on any card"
        else:
            self.table = ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text(h, size=11,
                                          weight=ft.FontWeight.BOLD,
                                          color=ft.Colors.WHITE))
                    for h in ["Username", "Full Name", "Email", "Role",
                              "Perms", "Created", "Last Login", "Actions"]
                ],
                rows=[],
                heading_row_color="#1e293b",
                column_spacing=12,
                data_row_min_height=44,
                data_row_max_height=70)
            self.mobile_list = None
            hint = "💡 Click 🗑️ to delete a user"

        # ---- Content container (filled by _mount_content_view) ----
        self._content_container = ft.Container(content=None, padding=0)

        table_card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("📋", size=14),
                    ft.Text("All Users", size=13,
                            weight=ft.FontWeight.BOLD,
                            color="#1e40af"),
                    ft.Container(expand=True),
                    ft.Text(hint, size=9,
                            color=ft.Colors.GREY_500, italic=True),
                ], spacing=6),
                self._content_container,
            ], spacing=8),
            padding=10 if narrow else 12,
            bgcolor=ft.Colors.WHITE, border_radius=12,
            border=ft.Border.all(1, "#e2e8f0"))

        self.status_label = ft.Text("Ready.", size=10,
                                    color=ft.Colors.GREY_600, italic=True)

        self.controls = [
            header,
            stats_row,
            toolbar,
            table_card,
            self.status_label,
        ]

        self._mount_content_view()

    # -----------------------------------------------------------------------------
    def _mount_content_view(self):
        try:
            if self._mobile_mode and self.mobile_list is not None:
                self._content_container.content = self.mobile_list
                print(f"[USERS] mounted mobile_list "
                      f"({len(self.mobile_list.controls)} cards)")
            elif (not self._mobile_mode) and self.table is not None:
                self._content_container.content = ft.Row(
                    [self.table], scroll=ft.ScrollMode.ADAPTIVE)
                print(f"[USERS] mounted desktop table "
                      f"({len(self.table.rows)} rows)")
            else:
                print("[USERS] mount: nothing to mount")
        except Exception as ex:
            print(f"[USERS] mount error: {ex}")

    def build(self):
        return self

    # -----------------------------------------------------------------------------
    def on_resize(self, e=None):
        try:
            new_narrow = self._is_narrow()
            if new_narrow != self._mobile_mode:
                print(f"[USERS] viewport changed → "
                      f"{'mobile' if new_narrow else 'desktop'}")
                self.controls.clear()
                self.stats_labels.clear()
                self.setup_ui()
                try:
                    self.refresh()
                except Exception as ex:
                    print(f"[USERS] refresh after resize failed: {ex}")
        except Exception as ex:
            print(f"[USERS] on_resize error: {ex}")

    # =============================================================================
    # refresh
    # =============================================================================
    def refresh(self, e=None):
        if not self._ui_built and not self.status_label:
            return

        try:
            try:
                if hasattr(self.db, "reload"):
                    self.db.reload()
                elif hasattr(self.db, "_load_all"):
                    self.db._load_all()
            except Exception as _re:
                print(f"[USERS] reload skipped: {_re}")

            raw = self.db.get_users()
            self.users = []
            for u in raw:
                clean = {}
                for k, v in u.items():
                    clean[str(k)] = _safe_str(v)
                if not clean.get("permissions"):
                    role = clean.get("role", "viewer")
                    perms = ROLE_DEFAULT_PERMISSIONS.get(
                        role.lower(),
                        ROLE_DEFAULT_PERMISSIONS["viewer"])
                    clean["permissions"] = _serialize_permissions(perms)
                self.users.append(clean)

            print(f"[USERS] loaded {len(self.users)} users from DB")

            if self._mobile_mode:
                self._render_mobile_cards()
            else:
                self._render_desktop_table()

            self._update_stats()
            self._mount_content_view()

            if self.status_label:
                self.status_label.value = (
                    f"✅ Loaded {len(self.users)} users "
                    f"at {datetime.now().strftime('%H:%M:%S')}")
                self.status_label.color = ft.Colors.GREEN_700
            self._safe_update()
        except Exception as ex:
            print(f"[USERS] refresh error: {ex}")
            traceback.print_exc()
            self._show_status(f"❌ Load failed: {ex}", ft.Colors.RED_500)

    def _update_stats(self):
        total = len(self.users)
        supers = sum(1 for u in self.users
                     if u.get("role", "").lower() == "super_admin")
        admins = sum(1 for u in self.users
                     if u.get("role", "").lower() == "admin")
        staff = total - supers - admins
        for k, v in [("total", total), ("supers", supers),
                     ("admins", admins), ("staff", staff)]:
            if k in self.stats_labels:
                self.stats_labels[k].value = str(v)

    # =============================================================================
    # Desktop table renderer
    # =============================================================================
    def _render_desktop_table(self):
        if self.table is None:
            return
        self.table.rows.clear()

        for u in self.users:
            username = u.get("username", "")
            full_name = u.get("full_name", "")
            email = u.get("email", "")
            role = u.get("role", "staff")
            created = u.get("created_at", "")[:10] or "—"
            last_login = u.get("last_login", "")[:10] or "Never"
            uid = u.get("id")

            perms = _parse_permissions(u.get("permissions", ""), role)
            perm_count = len(perms)

            role_lower = role.lower()
            if role_lower == "super_admin":
                role_color, role_icon = "#d97706", "👑"
            elif role_lower == "admin":
                role_color, role_icon = "#7c3aed", "🛡️"
            elif role_lower == "staff":
                role_color, role_icon = "#059669", "🧑"
            else:
                role_color, role_icon = "#64748b", "👁️"

            role_badge = ft.Container(
                content=ft.Text(f"{role_icon} {role}", size=10,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE),
                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                bgcolor=role_color, border_radius=10)

            perms_badge = ft.Container(
                content=ft.Text(f"{perm_count} perms", size=10,
                                color="#1e40af",
                                weight=ft.FontWeight.BOLD),
                padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                bgcolor="#dbeafe", border_radius=10)

            is_self = (uid == self.current_user.get("id"))

            def _make_edit(_uid=uid):
                def h(e):
                    fresh = next(
                        (x for x in self.users if x.get("id") == _uid), None)
                    if fresh:
                        self.open_edit_dialog(e, user=fresh)
                    else:
                        self._show_status(
                            "⚠️ User no longer exists — refreshing…",
                            ft.Colors.ORANGE_700)
                        self.refresh()
                return h

            def _make_delete(_uid=uid):
                def h(e):
                    fresh = next(
                        (x for x in self.users if x.get("id") == _uid), None)
                    if fresh:
                        self._confirm_delete(fresh)
                    else:
                        self._show_status(
                            "⚠️ User no longer exists — refreshing…",
                            ft.Colors.ORANGE_700)
                        self.refresh()
                return h

            actions = ft.Row([
                ft.IconButton(icon=ft.Icons.EDIT, icon_size=18,
                              icon_color="#2563eb",
                              tooltip="Edit user",
                              on_click=_make_edit()),
                ft.IconButton(
                    icon=ft.Icons.DELETE, icon_size=18,
                    icon_color="#dc2626" if not is_self else "#cbd5e1",
                    tooltip=("Cannot delete self"
                             if is_self else "Delete user"),
                    disabled=is_self,
                    on_click=_make_delete()),
            ], spacing=0)

            self.table.rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(username, size=11,
                                    weight=ft.FontWeight.BOLD,
                                    color="#0f172a")),
                ft.DataCell(ft.Text(full_name or "—", size=11)),
                ft.DataCell(ft.Text(email or "—", size=11,
                                    color=ft.Colors.GREY_600)),
                ft.DataCell(role_badge),
                ft.DataCell(perms_badge),
                ft.DataCell(ft.Text(created, size=11,
                                    color=ft.Colors.GREY_600)),
                ft.DataCell(ft.Text(last_login, size=11,
                                    color=ft.Colors.GREY_600)),
                ft.DataCell(actions),
            ]))

        print(f"[USERS] rendered {len(self.table.rows)} desktop rows")

    # =============================================================================
    # Mobile card renderer
    # =============================================================================
    def _render_mobile_cards(self):
        if self.mobile_list is None:
            print("[USERS] _render_mobile_cards: mobile_list is None!")
            return
        self.mobile_list.controls.clear()

        for u in self.users:
            username = u.get("username", "")
            full_name = u.get("full_name", "")
            email = u.get("email", "")
            role = u.get("role", "staff")
            created = u.get("created_at", "")[:10] or "—"
            last_login = u.get("last_login", "")[:10] or "Never"
            uid = u.get("id")

            perms = _parse_permissions(u.get("permissions", ""), role)
            perm_count = len(perms)

            role_lower = role.lower()
            if role_lower == "super_admin":
                role_color, role_icon = "#d97706", "👑"
            elif role_lower == "admin":
                role_color, role_icon = "#7c3aed", "🛡️"
            elif role_lower == "staff":
                role_color, role_icon = "#059669", "🧑"
            else:
                role_color, role_icon = "#64748b", "👁️"

            is_self = (uid == self.current_user.get("id"))

            def _edit(e, _uid=uid):
                fresh = next((x for x in self.users
                              if x.get("id") == _uid), None)
                if fresh:
                    self.open_edit_dialog(e, user=fresh)
                else:
                    self.refresh()

            def _delete(e, _uid=uid):
                fresh = next((x for x in self.users
                              if x.get("id") == _uid), None)
                if fresh:
                    self._confirm_delete(fresh)
                else:
                    self.refresh()

            self.mobile_list.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text(username, size=13,
                                    weight=ft.FontWeight.BOLD,
                                    color="#0f172a",
                                    expand=True,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Container(
                                content=ft.Text(
                                    f"{role_icon} {role}", size=9,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE),
                                padding=ft.Padding.symmetric(
                                    horizontal=8, vertical=3),
                                bgcolor=role_color,
                                border_radius=10),
                        ], spacing=8),

                        ft.Text(full_name or "—", size=11,
                                color=ft.Colors.GREY_700,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(email or "—", size=10,
                                color=ft.Colors.GREY_500,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),

                        ft.Row([
                            ft.Text(f"🔑 {perm_count} perms", size=9,
                                    color="#1e40af"),
                            ft.Text(f"📅 {created}", size=9,
                                    color=ft.Colors.GREY_600),
                            ft.Text(f"🕒 {last_login}", size=9,
                                    color=ft.Colors.GREY_600),
                        ], spacing=10, wrap=True),

                        ft.Row([
                            ft.TextButton(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.EDIT, size=14,
                                            color="#2563eb"),
                                    ft.Text("Edit", size=11,
                                            color="#2563eb"),
                                ], spacing=4, tight=True),
                                on_click=_edit),
                            ft.TextButton(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.DELETE, size=14,
                                            color="#dc2626"
                                            if not is_self
                                            else "#cbd5e1"),
                                    ft.Text("Delete", size=11,
                                            color="#dc2626"
                                            if not is_self
                                            else "#cbd5e1"),
                                ], spacing=4, tight=True),
                                disabled=is_self,
                                on_click=_delete),
                        ], spacing=4,
                           alignment=ft.MainAxisAlignment.END),
                    ], spacing=6),
                    padding=12,
                    bgcolor=ft.Colors.WHITE,
                    border_radius=10,
                    border=ft.Border.all(1, "#e2e8f0"),
                )
            )

        print(f"[USERS] rendered {len(self.mobile_list.controls)} cards")

    # =============================================================================
    # Dialog launchers
    # =============================================================================
    def open_add_dialog(self, e=None):
        try:
            dlg = UserFormDialog(
                page=self.page_ref,
                db=self.db,
                current_user=self.current_user,
                user=None,
                on_save=self.refresh)
            dlg.show()
        except Exception as ex:
            print(f"[USERS] open_add_dialog error: {ex}")
            traceback.print_exc()
            self._show_status(f"❌ {ex}", ft.Colors.RED_500)

    def open_edit_dialog(self, e=None, user=None):
        if user is None:
            self._show_status("⚠️ Select a user first.",
                              ft.Colors.ORANGE_700)
            return
        try:
            dlg = UserFormDialog(
                page=self.page_ref,
                db=self.db,
                current_user=self.current_user,
                user=user,
                on_save=self.refresh)
            dlg.show()
        except Exception as ex:
            print(f"[USERS] open_edit_dialog error: {ex}")
            traceback.print_exc()
            self._show_status(f"❌ {ex}", ft.Colors.RED_500)

    # =============================================================================
    # Delete confirmation
    # =============================================================================
    def _confirm_delete(self, user):
        uid = user.get("id")
        username = user.get("username", "?")
        role = user.get("role", "").lower()

        if uid == self.current_user.get("id"):
            self._show_status("⚠️ You cannot delete your own account.",
                              ft.Colors.RED_500)
            return

        if role == "super_admin":
            supers = [u for u in self.users
                      if u.get("role", "").lower() == "super_admin"]
            if len(supers) <= 1:
                self._show_status(
                    "⚠️ Cannot delete the last super_admin account.",
                    ft.Colors.RED_500)
                return

        def _do(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
            try:
                if hasattr(self.db, "delete_user"):
                    self.db.delete_user(uid)
                elif pd is not None:
                    self.db.users = self.db.users[
                        self.db.users["id"] != uid]
                    self.db._save_df(self.db.users, "users.csv")

                try:
                    self.db.log_activity(
                        self.current_user.get("id"),
                        "delete_user",
                        f"Deleted user: {username}")
                except Exception:
                    pass

                self.refresh()
                self._show_status(f"✅ User '{username}' deleted.",
                                  ft.Colors.GREEN_700)
            except Exception as ex:
                print(f"[USERS] delete error: {ex}")
                traceback.print_exc()
                self._show_status(f"❌ Delete failed: {ex}",
                                  ft.Colors.RED_500)

        def _cancel(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, color="#dc2626"),
                ft.Text("Confirm Delete",
                        weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Text(
                f"Delete user '{username}'?\nThis cannot be undone.",
                size=12),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=_cancel),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.DELETE, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Delete", color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=_do,
                    bgcolor="#dc2626"),
            ])
        self.page_ref.show_dialog(dialog)

    # =============================================================================
    # Helpers
    # =============================================================================
    def _show_status(self, message, color=ft.Colors.GREY_700):
        if self.status_label:
            self.status_label.value = message
            self.status_label.color = color
        self._safe_update()

    def _safe_update(self):
        try:
            self.update()
        except Exception:
            pass


# =================================================================================
# UserFormDialog — FULL Add / Edit
# =================================================================================
class UserFormDialog:

    def __init__(self, page, db, current_user, user=None, on_save=None):
        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}
        self.user = user or {}
        self.is_edit = user is not None
        self.on_save = on_save

        self.username_field = None
        self.password_field = None
        self.confirm_password_field = None
        self.full_name_field = None
        self.email_field = None
        self.role_dropdown = None
        self.permission_checkboxes = {}
        self.perm_note = None
        self.dialog = None

        self._build()

    def _build(self):
        u = self.user

        # Narrow detection
        narrow = False
        try:
            plat = getattr(self.page_ref, "platform", None)
            if plat is not None:
                try:
                    if plat in (ft.PagePlatform.ANDROID,
                                ft.PagePlatform.IOS):
                        narrow = True
                except Exception:
                    pstr = str(plat).lower()
                    if "android" in pstr or "ios" in pstr:
                        narrow = True
        except Exception:
            pass

        if not narrow:
            try:
                w = self.page_ref.width
                if w is None:
                    try:
                        w = self.page_ref.window.width
                    except Exception:
                        w = None
                narrow = (w is None) or (w < MOBILE_BREAKPOINT)
            except Exception:
                narrow = True

        # ---- Credentials ----
        self.username_field = ft.TextField(
            label="Username *",
            value=_safe_str(u.get("username")),
            prefix_icon=ft.Icons.PERSON_OUTLINE,
            text_size=12, content_padding=12)

        self.password_field = ft.TextField(
            label=("New Password (leave blank to keep)"
                   if self.is_edit else "Password *"),
            password=True, can_reveal_password=True,
            prefix_icon=ft.Icons.LOCK_OUTLINE,
            text_size=12, content_padding=12)

        self.confirm_password_field = ft.TextField(
            label="Confirm Password",
            password=True, can_reveal_password=True,
            prefix_icon=ft.Icons.LOCK_OUTLINE,
            text_size=12, content_padding=12)

        pw_row = (
            ft.Column([
                self.password_field,
                self.confirm_password_field,
            ], spacing=8)
            if narrow else
            ft.Row([self.password_field,
                    self.confirm_password_field],
                   spacing=8)
        )

        credentials_section = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("🔐", size=14),
                    ft.Text("Credentials", size=12,
                            weight=ft.FontWeight.BOLD, color="#1e40af"),
                ], spacing=6),
                self.username_field,
                pw_row,
            ], spacing=8),
            padding=10 if narrow else 12,
            bgcolor="#f0f9ff", border_radius=10,
            border=ft.Border.all(1, "#bae6fd"))

        # ---- Profile ----
        self.full_name_field = ft.TextField(
            label="Full Name *",
            value=_safe_str(u.get("full_name")),
            prefix_icon=ft.Icons.BADGE_OUTLINED,
            text_size=12, content_padding=12)

        self.email_field = ft.TextField(
            label="Email",
            value=_safe_str(u.get("email")),
            prefix_icon=ft.Icons.EMAIL_OUTLINED,
            text_size=12, content_padding=12)

        self.role_dropdown = ft.Dropdown(
            label="Role *",
            value=_safe_str(u.get("role")) or "staff",
            options=[ft.dropdown.Option(r) for r in ROLE_OPTIONS],
            text_size=12, content_padding=12)
        self.role_dropdown.on_change = self._on_role_change

        profile_section = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("👤", size=14),
                    ft.Text("Profile", size=12,
                            weight=ft.FontWeight.BOLD, color="#1e40af"),
                ], spacing=6),
                self.full_name_field,
                self.email_field,
                self.role_dropdown,
            ], spacing=8),
            padding=10 if narrow else 12,
            bgcolor="#f5f3ff", border_radius=10,
            border=ft.Border.all(1, "#ddd6fe"))

        # ---- Permissions ----
        current_perms = _parse_permissions(
            u.get("permissions", ""),
            u.get("role", "staff"))

        perm_grid = ft.ResponsiveRow(spacing=6, run_spacing=6)
        for key, icon, label in PERMISSION_CATALOG:
            cb = ft.Checkbox(
                label=f"{icon}  {label}",
                value=(key in current_perms),
                label_style=ft.TextStyle(size=11))
            self.permission_checkboxes[key] = cb
            perm_grid.controls.append(
                ft.Container(content=cb,
                             col={"xs": 12, "sm": 12, "md": 6}))

        self.perm_note = ft.Text(
            "ℹ️  Permissions are auto-set based on role.",
            size=10, color=ft.Colors.GREY_600, italic=True)

        def _select_all(e):
            for cb in self.permission_checkboxes.values():
                if not cb.disabled:
                    cb.value = True
            self._safe_update()

        def _clear_all(e):
            for cb in self.permission_checkboxes.values():
                if not cb.disabled:
                    cb.value = False
            self._safe_update()

        perm_section = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("🔑", size=14),
                    ft.Text("Permissions", size=12,
                            weight=ft.FontWeight.BOLD, color="#1e40af"),
                    ft.Container(expand=True),
                    ft.TextButton(content=ft.Text("✓ All", size=10),
                                  on_click=_select_all),
                    ft.TextButton(content=ft.Text("✗ None", size=10),
                                  on_click=_clear_all),
                ], spacing=6),
                self.perm_note,
                perm_grid,
            ], spacing=6),
            padding=10 if narrow else 12,
            bgcolor="#f0fdf4", border_radius=10,
            border=ft.Border.all(1, "#bbf7d0"))

        body = ft.Container(
            content=ft.Column([
                credentials_section,
                profile_section,
                perm_section,
            ], spacing=10, scroll=ft.ScrollMode.AUTO),
            width=640 if not narrow else None,
            height=560 if not narrow else None,
            expand=narrow,
            padding=6)

        title = "✏️  Edit User" if self.is_edit else "➕  Add New User"

        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD,
                          size=15 if narrow else 18),
            content=body,
            content_padding=10 if narrow else 20,
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda e: self.close()),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.SAVE, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Save", color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=self._save,
                    bgcolor="#059669"),
            ])

        self._on_role_change(None, force_defaults=not self.is_edit)

    # -----------------------------------------------------------------------------
    def _on_role_change(self, e=None, force_defaults=False):
        role = _safe_str(self.role_dropdown.value) or "staff"

        if role == "super_admin":
            for cb in self.permission_checkboxes.values():
                cb.value = True
                cb.disabled = True
            self.perm_note.value = (
                "🔒  super_admin always has all permissions.")
            self.perm_note.color = "#d97706"
        else:
            defaults = ROLE_DEFAULT_PERMISSIONS.get(
                role, ROLE_DEFAULT_PERMISSIONS["viewer"])
            if force_defaults or (not self.is_edit) or e is not None:
                for key, cb in self.permission_checkboxes.items():
                    cb.value = (key in defaults)
                    cb.disabled = False
            else:
                for cb in self.permission_checkboxes.values():
                    cb.disabled = False
            self.perm_note.value = (
                f"ℹ️  Defaults applied for role '{role}'.")
            self.perm_note.color = ft.Colors.GREY_600

        self._safe_update()

    # -----------------------------------------------------------------------------
    def _save(self, e=None):
        try:
            username = _safe_str(self.username_field.value)
            if not username:
                self._snack("⚠️ Username is required.",
                            ft.Colors.RED_500)
                return

            full_name = _safe_str(self.full_name_field.value)
            if not full_name:
                self._snack("⚠️ Full Name is required.",
                            ft.Colors.RED_500)
                return

            email = _safe_str(self.email_field.value)
            role = _safe_str(self.role_dropdown.value) or "staff"
            password = _safe_str(self.password_field.value)
            confirm = _safe_str(self.confirm_password_field.value)

            if not self.is_edit and not password:
                self._snack("⚠️ Password is required for new users.",
                            ft.Colors.RED_500)
                return
            if password and password != confirm:
                self._snack("⚠️ Passwords do not match.",
                            ft.Colors.RED_500)
                return
            if password and len(password) < 4:
                self._snack("⚠️ Password must be at least 4 chars.",
                            ft.Colors.RED_500)
                return

            # Username uniqueness
            existing = self.db.get_users()
            for u in existing:
                other_id = _safe_str(u.get("id"))
                this_id = _safe_str(self.user.get("id"))
                if other_id == this_id:
                    continue
                if _safe_str(u.get("username")).lower() == username.lower():
                    self._snack(
                        f"⚠️ Username '{username}' already exists.",
                        ft.Colors.RED_500)
                    return

            perms = {k for k, cb in self.permission_checkboxes.items()
                     if cb.value}
            if role == "super_admin":
                perms = {p[0] for p in PERMISSION_CATALOG}

            user_data = {
                "username": username,
                "full_name": full_name,
                "email": email,
                "role": role,
                "permissions": _serialize_permissions(perms),
            }
            if password:
                user_data["password_hash"] = _hash_password(password)

            if self.is_edit:
                self._update_existing(user_data)
                try:
                    self.db.log_activity(
                        self.current_user.get("id"), "edit_user",
                        f"Edited user: {username}")
                except Exception:
                    pass
                label = "updated"
            else:
                self._add_new(user_data)
                try:
                    self.db.log_activity(
                        self.current_user.get("id"), "add_user",
                        f"Added user: {username}")
                except Exception:
                    pass
                label = "created"

            self.close()
            self._snack(f"✅ User '{username}' {label} successfully.",
                        ft.Colors.GREEN_700)
            if self.on_save:
                try:
                    self.on_save()
                except Exception as ex:
                    print(f"[USERS] on_save callback failed: {ex}")
        except Exception as ex:
            print(f"[USERS] save error: {ex}")
            traceback.print_exc()
            self._snack(f"❌ Save failed: {ex}", ft.Colors.RED_500)

    def _add_new(self, data):
        if hasattr(self.db, "add_user"):
            try:
                self.db.add_user(data)
                return
            except Exception as ex:
                print(f"[USERS] db.add_user failed: {ex}; fallback")

        if pd is None:
            raise RuntimeError("pandas not available")
        new_id = f"USR/{datetime.now().strftime('%Y%m%d%H%M%S')}"
        row = {
            "id": new_id,
            "username": data["username"],
            "password_hash": data.get("password_hash", ""),
            "full_name": data["full_name"],
            "email": data["email"],
            "role": data["role"],
            "permissions": data["permissions"],
            "created_at": datetime.now().isoformat(),
            "last_login": "",
        }

        if "permissions" not in self.db.users.columns:
            self.db.users["permissions"] = ""

        new_df = pd.DataFrame([row]).reindex(
            columns=self.db.users.columns, fill_value="")
        self.db.users = pd.concat([self.db.users, new_df],
                                  ignore_index=True)
        self.db._save_df(self.db.users, "users.csv")

    def _update_existing(self, data):
        uid = _safe_str(self.user.get("id"))

        if hasattr(self.db, "update_user"):
            try:
                self.db.update_user(uid, **data)
                return
            except TypeError:
                try:
                    self.db.update_user(uid, data)
                    return
                except Exception as ex:
                    print(f"[USERS] db.update_user(dict) failed: "
                          f"{ex}; fallback")
            except Exception as ex:
                print(f"[USERS] db.update_user failed: {ex}; fallback")

        if pd is None:
            raise RuntimeError("pandas not available")

        if "permissions" not in self.db.users.columns:
            self.db.users["permissions"] = ""

        mask = self.db.users["id"] == uid

        for key in ["username", "full_name", "email", "role",
                    "permissions"]:
            if key in data and key in self.db.users.columns:
                self.db.users.loc[mask, key] = data[key]

        if "password_hash" in data and \
                "password_hash" in self.db.users.columns:
            self.db.users.loc[mask, "password_hash"] = \
                data["password_hash"]

        self.db._save_df(self.db.users, "users.csv")

    # -----------------------------------------------------------------------------
    def show(self):
        try:
            self.page_ref.show_dialog(self.dialog)
        except Exception as ex:
            print(f"[USERS] show dialog failed: {ex}")

    def close(self):
        try:
            self.page_ref.pop_dialog()
        except Exception:
            pass

    def _snack(self, message, color=ft.Colors.GREEN_600):
        try:
            self.page_ref.show_dialog(
                ft.SnackBar(content=ft.Text(message), bgcolor=color))
            return
        except Exception:
            pass
        try:
            self.page_ref.snack_bar = ft.SnackBar(
                content=ft.Text(message), bgcolor=color)
            self.page_ref.snack_bar.open = True
            self.page_ref.update()
        except Exception:
            pass

    def _safe_update(self):
        try:
            self.page_ref.update()
        except Exception:
            pass


# =================================================================================
# SECTION 18 END — USERS TAB (v1.7)
# =================================================================================
