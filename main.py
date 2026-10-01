# =================================================================================
# SECTION 21 (FLET 1.0.0 VERSION) — MAIN APPLICATION
# =================================================================================
# Bootstrap for the web app:
#   1. Detect base folder
#   2. Print diagnostics
#   3. Instantiate HajDatabase
#   4. Show LoginView
#   5. On success, open MainWindowView
#   6. Handle logout → return to login
#
# CLOUD-READY (Railway / Render / Fly.io / VPS):
#   • Port is read from the PORT environment variable
#   • Host is bound to 0.0.0.0 so external connections work
#   • Falls back to port 8000 when PORT is not set (local dev)
#   • Serves /static/ folder so downloaded files work in the browser
#
# PATCHES APPLIED (v1.2):
#   21.1.A — Cloud environment detection (RAILWAY_ENVIRONMENT etc.) with a
#            clearer startup banner that names the platform.
#   21.1.B — Defensive window-close handler (`page.window.close()` is a
#            no-op on web — was raising AttributeError and killing the
#            Cancel button).
#   21.1.C — Flet 1.0 window sizing via `page.window.width/height`.
#   21.1.D — Friendly error page if HajDatabase() fails to init.
#   21.1.E — Graceful SIGTERM handling so Railway redeploys don't leave
#            half-written CSVs on the volume.
#   21.1.F — NEW: Monkey-patch Page.update() to swallow the "destroyed
#            session" RuntimeError that spams the log after every browser
#            tab close. Real bugs still propagate.
#   21.1.G — NEW: Ensure static/downloads/ exists at boot (used by
#            send_file_to_user for browser downloads).
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
APP_HOST = "0.0.0.0"          # MUST be 0.0.0.0 for cloud hosting


# ---- Cloud platform detection (best-effort) ----
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

log = logging.getLogger("main")


# =================================================================================
# 21.1.5 — MONKEY-PATCH: swallow destroyed-session errors  (PATCH 21.1.F)
# =================================================================================
# Flet destroys the session when the browser tab closes or the WebSocket
# drops. Background threads / scheduled tasks that outlive the session
# then crash on page.update() with:
#     RuntimeError: An attempt to fetch destroyed session.
#
# There's nothing to update in that case — the error is harmless. We
# swallow only THAT specific error; any other exception still raises.
# =================================================================================
def _patch_page_update():
    try:
        from flet.controls.page import Page
        _original_update = Page.update

        def _safe_page_update(self, *args, **kwargs):
            try:
                return _original_update(self, *args, **kwargs)
            except RuntimeError as ex:
                if "destroyed session" in str(ex).lower():
                    return None
                raise
            except Exception:
                # Any other update error during shutdown — also safe
                return None

        Page.update = _safe_page_update
        log.info("✅ Patched Page.update() to swallow destroyed-session errors")
    except Exception as e:
        log.warning("Could not patch Page.update(): %s", e)


