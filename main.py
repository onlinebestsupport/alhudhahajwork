# =================================================================================
# SECTION 21 (FLET 1.0.0 VERSION) — MAIN APPLICATION
# =================================================================================
# PATCHES APPLIED (v1.4):
#   21.1.A — Cloud environment detection
#   21.1.B — Defensive window-close handler
#   21.1.C — Flet 1.0 window sizing
#   21.1.D — Friendly DB error page
#   21.1.E — Graceful SIGTERM handling
#   21.1.F — Suppress destroyed-session errors ONLY (narrow patch)
#            — All other exceptions now propagate so UI bugs are visible
#   21.1.G — Ensure static/downloads/ exists at boot
# =================================================================================

import flet as ft
import os
import sys
import signal
import logging
from datetime import datetime

from core.helpers import get_app_base_path
from core.database import HajDatabase
from core.login_view import LoginView
from core.main_window import MainWindowView


# =================================================================================
# 21.1 — CONFIGURATION
# =================================================================================
APP_PORT = int(os.getenv("PORT", 8000))
APP_HOST = "0.0.0.0"


def _detect_platform() -> str:
    env = os.environ
    if env.get("RAILWAY_ENVIRONMENT") or env.get("RAILWAY_PROJECT_ID"):
        return "Railway"
    if env.get("RENDER") or env.get("RENDER_SERVICE_ID"):
        return "Render"
    if env.get("FLY_APP_NAME"):
        return "Fly.io"
    if env.get("DYNO"):
        return "Heroku"
    if env.get("PORT"):
        return "PaaS (PORT env)"
    return "Local / Desktop"


PLATFORM = _detect_platform()
IS_CLOUD = PLATFORM != "Local / Desktop"


# Simple print-based logger — always shows on Railway
def _boot_log(msg: str):
    print(f"[BOOT] {msg}", flush=True)


# =================================================================================
# 21.1.5 — MONKEY-PATCH: swallow destroyed-session errors ONLY
# =================================================================================
# Flet destroys the session when the browser tab closes or the WebSocket
# drops. Background threads then crash on page.update() with:
#     RuntimeError: An attempt to fetch destroyed session.
#
# The patch below swallows ONLY that specific error. Any other exception
# (dialog bugs, control errors, etc.) propagates normally — so we don't
# silently hide real UI problems.
#
# Runs at MODULE IMPORT TIME so every session is covered.
# =================================================================================
_PATCH_INSTALLED = False


def _patch_page_update():
    """Patch Page.update() to swallow ONLY destroyed-session RuntimeErrors.

    All other exceptions propagate normally so UI bugs aren't hidden.
    """
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return

    # Try multiple possible import paths — Flet's internals shift
    # between patch releases within the same major version.
    Page = None
    import_errors = []
    for path in ("flet.controls.page", "flet.page", "flet"):
        try:
            mod = __import__(path, fromlist=["Page"])
            Page = getattr(mod, "Page", None)
            if Page is not None:
                _boot_log(f"Page class resolved from '{path}'")
                break
        except Exception as e:
            import_errors.append(f"{path}: {e}")

    if Page is None:
        _boot_log(f"❌ Could not locate Page class. Tried: {import_errors}")
        return

    try:
        _original_update = Page.update

        def _safe_update(self, *args, **kwargs):
            try:
                return _original_update(self, *args, **kwargs)
            except RuntimeError as ex:
                # ONLY swallow the harmless post-tab-close error.
                # Real bugs (dialog crashes, control errors) still raise
                # so they surface in the logs.
                if "destroyed session" in str(ex).lower():
                    return None
                raise
            # No catch-all — let every other exception surface

        Page.update = _safe_update
        _PATCH_INSTALLED = True
        _boot_log("✅ Patched Page.update() (narrow — only swallows "
                  "destroyed-session errors; other bugs will surface)")
    except Exception as e:
        _boot_log(f"❌ Patch failed: {e}")


# Apply at import time — runs the instant Python loads this module
_patch_page_update()


