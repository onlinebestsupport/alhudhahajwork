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
# =================================================================================

import flet as ft
import os
import sys
from datetime import datetime

from core.helpers import get_app_base_path
from core.database import HajDatabase
from core.login_view import LoginView
from core.main_window import MainWindowView


# =================================================================================
# 21.2 — CLASS: HajTravelApp
# =================================================================================
class HajTravelApp:

    def __init__(self):
        # ---- 21.2.1.1 — Diagnostics ----
        base_path = get_app_base_path()
        print("=" * 60)
        print("🏆 Alhudha Haj Travel System — Web Edition")
        print(f"📁 Base path: {base_path}")
        print(f"📁 Data dir : {os.path.join(base_path, 'data')}")
        print(f"🕐 Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # ---- 21.2.1.2 — Instantiate DB once (shared across sessions) ----
        try:
            self.db = HajDatabase()
            print("✅ Database loaded successfully")
        except Exception as ex:
            print(f"❌ Database init failed: {ex}")
            raise

    # =============================================================================
    # 21.2.2 — Show login / main window
    # =============================================================================
    def run(self, page: ft.Page):
        """Main entry point called by ft.run()."""
        page.title = "Alhudha Haj Travel System"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.padding = 0
        page.window_width = 1400
        page.window_height = 900

        state = {"user": None}

        # ---- Show login screen ----
        def show_login():
            page.controls.clear()
            login = LoginView(
                page=page,
                db=self.db,
                on_login_success=on_login_success,
                on_cancel=lambda: page.window.close(),
            )
            page.add(login.build())
            page.update()

        # ---- Login success ----
        def on_login_success(user):
            state["user"] = user
            show_main_window(user)

        # ---- Logout → back to login ----
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

        # ---- Main window ----
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

        # ---- Start ----
        show_login()


# =================================================================================
# 21.3 — ENTRY POINT
# =================================================================================
def main(page: ft.Page):
    app = HajTravelApp()
    app.run(page)


if __name__ == "__main__":
    ft.run(main, view=ft.AppView.WEB_BROWSER)