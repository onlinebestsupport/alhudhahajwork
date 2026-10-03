# =================================================================================
# users_tab.py — MINIMAL SCREEN TEST (no DB, no logic, no scrollables)
# =================================================================================
import flet as ft


class UsersTab(ft.Column):

    def __init__(self, page, db=None, current_user=None):
        super().__init__()

        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}

        # NO scroll, NO expand — just plain content
        self.spacing = 12

        print("[USERS-TEST] __init__ called")

        self.controls = [
            ft.Container(
                content=ft.Text("👤 USER MANAGEMENT TEST",
                                size=18, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE),
                padding=20,
                bgcolor="#1e3a8a",
                border_radius=12,
            ),

            ft.Row([
                ft.Container(
                    content=ft.Column([
                        ft.Text("Total", size=11, color=ft.Colors.GREY_600),
                        ft.Text("3", size=24, weight=ft.FontWeight.BOLD,
                                color="#2563eb"),
                    ], spacing=2),
                    padding=14, bgcolor=ft.Colors.WHITE,
                    border_radius=10, expand=True,
                    border=ft.Border.all(2, "#2563eb"),
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Text("Admins", size=11, color=ft.Colors.GREY_600),
                        ft.Text("2", size=24, weight=ft.FontWeight.BOLD,
                                color="#d97706"),
                    ], spacing=2),
                    padding=14, bgcolor=ft.Colors.WHITE,
                    border_radius=10, expand=True,
                    border=ft.Border.all(2, "#d97706"),
                ),
            ], spacing=10),

            ft.Text("HARDCODED USERS — if you see these, the tab renders fine",
                    size=12, italic=True, color=ft.Colors.GREY_600),

            # THREE HARDCODED CARDS — no loop, no DB
            ft.Container(
                content=ft.Column([
                    ft.Text("admin", size=14, weight=ft.FontWeight.BOLD),
                    ft.Text("System Administrator", size=11),
                    ft.Text("👑 super_admin", size=11, color="#d97706"),
                ], spacing=4),
                padding=14, bgcolor="#f0f9ff",
                border_radius=10,
                border=ft.Border.all(1, "#bae6fd"),
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("manager1", size=14, weight=ft.FontWeight.BOLD),
                    ft.Text("Batch Manager", size=11),
                    ft.Text("👑 super_admin", size=11, color="#d97706"),
                ], spacing=4),
                padding=14, bgcolor="#f0f9ff",
                border_radius=10,
                border=ft.Border.all(1, "#bae6fd"),
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("staff1", size=14, weight=ft.FontWeight.BOLD),
                    ft.Text("Staff Member", size=11),
                    ft.Text("🧑 staff", size=11, color="#059669"),
                ], spacing=4),
                padding=14, bgcolor="#f0f9ff",
                border_radius=10,
                border=ft.Border.all(1, "#bae6fd"),
            ),

            ft.Container(
                content=ft.Text("✅ END OF TEST CONTENT — you should see 3 cards above",
                                size=11, italic=True,
                                color=ft.Colors.GREEN_700),
                padding=10,
                bgcolor="#dcfce7", border_radius=8,
            ),
        ]

        print(f"[USERS-TEST] controls set: {len(self.controls)} items")

    def build(self):
        return self