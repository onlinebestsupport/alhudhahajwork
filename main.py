# =================================================================================
# SECTION 21 (FLET 1.0.0 VERSION) — MAIN APPLICATION (FastAPI + uvicorn)
# =================================================================================
# v2.15 — Async-aware "Back to Home" navigation
#   • page.launch_url() in Flet 1.0 is async → wrapped in run_task
#   • Falls through 5 attempts: UrlLauncher(_self) → page.launch_url(_self)
#     → UrlLauncher(default) → page.launch_url(default) → page.go
#   • All previous patches preserved (sessions, captcha, traveler portal)
# =================================================================================

import flet as ft
import flet.fastapi as flet_fastapi
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (FileResponse, RedirectResponse,
                               Response, JSONResponse)
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
import os
import sys
import signal
import logging
import shutil
import asyncio
import math
import traceback
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

SESSION_KEY = "alhudha_session_user_id"
TRAVELER_COOKIE = "alhudha_traveler_token"


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
# 21.1.4 — JSON SANITIZER
# =================================================================================
def _json_safe(obj):
    """Recursively convert NaN / Infinity to JSON-safe values."""
    if obj is None:
        return None
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, (int, bool)):
        return obj
    if isinstance(obj, str):
        if obj.lower() in ("nan", "inf", "-inf", "infinity", "-infinity"):
            return None
        return obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(x) for x in obj]
    try:
        import pandas as pd
        if isinstance(obj, pd.DataFrame):
            return _json_safe(obj.to_dict(orient="records"))
        if isinstance(obj, pd.Series):
            return _json_safe(obj.to_dict())
    except Exception:
        pass
    try:
        s = str(obj)
        if s.lower() in ("nan", "inf", "-inf", "infinity", "-infinity"):
            return None
        return s
    except Exception:
        return None


# =================================================================================
# 21.1.5 — MONKEY-PATCH: swallow destroyed-session errors only
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
    static_dir = ""
    logo_path = ""
    flet_assets_dir = ""


def _seed_volume_if_empty(base_path: str):
    try:
        data_dir = os.path.join(base_path, "data")
        seed_dir = os.path.join(base_path, "seed_data")
        os.makedirs(data_dir, exist_ok=True)

        if not os.path.isdir(seed_dir):
            print(f"[SEED] No seed_data folder at {seed_dir}", flush=True)
            return

        seeded = []
        for fname in os.listdir(seed_dir):
            if not fname.endswith(".csv"):
                continue
            dest = os.path.join(data_dir, fname)
            if os.path.exists(dest):
                continue
            shutil.copy2(os.path.join(seed_dir, fname), dest)
            seeded.append(fname)

        if seeded:
            print(f"[SEED] Copied {len(seeded)} file(s) to {data_dir}: "
                  f"{seeded}", flush=True)
        else:
            print(f"[SEED] Volume already populated — no seeding needed",
                  flush=True)
    except Exception as e:
        print(f"[SEED] Failed: {e}", flush=True)


def _init_db():
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
# 21.2.5 — ADMIN session helpers (with retry)
# =================================================================================
def _find_user_by_id(db, user_id):
    try:
        from core.traveler_portal import _to_list
        for u in _to_list(db.get_users()):
            if str(u.get("id")) == str(user_id):
                return dict(u)
    except Exception as e:
        print(f"[SESSION] find_user_by_id failed: {e}")
    return None


