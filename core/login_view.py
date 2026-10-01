# =================================================================================
# SECTION 2 (FLET 1.0.0 VERSION) — LOGIN VIEW
# =================================================================================
# UPDATED — 2026-10-01 (v1.2)
#   • Al-Hudha logo shown at the top of the login card (with emoji fallback)
#   • Password hashing matches core/users_tab.py (SHA-256)
#   • Enter key submits the form
#   • Flet 1.0 web-safe SnackBar via page.show_dialog()
#   • Defensive page.update() — never crashes on a closed session
# =================================================================================

import hashlib
import traceback
from datetime import datetime

import flet as ft


# =================================================================================
# 2.1 — Password hash helper (MUST match users_tab.py)
# =================================================================================
def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# =================================================================================
# 2.2 — Safe string helper
# =================================================================================
def _safe_str(v) -> str:
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


# =================================================================================
# 2.3 — CLASS: LoginView
# =================================================================================
class LoginView:

    def __init__(self, page: ft.Page, db, on_login_success=None,
                 on_cancel=None):
        self.page = page
        self.db = db
        self.on_login_success = on_login_success
        self.on_cancel = on_cancel

        self.username_field = None
        self.password_field = None
        self.status_label = None
        self.login_btn = None
        self.root = None

        self._build()

    # -----------------------------------------------------------------------------
    # 2.3.1 — _build
    # -----------------------------------------------------------------------------
    def _build(self):
        # ---- Company name (defensive) ----
        company_name = "Alhudha Haj Travel System"
        try:
            if (hasattr(self.db, "company_settings")
                    and not self.db.company_settings.empty):
                raw = self.db.company_settings.iloc[0].get("company_name", "")
                if raw:
                    company_name = str(raw)
        except Exception:
            pass

        # ---- Logo with emoji fallback ----
        logo = ft.Image(
            src="/static/logo.png",
            width=100, height=100,
            fit=ft.BoxFit.CONTAIN,
            error_content=ft.Text("🏆", size=56),
        )

        # ---- Title / subtitle ----
        title = ft.Text(
            company_name,
            size=22,
            weight=ft.FontWeight.BOLD,
            color="#1e3c72",
            text_align=ft.TextAlign.CENTER,
        )
        subtitle = ft.Text(
            "Pilgrimage Management System",
            size=12,
            color=ft.Colors.GREY_600,
            text_align=ft.TextAlign.CENTER,
        )

        # ---- Fields ----
        self.username_field = ft.TextField(
            label="Username",
            hint_text="Enter username",
            prefix_icon=ft.Icons.PERSON_OUTLINE,
            autofocus=True,
            text_size=13,
            height=56,
            on_submit=lambda e: self._do_login(None),
        )

        self.password_field = ft.TextField(
            label="Password",
            hint_text="Enter password",
            prefix_icon=ft.Icons.LOCK_OUTLINE,
            password=True,
            can_reveal_password=True,
            text_size=13,
            height=56,
            on_submit=lambda e: self._do_login(None),
        )

        # ---- Status message (hidden by default) ----
        self.status_label = ft.Text(
            "", size=11, color=ft.Colors.RED_500,
            text_align=ft.TextAlign.CENTER)

        # ---- Buttons ----
        self.login_btn = ft.Button(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.LOGIN, size=18,
                            color=ft.Colors.WHITE),
                    ft.Text("Login", size=14,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
                tight=True,
            ),
            on_click=self._do_login,
            height=48,
            bgcolor="#1e3c72",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            expand=True,
        )

        cancel_btn = ft.Button(
            content=ft.Text("Cancel", size=13,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
            on_click=lambda e: self._do_cancel(e),
            height=48,
            bgcolor="#7f8c8d",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10),
            ),
            expand=True,
        )

        # ---- Card ----
        card = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=logo,
                        width=100, height=100,
                        alignment=ft.Alignment.CENTER,
                    ),
                    ft.Container(height=8),
                    title,
                    subtitle,
                    ft.Container(height=16),
                    self.username_field,
                    ft.Container(height=8),
                    self.password_field,
                    ft.Container(height=4),
                    self.status_label,
                    ft.Container(height=8),
                    ft.Row(
                        controls=[self.login_btn, cancel_btn],
                        spacing=10,
                    ),
                ],
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            width=420,
            padding=ft.Padding.symmetric(horizontal=32, vertical=32),
            bgcolor=ft.Colors.WHITE,
            border_radius=18,
            border=ft.Border.all(1, "#e2e8f0"),
            shadow=ft.BoxShadow(
                blur_radius=24,
                spread_radius=2,
                color=ft.Colors.with_opacity(0.12, "#000000"),
                offset=ft.Offset(0, 8),
            ),
        )

        # ---- Page background ----
        self.root = ft.Container(
            content=ft.Column(
                controls=[card],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                expand=True,
            ),
            expand=True,
            bgcolor="#f0f2f5",
            alignment=ft.Alignment.CENTER,
        )

        # ---- Footer ----
        try:
            version = "3.0.0 (Web)"
            footer = ft.Text(
                f"© {datetime.now().year} Alhudha Travel · v{version}",
                size=10, color=ft.Colors.GREY_500,
                text_align=ft.TextAlign.CENTER)
            card.content.controls.append(ft.Container(height=8))
            card.content.controls.append(footer)
        except Exception:
            pass

    # -----------------------------------------------------------------------------
    # 2.3.2 — build (returns the root control)
    # -----------------------------------------------------------------------------
    def build(self):
        return self.root

    # -----------------------------------------------------------------------------
    # 2.3.3 — _do_cancel
    # -----------------------------------------------------------------------------
    def _do_cancel(self, e):
        print("[LOGIN] Cancel clicked")
        try:
            if self.on_cancel:
                self.on_cancel()
        except Exception as ex:
            print(f"[LOGIN] cancel handler failed: {ex}")

    # -----------------------------------------------------------------------------
    # 2.3.4 — _set_status (inline message under fields)
    # -----------------------------------------------------------------------------
    def _set_status(self, message, color=ft.Colors.RED_500):
        try:
            if self.status_label is not None:
                self.status_label.value = message or ""
                self.status_label.color = color
            self._safe_update()
        except Exception:
            pass

    # -----------------------------------------------------------------------------
    # 2.3.5 — _do_login (main authentication flow)
    # -----------------------------------------------------------------------------
    def _do_login(self, e):
        username = _safe_str(self.username_field.value)
        password = _safe_str(self.password_field.value)

        if not username:
            self._set_status("⚠️ Username is required.")
            return
        if not password:
            self._set_status("⚠️ Password is required.")
            return

        self._set_status("Verifying…", color=ft.Colors.BLUE_600)

        try:
            users = self.db.get_users()
        except Exception as ex:
            print(f"[LOGIN] get_users failed: {ex}")
            self._set_status(f"❌ Could not read users: {ex}")
            return

        if not users:
            self._set_status(
                "❌ No users found. Contact your administrator.")
            return

        # ---- Find user by username (case-insensitive) ----
        match = None
        for u in users:
            if _safe_str(u.get("username")).lower() == username.lower():
                match = u
                break

        if match is None:
            self._set_status("❌ Invalid username or password.")
            print(f"[LOGIN] No match for username='{username}'")
            return

        # ---- Check password ----
        stored_hash = _safe_str(match.get("password_hash", ""))
        if not stored_hash:
            self._set_status("❌ Account has no password set.")
            return

        input_hash = _hash_password(password)
        if input_hash != stored_hash:
            self._set_status("❌ Invalid username or password.")
            print(f"[LOGIN] Wrong password for '{username}'")
            return

        # ---- Success ----
        print(f"[LOGIN] ✅ Success: {username} "
              f"(role={match.get('role', '?')})")

        # Build a clean user dict to pass to the app
        user = dict(match)
        # Remove the password hash before storing in session/state
        user.pop("password_hash", None)

        # ---- Update last_login timestamp (best-effort) ----
        try:
            if hasattr(self.db, "update_user"):
                try:
                    self.db.update_user(user["id"],
                                        last_login=datetime.now().isoformat())
                except TypeError:
                    self.db.update_user(user["id"], {
                        "last_login": datetime.now().isoformat()
                    })
        except Exception as ex:
            print(f"[LOGIN] last_login update failed: {ex}")

        # ---- Log activity (best-effort) ----
        try:
            self.db.log_activity(user["id"], "login", "User logged in")
        except Exception as ex:
            print(f"[LOGIN] log_activity failed: {ex}")

        # ---- Notify parent ----
        try:
            if self.on_login_success:
                self.on_login_success(user)
        except Exception as ex:
            traceback.print_exc()
            self._set_status(f"❌ Login handler failed: {ex}")

    # -----------------------------------------------------------------------------
    # 2.3.6 — _safe_update (never raises)
    # -----------------------------------------------------------------------------
    def _safe_update(self):
        try:
            self.page.update()
        except Exception:
            pass