# =================================================================================
# 21.2 — CLASS: HajTravelApp
# =================================================================================
class HajTravelApp:

    def __init__(self):
        base_path = get_app_base_path()
        data_dir = os.path.join(base_path, "data")
        static_dir = os.path.join(base_path, "static")
        downloads_dir = os.path.join(static_dir, "downloads")

        try:
            os.makedirs(downloads_dir, exist_ok=True)
        except Exception as e:
            _boot_log(f"Could not create downloads dir: {e}")

        print("=" * 66, flush=True)
        print("🏆  Alhudha Haj Travel System — Web Edition", flush=True)
        print(f"📦  Platform   : {PLATFORM}", flush=True)
        print(f"📁  Base path  : {base_path}", flush=True)
        print(f"📁  Data dir   : {data_dir}", flush=True)
        print(f"📁  Static dir : {static_dir}", flush=True)
        print(f"📁  Downloads  : {downloads_dir}", flush=True)
        print(f"🌐  Host       : {APP_HOST}", flush=True)
        print(f"🚪  Port       : {APP_PORT} (PORT env = "
              f"{os.getenv('PORT', '<unset>')})", flush=True)
        print(f"🕐  Started    : "
              f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
        if os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
            print(f"💾  Volume     : "
                  f"{os.getenv('RAILWAY_VOLUME_MOUNT_PATH')}", flush=True)
        print(f"🩹  Patch      : "
              f"{'installed' if _PATCH_INSTALLED else 'NOT INSTALLED'}",
              flush=True)
        print("=" * 66, flush=True)

        # ---- DB init with retry + backoff ----
        self.db = None
        self._db_ready = False
        self._db_error = ""

        import time
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                self.db = HajDatabase()
                _boot_log(f"Database loaded successfully "
                          f"(attempt {attempt})")
                self._db_ready = True
                break
            except FileNotFoundError as ex:
                self._db_error = f"Data files not found: {ex}"
                _boot_log(f"DB init {attempt}/{max_retries} — "
                          f"FileNotFoundError: {ex}")
            except PermissionError as ex:
                self._db_error = f"Permission denied: {ex}"
                _boot_log(f"DB init {attempt}/{max_retries} — "
                          f"PermissionError: {ex}")
            except Exception as ex:
                self._db_error = str(ex)
                _boot_log(f"DB init {attempt}/{max_retries} — "
                          f"unexpected: {ex}")
                import traceback
                traceback.print_exc()

            if attempt < max_retries:
                backoff = 2 ** (attempt - 1)
                _boot_log(f"Retrying DB init in {backoff}s…")
                time.sleep(backoff)

        if not self._db_ready:
            _boot_log(f"Database init failed after {max_retries} attempts")

        self._install_signal_handlers()

    # -----------------------------------------------------------------------------
    # _install_signal_handlers
    # -----------------------------------------------------------------------------
    def _install_signal_handlers(self):
        def _handler(signum, frame):
            _boot_log(f"Received signal {signum} — flushing DB…")
            try:
                if self.db is not None:
                    flush = (getattr(self.db, "flush", None)
                             or getattr(self.db, "_save_all", None))
                    if callable(flush):
                        flush()
            except Exception as e:
                _boot_log(f"DB flush on shutdown failed: {e}")
            sys.exit(0)

        try:
            signal.signal(signal.SIGTERM, _handler)
            signal.signal(signal.SIGINT, _handler)
        except Exception as e:
            _boot_log(f"Could not install signal handlers: {e}")

    # =============================================================================
    # run(page)
    # =============================================================================
    def run(self, page: ft.Page):
        # Re-apply patch in case module-level patch was skipped
        _patch_page_update()

        page.title = "Alhudha Haj Travel System"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.padding = 0

        try:
            page.window.width = 1400
            page.window.height = 900
        except Exception:
            try:
                page.window_width = 1400
                page.window_height = 900
            except Exception:
                pass

        if not self._db_ready:
            self._show_db_error(page)
            return

        state = {"user": None}

        def _close_window():
            try:
                page.window.close()
            except Exception:
                try:
                    page.window_close()
                except Exception:
                    pass

        def show_login():
            page.controls.clear()
            login = LoginView(
                page=page,
                db=self.db,
                on_login_success=on_login_success,
                on_cancel=_close_window,
            )
            page.add(login.build())
            try:
                page.update()
            except Exception as ex:
                _boot_log(f"show_login update failed: {ex}")

        def on_login_success(user):
            state["user"] = user
            show_main_window(user)

        def on_logout():
            user = state.get("user")
            if user:
                try:
                    self.db.log_activity(
                        user['id'], "logout", "User logged out")
                except Exception:
                    pass
            state["user"] = None
            show_login()

        def show_main_window(user):
            page.controls.clear()
            try:
                self.db.log_activity(
                    user['id'], "login", "User logged in")
            except Exception:
                pass

            mw = MainWindowView(
                page, self.db, user, on_logout=on_logout)
            page.add(mw.build())
            try:
                page.update()
            except Exception as ex:
                _boot_log(f"show_main_window update failed: {ex}")

        show_login()

    def _show_db_error(self, page: ft.Page):
        try:
            page.controls.clear()
            page.add(ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.STORAGE, size=64,
                            color=ft.Colors.RED_400),
                    ft.Text("Database unavailable", size=22,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.RED_700),
                    ft.Text(
                        "The application could not open its data files.\n"
                        "If this is a cloud deployment, verify that a "
                        "persistent volume is attached and writable.",
                        size=12, color=ft.Colors.GREY_600,
                        text_align=ft.TextAlign.CENTER),
                    ft.Container(height=8),
                    ft.Text(f"Details: {getattr(self, '_db_error', '')}",
                            size=11, color=ft.Colors.GREY_500,
                            selectable=True,
                            text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=12),
                padding=60, alignment=ft.Alignment.CENTER,
                expand=True, bgcolor="#fef2f2",
                border_radius=12,
                border=ft.Border.all(1, "#fecaca")))
            page.update()
        except Exception:
            pass


# =================================================================================
# 21.3 — ENTRY POINT
# =================================================================================
def main(page: ft.Page):
    app = HajTravelApp()
    app.run(page)


if __name__ == "__main__":
    static_dir = os.path.join(get_app_base_path(), "static")
    os.makedirs(static_dir, exist_ok=True)
    os.makedirs(os.path.join(static_dir, "downloads"), exist_ok=True)

    _boot_log(f"Launching Flet — host={APP_HOST} port={APP_PORT} "
              f"platform={PLATFORM}")

    ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        host=APP_HOST,
        port=APP_PORT,
        assets_dir=static_dir,
    )