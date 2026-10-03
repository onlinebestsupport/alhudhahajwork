# =================================================================================
# core/data_admin_tab.py — Data Administration (SUPER_ADMIN ONLY)
# =================================================================================
# v1.1 — Added Reset Activity Log button
#   • Lists every CSV in /app/data
#   • Row count + column names + size + last modified
#   • Download individual CSV / Upload CSV to replace
#   • Export ALL CSVs as ZIP bundle
#   • Preview sample rows of any table
#   • Create manual backup snapshot
#   • NEW: Reset activity_log.csv (with backup + confirmation)
#   • Restricted to super_admin role only
# =================================================================================

import io
import os
import shutil
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

import flet as ft
import pandas as pd

try:
    from core.helpers import send_file_to_user
except ImportError:
    def send_file_to_user(page, path, label="Download"):
        return None


MOBILE_BREAKPOINT = 700


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


def _human_size(n):
    try:
        n = float(n)
    except Exception:
        return "?"
    if n < 1024:
        return f"{int(n)} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n/(1024*1024):.2f} MB"
    return f"{n/(1024*1024*1024):.2f} GB"


# =================================================================================
# CLASS: DataAdminTab  (super_admin only)
# =================================================================================
class DataAdminTab:

    def __init__(self, page, db, current_user):
        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}
        self.data_dir = Path("/app/data")

        self.stats_labels = {}
        self.cards_container = None
        self.status_label = None
        self.root = None
        self.file_picker = ft.FilePicker()
        self._picker_registered = False
        self._pending_upload_table = None

        role = _safe_str(self.current_user.get("role", "")).lower()
        if role != "super_admin":
            print(f"[DATA-ADMIN] ⛔ Access denied (role={role})")
            self.root = self._access_denied_ui()
            return

        try:
            self.setup_ui()
        except Exception as e:
            print(f"[DATA-ADMIN] setup_ui FAILED: {e}")
            traceback.print_exc()
            self.root = self._error_ui(e)
            return

        try:
            self.refresh()
        except Exception as e:
            print(f"[DATA-ADMIN] refresh FAILED: {e}")
            traceback.print_exc()

    def build(self):
        return self.root

    def _is_narrow(self):
        try:
            w = self.page_ref.width
            if w is None:
                w = getattr(self.page_ref.window, "width", None)
            return (w or 1200) < MOBILE_BREAKPOINT
        except Exception:
            return False

    def _access_denied_ui(self):
        return ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.LOCK, size=64,
                        color=ft.Colors.RED_400),
                ft.Text("Access Denied", size=22,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.RED_700),
                ft.Text(
                    "Only super administrators can access "
                    "Data Administration.\n"
                    "Contact your administrator if you believe "
                    "this is a mistake.",
                    size=12, color=ft.Colors.GREY_600,
                    text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=12),
            padding=60, alignment=ft.Alignment.CENTER,
            bgcolor="#fef2f2", border_radius=12,
            border=ft.Border.all(1, "#fecaca"),
            expand=True)

    def _error_ui(self, exc):
        return ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.WARNING_AMBER, size=48,
                        color=ft.Colors.ORANGE_600),
                ft.Text("Data Administration failed to load", size=18,
                        weight=ft.FontWeight.BOLD),
                ft.Text(str(exc), size=12,
                        color=ft.Colors.RED_500, selectable=True),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=10),
            padding=40, bgcolor="#fef3c7", border_radius=12,
            alignment=ft.Alignment.CENTER, expand=True)

    # =============================================================================
    # setup_ui
    # =============================================================================
    def setup_ui(self):
        narrow = self._is_narrow()

        # ---- [1] Header ----
        header = ft.Container(
            content=ft.Row([
                ft.Text("🗄️", size=22 if narrow else 26),
                ft.Column([
                    ft.Text("Data Administration",
                            size=14 if narrow else 16,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                    ft.Text("Direct access to your database files",
                            size=9 if narrow else 10,
                            color=ft.Colors.BLUE_100,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=2, expand=True),
                ft.Container(
                    content=ft.Text("SUPER ADMIN",
                                    size=9, color=ft.Colors.WHITE,
                                    weight=ft.FontWeight.BOLD),
                    padding=ft.Padding.symmetric(
                        horizontal=8, vertical=4),
                    bgcolor="#dc2626",
                    border_radius=6),
            ], spacing=8 if narrow else 12),
            padding=ft.Padding.symmetric(
                horizontal=12 if narrow else 22,
                vertical=10 if narrow else 14),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#7f1d1d", "#b91c1c", "#dc2626"]),
            border_radius=12)

        # ---- [2] Stats cards ----
        stat_specs = [
            ("tables",  "📄", "Tables",     "#2563eb"),
            ("rows",    "📊", "Total Rows", "#059669"),
            ("size",    "💾", "DB Size",    "#7c3aed"),
            ("backups", "📦", "Backups",    "#d97706"),
        ]
        stat_cards = []
        for key, icon, label, color in stat_specs:
            value = ft.Text("0", size=16 if narrow else 18,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE)
            self.stats_labels[key] = value
            stat_cards.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Text(icon, size=14),
                        ft.Text(label, size=10,
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=4),
                    value,
                ], spacing=2,
                   horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=10,
                bgcolor=color,
                border_radius=10,
                height=64,
                col={"xs": 6, "sm": 6, "md": 3}))

        stats_row = ft.ResponsiveRow(stat_cards, spacing=6, run_spacing=6)

        # ---- [3] Toolbar ----
        def _btn(label, icon, color, handler, expand=False):
            return ft.Button(
                content=ft.Row([
                    ft.Icon(icon, size=16, color=ft.Colors.WHITE),
                    ft.Text(label, size=11,
                            color=ft.Colors.WHITE,
                            weight=ft.FontWeight.BOLD),
                ], spacing=6, tight=True,
                   alignment=ft.MainAxisAlignment.CENTER),
                on_click=handler,
                height=42,
                bgcolor=color,
                expand=expand)

        # NEW: Reset Activity Log button (danger — red)
        reset_log_btn = _btn(
            "Reset Activity Log", ft.Icons.DELETE_SWEEP,
            "#991b1b", self.reset_activity_log_confirm, expand=narrow)

        if narrow:
            toolbar_inner = ft.Column([
                _btn("Export All (ZIP)", ft.Icons.DOWNLOAD,
                     "#0891b2", self.export_all_zip, expand=True),
                _btn("Create Backup Now", ft.Icons.SAVE,
                     "#059669", self.create_backup, expand=True),
                _btn("Refresh List", ft.Icons.REFRESH,
                     "#2563eb", self.refresh, expand=True),
                reset_log_btn,
            ], spacing=8)
        else:
            toolbar_inner = ft.Column([
                ft.Row([
                    _btn("Export All (ZIP)", ft.Icons.DOWNLOAD,
                         "#0891b2", self.export_all_zip),
                    _btn("Create Backup Now", ft.Icons.SAVE,
                         "#059669", self.create_backup),
                    _btn("Refresh List", ft.Icons.REFRESH,
                         "#2563eb", self.refresh),
                ], spacing=8),
                ft.Row([
                    reset_log_btn,
                ], spacing=8),
            ], spacing=8)

        toolbar = ft.Container(
            content=toolbar_inner,
            padding=10,
            bgcolor=ft.Colors.WHITE,
            border_radius=12,
            border=ft.Border.all(1, "#e2e8f0"))

        # ---- [4] Table cards ----
        self.cards_container = ft.Column(spacing=8)

        # ---- [5] Status ----
        self.status_label = ft.Text("Ready.", size=10,
                                    color=ft.Colors.GREY_600, italic=True)

        # ---- Root ----
        self.root = ft.Container(
            content=ft.Column(
                controls=[
                    header,
                    ft.Container(height=4),
                    stats_row,
                    toolbar,
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text("📋", size=14),
                                ft.Text("Database Tables",
                                        size=13,
                                        weight=ft.FontWeight.BOLD,
                                        color="#1e40af"),
                            ], spacing=6),
                            ft.Text(
                                "Each card below represents one CSV "
                                "file in /app/data. Download to view "
                                "in Excel, or upload to replace.",
                                size=10, color=ft.Colors.GREY_600,
                                italic=True),
                            self.cards_container,
                        ], spacing=8),
                        padding=12,
                        bgcolor=ft.Colors.WHITE,
                        border_radius=12,
                        border=ft.Border.all(1, "#e2e8f0")),
                    self.status_label,
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=10,
            bgcolor="#f0f2f5",
            expand=True,
        )

        self._register_picker()

    def _register_picker(self):
        if self._picker_registered:
            return
        try:
            if hasattr(self.page_ref, "services"):
                if self.file_picker not in self.page_ref.services:
                    self.page_ref.services.append(self.file_picker)
                    self._picker_registered = True
                    print("[DATA-ADMIN] FilePicker registered ✅")
            else:
                if self.file_picker not in self.page_ref.overlay:
                    self.page_ref.overlay.append(self.file_picker)
                    self._picker_registered = True
                    print("[DATA-ADMIN] FilePicker registered via overlay ✅")
            try:
                self.page_ref.update()
            except Exception:
                pass
        except Exception as ex:
            print(f"[DATA-ADMIN] picker registration failed: {ex}")

    # =============================================================================
    # refresh
    # =============================================================================
    def refresh(self, e=None):
        try:
            self.cards_container.controls.clear()

            csvs = sorted(self.data_dir.glob("*.csv"))
            total_rows = 0
            total_size = 0

            for csv_file in csvs:
                try:
                    df = pd.read_csv(csv_file, nrows=0)
                    col_names = list(df.columns)
                    with open(csv_file, "r", encoding="utf-8") as fh:
                        row_count = max(0, sum(1 for _ in fh) - 1)
                    size = csv_file.stat().st_size
                    mtime = datetime.fromtimestamp(
                        csv_file.stat().st_mtime)
                    total_rows += row_count
                    total_size += size

                    self.cards_container.controls.append(
                        self._build_table_card(
                            csv_file.name, row_count, size,
                            col_names, mtime))
                except Exception as ex:
                    print(f"[DATA-ADMIN] cannot read {csv_file}: {ex}")

            backup_count = 0
            try:
                backup_dir = self.data_dir / "backups"
                if backup_dir.exists():
                    backup_count = len(list(backup_dir.glob("*.zip")))
            except Exception:
                pass

            self.stats_labels["tables"].value = str(len(csvs))
            self.stats_labels["rows"].value = str(total_rows)
            self.stats_labels["size"].value = _human_size(total_size)
            self.stats_labels["backups"].value = str(backup_count)

            self._show_status(
                f"✅ Loaded {len(csvs)} tables, "
                f"{total_rows} rows, {backup_count} backups",
                ft.Colors.GREEN_700)

            self._safe_update()
        except Exception as ex:
            print(f"[DATA-ADMIN] refresh error: {ex}")
            traceback.print_exc()
            self._show_status(f"❌ Refresh failed: {ex}",
                              ft.Colors.RED_500)

    def _build_table_card(self, name, rows, size, cols, mtime):
        narrow = self._is_narrow()

        chips = []
        for c in cols[:8]:
            chips.append(
                ft.Container(
                    content=ft.Text(str(c), size=9,
                                    color="#1e40af",
                                    weight=ft.FontWeight.BOLD),
                    padding=ft.Padding.symmetric(
                        horizontal=6, vertical=2),
                    bgcolor="#dbeafe", border_radius=6))
        if len(cols) > 8:
            chips.append(
                ft.Container(
                    content=ft.Text(f"+{len(cols)-8} more", size=9,
                                    color=ft.Colors.GREY_600),
                    padding=ft.Padding.symmetric(
                        horizontal=6, vertical=2),
                    bgcolor="#f1f5f9", border_radius=6))

        chip_row = ft.Row(chips, spacing=4)

        def _download(e, _n=name):
            self._download_csv(_n)

        def _upload(e, _n=name):
            self._upload_csv(_n)

        def _preview(e, _n=name):
            self._preview_csv(_n)

        actions_row = ft.Row([
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.VISIBILITY, size=14,
                            color="#0f172a"),
                    ft.Text("Preview", size=11, color="#0f172a"),
                ], spacing=4, tight=True),
                on_click=_preview),
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.DOWNLOAD, size=14,
                            color="#0891b2"),
                    ft.Text("Download", size=11, color="#0891b2"),
                ], spacing=4, tight=True),
                on_click=_download),
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.UPLOAD, size=14,
                            color="#dc2626"),
                    ft.Text("Upload Replace", size=11, color="#dc2626"),
                ], spacing=4, tight=True),
                on_click=_upload),
        ], spacing=0,
           alignment=ft.MainAxisAlignment.END)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text(name, size=12,
                            weight=ft.FontWeight.BOLD,
                            color="#0f172a",
                            expand=True,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Container(
                        content=ft.Text(f"{rows} rows", size=9,
                                        color=ft.Colors.WHITE,
                                        weight=ft.FontWeight.BOLD),
                        padding=ft.Padding.symmetric(
                            horizontal=6, vertical=2),
                        bgcolor="#2563eb", border_radius=8),
                    ft.Container(
                        content=ft.Text(_human_size(size), size=9,
                                        color=ft.Colors.GREY_700),
                        padding=ft.Padding.symmetric(
                            horizontal=6, vertical=2),
                        bgcolor="#f1f5f9", border_radius=8),
                ], spacing=6),
                ft.Text(f"🕒 {mtime.strftime('%Y-%m-%d %H:%M')}  ·  "
                        f"🧮 {len(cols)} columns",
                        size=9, color=ft.Colors.GREY_600),
                chip_row,
                actions_row,
            ], spacing=6),
            padding=12,
            bgcolor="#f8fafc",
            border=ft.Border.all(1, "#e2e8f0"),
            border_radius=10)

    # =============================================================================
    # NEW: Reset Activity Log
    # =============================================================================
    def reset_activity_log_confirm(self, e=None):
        """Show confirmation dialog, then clear activity_log.csv."""
        log_path = self.data_dir / "activity_log.csv"

        if not log_path.exists():
            self._snack("⚠️ activity_log.csv not found",
                        ft.Colors.ORANGE_700)
            return

        # Count current rows
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                current_rows = max(0, sum(1 for _ in fh) - 1)
        except Exception:
            current_rows = 0

        # Get header (first line)
        header_line = ""
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                header_line = fh.readline().strip()
        except Exception:
            pass

        def do_reset(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

            try:
                # 1. Backup the current log first
                backup_dir = self.data_dir / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"activity_log.{stamp}.pre-reset.bak"
                shutil.copy2(log_path, backup_path)
                print(f"[DATA-ADMIN] activity log backup: {backup_path}")

                # 2. Rewrite the file with only the header
                if header_line:
                    with open(log_path, "w",
                              encoding="utf-8") as fh:
                        fh.write(header_line + "\n")
                else:
                    # fallback — write a default header
                    with open(log_path, "w",
                              encoding="utf-8") as fh:
                        fh.write("timestamp,user_id,action,details\n")

                # 3. Try to reload DB cache so other views see empty log
                try:
                    if hasattr(self.db, "reload_activity_log"):
                        self.db.reload_activity_log()
                    elif hasattr(self.db, "reload_all"):
                        self.db.reload_all()
                except Exception:
                    pass

                self.refresh()
                self._snack(
                    f"✅ Activity log cleared — "
                    f"{current_rows} rows removed.\n"
                    f"Backup saved: {backup_path.name}",
                    ft.Colors.GREEN_700)

                # Log the reset action itself (fresh entry)
                try:
                    self.db.log_activity(
                        self.current_user.get("id"),
                        "reset_activity_log",
                        f"Cleared {current_rows} activity log rows")
                except Exception:
                    pass

            except Exception as ex:
                print(f"[DATA-ADMIN] reset log error: {ex}")
                traceback.print_exc()
                self._snack(f"❌ Reset failed: {ex}",
                            ft.Colors.RED_500)

        def cancel(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, size=24,
                        color="#dc2626"),
                ft.Text("Reset Activity Log?",
                        weight=ft.FontWeight.BOLD, size=15),
            ], spacing=8),
            content=ft.Column([
                ft.Text(
                    f"This will permanently delete ALL "
                    f"activity log entries.",
                    size=12),
                ft.Container(height=8),
                ft.Container(
                    content=ft.Column([
                        ft.Text(f"📊 Current entries:  {current_rows}",
                                size=11, weight=ft.FontWeight.BOLD,
                                color="#991b1b"),
                        ft.Text(f"📁 File:  activity_log.csv",
                                size=11, color="#991b1b"),
                        ft.Text(f"💾 Backup:  will be saved to "
                                f"/app/data/backups/",
                                size=11, color="#991b1b"),
                    ], spacing=4),
                    padding=10, bgcolor="#fee2e2",
                    border_radius=6,
                    border=ft.Border.all(1, "#fecaca")),
                ft.Container(height=8),
                ft.Text(
                    "⚠️ A timestamped backup of the current log "
                    "will be created BEFORE the reset. "
                    "You can restore it from the Backups folder "
                    "if needed.",
                    size=10, color=ft.Colors.GREY_600,
                    italic=True),
            ], spacing=6, tight=True),
            actions=[
                ft.TextButton(
                    content=ft.Text("Cancel"),
                    on_click=cancel),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.DELETE_SWEEP, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Reset Now",
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=do_reset,
                    bgcolor="#dc2626"),
            ])
        self.page_ref.show_dialog(dlg)

    # =============================================================================
    # ACTIONS — Download / Export / Backup / Preview / Upload
    # =============================================================================
    def _download_csv(self, name):
        try:
            path = self.data_dir / name
            if not path.exists():
                self._snack(f"⚠️ {name} not found")
                return
            url = send_file_to_user(self.page_ref, str(path), name)
            self._snack(f"⬇️ Downloading {name}",
                        ft.Colors.BLUE_700)
            if url:
                try:
                    self.page_ref.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            print(f"[DATA-ADMIN] download error: {ex}")
            self._snack(f"❌ {ex}", ft.Colors.RED_500)

    def export_all_zip(self, e=None):
        try:
            out_dir = Path("/tmp/alhudha_exports")
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            bundle = out_dir / f"alhudha_full_db_{stamp}.zip"

            with zipfile.ZipFile(bundle, "w",
                                 zipfile.ZIP_DEFLATED) as z:
                for f in self.data_dir.glob("*.csv"):
                    z.write(f, arcname=f.name)
                for f in self.data_dir.glob("*.json"):
                    z.write(f, arcname=f.name)

            url = send_file_to_user(self.page_ref, str(bundle),
                                    "Full DB export")
            self._snack(f"✅ Export bundle: {bundle.name}",
                        ft.Colors.GREEN_700)
            if url:
                try:
                    self.page_ref.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            print(f"[DATA-ADMIN] export error: {ex}")
            self._snack(f"❌ {ex}", ft.Colors.RED_500)

    def create_backup(self, e=None):
        try:
            if hasattr(self.db, "create_backup"):
                path = self.db.create_backup()
                self._snack(f"✅ Backup created: {Path(path).name}",
                            ft.Colors.GREEN_700)
                self.refresh()
            else:
                self._snack("⚠️ db.create_backup() not available",
                            ft.Colors.ORANGE_700)
        except Exception as ex:
            print(f"[DATA-ADMIN] backup error: {ex}")
            self._snack(f"❌ {ex}", ft.Colors.RED_500)

    def _preview_csv(self, name):
        try:
            path = self.data_dir / name
            if not path.exists():
                self._snack(f"⚠️ {name} not found")
                return
            df = pd.read_csv(path, nrows=20)
            full_df = pd.read_csv(path, usecols=[0])
            total_rows = len(full_df)

            lines = []
            lines.append(" | ".join(str(c)[:15] for c in df.columns))
            lines.append("─" * 80)
            for _, row in df.iterrows():
                lines.append(" | ".join(str(v)[:15] for v in row.values))
            preview = "\n".join(lines)

            narrow = self._is_narrow()
            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text(f"👁️ {name} — first 20 rows",
                              weight=ft.FontWeight.BOLD,
                              size=13 if narrow else 14),
                content=ft.Container(
                    content=ft.Column([
                        ft.Text(preview, size=10,
                                font_family="Consolas",
                                selectable=True),
                        ft.Container(height=6),
                        ft.Text(f"Total: {total_rows} rows × "
                                f"{len(df.columns)} columns",
                                size=10, italic=True,
                                color=ft.Colors.GREY_600),
                    ], scroll=ft.ScrollMode.AUTO),
                    width=None if narrow else 800,
                    height=None if narrow else 500,
                    expand=narrow,
                    padding=10),
                actions=[
                    ft.TextButton(
                        content=ft.Text("Close"),
                        on_click=lambda e: self.page_ref.pop_dialog()),
                ])
            self.page_ref.show_dialog(dialog)
        except Exception as ex:
            print(f"[DATA-ADMIN] preview error: {ex}")
            self._snack(f"❌ {ex}", ft.Colors.RED_500)

    def _upload_csv(self, name):
        def do_pick(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
            self._pending_upload_table = name
            try:
                async def _pick():
                    try:
                        files = await self.file_picker.pick_files(
                            allow_multiple=False, with_data=True)
                        if files:
                            self._do_upload(files[0])
                    except Exception as ex:
                        print(f"[DATA-ADMIN] picker error: {ex}")

                self.page_ref.run_task(_pick)
            except Exception as ex:
                print(f"[DATA-ADMIN] run_task failed: {ex}")
                self._snack(f"⚠️ File picker error: {ex}",
                            ft.Colors.RED_500)

        def cancel(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

        path = self.data_dir / name
        current_rows = "?"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                current_rows = max(0, sum(1 for _ in fh) - 1)
        except Exception:
            pass

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, color="#dc2626"),
                ft.Text("Replace CSV?", weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Column([
                ft.Text(
                    f"You are about to REPLACE the entire contents "
                    f"of '{name}'.",
                    size=12),
                ft.Container(height=6),
                ft.Container(
                    content=ft.Text(
                        f"Current: {current_rows} rows\n\n"
                        f"⚠️ A timestamped backup will be created "
                        f"in /app/data/backups/ before replacing.",
                        size=11, color="#991b1b"),
                    padding=10, bgcolor="#fee2e2",
                    border_radius=6),
            ], spacing=6, tight=True),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=cancel),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.UPLOAD, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Choose File",
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=do_pick,
                    bgcolor="#dc2626"),
            ])
        self.page_ref.show_dialog(dialog)

    def _do_upload(self, file_obj):
        name = self._pending_upload_table
        if not name:
            return
        try:
            data = getattr(file_obj, "bytes", None)
            fname = getattr(file_obj, "name", "upload.csv")
            if not data:
                src = getattr(file_obj, "path", None)
                if src and os.path.exists(src):
                    with open(src, "rb") as fh:
                        data = fh.read()
            if not data:
                self._snack("⚠️ Empty file", ft.Colors.RED_500)
                return

            new_df = pd.read_csv(io.BytesIO(data))
            target = self.data_dir / name

            try:
                old_df = pd.read_csv(target, nrows=0)
                old_cols = list(old_df.columns)
                new_cols = list(new_df.columns)
                missing = [c for c in old_cols if c not in new_cols]
                if missing:
                    self._snack(
                        f"⚠️ Missing columns: {', '.join(missing[:5])}",
                        ft.Colors.RED_500)
                    return
                new_df = new_df.reindex(columns=old_cols)
            except Exception as e:
                print(f"[DATA-ADMIN] column check skipped: {e}")

            backup_dir = self.data_dir / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if target.exists():
                shutil.copy2(
                    target,
                    backup_dir / f"{name}.{stamp}.pre-upload.bak")

            new_df.to_csv(target, index=False, encoding="utf-8-sig")

            try:
                if hasattr(self.db, "reload_all"):
                    self.db.reload_all()
                elif hasattr(self.db, "reload"):
                    self.db.reload()
            except Exception:
                pass

            self.refresh()
            self._snack(
                f"✅ Replaced {name} with {len(new_df)} rows "
                f"from {fname}",
                ft.Colors.GREEN_700)
        except Exception as ex:
            print(f"[DATA-ADMIN] upload error: {ex}")
            traceback.print_exc()
            self._snack(f"❌ Upload failed: {ex}",
                        ft.Colors.RED_500)
        finally:
            self._pending_upload_table = None

    # =============================================================================
    # Helpers
    # =============================================================================
    def _show_status(self, message, color=ft.Colors.GREY_700):
        try:
            if self.status_label is not None:
                self.status_label.value = message
                self.status_label.color = color
        except Exception:
            pass
        self._safe_update()

    def _snack(self, msg, color=ft.Colors.GREEN_700):
        try:
            self.page_ref.show_dialog(
                ft.SnackBar(content=ft.Text(msg), bgcolor=color))
        except Exception:
            pass

    def _safe_update(self):
        try:
            if self.root is not None:
                self.root.update()
        except Exception:
            pass


DataAdminView = DataAdminTab


# =================================================================================
# SECTION END
# =================================================================================
