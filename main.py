# =================================================================================
# SECTION 21 (FLET 1.0.0 VERSION) — MAIN APPLICATION (FastAPI + uvicorn)
# =================================================================================
# PATCHES APPLIED (v2.0):
#   • Switched from ft.run() to FastAPI + uvicorn for proper file download
#     support via FileResponse + Content-Disposition.
#   • Added /download/<filename> endpoint that serves files from
#     static/downloads/ with forced download headers.
#   • Destroyed-session patch applied at import time (narrow — only
#     swallows the harmless post-tab-close RuntimeError).
#   • Cloud-aware startup banner.
#   • Graceful SIGTERM handling.
# =================================================================================

import flet as ft
import flet.fastapi as flet_fastapi
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import uvicorn
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


def _boot_log(msg: str):
    print(f"[BOOT] {msg}", flush=True)


# =================================================================================
# 21.1.5 — MONKEY-PATCH: swallow destroyed-session errors ONLY
# =================================================================================
_PATCH_INSTALLED = False


def _patch_page_update():
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return
    Page = None
    for path in ("flet.controls.page", "flet.page", "flet"):
        try:
            mod = __import__(path, fromlist=["Page"])
            Page = getattr(mod, "Page", None)
            if Page is not None:
                _boot_log(f"Page class resolved from '{path}'")
                break
        except Exception:
            continue
    if Page is None:
        _boot_log("❌ Could not locate Page class")
        return
    try:
        _original_update = Page.update

        def _safe_update(self, *args, **kwargs):
            try:
                return _original_update(self, *args, **kwargs)
            except RuntimeError as ex:
                if "destroyed session" in str(ex).lower():
                    return None
                raise

        Page.update = _safe_update
        _PATCH_INSTALLED = True
        _boot_log("✅ Patched Page.update() (narrow)")
    except Exception as e:
        _boot_log(f"❌ Patch failed: {e}")


_patch_page_update()


# =================================================================================
# 21.2 — APP STATE
# =================================================================================
class AppState:
    db = None
    db_ready = False
    db_error = ""


def _init_db():
    """Initialize database with retry + backoff."""
    import time
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            AppState.db = HajDatabase()
            _boot_log(f"Database loaded successfully (attempt {attempt})")
            AppState.db_ready = True
            return
        except FileNotFoundError as ex:
            AppState.db_error = f"Data files not found: {ex}"
            _boot_log(f"DB init {attempt}/{max_retries} — FileNotFoundError: {ex}")
        except PermissionError as ex:
            AppState.db_error = f"Permission denied: {ex}"
            _boot_log(f"DB init {attempt}/{max_retries} — PermissionError: {ex}")
        except Exception as ex:
            AppState.db_error = str(ex)
            _boot_log(f"DB init {attempt}/{max_retries} — unexpected: {ex}")
            import traceback
            traceback.print_exc()
        if attempt < max_retries:
            backoff = 2 ** (attempt - 1)
            _boot_log(f"Retrying DB init in {backoff}s…")
            time.sleep(backoff)
    _boot_log(f"Database init failed after {max_retries} attempts")


def _install_signal_handlers():
    def _handler(signum, frame):
        _boot_log(f"Received signal {signum} — flushing DB…")
        try:
            if AppState.db is not None:
                flush = (getattr(AppState.db, "flush", None)
                         or getattr(AppState.db, "_save_all", None))
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