async def _save_session(page, user, max_retries=3):
    """Save user id to client_storage. Retries if storage is not ready yet."""
    if not user:
        return
    uid = user.get("id")
    if not uid:
        return

    for attempt in range(max_retries):
        try:
            storage = getattr(page, "client_storage", None)
            if storage is None:
                print(f"[SESSION] save: client_storage is None "
                      f"(attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(0.3)
                continue

            result = storage.set(SESSION_KEY, str(uid))
            if asyncio.iscoroutine(result):
                await result

            print(f"[SESSION] ✅ Saved user_id={uid} to client_storage")
            return
        except Exception as e:
            print(f"[SESSION] save attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(0.3)

    print(f"[SESSION] ❌ Save failed after {max_retries} attempts")


async def _load_session(page, max_retries=4):
    """
    Load user from client_storage. Retries with backoff because
    client_storage may not be initialized immediately on page load,
    especially after a browser refresh.
    """
    for attempt in range(max_retries):
        try:
            storage = getattr(page, "client_storage", None)
            if storage is None:
                print(f"[SESSION] load: client_storage is None "
                      f"(attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(0.3)
                continue

            result = storage.get(SESSION_KEY)
            if asyncio.iscoroutine(result):
                uid = await result
            else:
                uid = result

            print(f"[SESSION] load attempt {attempt + 1}: "
                  f"uid={uid!r}")

            if uid:
                user = _find_user_by_id(AppState.db, uid)
                if user:
                    print(f"[SESSION] ✅ Restored user "
                          f"'{user.get('username')}'")
                    return user
                else:
                    print(f"[SESSION] user_id={uid} no longer exists — "
                          f"clearing stale session")
                    try:
                        r = storage.remove(SESSION_KEY)
                        if asyncio.iscoroutine(r):
                            await r
                    except Exception:
                        pass
                    return None
            else:
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.4)
                    continue
                print("[SESSION] no saved session found")
                return None

        except Exception as e:
            print(f"[SESSION] load attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(0.3)

    print(f"[SESSION] ❌ Load failed after {max_retries} attempts")
    return None


async def _clear_session(page):
    try:
        storage = getattr(page, "client_storage", None)
        if storage is None:
            return
        result = storage.remove(SESSION_KEY)
        if asyncio.iscoroutine(result):
            await result
        print("[SESSION] ✅ Cleared saved session")
    except Exception as e:
        print(f"[SESSION] clear failed: {e}")


# =================================================================================
# 21.3 — FLET ADMIN APP ENTRY POINT
# =================================================================================
def flet_main(page: ft.Page):
    page.title = "Alhudha Haj Travel — Admin"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0

    # Responsive window
    try:
        page.window.width = 400
        page.window.height = 800
        page.window.resizable = True
    except Exception:
        try:
            page.window_width = 400
            page.window_height = 800
        except Exception:
            pass

    # Mobile CSS
    try:
        page.html_style = """
            html, body {
                margin: 0; padding: 0;
                width: 100%; height: 100%;
                overflow-x: hidden;
                -webkit-text-size-adjust: 100%;
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            }
            * { -webkit-tap-highlight-color: transparent; box-sizing: border-box; }
            flt-dialog, .flt-dialog { max-width: 100vw !important; }
            flt-view, .flt-view { overflow-x: hidden !important; }
        """
    except Exception:
        pass

    # DB failure UI
    if not AppState.db_ready:
        page.controls.clear()
        page.add(ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.STORAGE, size=64, color=ft.Colors.RED_400),
                ft.Text("Database unavailable", size=22,
                        weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
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

    # -----------------------------------------------------------------------------
    # [FIX v2.15] Navigate to / — async-aware for Flet 1.0
    # -----------------------------------------------------------------------------
    def _go_home_page():
        """
        Send the browser to / (public homepage).
        Handles Flet 1.0's async launch_url API.

        Attempt order:
          1. ft.UrlLauncher().launch_url("/", web_window_name="_self")
          2. page.launch_url("/", web_window_name="_self")
          3. ft.UrlLauncher().launch_url("/")  → new tab
          4. page.launch_url("/")               → new tab
          5. page.go("/")                       → Flet route
        """
        print("[NAV] Back to Home clicked → scheduling navigation")

        async def _do():
            # -- Attempt 1: UrlLauncher service with _self --
            try:
                launcher = ft.UrlLauncher()
                result = launcher.launch_url(
                    "/", web_window_name="_self")
                if asyncio.iscoroutine(result):
                    await result
                print("[NAV] ✅ UrlLauncher(_self) succeeded")
                return
            except Exception as e:
                print(f"[NAV] UrlLauncher(_self) failed: {e}")

            # -- Attempt 2: page.launch_url with _self --
            try:
                result = page.launch_url(
                    "/", web_window_name="_self")
                if asyncio.iscoroutine(result):
                    await result
                print("[NAV] ✅ page.launch_url(_self) succeeded")
                return
            except Exception as e:
                print(f"[NAV] page.launch_url(_self) failed: {e}")

            # -- Attempt 3: UrlLauncher default (new tab) --
            try:
                launcher = ft.UrlLauncher()
                result = launcher.launch_url("/")
                if asyncio.iscoroutine(result):
                    await result
                print("[NAV] ⚠️ UrlLauncher(default) opened new tab")
                return
            except Exception as e:
                print(f"[NAV] UrlLauncher(default) failed: {e}")

            # -- Attempt 4: page.launch_url default (new tab) --
            try:
                result = page.launch_url("/")
                if asyncio.iscoroutine(result):
                    await result
                print("[NAV] ⚠️ page.launch_url(default) opened new tab")
                return
            except Exception as e:
                print(f"[NAV] page.launch_url(default) failed: {e}")

            # -- Attempt 5: page.go (Flet route) --
            try:
                page.go("/")
                print("[NAV] ⚠️ page.go('/') attempted")
            except Exception as e:
                print(f"[NAV] page.go('/') failed: {e}")

        # Schedule on Flet's event loop
        try:
            page.run_task(_do)
        except Exception as e:
            print(f"[NAV] run_task failed: {e}")

    def show_login():
        page.controls.clear()
        login = LoginView(
            page=page, db=AppState.db,
            on_login_success=on_login_success,
            on_cancel=_go_home_page)      # ← Back to Home
        page.add(login.build())
        try:
            page.update()
        except Exception as ex:
            _boot_log(f"show_login update failed: {ex}")

    def on_login_success(user):
        state["user"] = user
        try:
            page.run_task(_save_session, page, user)
        except Exception as ex:
            print(f"[LOGIN] save_session run_task failed: {ex}")
        show_main_window(user)

    def on_logout():
        user = state.get("user")
        if user:
            try:
                AppState.db.log_activity(
                    user['id'], "logout", "User logged out")
            except Exception:
                pass
        state["user"] = None
        try:
            page.run_task(_clear_session, page)
        except Exception:
            pass
        show_login()

    def show_main_window(user):
        page.controls.clear()
        try:
            AppState.db.log_activity(
                user['id'], "login", "User logged in")
        except Exception:
            pass
        mw = MainWindowView(
            page, AppState.db, user, on_logout=on_logout)
        page.add(mw.build())
        try:
            page.update()
        except Exception as ex:
            _boot_log(f"show_main_window update failed: {ex}")

    async def _bootstrap():
        print("[SESSION] → Bootstrap starting...")
        try:
            restored = await _load_session(page)
        except Exception as ex:
            print(f"[SESSION] bootstrap load error: {ex}")
            traceback.print_exc()
            restored = None

        if restored:
            print(f"[SESSION] → Showing main window for "
                  f"'{restored.get('username')}'")
            state["user"] = restored
            show_main_window(restored)
        else:
            print("[SESSION] → No session — showing login")
            show_login()

    try:
        page.run_task(_bootstrap)
    except Exception as ex:
        print(f"[SESSION] run_task bootstrap failed: {ex}")
        show_login()


# =================================================================================
# 21.4 — FAVICON MIDDLEWARE
# =================================================================================
class FaviconOverrideMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, logo_path: str):
        super().__init__(app)
        self.logo_path = logo_path

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.lower().rstrip("/")
        favicon_paths = {
            "/favicon.ico", "/favicon.png",
            "/admin/favicon.ico", "/admin/favicon.png",
        }
        if path in favicon_paths and os.path.exists(self.logo_path):
            try:
                with open(self.logo_path, "rb") as f:
                    data = f.read()
                return Response(
                    content=data, media_type="image/png",
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache", "Expires": "0",
                    })
            except Exception as e:
                _boot_log(f"Favicon middleware error: {e}")
        return await call_next(request)


# =================================================================================
# 21.5 — FASTAPI SETUP
# =================================================================================
def _build_app() -> FastAPI:
    base_path = get_app_base_path()
    static_dir = os.path.join(base_path, "static")
    downloads_dir = os.path.join(static_dir, "downloads")
    index_html = os.path.join(static_dir, "index.html")
    traveler_html = os.path.join(static_dir, "traveler.html")
    logo_path = os.path.join(static_dir, "logo.png")
    flet_assets_dir = os.path.join(base_path, "flet_assets")

    os.makedirs(downloads_dir, exist_ok=True)
    os.makedirs(os.path.join(flet_assets_dir, "icons"), exist_ok=True)

    try:
        if os.path.exists(logo_path):
            fav = os.path.join(flet_assets_dir, "favicon.png")
            anim = os.path.join(flet_assets_dir, "icons",
                                "loading-animation.png")
            if not os.path.exists(fav):
                shutil.copy2(logo_path, fav)
            if not os.path.exists(anim):
                shutil.copy2(logo_path, anim)
    except Exception as e:
        _boot_log(f"Flet assets seed failed: {e}")

    AppState.static_dir = static_dir
    AppState.logo_path = logo_path
    AppState.flet_assets_dir = flet_assets_dir

    _boot_log(f"Base path       : {base_path}")
    _boot_log(f"Static dir      : {static_dir}")
    _boot_log(f"Flet assets dir : {flet_assets_dir}")

    app = FastAPI(title="Alhudha Haj Travel System")
    app.add_middleware(FaviconOverrideMiddleware, logo_path=logo_path)

    @app.exception_handler(Exception)
    async def _global_error_handler(request: Request, exc: Exception):
        _boot_log(f"❌ Unhandled error on {request.url.path}: {exc}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {exc}"})

    @app.get("/download/{filename}")
    async def download_file(filename: str):
        safe_name = os.path.basename(filename)
        filepath = os.path.join(downloads_dir, safe_name)
        if not os.path.exists(filepath):
            raise HTTPException(status_code=404,
                                detail=f"{safe_name} not found")
        return FileResponse(
            path=filepath, media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"'
            })

    @app.get("/api/frontpage")
    async def api_frontpage():
        try:
            from core.frontpage_config import load_config
            return _json_safe(load_config())
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/batches")
    async def api_batches():
        try:
            from core.frontpage_config import load_config, get_selected_batches
            from core.traveler_portal import _to_list
            cfg = load_config()
            all_batches = []
            if AppState.db_ready and AppState.db is not None:
                try:
                    all_batches = _to_list(AppState.db.get_batches())
                except Exception as e:
                    _boot_log(f"api_batches get_batches failed: {e}")
            selected = get_selected_batches(cfg, all_batches)
            packages = []
            for b in selected:
                try:
                    price_val = float(b.get("price", 0) or 0)
                    if math.isnan(price_val) or math.isinf(price_val):
                        price_val = 0.0
                except Exception:
                    price_val = 0.0
                try:
                    seats_val = int(b.get("total_seats", 0) or 0)
                except Exception:
                    seats_val = 0
                packages.append({
                    "id": str(b.get("id", "")),
                    "name": str(b.get("batch_name", "Package")),
                    "description": str(b.get("description", "")
                                       or "Complete Haj/Umrah package"),
                    "price": price_val,
                    "departure_date": str(b.get("departure_date", "") or ""),
                    "return_date": str(b.get("return_date", "") or ""),
                    "year": str(b.get("year", "") or ""),
                    "tour_type_name": str(b.get("tour_type_name", "") or ""),
                    "status": str(b.get("status", "") or ""),
                    "total_seats": seats_val,
                })
            return _json_safe({"success": True, "batches": packages,
                               "count": len(packages)})
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    # ---- CAPTCHA endpoints ----
    from pydantic import BaseModel

    class CaptchaVerifyPayload(BaseModel):
        session_id: str
        answer: str

    @app.get("/api/captcha/new")
    async def captcha_new(session_id: str = ""):
        try:
            from core.traveler_portal import get_captcha_new
            return get_captcha_new(session_id)
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "detail": str(e)}

    @app.post("/api/captcha/verify")
    async def captcha_verify(payload: CaptchaVerifyPayload):
        try:
            from core.traveler_portal import check_captcha_answer
            return check_captcha_answer(payload.session_id, payload.answer)
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "reason": "error", "detail": str(e)}

    # ---- Traveler portal endpoints ----
    @app.get("/traveler")
    async def traveler_portal_page():
        if os.path.exists(traveler_html):
            return FileResponse(traveler_html, media_type="text/html")
        raise HTTPException(status_code=404,
                            detail="Traveler portal not found")

    @app.post("/api/traveler/login")
    async def traveler_login(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400,
                                detail="Invalid JSON body")

        passport_no = str(body.get("passport_no", "")).strip()
        pin = str(body.get("pin", "")).strip()
        captcha_session_id = str(body.get("captcha_session_id", "")).strip()
        captcha_answer = str(body.get("captcha_answer", "")).strip()

        try:
            from core.traveler_portal import (
                authenticate_traveler_with_captcha, create_session)
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

        if not AppState.db_ready or AppState.db is None:
            raise HTTPException(status_code=503,
                                detail="Database unavailable")

        try:
            traveler, err = authenticate_traveler_with_captcha(
                AppState.db, passport_no, pin,
                captcha_session_id, captcha_answer)
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

        if err:
            if err.startswith("captcha:"):
                reason = err.split(":", 1)[1]
                msg_map = {
                    "empty": "Please answer the security question.",
                    "wrong": "Wrong answer to the security question.",
                    "expired": "Security question expired. Please try again.",
                    "too_many_tries": "Too many wrong answers. Please reload.",
                    "no_session": "Session error. Please reload.",
                }
                raise HTTPException(
                    status_code=400,
                    detail=msg_map.get(reason,
                                       "Security check failed."))
            raise HTTPException(status_code=401, detail=err)

        try:
            token = create_session(traveler)
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500,
                                detail=f"Session create failed: {e}")

        _boot_log(f"Traveler login OK: {traveler.get('id')}")

        response = Response(
            content='{"success": true}',
            media_type="application/json")
        response.set_cookie(
            TRAVELER_COOKIE, token,
            max_age=8 * 3600,
            httponly=False,
            samesite="lax",
            path="/")
        return response

    @app.post("/api/traveler/logout")
    async def traveler_logout(request: Request):
        token = request.cookies.get(TRAVELER_COOKIE, "")
        try:
            from core.traveler_portal import destroy_session
            destroy_session(token)
        except Exception:
            pass
        response = Response(
            content='{"success": true}',
            media_type="application/json")
        response.delete_cookie(TRAVELER_COOKIE, path="/")
        return response

    @app.get("/api/traveler/me")
    async def traveler_me(request: Request):
        try:
            token = request.cookies.get(TRAVELER_COOKIE, "")
            if not token:
                raise HTTPException(status_code=401,
                                    detail="Not logged in")

            from core.traveler_portal import (
                verify_session, build_traveler_view, _to_list)

            session = verify_session(token)
            if not session:
                raise HTTPException(status_code=401,
                                    detail="Session expired")

            if not AppState.db_ready or AppState.db is None:
                raise HTTPException(status_code=503,
                                    detail="Database unavailable")

            travelers = _to_list(AppState.db.get_travelers())
            traveler = None
            for t in travelers:
                if str(t.get("id", "")) == session.get("traveler_id"):
                    traveler = dict(t)
                    break

            if not traveler:
                raise HTTPException(status_code=404,
                                    detail="Traveler not found")

            data = build_traveler_view(AppState.db, traveler)
            safe_data = _json_safe(data)
            return {"success": True, "data": safe_data}

        except HTTPException:
            raise
        except Exception as e:
            _boot_log(f"❌ /api/traveler/me failed: {e}")
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Server error: {type(e).__name__}: {e}")

    @app.get("/api/traveler/document/{doc_key}")
    async def traveler_document(doc_key: str, request: Request):
        try:
            token = request.cookies.get(TRAVELER_COOKIE, "")
            if not token:
                raise HTTPException(status_code=401,
                                    detail="Not logged in")

            from core.traveler_portal import (
                verify_session, get_document_path, _to_list)

            session = verify_session(token)
            if not session:
                raise HTTPException(status_code=401,
                                    detail="Session expired")

            if not AppState.db_ready or AppState.db is None:
                raise HTTPException(status_code=503,
                                    detail="Database unavailable")

            travelers = _to_list(AppState.db.get_travelers())
            traveler = None
            for t in travelers:
                if str(t.get("id", "")) == session.get("traveler_id"):
                    traveler = dict(t)
                    break

            if not traveler:
                raise HTTPException(status_code=404,
                                    detail="Traveler not found")

            path = get_document_path(AppState.db, traveler, doc_key)
            if not path or not os.path.exists(path):
                raise HTTPException(status_code=404,
                                    detail=f"Document '{doc_key}' not found")

            low = path.lower()
            if low.endswith(".pdf"):
                media_type = "application/pdf"
            elif low.endswith(".png"):
                media_type = "image/png"
            elif low.endswith(".gif"):
                media_type = "image/gif"
            elif low.endswith(".bmp"):
                media_type = "image/bmp"
            else:
                media_type = "image/jpeg"

            return FileResponse(path, media_type=media_type)

        except HTTPException:
            raise
        except Exception as e:
            _boot_log(f"❌ /api/traveler/document/{doc_key} failed: {e}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    _boot_log("Traveler portal endpoints registered")

    admin_app = flet_fastapi.app(flet_main, assets_dir=flet_assets_dir)
    app.mount("/admin", admin_app)
    _boot_log(f"Mounted Flet admin at /admin (assets_dir={flet_assets_dir})")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    _boot_log("Mounted /static for logo + assets")

    @app.get("/")
    async def root():
        if os.path.exists(index_html):
            return FileResponse(index_html, media_type="text/html")
        return RedirectResponse(url="/admin")

    return app


# =================================================================================
# 21.6 — ENTRY POINT
# =================================================================================
base_path = get_app_base_path()

static_dir = os.path.join(base_path, "static")
os.makedirs(static_dir, exist_ok=True)
os.makedirs(os.path.join(static_dir, "downloads"), exist_ok=True)
os.makedirs(os.path.join(base_path, "data"), exist_ok=True)
os.makedirs(os.path.join(base_path, "flet_assets", "icons"), exist_ok=True)

_boot_log(f"Launching — host={APP_HOST} port={APP_PORT} platform={PLATFORM}")

print("=" * 66, flush=True)
print("🏆  Alhudha Haj Travel System — Web Edition", flush=True)
print(f"📦  Platform       : {PLATFORM}", flush=True)
print(f"📁  Base path      : {base_path}", flush=True)
print(f"📁  Data dir       : {os.path.join(base_path, 'data')}", flush=True)
print(f"📁  Static dir     : {static_dir}", flush=True)
print(f"🌐  Host           : {APP_HOST}", flush=True)
print(f"🚪  Port           : {APP_PORT}", flush=True)
print(f"🕐  Started        : "
      f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
if os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
    print(f"💾  Volume         : "
          f"{os.getenv('RAILWAY_VOLUME_MOUNT_PATH')}", flush=True)
print(f"🩹  Patch          : "
      f"{'installed' if _PATCH_INSTALLED else 'NOT INSTALLED'}", flush=True)
print(f"🏠  Front page     : http://{APP_HOST}:{APP_PORT}/", flush=True)
print(f"🔐  Admin app      : http://{APP_HOST}:{APP_PORT}/admin", flush=True)
print(f"👤  Traveler app   : http://{APP_HOST}:{APP_PORT}/traveler", flush=True)
print("=" * 66, flush=True)

_seed_volume_if_empty(base_path)
_init_db()
_install_signal_handlers()

app = _build_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=APP_HOST,
        port=APP_PORT,
        log_level="info",
    )
