# =================================================================================
# SECTION 2 (FLET 1.0.0 VERSION) — LOGIN VIEW
# =================================================================================
# v1.9 — 2026-10-06
#   • Session helpers now use Flet 1.0.3's page.session.store
#     (client_storage was removed in Flet 1.0.3)
#   • Everything else identical to v1.8
# =================================================================================

import asyncio
import hashlib
import json
import time
import traceback
import uuid
from datetime import datetime

import flet as ft

try:
    from core.captcha import (
        generate_math_captcha,
        verify_math_captcha,
        invalidate_captcha,
    )
except ImportError:
    print("[LOGIN] captcha.py missing — running without CAPTCHA")

    def generate_math_captcha(sid):
        return {"question": "0 + 0", "session_id": sid, "expires_in": 300}

    def verify_math_captcha(sid, ans):
        return True, "ok"

    def invalidate_captcha(sid):
        return None


_SESSION_KEY = "alhudha_admin_session"
_SESSION_TTL = 8 * 3600


# =================================================================================
# 2.1 — Password hash helper
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
# 2.3 — Session helpers (v1.9 — page.session.store)
# =================================================================================
def save_session_to_storage(page, user: dict):
    """Save user session to Flet's per-session store (Flet 1.0.3)."""
    try:
        uid = _safe_str(user.get("id", ""))
        if not uid:
            return
        page.session.store.set("admin_user_id", uid)
        page.session.store.set("admin_username",
                               _safe_str(user.get("username", "")))
        page.session.store.set("admin_role",
                               _safe_str(user.get("role", "")))
        print(f"[LOGIN] Session saved to page.session.store: {uid}")
    except Exception as ex:
        print(f"[LOGIN] page.session.store write failed: {ex}")
        # Legacy fallback
        try:
            storage = getattr(page, "client_storage", None)
            if storage is not None:
                payload = {
                    "user_id": _safe_str(user.get("id", "")),
                    "username": _safe_str(user.get("username", "")),
                    "role": _safe_str(user.get("role", "")),
                    "expires_at": time.time() + _SESSION_TTL,
                }
                storage.set(_SESSION_KEY, json.dumps(payload))
                print("[LOGIN] Session saved via client_storage fallback")
        except Exception as e2:
            print(f"[LOGIN] client_storage fallback failed: {e2}")


def load_session_from_storage(page):
    """Load saved session from Flet's per-session store."""
    try:
        if page.session.store.contains_key("admin_user_id"):
            uid = page.session.store.get("admin_user_id")
            if uid:
                return {
                    "user_id": uid,
                    "username": page.session.store.get("admin_username", ""),
                    "role": page.session.store.get("admin_role", ""),
                }
    except Exception as ex:
        print(f"[LOGIN] page.session.store read failed: {ex}")

    # Legacy fallback
    try:
        storage = getattr(page, "client_storage", None)
        if storage is None:
            return None
        raw = storage.get(_SESSION_KEY)
        if not raw:
            return None
        data = json.loads(raw)
        if time.time() > data.get("expires_at", 0):
            try:
                storage.remove(_SESSION_KEY)
            except Exception:
                pass
            return None
        return data
    except Exception as ex:
        print(f"[LOGIN] client_storage read failed: {ex}")
        return None


def clear_session_from_storage(page):
    """Clear saved session."""
    try:
        for k in ("admin_user_id", "admin_username", "admin_role"):
            try:
                page.session.store.remove(k)
            except Exception:
                pass
        print("[LOGIN] Session cleared (page.session.store)")
    except Exception as ex:
        print(f"[LOGIN] clear failed: {ex}")
    # Legacy fallback
    try:
        storage = getattr(page, "client_storage", None)
        if storage is not None:
            storage.remove(_SESSION_KEY)
    except Exception:
        pass