# =================================================================================
# 21.2 — CLASS: HajTravelApp
# =================================================================================
class HajTravelApp:

    # -----------------------------------------------------------------------------
    # 21.2.1 — __init__
    # -----------------------------------------------------------------------------
    def __init__(self):
        base_path = get_app_base_path()
        data_dir = os.path.join(base_path, "data")
        static_dir = os.path.join(base_path, "static")
        downloads_dir = os.path.join(static_dir, "downloads")

        # Ensure downloads subfolder exists (PATCH 21.1.G)
        try:
            os.makedirs(downloads_dir, exist_ok=True)
        except Exception as e:
            print(f"[BOOT] Could not create downloads dir: {e}")

        print("=" * 66)
        print("🏆  Alhudha Haj Travel System — Web Edition")
        print(f"📦  Platform   : {PLATFORM}")
        print(f"📁  Base path  : {base_path}")
        print(f"📁  Data dir   : {data_dir}")
        print(f"📁  Static dir : {static_dir}")
        print(f"📁  Downloads  : {downloads_dir}")
        print(f"🌐  Host       : {APP_HOST}")
        print(f"🚪  Port       : {APP_PORT} (PORT env = "
              f"{os.getenv('PORT', '<unset>')})")
        print(f"🕐  Started    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
            print(f"💾  Volume     : {os.getenv('RAILWAY_VOLUME_MOUNT_PATH')}")
        print("=" * 66)

        # ---- DB init with retry + backoff ----
        self.db = None
        self._db_ready = False
        self._db_error = ""

        import time
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                self.db = HajDatabase()
                log.info("Database loaded successfully (attempt %d)", attempt)
                self._db_ready = True
                break
            except FileNotFoundError as ex:
                self._db_error = f"Data files not found: {ex}"
                log.error("DB init attempt %d/%d — FileNotFoundError: %s",
                          attempt, max_retries, ex)
            except PermissionError as ex:
                self._db_error = f"Permission denied: {ex}"
                log.error("DB init attempt %d/%d — PermissionError: %s "
                          "(check Railway Volume is writable)",
                          attempt, max_retries, ex)
            except Exception as ex:
                self._db_error = str(ex)
                log.error("DB init attempt %d/%d — unexpected: %s",
                          attempt, max_retries, ex, exc_info=True)

            if attempt < max_retries:
                backoff = 2 ** (attempt - 1)
                log.info("Retrying DB init in %ds…", backoff)
                time.sleep(backoff)

        if not self._db_ready:
            log.error("Database init failed after %d attempts", max_retries)

        # ---- Graceful SIGTERM handling ----
        self._install_signal_handlers()

    # -----------------------------------------------------------------------------
    # 21.2.1b — _install_signal_handlers
    # -----------------------------------------------------------------------------
    def _install_signal_handlers(self):
        def _handler(signum, frame):
            log.info("Received signal %s — flushing DB before exit…", signum)
            try:
                if self.db is not None:
                    flush = (getattr(self.db, "flush", None)
                             or getattr(self.db, "_save_all", None))
                    if callable(flush):
                        flush()
            except Exception as e:
                log.warning("DB flush on shutdown failed: %s", e)
            sys.exit(0)

        try:
            signal.signal(signal.SIGTERM, _handler)
            signal.signal(signal.SIGINT, _handler)
        except Exception as e:
            log.debug("Could not install signal handlers: %s", e)

    # =============================================================================
    # 21.2.2 — run(page)
    # =============================================================================
    def run(self, page: ft.Page):
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
                    log.debug("window.close() is a no-op in web mode")

        def show_login():
            page.controls.clear()
            login = LoginView(
                page=page,
                db=self.db,
                on_login_success=on_login_success,
                on_cancel=_close_window,
            )
            page.add(login.build())
            page.update()

        def on_login_success(user):
            state["user"] = user
            show_main_window(user)

        def on_logout():
            user = state.get("user")
            if user:
                try:
                    self.db.log_activity(
                        user['id'], "logout", "User logged out")
                except Exception as ex:
                    log.warning("Logout log failed: %s", ex)
            state["user"] = None
            show_login()

        def show_main_window(user):
            page.controls.clear()
            try:
                self.db.log_activity(
                    user['id'], "login", "User logged in")
            except Exception as ex:
                print(f"[LOGIN LOG] failed: {ex}")

            mw = MainWindowView(
                page, self.db, user, on_logout=on_logout)
            page.add(mw.build())
            page.update()

        show_login()

    # -----------------------------------------------------------------------------
    # 21.2.2b — _show_db_error
    # -----------------------------------------------------------------------------
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
        except Exception as ex:
            log.error("Could not render DB error page: %s", ex)


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

    # Install monkey-patch BEFORE ft.run so it applies to every session
    _patch_page_update()

    log.info("Launching Flet — view=WEB_BROWSER, host=%s, port=%s "
             "(platform=%s)", APP_HOST, APP_PORT, PLATFORM)

    ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        host=APP_HOST,
        port=APP_PORT,
        assets_dir=static_dir,
    )