# =================================================================================
# core/data_admin_tab.py — Data Administration (SUPER_ADMIN ONLY)
# =================================================================================
# v1.0 — Data Administration tab
#   • Lists every CSV in /app/data
#   • Row count + column names + size + last modified
#   • Download individual CSV (browser)
#   • Upload CSV to replace a table (with auto-backup + column validation)
#   • Export ALL CSVs as ZIP bundle
#   • View sample rows of any table
#   • Create manual backup snapshot
#   • Restricted to super_admin role only
#
# SECTION INDEX:
#   [1] Header
#   [2] Stats cards
#   [3] Toolbar (Export All, Refresh, Create Backup)
#   [4] Table cards (one per CSV)
#   [5] Status line
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

        # UI refs
        self.stats_labels = {}
        self.cards_container = None
        self.status_label = None
        self.root = None
        self.file_picker = ft.FilePicker()
        self._picker_registered = False
        self._pending_upload_table = None

        # Access check
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

    # -----------------------------------------------------------------------------
    def _is_narrow(self):
        try:
            w = self.page_ref.width
            if w is None:
                w = getattr(self.page_ref.window, "width", None)
            return (w or 1200) < MOBILE_BREAKPOINT
        except Exception:
            return False

    # -----------------------------------------------------------------------------
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
    # [ROOT] setup_ui
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

        if narrow:
            toolbar_inner = ft.Column([
                _btn("Export All (ZIP)", ft.Icons.DOWNLOAD,
                     "#0891b2", self.export_all_zip, expand=True),
                _btn("Create Backup Now", ft.Icons.SAVE,
                     "#059669", self.create_backup, expand=True),
                _btn("Refresh List", ft.Icons.REFRESH,
                     "#2563eb", self.refresh, expand=True),
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
            ], spacing=0)

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
    # refresh — scan /app/data and render cards
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
                    # count rows quickly
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

            # Count backups
            backup_count = 0
            try:
                backup_dir = self.data_dir / "backups"
                if backup_dir.exists():
                    backup_count = len(list(backup_dir.glob("*.zip")))
            except Exception:
                pass

            # Update stats
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

        # Column chips
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
    # ACTIONS
    # =============================================================================

    # -------- Download individual CSV --------
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

    # -------- Export ALL as ZIP --------
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

    # -------- Create backup now --------
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

    # -------- Preview first 20 rows --------
    def _preview_csv(self, name):
        try:
            path = self.data_dir / name
            if not path.exists():
                self._snack(f"⚠️ {name} not found")
                return
            df = pd.read_csv(path, nrows=20)
            full_df = pd.read_csv(path, usecols=[0])
            total_rows = len(full_df)

            # Build readable preview
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

    # -------- Upload CSV to replace table --------
    def _upload_csv(self, name):
        """Ask for confirmation, then open file picker."""
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
        """Process the selected file."""
        name = self._pending_upload_table
        if not name:
            return
        try:
            data = getattr(file_obj, "bytes", None)
            fname = getattr(file_obj, "name", "upload.csv")
            if not data:
                # fallback for some Flet versions
                src = getattr(file_obj, "path", None)
                if src and os.path.exists(src):
                    with open(src, "rb") as fh:
                        data = fh.read()
            if not data:
                self._snack("⚠️ Empty file", ft.Colors.RED_500)
                return

            new_df = pd.read_csv(io.BytesIO(data))
            target = self.data_dir / name

            # Validate columns against existing
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
                # reorder to match original
                new_df = new_df.reindex(columns=old_cols)
            except Exception as e:
                print(f"[DATA-ADMIN] column check skipped: {e}")

            # Backup current file
            backup_dir = self.data_dir / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if target.exists():
                shutil.copy2(
                    target,
                    backup_dir / f"{name}.{stamp}.pre-upload.bak")

            # Write new file
            new_df.to_csv(target, index=False, encoding="utf-8-sig")

            # Try to reload DB caches
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


# Alias for main_window.py
DataAdminView = DataAdminTab


# =================================================================================
# SECTION END
# =================================================================================