# =================================================================================
# 2.4 — CLASS: LoginView
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

        self.captcha_session_id = str(uuid.uuid4())
        self.captcha_question_label = None
        self.captcha_answer_field = None

        self._build()

    def _build(self):
        company_name = "Alhudha Haj Travel System"
        try:
            if (hasattr(self.db, "company_settings")
                    and not self.db.company_settings.empty):
                raw = self.db.company_settings.iloc[0].get(
                    "company_name", "")
                if raw:
                    company_name = str(raw)
        except Exception:
            pass

        back_bar = ft.Container(
            content=ft.Row([
                ft.TextButton(
                    content=ft.Row([
                        ft.Icon(ft.Icons.ARROW_BACK, size=16,
                                color="#1e3c72"),
                        ft.Text("Back to Home", size=12,
                                color="#1e3c72",
                                weight=ft.FontWeight.BOLD),
                    ], spacing=4, tight=True),
                    on_click=self._go_home,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=8),
                        padding=ft.Padding.symmetric(
                            horizontal=10, vertical=6)),
                ),
            ], alignment=ft.MainAxisAlignment.START),
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        )

        logo = ft.Image(
            src="/static/logo.png",
            width=100, height=100,
            fit=ft.BoxFit.CONTAIN,
            error_content=ft.Text("🏆", size=56),
        )

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

        self.captcha_question_label = ft.Text(
            "Loading…",
            size=18,
            weight=ft.FontWeight.BOLD,
            color="#1e3c72",
            text_align=ft.TextAlign.CENTER,
        )

        captcha_refresh_btn = ft.IconButton(
            icon=ft.Icons.REFRESH,
            icon_color="#1e3c72",
            icon_size=20,
            tooltip="New question",
            on_click=lambda e: self._refresh_captcha(),
        )

        captcha_header = ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Row([
                        ft.Text("🔐", size=16),
                        ft.Text("Security Check", size=10,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.GREY_700),
                    ], spacing=4),
                    expand=True,
                ),
                captcha_refresh_btn,
            ], spacing=4),
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            bgcolor="#f8fafc",
            border=ft.Border.all(1, "#e2e8f0"),
            border_radius=8,
        )

        captcha_row = ft.Row([
            ft.Container(
                content=ft.Text("❓", size=20),
                width=36, height=40,
                alignment=ft.Alignment.CENTER,
            ),
            ft.Container(
                content=self.captcha_question_label,
                expand=True,
                alignment=ft.Alignment.CENTER_LEFT,
            ),
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        self.captcha_answer_field = ft.TextField(
            label="Answer",
            hint_text="Enter the answer",
            prefix_icon=ft.Icons.CALCULATE,
            keyboard_type=ft.KeyboardType.NUMBER,
            text_size=13,
            height=56,
            on_submit=lambda e: self._do_login(None),
        )

        captcha_block = ft.Column([
            captcha_header,
            ft.Container(height=4),
            captcha_row,
            ft.Container(height=4),
            self.captcha_answer_field,
        ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
           tight=True)

        self.status_label = ft.Text(
            "", size=11, color=ft.Colors.RED_500,
            text_align=ft.TextAlign.CENTER)

        self.login_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.LOGIN, size=18, color=ft.Colors.WHITE),
                ft.Text("Login", size=14,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE),
            ], spacing=8, alignment=ft.MainAxisAlignment.CENTER,
               tight=True),
            on_click=self._do_login,
            height=48,
            bgcolor="#1e3c72",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)),
            expand=True,
        )

        home_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.HOME, size=16, color=ft.Colors.WHITE),
                ft.Text("Home", size=13,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE),
            ], spacing=6, alignment=ft.MainAxisAlignment.CENTER,
               tight=True),
            on_click=self._go_home,
            height=48,
            bgcolor="#7f8c8d",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)),
            expand=True,
        )

        card = ft.Container(
            content=ft.Column([
                ft.Container(content=logo, width=100, height=100,
                             alignment=ft.Alignment.CENTER),
                ft.Container(height=8),
                title,
                subtitle,
                ft.Container(height=16),
                self.username_field,
                ft.Container(height=8),
                self.password_field,
                ft.Container(height=12),
                captcha_block,
                ft.Container(height=8),
                self.status_label,
                ft.Container(height=8),
                ft.Row([self.login_btn, home_btn], spacing=10),
                ft.Container(height=8),
                ft.Text(f"© {datetime.now().year} Alhudha Travel · v3.0",
                        size=10, color=ft.Colors.GREY_500,
                        text_align=ft.TextAlign.CENTER),
            ], spacing=6,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               tight=True),
            width=420,
            padding=ft.Padding.symmetric(horizontal=32, vertical=32),
            bgcolor=ft.Colors.WHITE,
            border_radius=18,
            border=ft.Border.all(1, "#e2e8f0"),
            shadow=ft.BoxShadow(
                blur_radius=24, spread_radius=2,
                color=ft.Colors.with_opacity(0.12, "#000000"),
                offset=ft.Offset(0, 8)),
        )

        self.root = ft.Container(
            content=ft.Column(
                controls=[
                    back_bar,
                    ft.Container(
                        content=ft.Column(
                            controls=[card],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        alignment=ft.Alignment.CENTER,
                        padding=ft.Padding.symmetric(vertical=20),
                    ),
                ],
                spacing=0,
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=True,
            bgcolor="#f0f2f5",
        )

        self._refresh_captcha()

    def build(self):
        return self.root

    def _go_home(self, e=None):
        print("[LOGIN] Back to Home clicked")

        try:
            if self.on_cancel:
                self.on_cancel()
                return
        except Exception as ex:
            print(f"[LOGIN] on_cancel failed: {ex}")

        async def _do():
            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url("/",
                                        web_only_window_name="_self")
                if asyncio.iscoroutine(r):
                    await r
                print("[LOGIN] OK web_only_window_name=_self")
                return
            except TypeError as te:
                print(f"[LOGIN] 1.0 param rejected: {te}")
            except Exception as e:
                print(f"[LOGIN] 1.0 param raised: {e}")

            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url("/", web_window_name="_self")
                if asyncio.iscoroutine(r):
                    await r
                print("[LOGIN] OK web_window_name=_self")
                return
            except Exception as e:
                print(f"[LOGIN] legacy param failed: {e}")

            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url("/")
                if asyncio.iscoroutine(r):
                    await r
                print("[LOGIN] OK bare — new tab")
                return
            except Exception as e:
                print(f"[LOGIN] bare failed: {e}")

        try:
            self.page.run_task(_do)
        except Exception as ex:
            print(f"[LOGIN] run_task failed: {ex}")

    def _refresh_captcha(self, e=None):
        try:
            challenge = generate_math_captcha(self.captcha_session_id)
            question = challenge.get("question", "? + ?")
            if self.captcha_question_label:
                self.captcha_question_label.value = f"{question} = ?"
            if self.captcha_answer_field:
                self.captcha_answer_field.value = ""
            self._safe_update()
        except Exception as ex:
            print(f"[LOGIN] captcha refresh failed: {ex}")

    def _verify_captcha(self) -> bool:
        try:
            user_answer = ""
            if self.captcha_answer_field:
                user_answer = _safe_str(self.captcha_answer_field.value)

            ok, reason = verify_math_captcha(
                self.captcha_session_id, user_answer)

            if ok:
                return True

            messages = {
                "empty": "⚠️ Please answer the security question.",
                "wrong": "❌ Wrong answer to the security question.",
                "expired": "⏱️ Security question expired. Try again.",
                "too_many_tries": "⛔ Too many wrong answers. Please reload.",
                "no_session": "⛔ Session error. Please reload.",
            }
            self._set_status(
                messages.get(reason, "❌ Security check failed."))
            self._refresh_captcha()
            return False
        except Exception as ex:
            print(f"[LOGIN] captcha verify error: {ex}")
            self._set_status("❌ Security check error.")
            return False

    def _set_status(self, message, color=ft.Colors.RED_500):
        try:
            if self.status_label is not None:
                self.status_label.value = message or ""
                self.status_label.color = color
            self._safe_update()
        except Exception:
            pass

    def _do_login(self, e):
        username = _safe_str(self.username_field.value)
        password = _safe_str(self.password_field.value)

        if not username:
            self._set_status("⚠️ Username is required.")
            return
        if not password:
            self._set_status("⚠️ Password is required.")
            return

        if not self._verify_captcha():
            return

        self._set_status("Verifying…", color=ft.Colors.BLUE_600)

        try:
            users = self.db.get_users()
        except Exception as ex:
            print(f"[LOGIN] get_users failed: {ex}")
            self._set_status(f"❌ Could not read users: {ex}")
            self._refresh_captcha()
            return

        if not users:
            self._set_status(
                "❌ No users found. Contact your administrator.")
            self._refresh_captcha()
            return

        match = None
        for u in users:
            if _safe_str(u.get("username")).lower() == username.lower():
                match = u
                break

        if match is None:
            self._set_status("❌ Invalid username or password.")
            self._refresh_captcha()
            return

        stored_hash = _safe_str(match.get("password_hash", ""))
        if not stored_hash:
            self._set_status("❌ Account has no password set.")
            self._refresh_captcha()
            return

        input_hash = _hash_password(password)
        if input_hash != stored_hash:
            self._set_status("❌ Invalid username or password.")
            self._refresh_captcha()
            return

        print(f"[LOGIN] Success: {username} "
              f"(role={match.get('role', '?')})")

        try:
            invalidate_captcha(self.captcha_session_id)
        except Exception:
            pass

        user = dict(match)
        user.pop("password_hash", None)

        # v1.9: save to page.session.store
        save_session_to_storage(self.page, user)

        try:
            if hasattr(self.db, "update_user"):
                try:
                    self.db.update_user(
                        user["id"],
                        last_login=datetime.now().isoformat())
                except TypeError:
                    self.db.update_user(user["id"], {
                        "last_login": datetime.now().isoformat()})
        except Exception as ex:
            print(f"[LOGIN] last_login update failed: {ex}")

        try:
            self.db.log_activity(user["id"], "login", "User logged in")
        except Exception as ex:
            print(f"[LOGIN] log_activity failed: {ex}")

        try:
            if self.on_login_success:
                self.on_login_success(user)
        except Exception as ex:
            traceback.print_exc()
            self._set_status(f"❌ Login handler failed: {ex}")

    def _safe_update(self):
        try:
            self.page.update()
        except Exception:
            pass
