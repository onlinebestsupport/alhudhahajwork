# =================================================================================
# SECTION 18 — USERS TAB (FLET 1.0) — v3.0
# =================================================================================
# Mirrors PaymentsTab structure exactly:
#   • Plain class (not ft.Column subclass)
#   • self.root = ft.Container(content=Column(...), expand=True)
#   • ResponsiveRow as a direct child of the outer Column
#   • No nested scroll containers
# =================================================================================

import flet as ft
import hashlib
import json
import traceback
from datetime import datetime

try:
    import pandas as pd return set
(jsonexcept ImportError:
    pd =.load None


# =================================================================================
#s PERMISSION CATAL(sOG
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
           ))
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
# 18.1 — CLASS: UsersTab
# =================================================================================
class UsersTab:

    def __init__(self, page: ft.Page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user or {}

        self.users = []

        self.stat_labels = {}
        self.users_column = None
        self.status_label = None
        self.root = None

        # permission gate
        if not _user_has_permission(self.current_user, "manage_users"):
            print(f"[USERS] ⛔ Access denied")
            self.root = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.LOCK, size=64,
                            color=ft.Colors.RED_400),
                    ft.Text("Access Denied", size=22,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.RED_700),
                    ft.Text("You do not have permission to manage users.",
                            size=12, color=ft.Colors.GREY_600),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=12),
                padding=60, alignment=ft.Alignment.CENTER,
                bgcolor="#fef2f2", border_radius=12,
                border=ft.Border.all(1, "#fecaca"),
                expand=True)
            return

        try:
            self.setup_ui()
        except Exception as ex:
            print(f"[USERS] setup_ui FAILED: {ex}")
            traceback.print_exc()
            self.root = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.WARNING_AMBER, size=48,
                            color=ft.Colors.ORANGE_600),
                    ft.Text("Users tab failed to load", size=18,
                            weight=ft.FontWeight.BOLD),
                    ft.Text(str(ex), size=12,
                            color=ft.Colors.RED_500, selectable=True),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=10),
                padding=40, bgcolor="#fef3c7", border_radius=12,
                alignment=ft.Alignment.CENTER, expand=True)
            return

        try:
            self.refresh()
        except Exception as ex:
            print(f"[USERS] refresh FAILED: {ex}")
            traceback.print_exc()

    def build(self):
        return self.root

    # =============================================================================
    # setup_ui — SAME structure as PaymentsTab.setup_ui
    # =============================================================================
    def setup_ui(self):
        stat_configs = [
            ("total",  "👥 Total",         "#3498db"),
            ("supers", "👑 Super Admins",  "#d97706"),
            ("admins", "🛡️ Admins",        "#7c3aed"),
            ("staff",  "🧑 Staff/Viewers", "#059669"),
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
                             col={"xs": 6, "sm": 6, "md": 3})
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

        toolbar = ft.ResponsiveRow(
            controls=[
                ft.Container(
                    content=_tb("➕ Add User", "#27ae60",
                                self.open_add_dialog),
                    col={"xs": 12, "sm": 6, "md": 4}),
                ft.Container(
                    content=_tb("🔄 Refresh", "#3498db",
                                self.refresh),
                    col={"xs": 12, "sm": 6, "md": 4}),
            ],
            spacing=8, run_spacing=8,
        )

        # Users list container: a Column, no scroll
        self.users_column = ft.Column(spacing=8)

        self.status_label = ft.Text("Ready.", size=10,
                                    color=ft.Colors.GREY_600, italic=True)

        # ---- ROOT: same shape as PaymentsTab ----
        self.root = ft.Container(
            content=ft.Column(
                controls=[
                    stats_row,
                    ft.Container(content=toolbar, padding=8,
                                 bgcolor=ft.Colors.WHITE,
                                 border_radius=10),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("💡 Tap Edit / Delete on any card "
                                    "below to manage users.",
                                    size=10,
                                    color=ft.Colors.GREY_600,
                                    italic=True),
                            self.users_column,
                        ], spacing=6),
                        bgcolor=ft.Colors.WHITE,
                        border_radius=10, padding=10),
                    self.status_label,
                ],
                spacing=10, scroll=ft.ScrollMode.AUTO,
            ),
            padding=10, bgcolor="#f0f2f5", expand=True,
        )

    # =============================================================================
    # refresh
    # =============================================================================
    def refresh(self, e=None):
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

            print(f"[USERS] loaded {len(self.users)} users")

            self.display_users()
            self.update_stats()
            try:
                self.page.update()
            except Exception:
                pass
        except Exception as ex:
            print(f"[USERS] refresh error: {ex}")
            traceback.print_exc()

    # =============================================================================
    # display_users — builds user cards
    # =============================================================================
    def display_users(self):
        if self.users_column is None:
            return
        self.users_column.controls.clear()

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

            self.users_column.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text(username, size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color="#0f172a",
                                    expand=True,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Container(
                                content=ft.Text(
                                    f"{role_icon} {role}", size=10,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE),
                                padding=ft.Padding.symmetric(
                                    horizontal=8, vertical=3),
                                bgcolor=role_color,
                                border_radius=10),
                        ], spacing=8),
                        ft.Text(full_name or "—", size=12,
                                color=ft.Colors.GREY_700),
                        ft.Text(email or "—", size=11,
                                color=ft.Colors.GREY_500),
                        ft.Row([
                            ft.Text(f"🔑 {perm_count} perms", size=10,
                                    color="#1e40af"),
                            ft.Text(f"📅 {created}", size=10,
                                    color=ft.Colors.GREY_600),
                            ft.Text(f"🕒 {last_login}", size=10,
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
                    bgcolor="#f0f9ff",
                    border_radius=10,
                    border=ft.Border.all(1, "#bae6fd"),
                )
            )

        print(f"[USERS] rendered {len(self.users_column.controls)} cards")

    def update_stats(self):
        total = len(self.users)
        supers = sum(1 for u in self.users
                     if u.get("role", "").lower() == "super_admin")
        admins = sum(1 for u in self.users
                     if u.get("role", "").lower() == "admin")
        staff = total - supers - admins

        if "total" in self.stat_labels:
            self.stat_labels["total"].value = str(total)
        if "supers" in self.stat_labels:
            self.stat_labels["supers"].value = str(supers)
        if "admins" in self.stat_labels:
            self.stat_labels["admins"].value = str(admins)
        if "staff" in self.stat_labels:
            self.stat_labels["staff"].value = str(staff)

    # =============================================================================
    # Dialogs
    # =============================================================================
    def open_add_dialog(self, e=None):
        try:
            UserFormDialog(
                page=self.page, db=self.db,
                current_user=self.current_user,
                user=None, on_save=self.refresh).show()
        except Exception as ex:
            print(f"[USERS] open_add_dialog error: {ex}")
            traceback.print_exc()

    def open_edit_dialog(self, e=None, user=None):
        if user is None:
            return
        try:
            UserFormDialog(
                page=self.page, db=self.db,
                current_user=self.current_user,
                user=user, on_save=self.refresh).show()
        except Exception as ex:
            print(f"[USERS] open_edit_dialog error: {ex}")
            traceback.print_exc()

    def _confirm_delete(self, user):
        uid = user.get("id")
        username = user.get("username", "?")
        role = user.get("role", "").lower()

        if uid == self.current_user.get("id"):
            self._snack("⚠️ You cannot delete your own account.")
            return
        if role == "super_admin":
            supers = [u for u in self.users
                      if u.get("role", "").lower() == "super_admin"]
            if len(supers) <= 1:
                self._snack("⚠️ Cannot delete the last super_admin.")
                return

        def _do(ev):
            try:
                self.page.pop_dialog()
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
                self._snack(f"✅ Deleted '{username}'")
            except Exception as ex:
                self._snack(f"❌ {ex}")

        def _cancel(ev):
            try:
                self.page.pop_dialog()
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
        self.page.show_dialog(dialog)

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
# 18.2 — CLASS: UserFormDialog
# =================================================================================
class UserFormDialog:

    def __init__(self, page, db, current_user, user=None, on_save=None):
        self.page = page
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
        narrow = False
        try:
            plat = getattr(self.page, "platform", None)
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
                w = self.page.width
                if w is None:
                    w = getattr(self.page.window, "width", None)
                narrow = (w is None) or (w < MOBILE_BREAKPOINT)
            except Exception:
                narrow = True

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
            ft.Column([self.password_field,
                       self.confirm_password_field], spacing=8)
            if narrow else
            ft.Row([self.password_field,
                    self.confirm_password_field], spacing=8)
        )

        credentials_section = ft.Container(
            content=ft.Column([
                ft.Text("🔐 Credentials", size=12,
                        weight=ft.FontWeight.BOLD, color="#1e40af"),
                self.username_field,
                pw_row,
            ], spacing=8),
            padding=10, bgcolor="#f0f9ff", border_radius=10,
            border=ft.Border.all(1, "#bae6fd"))

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
                ft.Text("👤 Profile", size=12,
                        weight=ft.FontWeight.BOLD, color="#1e40af"),
                self.full_name_field,
                self.email_field,
                self.role_dropdown,
            ], spacing=8),
            padding=10, bgcolor="#f5f3ff", border_radius=10,
            border=ft.Border.all(1, "#ddd6fe"))

        current_perms = _parse_permissions(
            u.get("permissions", ""), u.get("role", "staff"))
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
                    ft.Text("🔑 Permissions", size=12,
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
            padding=10, bgcolor="#f0fdf4", border_radius=10,
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

    def _save(self, e=None):
        try:
            username = _safe_str(self.username_field.value)
            if not username:
                self._snack("⚠️ Username is required.")
                return
            full_name = _safe_str(self.full_name_field.value)
            if not full_name:
                self._snack("⚠️ Full Name is required.")
                return
            email = _safe_str(self.email_field.value)
            role = _safe_str(self.role_dropdown.value) or "staff"
            password = _safe_str(self.password_field.value)
            confirm = _safe_str(self.confirm_password_field.value)
            if not self.is_edit and not password:
                self._snack("⚠️ Password is required for new users.")
                return
            if password and password != confirm:
                self._snack("⚠️ Passwords do not match.")
                return
            if password and len(password) < 4:
                self._snack("⚠️ Password must be at least 4 chars.")
                return

            existing = self.db.get_users()
            for u in existing:
                other_id = _safe_str(u.get("id"))
                this_id = _safe_str(self.user.get("id"))
                if other_id == this_id:
                    continue
                if _safe_str(u.get("username")).lower() == username.lower():
                    self._snack(f"⚠️ Username '{username}' exists.")
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
                label = "updated"
            else:
                self._add_new(user_data)
                label = "created"

            self.close()
            self._snack(f"✅ User '{username}' {label} successfully.")
            if self.on_save:
                try:
                    self.on_save()
                except Exception as ex:
                    print(f"[USERS] on_save callback: {ex}")
        except Exception as ex:
            print(f"[USERS] save error: {ex}")
            traceback.print_exc()

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
                    print(f"[USERS] update_user(dict): {ex}; fallback")
            except Exception as ex:
                print(f"[USERS] update_user: {ex}; fallback")

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

    def show(self):
        try:
            self.page.show_dialog(self.dialog)
        except Exception as ex:
            print(f"[USERS] show dialog failed: {ex}")

    def close(self):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def _snack(self, message, color=ft.Colors.GREEN_600):
        try:
            self.page.show_dialog(
                ft.SnackBar(content=ft.Text(message), bgcolor=color))
        except Exception:
            pass

    def _safe_update(self):
        try:
            self.page.update()
        except Exception:
            pass


# =================================================================================
# SECTION 18 END (FLET 1.0.0 VERSION)
# =================================================================================