# =================================================================================
# 21.3 — FLET APP ENTRY POINT
# =================================================================================
def flet_main(page: ft.Page):
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

    if not AppState.db_ready:
        page.controls.clear()
        page.add(ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.STORAGE, size=64, color=ft.Colors.RED_400),
                ft.Text("Database unavailable", size=22,
                        weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
                ft.Text(
                    "The application could not open its data files.\n"
                    "If this is a cloud deployment, verify that a "
                    "persistent volume is attached and writable.",
                    size=12, color=ft.Colors.GREY_600,
                    text_align=ft.TextAlign.CENTER),
                ft.Container(height=8),
                ft.Text(f"Details: {AppState.db_error}",
                        size=11, color=ft.Colors.GREY_500,
                        selectable=True, text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
            padding=60, alignment=ft.Alignment.CENTER,
            expand=True, bgcolor="#fef2f2", border_radius=12,
            border=ft.Border.all(1, "#fecaca")))
        page.update()
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
            page=page, db=AppState.db,
            on_login_success=on_login_success,
            on_cancel=_close_window)
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
                AppState.db.log_activity(user['id'], "logout", "User logged out")
            except Exception:
                pass
        state["user"] = None
        show_login()

    def show_main_window(user):
        page.controls.clear()
        try:
            AppState.db.log_activity(user['id'], "login", "User logged in")
        except Exception:
            pass
        mw = MainWindowView(page, AppState.db, user, on_logout=on_logout)
        page.add(mw.build())
        try:
            page.update()
        except Exception as ex:
            _boot_log(f"show_main_window update failed: {ex}")

    show_login()


# =================================================================================
# 21.4 — FASTAPI SETUP + DOWNLOAD ENDPOINT
# =================================================================================
def _build_app() -> FastAPI:
    base_path = get_app_base_path()
    static_dir = os.path.join(base_path, "static")
    downloads_dir = os.path.join(static_dir, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)

    _boot_log(f"Static dir  : {static_dir}")
    _boot_log(f"Downloads   : {downloads_dir}")

    app = FastAPI(title="Alhudha Haj Travel System")

    # ---- File download endpoint ----
    # This is what send_file_to_user() will return URLs for.
    # FileResponse + Content-Disposition forces browser download.
    @app.get("/download/{filename}")
    async def download_file(filename: str):
        safe_name = os.path.basename(filename)  # prevent path traversal
        filepath = os.path.join(downloads_dir, safe_name)
        if not os.path.exists(filepath):
            _boot_log(f"Download 404: {filepath}")
            raise HTTPException(status_code=404,
                                detail=f"{safe_name} not found")
        _boot_log(f"Download OK: {safe_name}")
        return FileResponse(
            path=filepath,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"'
            })

    # ---- Flet app mounted at root ----
    # assets_dir is still passed for images/fonts used inside the UI,
    # but downloads now go through /download/ instead of /assets/.
    app.mount("/", flet_fastapi.app(flet_main, assets_dir=static_dir))

    return app


# =================================================================================
# 21.5 — ENTRY POINT
# =================================================================================
# Init DB and app at module level so uvicorn can import `app`
_init_db()
_install_signal_handlers()

base_path = get_app_base_path()
static_dir = os.path.join(base_path, "static")
os.makedirs(static_dir, exist_ok=True)
os.makedirs(os.path.join(static_dir, "downloads"), exist_ok=True)

_boot_log(f"Launching — host={APP_HOST} port={APP_PORT} platform={PLATFORM}")

print("=" * 66, flush=True)
print("🏆  Alhudha Haj Travel System — Web Edition", flush=True)
print(f"📦  Platform   : {PLATFORM}", flush=True)
print(f"📁  Base path  : {base_path}", flush=True)
print(f"📁  Data dir   : {os.path.join(base_path, 'data')}", flush=True)
print(f"📁  Static dir : {static_dir}", flush=True)
print(f"📁  Downloads  : {os.path.join(static_dir, 'downloads')}", flush=True)
print(f"🌐  Host       : {APP_HOST}", flush=True)
print(f"🚪  Port       : {APP_PORT}", flush=True)
print(f"🕐  Started    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
if os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
    print(f"💾  Volume     : {os.getenv('RAILWAY_VOLUME_MOUNT_PATH')}", flush=True)
print(f"🩹  Patch      : {'installed' if _PATCH_INSTALLED else 'NOT INSTALLED'}", flush=True)
print("=" * 66, flush=True)

# `app` must be module-level for uvicorn
app = _build_app()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=APP_HOST,
        port=APP_PORT,
        log_level="info",
    )