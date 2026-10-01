# =================================================================================
# SECTION 20 — BACKUP TAB (FLET 1.0) — FIXED + CLOUD-READY + MOBILE-RESPONSIVE
# =================================================================================
# v1.3 — Row Selection
#   • ADDED: Tap any row → SELECTS (highlights the backup)
#   • ADDED: Toolbar Download/Restore/Delete act on selected row
#   • ADDED: "Sel" column with ✓ marker
#   • FIXED: on_select_change (correct Flet 1.0.0 param)
#   • Action icons 18 → 20 for easier tapping
#   • Preserved: cloud banner, FilePicker, path scanning
# =================================================================================

import os
import shutil
import zipfile
import traceback
from datetime import datetime
from pathlib import Path

import flet as ft
import pandas as pd

try:
    from core.helpers import send_file_to_user
except ImportError:
    def send_file_to_user(page, path, label="Download"):
        return None


# Mobile breakpoint — viewport width below this uses card layouts
MOBILE_BREAKPOINT = 700


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
        self.mobile_list = None
        self.backup_count_label = None
        self.folder_path_label = None
        self.status_label = None
        self.selection_label = None
        self.backup_files = []
        self._mobile_mode = False

        # Currently selected backup (for toolbar actions)
        self._selected_backup_idx = None

        # File picker (Flet 1.0)
        self.file_picker = ft.FilePicker()
        self._picker_registered = False

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
    # 20.1.1b — _is_narrow
    # -----------------------------------------------------------------------------
    def _is_narrow(self):
        """True when viewport width < MOBILE_BREAKPOINT."""
        try:
            return (self.page_ref.width or 1200) < MOBILE_BREAKPOINT
        except Exception:
            return False

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
        """Old location created by _ensure_dirs() — may hold leftovers."""
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
            if d2.exists() and \
                    d2.resolve() != self._backup_dir().resolve():
                dirs.append(d2)
        except Exception:
            pass

        return dirs

    # =============================================================================
    # 20.1.4 — setup_ui  (MOBILE-RESPONSIVE + row selection)
    # =============================================================================
    def setup_ui(self):
        narrow = self._is_narrow()
        self._mobile_mode = narrow

        # ---- Header ----
        header = ft.Container(
            content=ft.Row([
                ft.Text("💾", size=22 if narrow else 26),
                ft.Column([
                    ft.Text("Backup Management",
                            size=14 if narrow else 16,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                    ft.Text("Create, restore and manage backups",
                            size=9 if narrow else 10,
                            color=ft.Colors.BLUE_100,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=2, expand=True),
            ], spacing=8 if narrow else 12),
            padding=ft.Padding.symmetric(
                horizontal=12 if narrow else 22,
                vertical=10 if narrow else 14),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#1e3a8a", "#2563eb", "#7c3aed"]),
            border_radius=12)

        # ---- Cloud info banner ----
        cloud_note = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CLOUD, size=16 if narrow else 18,
                        color="#d97706"),
                ft.Column([
                    ft.Text("Cloud storage note",
                            size=10, weight=ft.FontWeight.BOLD,
                            color="#92400e"),
                    ft.Text(
                        ("Use ⬇️ to save to your PC. Backups clear on "
                         "restart without a Volume.")
                        if narrow else
                        ("Backups are saved on the server. Use the "
                         "⬇️ Download button to save a copy to your PC. "
                         "Without a Railway Volume, server backups "
                         "are cleared when the app restarts."),
                        size=9 if narrow else 10,
                        color="#92400e"),
                ], spacing=2, expand=True),
            ], spacing=8 if narrow else 10),
            padding=10 if narrow else 12,
            bgcolor="#fef3c7",
            border_radius=10,
            border=ft.Border.all(1, "#fcd34d"))

        # ---- Folder path banner ----
        self.folder_path_label = ft.Text(
            "", size=10 if narrow else 11, color="#1e40af",
            italic=True, selectable=True, max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS)

        folder_banner = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.FOLDER_OPEN, size=16 if narrow else 18,
                        color="#1e40af"),
                ft.Column([
                    ft.Text("Backup folder",
                            size=9 if narrow else 10,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREY_700),
                    self.folder_path_label,
                ], spacing=2, expand=True),
            ], spacing=8 if narrow else 10),
            padding=10 if narrow else 12,
            bgcolor="#f0f9ff",
            border_radius=10,
            border=ft.Border.all(1, "#bae6fd"))

        # ---- Action buttons ----
        def _action_btn(label, icon, color, handler, expand_narrow=False):
            return ft.Button(
                content=ft.Row([
                    ft.Icon(icon, size=16 if narrow else 18,
                            color=ft.Colors.WHITE),
                    ft.Text(label, size=11 if narrow else 12,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                ], spacing=6, tight=True,
                   alignment=ft.MainAxisAlignment.CENTER),
                on_click=handler,
                height=44 if narrow else 46,
                bgcolor=color,
                expand=expand_narrow)

        if narrow:
            actions_block = ft.Column([
                _action_btn("Create New Backup", ft.Icons.SAVE,
                            "#059669", self.create_backup,
                            expand_narrow=True),
                ft.Row([
                    _action_btn("Refresh", ft.Icons.REFRESH,
                                "#2563eb", self.refresh),
                    _action_btn("Folder", ft.Icons.FOLDER_OPEN,
                                "#7c3aed", self.open_folder),
                ], spacing=8),
                ft.Row([
                    _action_btn("⬇️ Download", ft.Icons.DOWNLOAD,
                                "#0891b2", self._download_selected),
                    _action_btn("♻️ Restore", ft.Icons.RESTORE,
                                "#d97706", self._restore_selected),
                    _action_btn("🗑️ Delete", ft.Icons.DELETE,
                                "#dc2626", self._delete_selected),
                ], spacing=8),
            ], spacing=8)
        else:
            actions_block = ft.Row([
                _action_btn("Create New Backup", ft.Icons.SAVE,
                            "#059669", self.create_backup),
                _action_btn("Refresh List", ft.Icons.REFRESH,
                            "#2563eb", self.refresh),
                _action_btn("⬇️ Download (selected)", ft.Icons.DOWNLOAD,
                            "#0891b2", self._download_selected),
                _action_btn("♻️ Restore (selected)", ft.Icons.RESTORE,
                            "#d97706", self._restore_selected),
                _action_btn("🗑️ Delete (selected)", ft.Icons.DELETE,
                            "#dc2626", self._delete_selected),
                _action_btn("Show Folder Path", ft.Icons.FOLDER_OPEN,
                            "#7c3aed", self.open_folder),
            ], spacing=10, wrap=True)

        # ---- Desktop table ----
        self.table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Sel", size=11,
                                      weight=ft.FontWeight.BOLD,
                                      color=ft.Colors.WHITE)),
                ft.DataColumn(ft.Text(h, size=11,
                                      weight=ft.FontWeight.BOLD,
                                      color=ft.Colors.WHITE))
                for h in ["#", "Date", "File Name", "Size", "Status",
                          "Location", "Actions"]
            ],
            rows=[],
            heading_row_color="#1e293b",
            column_spacing=12,
            data_row_min_height=44,
            data_row_max_height=70)

        # ---- Mobile card list ----
        self.mobile_list = ft.Column(spacing=8)

        if narrow:
            table_body = ft.Container(content=self.mobile_list, padding=4)
        else:
            table_body = ft.Container(
                content=ft.ListView([self.table],
                                    expand=True, auto_scroll=False),
                bgcolor=ft.Colors.WHITE, border_radius=10,
                border=ft.Border.all(1, "#e2e8f0"),
                padding=6, height=420)

        self.backup_count_label = ft.Text(
            "Total: 0 backups", size=11,
            weight=ft.FontWeight.BOLD, color="#1e40af")

        self.selection_label = ft.Text(
            "", size=10, color=ft.Colors.BLUE_700,
            weight=ft.FontWeight.BOLD, italic=True)

        hint_text = ("💡 Tap a backup card to select, then use toolbar "
                     "Download / Restore / Delete"
                     if narrow else
                     "💡 Tap a row to SELECT it, then use toolbar "
                     "Download / Restore / Delete. "
                     "You can also use per-row icons.")

        table_card = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("📋", size=14),
                    ft.Text("All Backups", size=13,
                            weight=ft.FontWeight.BOLD, color="#1e40af"),
                    ft.Container(expand=True),
                    self.backup_count_label,
                ], spacing=6),
                ft.Text(hint_text, size=10,
                        color=ft.Colors.GREY_600, italic=True),
                self.selection_label,
                table_body,
            ], spacing=8),
            padding=10 if narrow else 12,
            bgcolor=ft.Colors.WHITE, border_radius=12,
            border=ft.Border.all(1, "#e2e8f0"))

        # ---- Status label ----
        self.status_label = ft.Text("Ready.", size=10,
                                    color=ft.Colors.GREY_600, italic=True)

        self.controls = [
            header,
            cloud_note,
            folder_banner,
            actions_block,
            table_card,
            self.status_label,
        ]

    # =============================================================================
    # 20.1.5 — did_mount / build
    # =============================================================================
    def build(self):
        return self

    def did_mount(self):
        # Register FilePicker only once
        if self._picker_registered:
            return
        try:
            if hasattr(self.page_ref, 'services'):
                if self.file_picker not in self.page_ref.services:
                    self.page_ref.services.append(self.file_picker)
                    self._picker_registered = True
                    print("[BACKUP] FilePicker registered ✅")
            else:
                if self.file_picker not in self.page_ref.overlay:
                    self.page_ref.overlay.append(self.file_picker)
                    self._picker_registered = True
                    print("[BACKUP] FilePicker registered via overlay ✅")
            self.page_ref.update()
        except Exception as ex:
            print(f"[BACKUP] file picker registration failed: {ex}")

    # =============================================================================
    # 20.1.5b — on_resize
    # =============================================================================
    def on_resize(self, e=None):
        """Re-evaluate layout when viewport changes."""
        try:
            new_narrow = self._is_narrow()
            if new_narrow != self._mobile_mode:
                print(f"[BACKUP] viewport changed → "
                      f"{'mobile' if new_narrow else 'desktop'}")
                self.controls.clear()
                self.setup_ui()
                try:
                    self.refresh()
                except Exception as ex:
                    print(f"[BACKUP] refresh after resize failed: {ex}")
        except Exception as ex:
            print(f"[BACKUP] on_resize error: {ex}")

    # =============================================================================
    # 20.1.6 — refresh
    # =============================================================================
    def refresh(self, e=None):
        try:
            self.backup_files = []
            self._selected_backup_idx = None
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
                        for h in self.db.backup_history[
                            "backup_file"].tolist()
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
                            "file_date": datetime.fromtimestamp(
                                stat.st_mtime),
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
    # 20.1.7 — _display_backups (desktop table)
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

            def _download(e, b=backup):
                self._download_backup(b)

            def _restore(e, b=backup):
                self._confirm_restore(b)

            def _delete(e, b=backup):
                self._confirm_delete(b)

            is_selected = (self._selected_backup_idx == i)

            def _on_row_tap(e, idx=i):
                try:
                    self._select_backup(idx)
                except Exception as ex:
                    print(f"[BACKUP] row tap error: {ex}")

            self.table.rows.append(
                ft.DataRow(
                    on_select_change=_on_row_tap,
                    selected=is_selected,
                    cells=[
                        # Selection indicator
                        ft.DataCell(
                            ft.Container(
                                content=ft.Text(
                                    "✓" if is_selected else "",
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color="#27ae60"),
                                width=24,
                                alignment=ft.Alignment.CENTER,
                                bgcolor=("#dcfce7" if is_selected
                                         else None),
                                border_radius=4,
                            )),
                        ft.DataCell(ft.Text(str(i + 1), size=11,
                                            text_align=ft.TextAlign.CENTER)),
                        ft.DataCell(ft.Text(date_str, size=11)),
                        ft.DataCell(ft.Text(
                            backup["file_name"], size=11,
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
                            ft.IconButton(ft.Icons.DOWNLOAD, icon_size=20,
                                          icon_color="#2563eb",
                                          tooltip="Download to your PC",
                                          on_click=_download),
                            ft.IconButton(ft.Icons.RESTORE, icon_size=20,
                                          icon_color="#d97706",
                                          tooltip="Restore this backup",
                                          on_click=_restore),
                            ft.IconButton(ft.Icons.DELETE, icon_size=20,
                                          icon_color="#dc2626",
                                          tooltip="Delete this backup",
                                          on_click=_delete),
                        ], spacing=0)),
                    ]))

        if self.backup_count_label:
            self.backup_count_label.value = (
                f"Total: {len(self.backup_files)} backups")

        # Branch to mobile renderer
        if self._mobile_mode:
            try:
                self._render_mobile_backups()
            except Exception as ex:
                print(f"[BACKUP] mobile render failed: {ex}")

    # =============================================================================
    # 20.1.7b — _render_mobile_backups
    # =============================================================================
    def _render_mobile_backups(self):
        """Render backup list as cards for narrow screens."""
        if self.mobile_list is None:
            return
        self.mobile_list.controls.clear()

        for i, backup in enumerate(self.backup_files):
            date_str = backup["file_date"].strftime("%Y-%m-%d %H:%M")
            size = backup["file_size"]
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size/1024:.1f} KB"
            else:
                size_str = f"{size/(1024*1024):.2f} MB"

            status_color = ("#059669"
                            if backup["status"] == "Registered"
                            else "#d97706")

            def _download(e, b=backup):
                self._download_backup(b)

            def _restore(e, b=backup):
                self._confirm_restore(b)

            def _delete(e, b=backup):
                self._confirm_delete(b)

            is_selected = (self._selected_backup_idx == i)

            def _on_card_tap(e, idx=i):
                try:
                    self._select_backup(idx)
                except Exception as ex:
                    print(f"[BACKUP] card tap error: {ex}")

            card = ft.Container(
                content=ft.Column([
                    # Row 1: index + file name + status
                    ft.Row([
                        ft.Container(
                            content=ft.Text(
                                f"#{i+1}", size=9,
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                            padding=ft.Padding.symmetric(
                                horizontal=6, vertical=2),
                            bgcolor="#1e40af",
                            border_radius=6),
                        ft.Text(backup["file_name"], size=11,
                                weight=ft.FontWeight.BOLD,
                                expand=True, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(
                            ("✓ " if is_selected else "") +
                            backup["status"],
                            size=9,
                            color="#27ae60" if is_selected else status_color,
                            weight=ft.FontWeight.BOLD),
                    ], spacing=6),

                    # Row 2: date + size + folder
                    ft.Row([
                        ft.Text(f"📅 {date_str}", size=9,
                                color=ft.Colors.GREY_600),
                        ft.Text(f"💾 {size_str}", size=9,
                                color=ft.Colors.GREY_600),
                        ft.Text(
                            f"📁 {Path(backup['folder']).name}",
                            size=9, color=ft.Colors.GREY_600),
                    ], spacing=8, wrap=True),

                    # Row 3: actions
                    ft.Row([
                        ft.IconButton(
                            ft.Icons.DOWNLOAD, icon_size=20,
                            icon_color="#2563eb",
                            tooltip="Download",
                            on_click=_download),
                        ft.IconButton(
                            ft.Icons.RESTORE, icon_size=20,
                            icon_color="#d97706",
                            tooltip="Restore",
                            on_click=_restore),
                        ft.IconButton(
                            ft.Icons.DELETE, icon_size=20,
                            icon_color="#dc2626",
                            tooltip="Delete",
                            on_click=_delete),
                    ], spacing=0,
                       alignment=ft.MainAxisAlignment.END),
                ], spacing=6),
                padding=12,
                bgcolor=("#dcfce7" if is_selected else ft.Colors.WHITE),
                border_radius=10,
                border=ft.Border.all(
                    2 if is_selected else 1,
                    "#27ae60" if is_selected else "#e2e8f0"),
                on_click=_on_card_tap,
                ink=True,
            )

            self.mobile_list.controls.append(card)

    # =============================================================================
    # 20.1.7c — _select_backup / _get_selected_backup
    # =============================================================================
    def _select_backup(self, idx):
        if self._selected_backup_idx == idx:
            self._selected_backup_idx = None
        else:
            self._selected_backup_idx = idx

        if self.selection_label:
            if self._selected_backup_idx is not None:
                try:
                    b = self.backup_files[self._selected_backup_idx]
                    size = b["file_size"]
                    if size < 1024 * 1024:
                        size_str = f"{size/1024:.1f} KB"
                    else:
                        size_str = f"{size/(1024*1024):.2f} MB"
                    self.selection_label.value = (
                        f"✅ Selected: {b['file_name']} | "
                        f"{size_str} | "
                        f"{b['file_date'].strftime('%Y-%m-%d %H:%M')}")
                except Exception:
                    self.selection_label.value = ""
            else:
                self.selection_label.value = ""

        # Re-render to update highlight
        self._display_backups()
        self._safe_update()

    def _get_selected_backup(self):
        if self._selected_backup_idx is None:
            return None
        try:
            return self.backup_files[self._selected_backup_idx]
        except Exception:
            return None

    # =============================================================================
    # 20.1.7d — toolbar action wrappers
    # =============================================================================
    def _download_selected(self, e=None):
        b = self._get_selected_backup()
        if not b:
            self._snack("⚠️ Tap a backup row/card first to select it",
                        ft.Colors.ORANGE_700)
            return
        self._download_backup(b)

    def _restore_selected(self, e=None):
        b = self._get_selected_backup()
        if not b:
            self._snack("⚠️ Tap a backup row/card first to select it",
                        ft.Colors.ORANGE_700)
            return
        self._confirm_restore(b)

    def _delete_selected(self, e=None):
        b = self._get_selected_backup()
        if not b:
            self._snack("⚠️ Tap a backup row/card first to select it",
                        ft.Colors.ORANGE_700)
            return
        self._confirm_delete(b)

    # =============================================================================
    # 20.1.7e — _download_backup  (cloud-friendly download)
    # =============================================================================
    def _download_backup(self, backup):
        """Copy the backup to /static and open the browser download URL."""
        try:
            path = backup.get("file_path", "")
            if not os.path.exists(path):
                self._snack(f"⚠️ File not found: {path}",
                            ft.Colors.RED_500)
                return

            url = send_file_to_user(
                self.page_ref, path, backup["file_name"])
            if url:
                try:
                    self.page_ref.launch_url(url)
                except Exception:
                    pass
                self._snack(f"⬇️ Downloading {backup['file_name']}",
                            ft.Colors.BLUE_700)
                print(f"[BACKUP] Download URL served: {url}")
            else:
                self._snack("⚠️ Could not serve file for download",
                            ft.Colors.RED_500)
        except Exception as ex:
            print(f"[BACKUP] download error: {ex}")
            traceback.print_exc()
            self._snack(f"❌ Download failed: {ex}",
                        ft.Colors.RED_500)

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

                self._snack(
                    f"✅ Backup created: {Path(backup_path).name}",
                    ft.Colors.GREEN_700)

                # Show full path so user knows where it went
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
                        ft.Container(height=6),
                        ft.Text(
                            "💡 Tip: Use the ⬇️ Download button "
                            "to save a copy to your PC.",
                            size=10, color=ft.Colors.GREY_600,
                            italic=True),
                    ], spacing=8, tight=True),
                    actions=[
                        ft.TextButton(
                            content=ft.Text("OK"),
                            on_click=lambda _: self.page_ref.pop_dialog()),
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
                    "✅ Restore complete. Reloading data…",
                    ft.Colors.GREEN_700)

                # Try to reload DB caches so views pick up new data
                try:
                    if hasattr(self.db, "reload_all"):
                        self.db.reload_all()
                except Exception:
                    pass
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
                    content=ft.Text(
                        backup["file_path"], size=10,
                        selectable=True,
                        color=ft.Colors.GREY_600,
                        max_lines=3,
                        overflow=ft.TextOverflow.ELLIPSIS),
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
        """Show the folder path in a dialog (web-safe)."""
        try:
            folder = self._backup_dir()
            path_str = str(folder)
            print(f"[BACKUP] Folder: {path_str}")

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Row([
                    ft.Icon(ft.Icons.FOLDER_OPEN, color="#7c3aed"),
                    ft.Text("Backup Folder Path",
                            weight=ft.FontWeight.BOLD),
                ], spacing=8),
                content=ft.Column([
                    ft.Text(
                        "Backups are stored on the server. Copy this "
                        "path to access them from a terminal.",
                        size=11, color=ft.Colors.GREY_600),
                    ft.Container(
                        content=ft.Text(path_str, size=11,
                                        selectable=True,
                                        color="#1e40af",
                                        font_family="Consolas"),
                        padding=10, bgcolor="#f0f9ff",
                        border_radius=6,
                        border=ft.Border.all(1, "#bae6fd")),
                    ft.Container(height=6),
                    ft.Text(
                        "💡 On the web, use the ⬇️ Download button to "
                        "save individual backups to your PC.",
                        size=10, color=ft.Colors.GREY_600,
                        italic=True),
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
            self.page_ref.show_dialog(
                ft.SnackBar(content=ft.Text(message), bgcolor=color))
        except Exception:
            # Fallback for old Flet builds
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
# SECTION 20 END — BACKUP TAB (FLET 1.0 — MOBILE-RESPONSIVE)
# =================================================================================