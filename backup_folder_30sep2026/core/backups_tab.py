# =================================================================================
# SECTION 20 — BACKUP TAB (FLET 1.0) — FIXED
# =================================================================================
# Purpose: Backup management — Create, Restore, Delete, Import, Refresh.
#
# FIXES IN THIS VERSION:
#   • Scans BOTH data_dir/backups/ AND data_dir.parent/backups/
#   • Displays the resolved folder path in the UI header
#   • Logs both paths to terminal on load
#   • Uses page_ref (page is read-only on Flet 1.0 controls)
#   • Full path shown in file listing (hover tooltip)
#   • FIXED: Registers FilePicker as a service (Flet 1.0 change)
# =================================================================================

import os
import shutil
import zipfile
import traceback
from datetime import datetime
from pathlib import Path

import flet as ft
import pandas as pd


# =================================================================================
# 20.1 — CLASS: BackupView
# =================================================================================
class BackupView(ft.Column):

    # =============================================================================
    # 20.1.1 — __init__
    # =============================================================================
    def __init__(self, page, db, current_user):
        super().__init__()
        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}

        self.scroll = ft.ScrollMode.AUTO
        self.expand = True
        self.spacing = 12

        # UI state
        self.table = None
        self.backup_count_label = None
        self.folder_path_label = None
        self.status_label = None
        self.backup_files = []

        # File picker (Flet 1.0)
        self.file_picker = ft.FilePicker()
        # Register in page overlay after mount

        try:
            self.setup_ui()
        except Exception as e:
            print(f"[BACKUP] setup_ui FAILED: {e}")
            traceback.print_exc()
            self._build_error_ui(e)
            return

        try:
            self.refresh()
        except Exception as e:
            print(f"[BACKUP] refresh FAILED: {e}")
            traceback.print_exc()

    # -----------------------------------------------------------------------------
    # 20.1.2 — _build_error_ui
    # -----------------------------------------------------------------------------
    def _build_error_ui(self, exc):
        try:
            self.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.WARNING_AMBER, size=48,
                                color=ft.Colors.ORANGE_600),
                        ft.Text("Backup tab failed to load", size=18,
                                weight=ft.FontWeight.BOLD),
                        ft.Text(str(exc), size=12,
                                color=ft.Colors.RED_500, selectable=True),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                       spacing=10),
                    padding=40, bgcolor="#fef3c7", border_radius=12,
                    alignment=ft.Alignment.CENTER, expand=True)
            ]
        except Exception:
            pass

    # -----------------------------------------------------------------------------
    # 20.1.3 — Path helpers
    # -----------------------------------------------------------------------------
    def _backup_dir(self):
        """Canonical folder used by db.create_backup()."""
        d = self.db.data_dir / "backups"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _legacy_backup_dir(self):
        """Old location created by _ensure_dirs() — may hold leftover backups."""
        return self.db.data_dir.parent / "backups"

    def _scan_all_dirs(self):
        """Return a list of paths to scan for backups."""
        dirs = []
        try:
            d1 = self._backup_dir()
            dirs.append(d1)
        except Exception as ex:
            print(f"[BACKUP] cannot create canonical dir: {ex}")

        try:
            d2 = self._legacy_backup_dir()
            if d2.exists() and d2.resolve() != self._backup_dir().resolve():
                dirs.append(d2)
        except Exception:
            pass

        return dirs

    # =============================================================================
    # 20.1.4 — setup_ui
    # =============================================================================
    def setup_ui(self):
        # ---- Header ----
        header = ft.Container(
            content=ft.Row([
                ft.Text("💾", size=26),
                ft.Column([
                    ft.Text("Backup Management", size=16,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                    ft.Text("Create, restore and manage database backups",
                            size=10, color=ft.Colors.BLUE_100),
                ], spacing=2, expand=True),
            ], spacing=12),
            padding=ft.Padding.symmetric(horizontal=22, vertical=14),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#1e3a8a", "#2563eb", "#7c3aed"]),
            border_radius=12)

        # ---- Folder path banner ----
        self.folder_path_label = ft.Text(
            "", size=11, color="#1e40af", italic=True, selectable=True)

        folder_banner = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.FOLDER_OPEN, size=18, color="#1e40af"),
                ft.Column([
                    ft.Text("Backup folder location",
                            size=10, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREY_700),
                    self.folder_path_label,
                ], spacing=2, expand=True),
            ], spacing=10),
            padding=12, bgcolor="#f0f9ff",
            border_radius=10,
            border=ft.Border.all(1, "#bae6fd"))

        # ---- Action buttons ----
        def _action_btn(label, icon, color, handler):
            return ft.Button(
                content=ft.Row([
                    ft.Icon(icon, size=18, color=ft.Colors.WHITE),
                    ft.Text(label, size=12, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                ], spacing=8, tight=True),
                on_click=handler, height=46, bgcolor=color)

        actions_row = ft.Row([
            _action_btn("Create New Backup", ft.Icons.SAVE, "#059669",
                        self.create_backup),
            _action_btn("Refresh List", ft.Icons.REFRESH, "#2563eb",
                        self.refresh),
            _action_btn("Open Folder", ft.Icons.FOLDER_OPEN, "#7c3aed",
                        self.open_folder),
        ], spacing=10, wrap=True)

        # ---- Backup table ----
        self.table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("#", size=11,
                                      weight=ft.FontWeight.BOLD,
                                      color=ft.Colors.WHITE)),
                ft.DataColumn(ft.Text("Date", size=11,
                                      weight=ft.FontWeight.BOLD,
                                      color=ft.Colors.WHITE)),
                ft.DataColumn(ft.Text("File Name", size=11,
                                      weight=ft.FontWeight.BOLD,
                                      color=ft.Colors.WHITE)),
                ft.DataColumn(ft.Text("Size", size=11,
                                      weight=ft.FontWeight.BOLD,
                                      color=ft.Colors.WHITE)),
                ft.DataColumn(ft.Text("Status", size=11,
                                      weight=ft.FontWeight.BOLD,
                                      color=ft.Colors.WHITE)),
                ft.DataColumn(ft.Text("Location", size=11,
                                      weight=ft.FontWeight.BOLD,
                                      color=ft.Colors.WHITE)),
                ft.DataColumn(ft.Text("Actions", size=11,
                                      weight=ft.FontWeight.BOLD,
                                      color=ft.Colors.WHITE)),
            ],
            rows=[],
            heading_row_color="#1e293b",
            column_spacing=14,
            data_row_min_height=44,
            data_row_max_height=70)

        self.backup_count_label = ft.Text("Total: 0 backups", size=11,
                                          weight=ft.FontWeight.BOLD,
                                          color="#1e40af")

        table_card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("📋", size=14),
                    ft.Text("All Backups", size=13,
                            weight=ft.FontWeight.BOLD, color="#1e40af"),
                    ft.Container(expand=True),
                    self.backup_count_label,
                ], spacing=6),
                ft.Container(
                    content=ft.ListView([self.table], expand=True,
                                        auto_scroll=False),
                    bgcolor=ft.Colors.WHITE, border_radius=10,
                    border=ft.Border.all(1, "#e2e8f0"),
                    padding=6, height=380),
            ], spacing=8),
            padding=12, bgcolor=ft.Colors.WHITE, border_radius=12,
            border=ft.Border.all(1, "#e2e8f0"))

        # ---- Status label ----
        self.status_label = ft.Text("Ready.", size=10,
                                    color=ft.Colors.GREY_600, italic=True)

        self.controls = [
            header,
            folder_banner,
            actions_row,
            table_card,
            self.status_label,
        ]

    # =============================================================================
    # 20.1.5 — did_mount / build
    # =============================================================================
    def build(self):
        return self

    def did_mount(self):
        try:
            # Flet 1.0: FilePicker is a service and should be added to page.services
            # Do NOT use page.overlay.append() for services in Flet 1.0
            self.page_ref.services.append(self.file_picker)
            self.page_ref.update()
        except Exception as ex:
            print(f"[BACKUP] file picker service registration failed: {ex}")

    # =============================================================================
    # 20.1.6 — refresh (scan ALL known backup folders)
    # =============================================================================
    def refresh(self, e=None):
        try:
            self.backup_files = []
            scanned_dirs = self._scan_all_dirs()

            print(f"[BACKUP] scanning {len(scanned_dirs)} folder(s):")
            for d in scanned_dirs:
                print(f"[BACKUP]   → {d}")

            # Build history lookup (filenames only)
            history_names = set()
            try:
                if not self.db.backup_history.empty:
                    history_names = {
                        Path(str(h)).name
                        for h in self.db.backup_history["backup_file"].tolist()
                    }
            except Exception as ex:
                print(f"[BACKUP] history parse error: {ex}")

            # Scan each folder
            for folder in scanned_dirs:
                if not folder.exists():
                    continue
                for file in folder.glob("*.zip"):
                    try:
                        stat = file.stat()
                        self.backup_files.append({
                            "file_path": str(file),
                            "file_name": file.name,
                            "file_date": datetime.fromtimestamp(stat.st_mtime),
                            "file_size": stat.st_size,
                            "folder": str(folder),
                            "in_history": file.name in history_names,
                            "status": ("Registered"
                                       if file.name in history_names
                                       else "External"),
                        })
                    except Exception as ex:
                        print(f"[BACKUP] cannot stat {file}: {ex}")

            # Newest first
            self.backup_files.sort(key=lambda x: x["file_date"],
                                   reverse=True)

            print(f"[BACKUP] found {len(self.backup_files)} backup files")

            self._display_backups()

            # Update path label
            try:
                canonical = str(self._backup_dir())
                if self.folder_path_label:
                    self.folder_path_label.value = canonical
            except Exception:
                pass

            self._show_status(
                f"✅ Scanned {len(scanned_dirs)} folder(s) — "
                f"{len(self.backup_files)} backups found",
                ft.Colors.GREEN_700)

            self._safe_update()
        except Exception as ex:
            print(f"[BACKUP] refresh error: {ex}")
            traceback.print_exc()
            self._show_status(f"❌ Refresh failed: {ex}",
                              ft.Colors.RED_500)

    # =============================================================================
    # 20.1.7 — _display_backups
    # =============================================================================
    def _display_backups(self):
        self.table.rows.clear()

        for i, backup in enumerate(self.backup_files):
            date_str = backup["file_date"].strftime("%Y-%m-%d %H:%M:%S")
            size = backup["file_size"]
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.2f} MB"

            status_color = ("#059669"
                            if backup["status"] == "Registered"
                            else "#d97706")

            def _restore(e, b=backup):
                self._confirm_restore(b)

            def _delete(e, b=backup):
                self._confirm_delete(b)

            self.table.rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(str(i + 1), size=11,
                                    text_align=ft.TextAlign.CENTER)),
                ft.DataCell(ft.Text(date_str, size=11)),
                ft.DataCell(ft.Text(backup["file_name"], size=11,
                                    weight=ft.FontWeight.BOLD,
                                    tooltip=backup["file_path"])),
                ft.DataCell(ft.Text(size_str, size=11,
                                    text_align=ft.TextAlign.RIGHT)),
                ft.DataCell(ft.Text(backup["status"], size=10,
                                    weight=ft.FontWeight.BOLD,
                                    color=status_color)),
                ft.DataCell(ft.Text(
                    Path(backup["folder"]).name or backup["folder"],
                    size=10, color=ft.Colors.GREY_600,
                    tooltip=backup["folder"])),
                ft.DataCell(ft.Row([
                    ft.IconButton(ft.Icons.RESTORE, icon_size=18,
                                  icon_color="#d97706",
                                  tooltip="Restore this backup",
                                  on_click=_restore),
                    ft.IconButton(ft.Icons.DELETE, icon_size=18,
                                  icon_color="#dc2626",
                                  tooltip="Delete this backup",
                                  on_click=_delete),
                ], spacing=0)),
            ]))

        if self.backup_count_label:
            self.backup_count_label.value = (
                f"Total: {len(self.backup_files)} backups")

    # =============================================================================
    # 20.1.8 — create_backup
    # =============================================================================
    def create_backup(self, e=None):
        def _do(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

            try:
                self._show_status("⏳ Creating backup…",
                                  ft.Colors.BLUE_700)
                self._safe_update()

                backup_path = self.db.create_backup()
                print(f"[BACKUP] Created → {backup_path}")

                try:
                    self.db.log_activity(
                        self.current_user.get("id"),
                        "create_backup",
                        f"Created backup: {Path(backup_path).name}")
                except Exception:
                    pass

                self.refresh()

                # Confirm with path shown
                self._snack(
                    f"✅ Backup created: {Path(backup_path).name}",
                    ft.Colors.GREEN_700)

                # Show a second dialog with the full path so user knows
                info = ft.AlertDialog(
                    modal=True,
                    title=ft.Row([
                        ft.Icon(ft.Icons.CHECK_CIRCLE,
                                color="#059669"),
                        ft.Text("Backup Created",
                                weight=ft.FontWeight.BOLD),
                    ], spacing=8),
                    content=ft.Column([
                        ft.Text("Saved to:",
                                size=11, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.GREY_700),
                        ft.Container(
                            content=ft.Text(str(backup_path), size=11,
                                            selectable=True,
                                            color="#1e40af"),
                            padding=10, bgcolor="#f0f9ff",
                            border_radius=6,
                            border=ft.Border.all(1, "#bae6fd")),
                    ], spacing=8, tight=True),
                    actions=[
                        ft.TextButton(
                            content=ft.Text("OK"),
                            on_click=lambda _: (
                                self.page_ref.pop_dialog(),
                                self.open_folder(None))),
                    ])
                self.page_ref.show_dialog(info)
            except Exception as ex:
                print(f"[BACKUP] create error: {ex}")
                traceback.print_exc()
                self._show_status(f"❌ Backup failed: {ex}",
                                  ft.Colors.RED_500)
                self._snack(f"❌ Backup failed: {ex}",
                            ft.Colors.RED_500)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirm Backup",
                          weight=ft.FontWeight.BOLD),
            content=ft.Text(
                "Create a new backup of the database?\n\n"
                "This will save a compressed ZIP file in the "
                "backup folder.",
                size=12),
            actions=[
                ft.TextButton(
                    content=ft.Text("Cancel"),
                    on_click=lambda _: self.page_ref.pop_dialog()),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.SAVE, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Create Backup",
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=_do,
                    bgcolor="#059669"),
            ])
        self.page_ref.show_dialog(dialog)

    # =============================================================================
    # 20.1.9 — _confirm_restore
    # =============================================================================
    def _confirm_restore(self, backup):
        def _do(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
            try:
                self._show_status("⏳ Creating safety backup…",
                                  ft.Colors.BLUE_700)
                self._safe_update()

                safety = self.db.create_backup()
                print(f"[BACKUP] Safety backup: {safety}")

                self._show_status("⏳ Restoring backup…",
                                  ft.Colors.BLUE_700)
                self._safe_update()

                self.db.restore_backup(backup["file_path"])
                print(f"[BACKUP] Restored from: {backup['file_path']}")

                try:
                    self.db.log_activity(
                        self.current_user.get("id"),
                        "restore_backup",
                        f"Restored from: {backup['file_name']}")
                except Exception:
                    pass

                self._snack(
                    f"✅ Restored from {backup['file_name']}",
                    ft.Colors.GREEN_700)
                self._show_status(
                    "✅ Restore complete. Restart app to reload all views.",
                    ft.Colors.GREEN_700)
            except Exception as ex:
                print(f"[BACKUP] restore error: {ex}")
                traceback.print_exc()
                self._show_status(f"❌ Restore failed: {ex}",
                                  ft.Colors.RED_500)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, color="#dc2626"),
                ft.Text("Confirm Restore",
                        weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Column([
                ft.Text(f"File: {backup['file_name']}",
                        size=11, weight=ft.FontWeight.BOLD),
                ft.Text(
                    f"Date: "
                    f"{backup['file_date'].strftime('%Y-%m-%d %H:%M:%S')}",
                    size=11),
                ft.Text(
                    f"Size: {backup['file_size']/(1024*1024):.2f} MB",
                    size=11),
                ft.Container(height=6),
                ft.Container(
                    content=ft.Text(
                        "⚠️  This will OVERWRITE ALL current data.\n"
                        "A safety backup of the current state will be "
                        "created first.",
                        size=11, color="#991b1b"),
                    padding=10, bgcolor="#fee2e2",
                    border_radius=6),
            ], spacing=4, tight=True),
            actions=[
                ft.TextButton(
                    content=ft.Text("Cancel"),
                    on_click=lambda _: self.page_ref.pop_dialog()),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.RESTORE, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Restore Now",
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=_do,
                    bgcolor="#dc2626"),
            ])
        self.page_ref.show_dialog(dialog)

    # =============================================================================
    # 20.1.10 — _confirm_delete
    # =============================================================================
    def _confirm_delete(self, backup):
        extra = ""
        if len(self.backup_files) <= 1:
            extra = ("⚠️ This is the ONLY backup file.\n"
                     "Deleting it leaves you with no safety net.\n\n")

        def _do(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
            try:
                path = backup["file_path"]
                if os.path.exists(path):
                    os.remove(path)

                # Remove from history CSV if present
                if not self.db.backup_history.empty:
                    mask = (self.db.backup_history["backup_file"]
                            .apply(lambda x: Path(str(x)).name ==
                                   backup["file_name"]))
                    if mask.any():
                        self.db.backup_history = (
                            self.db.backup_history[~mask])
                        self.db._save_df(self.db.backup_history,
                                         "backup_history.csv")

                try:
                    self.db.log_activity(
                        self.current_user.get("id"),
                        "delete_backup",
                        f"Deleted backup: {backup['file_name']}")
                except Exception:
                    pass

                self._snack(
                    f"✅ Deleted {backup['file_name']}",
                    ft.Colors.GREEN_700)
                self.refresh()
            except Exception as ex:
                print(f"[BACKUP] delete error: {ex}")
                traceback.print_exc()
                self._snack(f"❌ Delete failed: {ex}",
                            ft.Colors.RED_500)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, color="#dc2626"),
                ft.Text("Confirm Delete",
                        weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Column([
                ft.Text(f"{extra}Delete '{backup['file_name']}'?\n"
                        f"This cannot be undone.",
                        size=12),
                ft.Container(
                    content=ft.Text(backup["file_path"], size=10,
                                    selectable=True,
                                    color=ft.Colors.GREY_600),
                    padding=6, bgcolor="#f1f5f9", border_radius=4),
            ], spacing=6, tight=True),
            actions=[
                ft.TextButton(
                    content=ft.Text("Cancel"),
                    on_click=lambda _: self.page_ref.pop_dialog()),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.DELETE, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Delete", color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=_do,
                    bgcolor="#dc2626"),
            ])
        self.page_ref.show_dialog(dialog)

    # =============================================================================
    # 20.1.11 — open_folder
    # =============================================================================
    def open_folder(self, e=None):
        """Show the folder path and try to open it locally."""
        try:
            folder = self._backup_dir()
            path_str = str(folder)
            print(f"[BACKUP] Folder: {path_str}")

            # Try opening locally (works only when running on same machine)
            try:
                if os.name == "nt":
                    os.startfile(path_str)
                elif os.uname().sysname == "Darwin":
                    import subprocess
                    subprocess.Popen(["open", path_str])
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", path_str])
                self._snack(f"📂 Opened: {path_str}",
                            ft.Colors.BLUE_700)
            except Exception:
                # Fallback: show path in a dialog
                dialog = ft.AlertDialog(
                    modal=True,
                    title=ft.Text("Backup Folder Path"),
                    content=ft.Column([
                        ft.Text("Copy this path and open it manually:",
                                size=11),
                        ft.Container(
                            content=ft.Text(path_str, size=11,
                                            selectable=True,
                                            color="#1e40af"),
                            padding=10, bgcolor="#f0f9ff",
                            border_radius=6,
                            border=ft.Border.all(1, "#bae6fd")),
                    ], spacing=8, tight=True),
                    actions=[
                        ft.TextButton(
                            content=ft.Text("Close"),
                            on_click=lambda _: self.page_ref.pop_dialog()),
                    ])
                self.page_ref.show_dialog(dialog)
        except Exception as ex:
            print(f"[BACKUP] open_folder error: {ex}")
            self._snack(f"❌ {ex}", ft.Colors.RED_500)

    # =============================================================================
    # 20.1.12 — Helpers
    # =============================================================================
    def _show_status(self, message, color=ft.Colors.GREY_700):
        if self.status_label:
            self.status_label.value = message
            self.status_label.color = color
        self._safe_update()

    def _snack(self, message, color=ft.Colors.GREEN_700):
        try:
            self.page_ref.snack_bar = ft.SnackBar(
                content=ft.Text(message), bgcolor=color)
            self.page_ref.snack_bar.open = True
            self.page_ref.update()
        except Exception:
            pass

    def _safe_update(self):
        try:
            self.update()
        except Exception:
            pass


# =================================================================================
# Alias so main_window.py can import BackupTab
# =================================================================================
BackupTab = BackupView


# =================================================================================
# SECTION 20 END
# =================================================================================