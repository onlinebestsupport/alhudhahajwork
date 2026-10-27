# =================================================================================
# core/data_admin_tab.py — Data Administration (SUPER_ADMIN ONLY)
# =================================================================================
# VERSION HISTORY
#   v2.0 — Async-safe operations, Selective ZIP Import, Missing Folders display,
#          Web-safe file viewing, and restored CSV management functions.
#
# SECTION MAP
#   §1  Module header & imports
#   §2  Module-level helpers
#   §3  class DataAdminTab
#       §3.1  __init__
#       §3.2  build
#       §3.3  _is_narrow
#       §3.4  _access_denied_ui
#       §3.5  _error_ui
#       §3.6  setup_ui
#       §3.7  _register_picker
#       §3.8  refresh
#       §3.9  _build_table_card
#       §3.10 reset_activity_log_confirm
#       §3.11 import_all_files
#       §3.12 _do_bulk_import
#       §3.13 _execute_bulk_import
#       §3.14 _download_csv
#       §3.15 export_all_zip
#       §3.16 create_backup
#       §3.17 _preview_csv
#       §3.18 _upload_csv
#       §3.19 _do_upload
#       §3.20 _show_status
#       §3.21 _snack
#       §3.22 _safe_update
#       §3.23 _build_documents_section
#       §3.24 _documents_refresh
#       §3.25 _documents_folder_row
#       §3.26 _documents_export_zip
#       §3.27 _documents_download_one
#       §3.28 _documents_import_zip
#       §3.29 _apply_documents_zip
#       §3.30 _documents_create_backup
#       §3.31 _documents_view_folder
#       §3.32 _documents_upload_to_folder
#       §3.33 _documents_delete_backup
#       §3.34 _documents_delete_folder
#   §4  Aliases
# =================================================================================

import io
import os
import shutil
import traceback
import zipfile
import asyncio
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
DOCUMENTS_ROOT = "/app/data/documents"

# =================================================================================
# §2  MODULE-LEVEL HELPERS
# =================================================================================

def _safe_str(v):
    if v is None: return ""
    if isinstance(v, float) and v != v: return ""
    try: s = str(v).strip()
    except Exception: return ""
    if s.lower() in ("nan", "none", "nat", "null"): return ""
    return s

def _human_size(n):
    try: n = float(n)
    except Exception: return "?"
    if n < 1024: return f"{int(n)} B"
    if n < 1024 * 1024: return f"{n/1024:.1f} KB"
    if n < 1024 * 1024 * 1024: return f"{n/(1024*1024):.2f} MB"
    return f"{n/(1024*1024*1024):.2f} GB"

def _dir_size(root: Path):
    total = 0
    count = 0
    try:
        for f in root.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                    count += 1
                except Exception:
                    pass
    except Exception:
        pass
    return total, count


