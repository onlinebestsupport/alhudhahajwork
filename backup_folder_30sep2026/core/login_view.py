# =================================================================================
# SECTION 5 (FLET 1.0.0 VERSION) — LOGIN VIEW
# =================================================================================

import flet as ft


# =================================================================================
# 5.1 — CLASS: LoginView
# =================================================================================
class LoginView:
    """
    Full-page login screen. Shows username + password inputs, Login/Cancel
    buttons, and an error label. On successful authentication, calls the
    on_login_success callback with the user dict.
    """

    def __init__(self, page: ft.Page, db, on_login_success,
                 on_cancel=None):
        self.page = page
        self.db = db
        self.on_login_success = on_login_success
        self.on_cancel = on_cancel

        self.username_input = None
        self.password_input = None
        self.status_label = None

    # =============================================================================
    # build() — returns the entire login screen as a Control
    # =============================================================================
    def build(self) -> ft.Control:
        # ---- Title ----
        title = ft.Text(
            "🏆 Alhudha Haj Travel System",
            size=26,
            weight=ft.FontWeight.BOLD,
            text_align=ft.TextAlign.CENTER,
        )
        subtitle = ft.Text(
            "Pilgrimage Management System",
            size=14,
            color=ft.Colors.GREY_600,
            text_align=ft.TextAlign.CENTER,
        )

        # ---- Input fields ----
        self.username_input = ft.TextField(
            label="Username",
            hint_text="Enter username",
            width=320,
            autofocus=True,
            on_submit=lambda e: self.handle_login(e),
        )
        self.password_input = ft.TextField(
            label="Password",
            hint_text="Enter password",
            password=True,
            can_reveal_password=True,
            width=320,
            on_submit=lambda e: self.handle_login(e),
        )

        # ---- Buttons ----
        login_btn = ft.Button(
            content=ft.Text("🔓 Login"),
            on_click=self.handle_login,
            width=150,
            height=45,
            bgcolor=ft.Colors.BLUE_700,
            color=ft.Colors.WHITE,
        )
        cancel_btn = ft.Button(
            content=ft.Text("Cancel"),
            on_click=self.handle_cancel,
            width=150,
            height=45,
            bgcolor=ft.Colors.GREY_600,
            color=ft.Colors.WHITE,
        )

        # ---- Error label ----
        self.status_label = ft.Text(
            "",
            color=ft.Colors.RED_600,
            size=13,
            text_align=ft.TextAlign.CENTER,
        )

        # ---- Login card ----
        login_card = ft.Container(
            content=ft.Column(
                controls=[
                    title,
                    subtitle,
                    ft.Divider(height=30, color=ft.Colors.TRANSPARENT),
                    self.username_input,
                    self.password_input,
                    ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
                    ft.Row(
                        controls=[login_btn, cancel_btn],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=15,
                    ),
                    self.status_label,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ),
            padding=40,
            width=450,
            bgcolor=ft.Colors.WHITE,
            border_radius=15,
            shadow=ft.BoxShadow(
                blur_radius=20,
                color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK),
                offset=ft.Offset(0, 4),
            ),
        )

        # ---- Full-screen background ----
        return ft.Container(
            content=ft.Column(
                controls=[login_card],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            ),
            bgcolor=ft.Colors.BLUE_GREY_50,
            expand=True,
            alignment=ft.Alignment.CENTER,
        )

    # =============================================================================
    # handle_login
    # =============================================================================
    def handle_login(self, e):
        username = (self.username_input.value or "").strip()
        password = self.password_input.value or ""

        # ---- Empty field check ----
        if not username or not password:
            self.status_label.value = "⚠️ Please enter username and password"
            self.page.update()
            return

        # ---- Authenticate ----
        try:
            user = self.db.authenticate_user(username, password)
        except Exception as ex:
            print(f"[LOGIN] Authentication error: {ex}")
            self.status_label.value = f"❌ System error: {ex}"
            self.page.update()
            return

        # ---- Success ----
        if user:
            print(f"[LOGIN] ✅ Success: {user.get('full_name')} ({user.get('role')})")
            self.status_label.value = ""
            self.page.update()
            if self.on_login_success:
                self.on_login_success(user)
        # ---- Failure ----
        else:
            print(f"[LOGIN] ❌ Failed for username '{username}'")
            self.status_label.value = "❌ Invalid username or password"
            self.password_input.value = ""
            self.page.update()

    # =============================================================================
    # handle_cancel
    # =============================================================================
    def handle_cancel(self, e):
        if self.on_cancel:
            self.on_cancel()
        else:
            # Default: close the window (best-effort)
            try:
                self.page.window.close()
            except Exception:
                pass


# =================================================================================
# SECTION 5 END (FLET 1.0.0 VERSION)
# =================================================================================