# =================================================================================
# §3  class DataAdminTab
# =================================================================================
class DataAdminTab:

    def __init__(self, page, db, current_user):
        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}
        self.data_dir = Path("/app/data")
        self.documents_dir = Path(DOCUMENTS_ROOT)

        self.stats_labels = {}
        self.cards_container = None
        self.status_label = None
        self.root = None

        self.docs_stats_labels = {}
        self.docs_folders_container = None
        self.docs_backups_container = None

        self.file_picker = ft.FilePicker()
        self._picker_registered = False
        self._pending_upload_table = None

        role = _safe_str(self.current_user.get("role", "")).lower()
        if role != "super_admin":
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
            if w is None: w = getattr(self.page_ref.window, "width", None)
            return (w or 1200) < MOBILE_BREAKPOINT
        except Exception:
            return False

    def _access_denied_ui(self):
        return ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.LOCK, size=64, color=ft.Colors.RED_400),
                ft.Text("Access Denied", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
                ft.Text("Only super administrators can access Data Administration.", size=12, color=ft.Colors.GREY_600, text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
            padding=60, alignment=ft.Alignment.CENTER, bgcolor="#fef2f2", border_radius=12, border=ft.Border.all(1, "#fecaca"), expand=True)

    def _error_ui(self, exc):
        return ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.WARNING_AMBER, size=48, color=ft.Colors.ORANGE_600),
                ft.Text("Data Administration failed to load", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(str(exc), size=12, color=ft.Colors.RED_500, selectable=True),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            padding=40, bgcolor="#fef3c7", border_radius=12, alignment=ft.Alignment.CENTER, expand=True)

    # =============================================================================
    # §3.6  setup_ui
    # =============================================================================
    def setup_ui(self):
        narrow = self._is_narrow()

        header = ft.Container(
            content=ft.Row([
                ft.Text("🗄️", size=22 if narrow else 26),
                ft.Column([
                    ft.Text("Data Administration", size=14 if narrow else 16, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    ft.Text("Direct access to your database files", size=9 if narrow else 10, color=ft.Colors.BLUE_100, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=2, expand=True),
                ft.Container(
                    content=ft.Text("SUPER ADMIN", size=9, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4), bgcolor="#dc2626", border_radius=6),
            ], spacing=8 if narrow else 12),
            padding=ft.Padding.symmetric(horizontal=12 if narrow else 22, vertical=10 if narrow else 14),
            gradient=ft.LinearGradient(begin=ft.Alignment.CENTER_LEFT, end=ft.Alignment.CENTER_RIGHT, colors=["#7f1d1d", "#b91c1c", "#dc2626"]),
            border_radius=12)

        stat_specs = [
            ("tables",  "📄", "Tables",     "#2563eb"),
            ("rows",    "📊", "Total Rows", "#059669"),
            ("size",    "💾", "DB Size",    "#7c3aed"),
            ("backups", "📦", "Backups",    "#d97706"),
        ]
        stat_cards = []
        for key, icon, label, color in stat_specs:
            value = ft.Text("0", size=16 if narrow else 18, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
            self.stats_labels[key] = value
            stat_cards.append(ft.Container(
                content=ft.Column([
                    ft.Row([ft.Text(icon, size=14), ft.Text(label, size=10, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD)], spacing=4),
                    value,
                ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=10, bgcolor=color, border_radius=10, height=64, col={"xs": 6, "sm": 6, "md": 3}))

        stats_row = ft.ResponsiveRow(stat_cards, spacing=6, run_spacing=6)

        def _btn(label, icon, color, handler, expand=False):
            return ft.Button(
                content=ft.Row([ft.Icon(icon, size=16, color=ft.Colors.WHITE), ft.Text(label, size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD)], spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER),
                on_click=handler, height=42, bgcolor=color, expand=expand)

        reset_log_btn = _btn("Reset Activity Log", ft.Icons.DELETE_SWEEP, "#991b1b", self.reset_activity_log_confirm, expand=narrow)
        import_all_btn = _btn("Import All (Local Files)", ft.Icons.CLOUD_UPLOAD, "#7c3aed", self.import_all_files, expand=narrow)

        if narrow:
            toolbar_inner = ft.Column([
                import_all_btn,
                _btn("Export All (ZIP)", ft.Icons.DOWNLOAD, "#0891b2", self.export_all_zip, expand=True),
                _btn("Create Backup Now", ft.Icons.SAVE, "#059669", self.create_backup, expand=True),
                _btn("Refresh List", ft.Icons.REFRESH, "#2563eb", self.refresh, expand=True),
                reset_log_btn,
            ], spacing=8)
        else:
            toolbar_inner = ft.Column([
                ft.Row([import_all_btn, _btn("Export All (ZIP)", ft.Icons.DOWNLOAD, "#0891b2", self.export_all_zip), _btn("Create Backup Now", ft.Icons.SAVE, "#059669", self.create_backup), _btn("Refresh List", ft.Icons.REFRESH, "#2563eb", self.refresh)], spacing=8),
                ft.Row([reset_log_btn], spacing=8),
            ], spacing=8)

        toolbar = ft.Container(content=toolbar_inner, padding=10, bgcolor=ft.Colors.WHITE, border_radius=12, border=ft.Border.all(1, "#e2e8f0"))
        self.cards_container = ft.Column(spacing=8)
        documents_section = self._build_documents_section()
        self.status_label = ft.Text("Ready.", size=10, color=ft.Colors.GREY_600, italic=True)

        self.root = ft.Container(
            content=ft.Column(
                controls=[
                    header,
                    ft.Container(height=4),
                    stats_row,
                    toolbar,
                    ft.Container(
                        content=ft.Column([
                            ft.Row([ft.Text("📋", size=14), ft.Text("Database Tables", size=13, weight=ft.FontWeight.BOLD, color="#1e40af")], spacing=6),
                            ft.Text("Each card below represents one CSV file in /app/data.", size=10, color=ft.Colors.GREY_600, italic=True),
                            self.cards_container,
                        ], spacing=8),
                        padding=12, bgcolor=ft.Colors.WHITE, border_radius=12, border=ft.Border.all(1, "#e2e8f0")),
                    documents_section,
                    self.status_label,
                ],
                spacing=10, scroll=ft.ScrollMode.AUTO,
            ),
            padding=10, bgcolor="#f0f2f5", expand=True,
        )
        self._register_picker()

    def _register_picker(self):
        if self._picker_registered: return
        try:
            if hasattr(self.page_ref, "services"):
                if self.file_picker not in self.page_ref.services:
                    self.page_ref.services.append(self.file_picker)
                    self._picker_registered = True
            else:
                if self.file_picker not in self.page_ref.overlay:
                    self.page_ref.overlay.append(self.file_picker)
                    self._picker_registered = True
            try: self.page_ref.update()
            except Exception: pass
        except Exception as ex:
            print(f"[DATA-ADMIN] picker registration failed: {ex}")

    # =============================================================================
    # §3.8  refresh
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
                    mtime = datetime.fromtimestamp(csv_file.stat().st_mtime)
                    total_rows += row_count
                    total_size += size
                    self.cards_container.controls.append(self._build_table_card(csv_file.name, row_count, size, col_names, mtime))
                except Exception as ex:
                    print(f"[DATA-ADMIN] cannot read {csv_file}: {ex}")

            backup_count = 0
            try:
                backup_dir = self.data_dir / "backups"
                if backup_dir.exists(): backup_count = len(list(backup_dir.glob("*.zip")))
            except Exception: pass

            self.stats_labels["tables"].value = str(len(csvs))
            self.stats_labels["rows"].value = str(total_rows)
            self.stats_labels["size"].value = _human_size(total_size)
            self.stats_labels["backups"].value = str(backup_count)

            self._documents_refresh()
            self._show_status(f"✅ Loaded {len(csvs)} tables, {total_rows} rows, {backup_count} backups", ft.Colors.GREEN_700)
            self._safe_update()
        except Exception as ex:
            print(f"[DATA-ADMIN] refresh error: {ex}")
            self._show_status(f"❌ Refresh failed: {ex}", ft.Colors.RED_500)

    def _build_table_card(self, name, rows, size, cols, mtime):
        chips = [ft.Container(content=ft.Text(str(c), size=9, color="#1e40af", weight=ft.FontWeight.BOLD), padding=ft.Padding.symmetric(horizontal=6, vertical=2), bgcolor="#dbeafe", border_radius=6) for c in cols[:8]]
        if len(cols) > 8:
            chips.append(ft.Container(content=ft.Text(f"+{len(cols)-8} more", size=9, color=ft.Colors.GREY_600), padding=ft.Padding.symmetric(horizontal=6, vertical=2), bgcolor="#f1f5f9", border_radius=6))
        
        actions_row = ft.Row([
            ft.TextButton(content=ft.Row([ft.Icon(ft.Icons.VISIBILITY, size=14, color="#0f172a"), ft.Text("Preview", size=11, color="#0f172a")], spacing=4, tight=True), on_click=lambda e, _n=name: self._preview_csv(_n)),
            ft.TextButton(content=ft.Row([ft.Icon(ft.Icons.DOWNLOAD, size=14, color="#0891b2"), ft.Text("Download", size=11, color="#0891b2")], spacing=4, tight=True), on_click=lambda e, _n=name: self._download_csv(_n)),
            ft.TextButton(content=ft.Row([ft.Icon(ft.Icons.UPLOAD, size=14, color="#dc2626"), ft.Text("Upload Replace", size=11, color="#dc2626")], spacing=4, tight=True), on_click=lambda e, _n=name: self._upload_csv(_n)),
        ], spacing=0, alignment=ft.MainAxisAlignment.END)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text(name, size=12, weight=ft.FontWeight.BOLD, color="#0f172a", expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Container(content=ft.Text(f"{rows} rows", size=9, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD), padding=ft.Padding.symmetric(horizontal=6, vertical=2), bgcolor="#2563eb", border_radius=8),
                    ft.Container(content=ft.Text(_human_size(size), size=9, color=ft.Colors.GREY_700), padding=ft.Padding.symmetric(horizontal=6, vertical=2), bgcolor="#f1f5f9", border_radius=8),
                ], spacing=6),
                ft.Text(f"🕒 {mtime.strftime('%Y-%m-%d %H:%M')}  ·  🧮 {len(cols)} columns", size=9, color=ft.Colors.GREY_600),
                ft.Row(chips, spacing=4),
                actions_row,
            ], spacing=6),
            padding=12, bgcolor="#f8fafc", border=ft.Border.all(1, "#e2e8f0"), border_radius=10)

    def reset_activity_log_confirm(self, e=None):
        log_path = self.data_dir / "activity_log.csv"
        if not log_path.exists():
            self._snack("⚠️ activity_log.csv not found", ft.Colors.ORANGE_700)
            return

        def do_reset(ev):
            self.page_ref.pop_dialog()
            try:
                backup_dir = self.data_dir / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(log_path, backup_dir / f"activity_log.{stamp}.pre-reset.bak")
                with open(log_path, "w", encoding="utf-8") as fh: fh.write("timestamp,user_id,action,details\n")
                try: self.db.reload_all()
                except Exception: pass
                self.refresh()
                self._snack("✅ Activity log cleared", ft.Colors.GREEN_700)
            except Exception as ex: self._snack(f"❌ Reset failed: {ex}", ft.Colors.RED_500)

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Reset Activity Log?", weight=ft.FontWeight.BOLD),
            content=ft.Text("This will permanently delete ALL activity log entries.", size=12),
            actions=[ft.TextButton(content=ft.Text("Cancel"), on_click=lambda e: self.page_ref.pop_dialog()), ft.Button(content=ft.Text("Reset Now"), on_click=do_reset, bgcolor="#dc2626")]
        )
        self.page_ref.show_dialog(dlg)

    def import_all_files(self, e=None):
        async def _pick():
            try:
                files = await self.file_picker.pick_files(allow_multiple=True, with_data=True, allowed_extensions=["csv"])
                if files: self._do_bulk_import(files)
            except Exception as ex: self._snack(f"❌ File picker error: {ex}", ft.Colors.RED_500)
        self.page_ref.run_task(_pick)

    def _do_bulk_import(self, files):
        existing = {p.name.lower(): p for p in self.data_dir.glob("*.csv")}
        plan = []
        for f in files:
            base = Path(f.name).name
            if not base.lower().endswith(".csv"):
                plan.append({"file": f, "base": base, "target": None, "status": "non-csv"})
                continue
            target = self.data_dir / base
            plan.append({"file": f, "base": base, "target": target, "status": "replace" if base.lower() in existing else "new"})

        def do_import(ev):
            self.page_ref.pop_dialog()
            self._execute_bulk_import(plan)

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Import All — Confirm", weight=ft.FontWeight.BOLD),
            content=ft.Text(f"Importing {len(plan)} file(s). Proceed?"),
            actions=[ft.TextButton(content=ft.Text("Cancel"), on_click=lambda e: self.page_ref.pop_dialog()), ft.Button(content=ft.Text("Import"), on_click=do_import, bgcolor="#2563eb")]
        )
        self.page_ref.show_dialog(dlg)

    def _execute_bulk_import(self, plan):
        backup_dir = self.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        imported, failed = [], []

        for p in plan:
            if p["status"] == "non-csv": continue
            try:
                f = p["file"]
                data = getattr(f, "bytes", None) or open(getattr(f, "path", None), "rb").read()
                new_df = pd.read_csv(io.BytesIO(data))
                target = p["target"]
                if p["status"] == "replace": shutil.copy2(target, backup_dir / f"{p['base']}.{stamp}.pre-import.bak")
                new_df.to_csv(target, index=False, encoding="utf-8-sig")
                imported.append(p["base"])
            except Exception as ex:
                failed.append((p["base"], str(ex)))

        try: self.db.reload_all()
        except Exception: pass
        self.refresh()
        self._snack(f"✅ {len(imported)} imported, {len(failed)} failed", ft.Colors.GREEN_700)

    def _download_csv(self, name):
        path = self.data_dir / name
        if path.exists():
            url = send_file_to_user(self.page_ref, str(path), name)
            if url: self.page_ref.launch_url(url)

    def export_all_zip(self, e=None):
        try:
            out_dir = Path("/tmp/alhudha_exports")
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            bundle = out_dir / f"alhudha_full_db_{stamp}.zip"
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
                for f in self.data_dir.glob("*.csv"): z.write(f, arcname=f.name)
                for f in self.data_dir.glob("*.json"): z.write(f, arcname=f.name)
            url = send_file_to_user(self.page_ref, str(bundle), "Full DB export")
            self._snack(f"✅ Exported {bundle.name}", ft.Colors.GREEN_700)
            if url: self.page_ref.launch_url(url)
        except Exception as ex: self._snack(f"❌ {ex}", ft.Colors.RED_500)

    def create_backup(self, e=None):
        try:
            if hasattr(self.db, "create_backup"):
                path = self.db.create_backup()
                self._snack(f"✅ Backup created: {Path(path).name}", ft.Colors.GREEN_700)
                self.refresh()
        except Exception as ex: self._snack(f"❌ {ex}", ft.Colors.RED_500)

    def _preview_csv(self, name):
        try:
            path = self.data_dir / name
            df = pd.read_csv(path)
            lines = [" | ".join(str(c) for c in df.columns), "─" * 80]
            for _, row in df.iterrows(): lines.append(" | ".join(str(v)[:30].ljust(30) for v in row.values))
            
            preview_list = ft.ListView(controls=[ft.Text(line, size=10, font_family="Consolas", selectable=True, no_wrap=True) for line in lines], spacing=0, expand=True)
            dlg = ft.AlertDialog(
                modal=True, title=ft.Text(f"👁️ {name} — Full Preview"),
                content=ft.Container(content=preview_list, width=900, height=600, padding=10, bgcolor=ft.Colors.WHITE),
                actions=[ft.TextButton(content=ft.Text("Close"), on_click=lambda e: self.page_ref.pop_dialog())]
            )
            self.page_ref.show_dialog(dlg)
        except Exception as ex: self._snack(f"❌ {ex}", ft.Colors.RED_500)

    def _upload_csv(self, name):
        def do_pick(ev):
            self.page_ref.pop_dialog()
            self._pending_upload_table = name
            async def _pick():
                files = await self.file_picker.pick_files(allow_multiple=False, with_data=True)
                if files: self._do_upload(files[0])
            self.page_ref.run_task(_pick)
        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Replace CSV?"), content=ft.Text(f"Replace contents of '{name}'?"),
            actions=[ft.TextButton(content=ft.Text("Cancel"), on_click=lambda e: self.page_ref.pop_dialog()), ft.Button(content=ft.Text("Choose File"), on_click=do_pick, bgcolor="#dc2626")]
        )
        self.page_ref.show_dialog(dlg)

    def _do_upload(self, file_obj):
        name = self._pending_upload_table
        if not name: return
        try:
            data = getattr(file_obj, "bytes", None) or open(getattr(file_obj, "path", None), "rb").read()
            new_df = pd.read_csv(io.BytesIO(data))
            target = self.data_dir / name
            backup_dir = self.data_dir / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_dir / f"{name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.pre-upload.bak")
            new_df.to_csv(target, index=False, encoding="utf-8-sig")
            self.db.reload_all()
            self.refresh()
            self._snack(f"✅ Replaced {name}", ft.Colors.GREEN_700)
        except Exception as ex: self._snack(f"❌ Upload failed: {ex}", ft.Colors.RED_500)
        finally: self._pending_upload_table = None

    def _show_status(self, message, color=ft.Colors.GREY_700):
        if self.status_label:
            self.status_label.value = message
            self.status_label.color = color
        self._safe_update()

    def _snack(self, msg, color=ft.Colors.GREEN_700):
        try: self.page_ref.show_dialog(ft.SnackBar(content=ft.Text(msg), bgcolor=color))
        except Exception: pass

    def _safe_update(self):
        try:
            if self.root: self.root.update()
        except Exception: pass

    # =============================================================================
    # §3.23  _build_documents_section
    # =============================================================================
    def _build_documents_section(self):
        def stat_chip(key, icon, color):
            value = ft.Text("—", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
            self.docs_stats_labels[key] = value
            return ft.Container(content=ft.Row([ft.Text(icon, size=12), value], spacing=4, tight=True), padding=ft.Padding.symmetric(horizontal=10, vertical=6), bgcolor=color, border_radius=8)

        stats_row = ft.Row([stat_chip("folders", "👥", "#0d9488"), stat_chip("files", "📎", "#0891b2"), stat_chip("size", "💾", "#7c3aed")], spacing=6, wrap=True)

        def _act_btn(label, icon, color, handler):
            return ft.Button(content=ft.Row([ft.Icon(icon, size=14, color=ft.Colors.WHITE), ft.Text(label, size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD)], spacing=5, tight=True), on_click=handler, height=38, bgcolor=color, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)))

        actions_row = ft.Row([
            _act_btn("Download All (ZIP)", ft.Icons.DOWNLOAD, "#0891b2", self._documents_export_zip),
            _act_btn("Import ZIP (Restore)", ft.Icons.UPLOAD_FILE, "#7c3aed", self._documents_import_zip),
            _act_btn("Backup Now", ft.Icons.SAVE, "#059669", self._documents_create_backup),
            _act_btn("Refresh", ft.Icons.REFRESH, "#2563eb", lambda e: self._documents_refresh()),
        ], spacing=6, wrap=True)

        self.docs_folders_container = ft.Column(spacing=4)
        self.docs_backups_container = ft.Column(spacing=2)

        return ft.Container(
            content=ft.Column([
                ft.Row([ft.Text("📁", size=16), ft.Column([ft.Text("Traveler Documents", size=13, weight=ft.FontWeight.BOLD, color="#1e40af"), ft.Text("Passports, photos, aadhaar, PAN, vaccine certs — persisted on the Railway Volume", size=10, color=ft.Colors.GREY_600, italic=True)], spacing=2, expand=True)], spacing=8),
                ft.Divider(height=1, color="#e2e8f0"),
                stats_row,
                ft.Container(height=4),
                actions_row,
                ft.Container(height=6),
                ft.Text("📂 Traveler folders:", size=11, weight=ft.FontWeight.BOLD, color="#0f172a"),
                self.docs_folders_container,
                ft.Container(height=6),
                ft.Text("💾 Recent backups:", size=11, weight=ft.FontWeight.BOLD, color="#0f172a"),
                self.docs_backups_container,
            ], spacing=8),
            padding=12, bgcolor=ft.Colors.WHITE, border_radius=12, border=ft.Border.all(1, "#e2e8f0"))

    # =============================================================================
    # §3.24  _documents_refresh
    # =============================================================================
    def _documents_refresh(self):
        try:
            self.documents_dir.mkdir(parents=True, exist_ok=True)
            travelers = self.db.get_travelers()
            travelers.sort(key=lambda t: t.get("id", ""))
            
            valid_folders = {}
            for t in travelers:
                tid = t.get("id", "")
                if tid:
                    clean_name = tid.replace('/', '_').replace('\\', '_')
                    valid_folders[clean_name] = f"{t.get('first_name', '')} {t.get('last_name', '')}".strip()

            folder_data = []
            
            # 1. Add all travelers (even if they don't have a folder yet)
            for tid, name in valid_folders.items():
                path = self.documents_dir / tid
                exists = path.exists()
                size, count = _dir_size(path) if exists else (0, 0)
                mtime = datetime.fromtimestamp(path.stat().st_mtime) if exists else datetime.now()
                folder_data.append({
                    "name": tid, "path": path, "size": size, "files": count,
                    "mtime": mtime, "is_linked": True, "traveler_name": name,
                    "has_folder": exists
                })
            
            # 2. Find unlinked folders
            for item in sorted(self.documents_dir.iterdir()):
                if item.is_dir() and item.name not in valid_folders:
                    size, count = _dir_size(item)
                    folder_data.append({
                        "name": item.name, "path": item, "size": size, "files": count,
                        "mtime": datetime.fromtimestamp(item.stat().st_mtime),
                        "is_linked": False, "traveler_name": "Unknown", "has_folder": True
                    })

            total_size, total_files = _dir_size(self.documents_dir)
            self.docs_stats_labels["folders"].value = str(len([f for f in folder_data if f["has_folder"]]))
            self.docs_stats_labels["files"].value = str(total_files)
            self.docs_stats_labels["size"].value = _human_size(total_size)

            self.docs_folders_container.controls.clear()
            for f in folder_data:
                self.docs_folders_container.controls.append(self._documents_folder_row(f))

            # Backups
            self.docs_backups_container.controls.clear()
            backups = []
            for b in self.data_dir.glob("documents_backup_*.zip"):
                backups.append((b.stat().st_mtime, b))
            backups.sort(reverse=True)

            if not backups:
                self.docs_backups_container.controls.append(ft.Text("No backups yet.", size=10, color=ft.Colors.GREY_600, italic=True))
            else:
                for mtime, b in backups[:10]:
                    def _dl_backup(e, _p=b):
                        url = send_file_to_user(self.page_ref, str(_p), _p.name)
                        if url: self.page_ref.launch_url(url)
                    def _del_backup(e, _p=b):
                        self._documents_delete_backup(_p)
                    self.docs_backups_container.controls.append(
                        ft.Row([
                            ft.Icon(ft.Icons.ARCHIVE, size=12, color="#0891b2"),
                            ft.Text(b.name, size=10, color="#0f172a", expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(_human_size(b.stat().st_size), size=9, color=ft.Colors.GREY_600),
                            ft.Text(datetime.fromtimestamp(mtime).strftime("%d-%m-%Y %H:%M"), size=9, color=ft.Colors.GREY_600),
                            ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_color="#0891b2", icon_size=16, on_click=_dl_backup),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#dc2626", icon_size=16, on_click=_del_backup),
                        ], spacing=6))
        except Exception as ex:
            print(f"[DATA-ADMIN] documents refresh failed: {ex}")
            traceback.print_exc()

    # =============================================================================
    # §3.25  _documents_folder_row
    # =============================================================================
    def _documents_folder_row(self, folder):
        name = folder["name"]
        is_linked = folder.get("is_linked", True)
        has_folder = folder.get("has_folder", False)
        t_name = folder.get("traveler_name", "")

        def _view(e): self._documents_view_folder(name)
        def _upload(e): self._documents_upload_to_folder(name)
        def _dl(e): self._documents_download_one(name)
        def _del(e): self._documents_delete_folder(name)

        if not is_linked:
            name_control = ft.Row([ft.Icon(ft.Icons.FOLDER_OFF, size=14, color="#dc2626"), ft.Text(name, size=10, weight=ft.FontWeight.BOLD, color="#dc2626", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS), ft.Text("(Unlinked)", size=9, color="#dc2626", weight=ft.FontWeight.BOLD)], spacing=4, expand=True)
            btn_upload = ft.IconButton(icon=ft.Icons.UPLOAD, icon_color="#d1d5db", disabled=True)
            btn_view = ft.IconButton(icon=ft.Icons.VISIBILITY, icon_color="#3498db", icon_size=16, on_click=_view)
            btn_dl = ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_color="#0891b2", icon_size=16, on_click=_dl)
            btn_del = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#dc2626", icon_size=16, on_click=_del)
            stat_text = ft.Text(f"{folder['files']} files", size=9, color=ft.Colors.GREY_600)
            bg_color = "#fef2f2"
        elif not has_folder:
            name_control = ft.Row([ft.Icon(ft.Icons.FOLDER_OPEN, size=14, color="#d1d5db"), ft.Text(name, size=10, weight=ft.FontWeight.BOLD, color="#0f172a", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS), ft.Text(f"({t_name})", size=9, color=ft.Colors.GREY_600, italic=True)], spacing=4, expand=True)
            btn_upload = ft.IconButton(icon=ft.Icons.UPLOAD, icon_color="#059669", icon_size=16, on_click=_upload)
            btn_view = ft.IconButton(icon=ft.Icons.VISIBILITY, icon_color="#d1d5db", disabled=True)
            btn_dl = ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_color="#d1d5db", disabled=True)
            btn_del = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#d1d5db", disabled=True)
            stat_text = ft.Text("No document folder", size=9, color="#dc2626", weight=ft.FontWeight.BOLD)
            bg_color = "#f8fafc"
        else:
            name_control = ft.Row([ft.Icon(ft.Icons.FOLDER, size=14, color="#f59e0b"), ft.Text(name, size=10, weight=ft.FontWeight.BOLD, color="#0f172a", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS), ft.Text(f"({t_name})", size=9, color=ft.Colors.GREY_600, italic=True)], spacing=4, expand=True)
            btn_upload = ft.IconButton(icon=ft.Icons.UPLOAD, icon_color="#059669", icon_size=16, on_click=_upload)
            btn_view = ft.IconButton(icon=ft.Icons.VISIBILITY, icon_color="#3498db", icon_size=16, on_click=_view)
            btn_dl = ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_color="#0891b2", icon_size=16, on_click=_dl)
            btn_del = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#dc2626", icon_size=16, on_click=_del)
            stat_text = ft.Text(f"{folder['files']} file{'s' if folder['files'] != 1 else ''}", size=9, color=ft.Colors.GREY_600)
            bg_color = "#f8fafc"

        return ft.Container(
            content=ft.Row([
                name_control, stat_text,
                ft.Container(content=ft.Text(_human_size(folder['size']), size=9, color=ft.Colors.GREY_700), padding=ft.Padding.symmetric(horizontal=5, vertical=2), bgcolor="#f1f5f9" if is_linked and has_folder else "#fee2e2", border_radius=6),
                ft.Text(folder['mtime'].strftime("%d-%m-%Y"), size=9, color=ft.Colors.GREY_500),
                ft.Row([btn_view, btn_upload, btn_dl, btn_del], spacing=0)
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=6, bgcolor=bg_color, border=ft.Border.all(1, "#e2e8f0" if is_linked else "#fecaca"), border_radius=8)

    def _documents_export_zip(self, e=None):
        if not self.documents_dir.exists(): return
        out_dir = Path("/tmp/alhudha_docs")
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bundle = out_dir / f"traveler_documents_{stamp}.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
            for f in self.documents_dir.rglob("*"):
                if f.is_file(): z.write(f, arcname=str(f.relative_to(self.documents_dir)))
        url = send_file_to_user(self.page_ref, str(bundle), "Traveler documents")
        if url: self.page_ref.launch_url(url)

    def _documents_download_one(self, folder_name):
        folder_path = self.documents_dir / folder_name
        if not folder_path.exists(): return
        out_dir = Path("/tmp/alhudha_docs")
        out_dir.mkdir(parents=True, exist_ok=True)
        bundle = out_dir / f"{folder_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
            for f in folder_path.rglob("*"):
                if f.is_file(): z.write(f, arcname=str(f.relative_to(folder_path)))
        url = send_file_to_user(self.page_ref, str(bundle), f"{folder_name} documents")
        if url: self.page_ref.launch_url(url)

    # =============================================================================
    # §3.28  _documents_import_zip (Async-safe & Selective)
    # =============================================================================
    def _documents_import_zip(self, e=None):
        async def _pick():
            try:
                self._show_status("⏳ Reading ZIP file...", ft.Colors.BLUE_600)
                self._safe_update()
                
                files = await self.file_picker.pick_files(allow_multiple=False, with_data=True, allowed_extensions=["zip"])
                if files:
                    await self._do_import_documents_zip(files[0])
                else:
                    self._show_status("Ready.", ft.Colors.GREY_700)
            except Exception as ex:
                self._snack(f"❌ Picker error: {ex}", ft.Colors.RED_500)
        self.page_ref.run_task(_pick)

    async def _do_import_documents_zip(self, file_obj):
        try:
            data = getattr(file_obj, "bytes", None) or open(getattr(file_obj, "path", None), "rb").read()
            zf = zipfile.ZipFile(io.BytesIO(data))
            
            top_folders = sorted(list(set(Path(n).parts[0] for n in zf.namelist() if Path(n).parts)))
            folder_cbs = {}
            rows = []
            for tf in top_folders:
                cb = ft.Checkbox(label=tf, value=True)
                folder_cbs[tf] = cb
                rows.append(cb)

            def do_import(ev):
                self.page_ref.pop_dialog()
                selected = [name for name, cb in folder_cbs.items() if cb.value]
                if not selected:
                    self._snack("No folders selected.", ft.Colors.ORANGE_700)
                    return
                self.page_ref.run_task(self._apply_documents_zip, data, selected)

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Row([ft.Icon(ft.Icons.UPLOAD_FILE, size=22, color="#7c3aed"), ft.Text("Select Folders to Import", weight=ft.FontWeight.BOLD)]),
                content=ft.Container(
                    content=ft.Column([ft.Text(f"Found {len(top_folders)} folder(s) in ZIP. Uncheck any you don't want to import.", size=11), *rows], spacing=4, scroll=ft.ScrollMode.AUTO),
                    width=400, height=400
                ),
                actions=[ft.TextButton(content=ft.Text("Cancel"), on_click=lambda e: self.page_ref.pop_dialog()), ft.Button(content=ft.Text("Import Selected"), on_click=do_import, bgcolor="#7c3aed")]
            )
            self._show_status("Ready.", ft.Colors.GREY_700)
            self.page_ref.show_dialog(dlg)
        except Exception as ex:
            self._show_status("Ready.", ft.Colors.GREY_700)
            self._snack(f"❌ Invalid ZIP: {ex}", ft.Colors.RED_500)

    async def _apply_documents_zip(self, data: bytes, selected_folders: list):
        self._show_status("⏳ Importing selected folders...", ft.Colors.BLUE_600)
        self._safe_update()
        await asyncio.sleep(0.1) # Yield to UI
        
        try:
            self.documents_dir.mkdir(parents=True, exist_ok=True)
            extracted = 0
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.is_dir(): continue
                    parts = Path(info.filename).parts
                    if not parts or parts[0] not in selected_folders: continue
                    
                    dest = self.documents_dir / info.filename
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted += 1
                    
                    # Yield control every 10 files to prevent WebSocket timeout
                    if extracted % 10 == 0:
                        await asyncio.sleep(0.01)

            self._documents_refresh()
            self._show_status(f"✅ Imported {extracted} file(s) into {len(selected_folders)} folders.", ft.Colors.GREEN_700)
            self._snack(f"✅ Imported {extracted} files.", ft.Colors.GREEN_700)
        except Exception as ex:
            self._show_status(f"❌ Import failed: {ex}", ft.Colors.RED_500)
            self._snack(f"❌ Import failed: {ex}", ft.Colors.RED_500)

    def _documents_create_backup(self, e=None):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = (self.data_dir / f"documents_backup_{stamp}.zip")
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in self.documents_dir.rglob("*"):
                if f.is_file(): z.write(f, arcname=str(f.relative_to(self.documents_dir)))
        self._snack(f"✅ Backup created: {backup_path.name}", ft.Colors.GREEN_700)
        self._documents_refresh()

    # =============================================================================
    # §3.31  _documents_view_folder (View in Web)
    # =============================================================================
    def _documents_view_folder(self, folder_name):
        folder_path = self.documents_dir / folder_name
        if not folder_path.exists(): return

        files_list = []
        for f in folder_path.rglob("*"):
            if f.is_file():
                files_list.append({"rel": str(f.relative_to(folder_path)), "abs": f, "size": f.stat().st_size})
        files_list.sort(key=lambda x: x["rel"])

        if not files_list:
            self._snack(f"📂 Folder is empty.", ft.Colors.BLUE_700)
            return

        rows = []
        for item in files_list:
            def _view_file(e, _path=item["abs"]):
                url = send_file_to_user(self.page_ref, str(_path), _path.name)
                if url: self.page_ref.launch_url(url)
            def _dl_file(e, _path=item["abs"]):
                url = send_file_to_user(self.page_ref, str(_path), _path.name)
                if url: self.page_ref.launch_url(url)

            rows.append(ft.Row([
                ft.Icon(ft.Icons.INSERT_DRIVE_FILE, size=16, color="#3498db"),
                ft.Text(item["rel"], size=11, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(_human_size(item["size"]), size=10, color=ft.Colors.GREY_600),
                ft.IconButton(icon=ft.Icons.VISIBILITY, icon_color="#3498db", icon_size=16, tooltip="View in Web", on_click=_view_file),
                ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_color="#0891b2", icon_size=16, tooltip="Download", on_click=_dl_file)
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text(f"Files in {folder_name}", weight=ft.FontWeight.BOLD),
            content=ft.Container(content=ft.Column(rows, spacing=4, scroll=ft.ScrollMode.AUTO), width=600, height=450, padding=4),
            actions=[ft.TextButton(content=ft.Text("Close"), on_click=lambda e: self.page_ref.pop_dialog())]
        )
        self.page_ref.show_dialog(dlg)

    # =============================================================================
    # §3.32  _documents_upload_to_folder (Async-safe)
    # =============================================================================
    def _documents_upload_to_folder(self, folder_name):
        async def _pick():
            try:
                files = await self.file_picker.pick_files(allow_multiple=True, with_data=True)
                if not files: return
                
                self._show_status(f"⏳ Uploading {len(files)} file(s)...", ft.Colors.BLUE_600)
                self._safe_update()
                await asyncio.sleep(0.1)
                
                dest_dir = self.documents_dir / folder_name / "uploads"
                dest_dir.mkdir(parents=True, exist_ok=True)
                
                for f in files:
                    data = getattr(f, 'bytes', None) or open(getattr(f, 'path', None), 'rb').read()
                    with open(dest_dir / f.name, "wb") as fh:
                        fh.write(data)
                    await asyncio.sleep(0.01) # Yield to event loop
                    
                self._documents_refresh()
                self._show_status(f"✅ Uploaded {len(files)} file(s) to {folder_name}", ft.Colors.GREEN_700)
                self._snack(f"✅ Uploaded {len(files)} file(s) to {folder_name}", ft.Colors.GREEN_700)
            except Exception as ex:
                self._show_status("Ready.", ft.Colors.GREY_700)
                self._snack(f"❌ Upload failed: {ex}", ft.Colors.RED_500)
        self.page_ref.run_task(_pick)

    def _documents_delete_backup(self, backup_path: Path):
        def do_delete(e):
            self.page_ref.pop_dialog()
            if backup_path.exists(): backup_path.unlink()
            self._snack("🗑️ Backup deleted", ft.Colors.GREEN_700)
            self._documents_refresh()
        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Delete Backup?"), content=ft.Text(f"Delete {backup_path.name}?"),
            actions=[ft.TextButton(content=ft.Text("Cancel"), on_click=lambda e: self.page_ref.pop_dialog()), ft.Button(content=ft.Text("Delete"), on_click=do_delete, bgcolor=ft.Colors.RED_600)]
        )
        self.page_ref.show_dialog(dlg)

    def _documents_delete_folder(self, folder_name):
        def do_delete(e):
            self.page_ref.pop_dialog()
            folder_path = self.documents_dir / folder_name
            if folder_path.exists():
                shutil.rmtree(folder_path)
            self._snack("🗑️ Folder deleted", ft.Colors.GREEN_700)
            self._documents_refresh()
        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Delete Folder?"), content=ft.Text(f"Delete entire folder '{folder_name}'?"),
            actions=[ft.TextButton(content=ft.Text("Cancel"), on_click=lambda e: self.page_ref.pop_dialog()), ft.Button(content=ft.Text("Delete"), on_click=do_delete, bgcolor=ft.Colors.RED_600)]
        )
        self.page_ref.show_dialog(dlg)


# =================================================================================
# §4  ALIASES
# =================================================================================
DataAdminView = DataAdminTab
# =================================================================================
# SECTION END
# =================================================================================
