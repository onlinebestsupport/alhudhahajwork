# =================================================================================
# core/data_admin_tab.py — Data Administration (SUPER_ADMIN ONLY)
# =================================================================================
# VERSION HISTORY
#   v1.9 — Added "Upload Folder (No ZIP)" feature for direct folder import.
#          Async-safe copying to prevent WebSocket timeouts (re-login issues).
#
# SECTION MAP
#   §1  Module header & imports
#   §2  Module-level helpers  (_safe_str, _human_size, _dir_size)
#   §3  class DataAdminTab
#       §3.1  __init__                  constructor / role gate
#       §3.2  build                     Flet entry point
#       §3.3  _is_narrow                responsive breakpoint check
#       §3.4  _access_denied_ui         super_admin gate UI
#       §3.5  _error_ui                 failure fallback UI
#       §3.6  setup_ui                  full layout
#       §3.7  _register_picker          FilePicker registration
#       §3.8  refresh                   scan CSVs + documents, rebuild
#       §3.9  _build_table_card         one card per CSV
#       §3.10 reset_activity_log_confirm  clear activity_log.csv
#       §3.11 import_all_files          multi-select CSV picker
#       §3.12 _do_bulk_import           preview + confirm dialog
#       §3.13 _execute_bulk_import      apply bulk plan
#       §3.14 _download_csv             single file download
#       §3.15 export_all_zip            bundle all CSVs into a ZIP
#       §3.16 create_backup             trigger db.create_backup()
#       §3.17 _preview_csv              show full CSV with scrollbar
#       §3.18 _upload_csv               single-file replace (picker)
#       §3.19 _do_upload                apply single-file upload
#       §3.20 _show_status              write to bottom status label
#       §3.21 _snack                    transient notification
#       §3.22 _safe_update              safe wrapper around root.update()
#       §3.23 _build_documents_section  Documents management UI
#       §3.24 _documents_refresh        scan + update stats/lists + backups
#       §3.25 _documents_folder_row     one row per traveler folder
#       §3.26 _documents_export_zip     full documents ZIP export
#       §3.27 _documents_download_one   per-traveler ZIP download
#       §3.28 _documents_import_zip     ZIP restore with backup
#       §3.29 _apply_documents_zip      apply ZIP restore
#       §3.30 _documents_create_backup  timestamped backup
#       §3.31 _documents_view_folder    View files inside a folder
#       §3.32 _documents_upload_to_folder Upload file to folder
#       §3.33 _documents_delete_backup  Delete a backup file
#       §3.34 _documents_delete_folder  Delete an entire traveler folder
#       §3.35 _documents_upload_folder  Direct folder upload (NEW)
#   §4  Aliases (DataAdminView = DataAdminTab)
# =================================================================================


# =================================================================================
# §1  MODULE HEADER & IMPORTS
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
    # §1.1 — Fallback if helper module missing (keeps UI usable)
    def send_file_to_user(page, path, label="Download"):
        return None


# §1.2 — Responsive breakpoint (px). Below this we stack the toolbar vertically.
MOBILE_BREAKPOINT = 700

# §1.3 — Persistent location of traveler documents (on the Railway Volume)
DOCUMENTS_ROOT = "/app/data/documents"


# =================================================================================
# §2  MODULE-LEVEL HELPERS
# =================================================================================

# ---------------------------------------------------------------------------------
# §2.1  _safe_str — normalise any value to a trimmed string
# ---------------------------------------------------------------------------------
def _safe_str(v):
    """Return a clean str for a value; treats NaN/None/null/nat as ''."""
    if v is None:
        return ""
    if isinstance(v, float) and v != v:  # NaN check
        return ""
    try:
        s = str(v).strip()
    except Exception:
        return ""
    if s.lower() in ("nan", "none", "nat", "null"):
        return ""
    return s


# ---------------------------------------------------------------------------------
# §2.2  _human_size — bytes → human-readable string
# ---------------------------------------------------------------------------------
def _human_size(n):
    """Convert byte count to '123 B' / '1.2 KB' / '3.45 MB' / '1.23 GB'."""
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


# ---------------------------------------------------------------------------------
# §2.3  _dir_size — total bytes + file count for a directory tree
# ---------------------------------------------------------------------------------
def _dir_size(root: Path):
    """Return (bytes, file_count) for all files under root."""
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
# §3  class DataAdminTab  (super_admin only)
# =================================================================================
class DataAdminTab:

    # -----------------------------------------------------------------------------
    # §3.1  __init__ — constructor + role gate
    # -----------------------------------------------------------------------------
    def __init__(self, page, db, current_user):
        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}
        self.data_dir = Path("/app/data")
        self.documents_dir = Path(DOCUMENTS_ROOT)

        # UI handles filled by setup_ui()
        self.stats_labels = {}          # CSV stats
        self.cards_container = None     # Column of CSV cards
        self.status_label = None        # bottom-line status
        self.root = None                # top-level Container

        # ---- Documents section handles ----
        self.docs_stats_labels = {}     # {"folders": Text, "files": Text, "size": Text}
        self.docs_folders_container = None
        self.docs_backups_container = None

        # File picker plumbing
        self.file_picker = ft.FilePicker()
        self._picker_registered = False
        self._pending_upload_table = None   # single CSV upload target

        # Role check
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

    # -----------------------------------------------------------------------------
    # §3.2  build
    # -----------------------------------------------------------------------------
    def build(self):
        return self.root

    # -----------------------------------------------------------------------------
    # §3.3  _is_narrow
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
    # §3.4  _access_denied_ui
    # -----------------------------------------------------------------------------
    def _access_denied_ui(self):
        return ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.LOCK, size=64, color=ft.Colors.RED_400),
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

    # -----------------------------------------------------------------------------
    # §3.5  _error_ui
    # -----------------------------------------------------------------------------
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
    # §3.6  setup_ui
    # =============================================================================
    def setup_ui(self):
        narrow = self._is_narrow()

        # ---- §3.6.1  Header banner ----
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
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
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

        # ---- §3.6.2  Stats cards row ----
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
                padding=10, bgcolor=color, border_radius=10, height=64,
                col={"xs": 6, "sm": 6, "md": 3}))

        stats_row = ft.ResponsiveRow(stat_cards, spacing=6, run_spacing=6)

        # ---- §3.6.3  Toolbar ----
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

        reset_log_btn = _btn(
            "Reset Activity Log", ft.Icons.DELETE_SWEEP,
            "#991b1b", self.reset_activity_log_confirm, expand=narrow)

        import_all_btn = _btn(
            "Import All (Local Files)", ft.Icons.CLOUD_UPLOAD,
            "#7c3aed", self.import_all_files, expand=narrow)

        if narrow:
            toolbar_inner = ft.Column([
                import_all_btn,
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
                    import_all_btn,
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

        # ---- §3.6.4  CSV cards container ----
        self.cards_container = ft.Column(spacing=8)

        # ---- §3.6.5  Documents section ----
        documents_section = self._build_documents_section()

        # ---- §3.6.6  Status label ----
        self.status_label = ft.Text("Ready.", size=10,
                                    color=ft.Colors.GREY_600, italic=True)

        # ---- §3.6.7  Assemble root ----
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
                        padding=12, bgcolor=ft.Colors.WHITE,
                        border_radius=12,
                        border=ft.Border.all(1, "#e2e8f0")),
                    documents_section,
                    self.status_label,
                ],
                spacing=10, scroll=ft.ScrollMode.AUTO,
            ),
            padding=10, bgcolor="#f0f2f5", expand=True,
        )

        # ---- §3.6.8  Register picker ----
        self._register_picker()

    # -----------------------------------------------------------------------------
    # §3.7  _register_picker
    # -----------------------------------------------------------------------------
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
    # §3.8  refresh — scan CSVs + documents
    # =============================================================================
    def refresh(self, e=None):
        try:
            # ---- CSVs ----
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

            # ---- Documents ----
            self._documents_refresh()

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

    # =============================================================================
    # §3.9  _build_table_card
    # =============================================================================
    def _build_table_card(self, name, rows, size, cols, mtime):
        narrow = self._is_narrow()

        chips = []
        for c in cols[:8]:
            chips.append(
                ft.Container(
                    content=ft.Text(str(c), size=9, color="#1e40af",
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

        def _download(e, _n=name):   self._download_csv(_n)
        def _upload(e, _n=name):     self._upload_csv(_n)
        def _preview(e, _n=name):    self._preview_csv(_n)

        actions_row = ft.Row([
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.VISIBILITY, size=14, color="#0f172a"),
                    ft.Text("Preview", size=11, color="#0f172a"),
                ], spacing=4, tight=True),
                on_click=_preview),
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.DOWNLOAD, size=14, color="#0891b2"),
                    ft.Text("Download", size=11, color="#0891b2"),
                ], spacing=4, tight=True),
                on_click=_download),
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.UPLOAD, size=14, color="#dc2626"),
                    ft.Text("Upload Replace", size=11, color="#dc2626"),
                ], spacing=4, tight=True),
                on_click=_upload),
        ], spacing=0, alignment=ft.MainAxisAlignment.END)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text(name, size=12,
                            weight=ft.FontWeight.BOLD,
                            color="#0f172a", expand=True,
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
            padding=12, bgcolor="#f8fafc",
            border=ft.Border.all(1, "#e2e8f0"),
            border_radius=10)

    # =============================================================================
    # §3.10  reset_activity_log_confirm
    # =============================================================================
    def reset_activity_log_confirm(self, e=None):
        log_path = self.data_dir / "activity_log.csv"

        if not log_path.exists():
            self._snack("⚠️ activity_log.csv not found",
                        ft.Colors.ORANGE_700)
            return

        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                current_rows = max(0, sum(1 for _ in fh) - 1)
        except Exception:
            current_rows = 0

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
                backup_dir = self.data_dir / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"activity_log.{stamp}.pre-reset.bak"
                shutil.copy2(log_path, backup_path)
                print(f"[DATA-ADMIN] activity log backup: {backup_path}")

                if header_line:
                    with open(log_path, "w", encoding="utf-8") as fh:
                        fh.write(header_line + "\n")
                else:
                    with open(log_path, "w", encoding="utf-8") as fh:
                        fh.write("timestamp,user_id,action,details\n")

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
                self._snack(f"❌ Reset failed: {ex}", ft.Colors.RED_500)

        def cancel(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, size=24, color="#dc2626"),
                ft.Text("Reset Activity Log?",
                        weight=ft.FontWeight.BOLD, size=15),
            ], spacing=8),
            content=ft.Column([
                ft.Text("This will permanently delete ALL "
                        "activity log entries.", size=12),
                ft.Container(height=8),
                ft.Container(
                    content=ft.Column([
                        ft.Text(f"📊 Current entries:  {current_rows}",
                                size=11, weight=ft.FontWeight.BOLD,
                                color="#991b1b"),
                        ft.Text("📁 File:  activity_log.csv",
                                size=11, color="#991b1b"),
                        ft.Text("💾 Backup:  will be saved to "
                                "/app/data/backups/",
                                size=11, color="#991b1b"),
                    ], spacing=4),
                    padding=10, bgcolor="#fee2e2", border_radius=6,
                    border=ft.Border.all(1, "#fecaca")),
                ft.Container(height=8),
                ft.Text("⚠️ A timestamped backup of the current log "
                        "will be created BEFORE the reset. "
                        "You can restore it from the Backups folder "
                        "if needed.",
                        size=10, color=ft.Colors.GREY_600, italic=True),
            ], spacing=6, tight=True),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=cancel),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.DELETE_SWEEP, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Reset Now", color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=do_reset,
                    bgcolor="#dc2626"),
            ])
        self.page_ref.show_dialog(dlg)

    # =============================================================================
    # §3.11  import_all_files
    # =============================================================================
    def import_all_files(self, e=None):
        async def _pick():
            try:
                files = await self.file_picker.pick_files(
                    allow_multiple=True,
                    with_data=True,
                    allowed_extensions=["csv"],
                )
                if not files:
                    self._snack("⚠️ No files selected",
                                ft.Colors.ORANGE_700)
                    return
                self._do_bulk_import(files)
            except Exception as ex:
                print(f"[DATA-ADMIN] bulk picker error: {ex}")
                traceback.print_exc()
                self._snack(f"❌ File picker error: {ex}",
                            ft.Colors.RED_500)

        try:
            self.page_ref.run_task(_pick)
        except Exception as ex:
            print(f"[DATA-ADMIN] run_task failed: {ex}")
            self._snack(f"⚠️ {ex}", ft.Colors.RED_500)

    # =============================================================================
    # §3.12  _do_bulk_import
    # =============================================================================
    def _do_bulk_import(self, files):
        existing = {p.name.lower(): p for p in self.data_dir.glob("*.csv")}

        plan = []
        for f in files:
            fname = getattr(f, "name", "") or ""
            base = Path(fname).name
            if not base.lower().endswith(".csv"):
                plan.append({"file": f, "base": base,
                             "target": None, "status": "non-csv"})
                continue
            target = self.data_dir / base
            if base.lower() in existing:
                plan.append({"file": f, "base": base,
                             "target": target, "status": "replace"})
            else:
                plan.append({"file": f, "base": base,
                             "target": target, "status": "new"})

        if not plan:
            self._snack("⚠️ No usable files", ft.Colors.ORANGE_700)
            return

        replaces = [p for p in plan if p["status"] == "replace"]
        news     = [p for p in plan if p["status"] == "new"]
        skipped  = [p for p in plan if p["status"] == "non-csv"]

        def _row_count(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return max(0, sum(1 for _ in fh) - 1)
            except Exception:
                return "?"

        replace_rows = [
            ft.Row([
                ft.Icon(ft.Icons.SWAP_HORIZ, size=12, color="#dc2626"),
                ft.Text(p["base"], size=10, expand=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{_row_count(p['target'])} rows",
                        size=9, color=ft.Colors.GREY_600),
            ], spacing=6) for p in replaces[:30]
        ]
        new_rows = [
            ft.Row([
                ft.Icon(ft.Icons.ADD_CIRCLE, size=12, color="#059669"),
                ft.Text(p["base"], size=10, expand=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text("new", size=9, color="#059669",
                        weight=ft.FontWeight.BOLD),
            ], spacing=6) for p in news[:30]
        ]
        skip_rows = [
            ft.Row([
                ft.Icon(ft.Icons.BLOCK, size=12, color=ft.Colors.GREY_500),
                ft.Text(p["base"] or "(unnamed)", size=10,
                        color=ft.Colors.GREY_500, expand=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=6) for p in skipped[:10]
        ]

        def do_import(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
            self._execute_bulk_import(plan)

        def cancel(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

        blocks = [
            ft.Text(f"Selected {len(plan)} file(s) from local system.",
                    size=12, weight=ft.FontWeight.BOLD),
            ft.Container(height=6),
        ]
        if replaces:
            blocks.append(ft.Container(
                content=ft.Column([
                    ft.Text(f"🔁 Will REPLACE ({len(replaces)}):",
                            size=11, weight=ft.FontWeight.BOLD,
                            color="#991b1b"),
                    *replace_rows,
                ], spacing=3),
                padding=10, bgcolor="#fee2e2", border_radius=6,
                border=ft.Border.all(1, "#fecaca")))
            blocks.append(ft.Container(height=6))
        if news:
            blocks.append(ft.Container(
                content=ft.Column([
                    ft.Text(f"➕ New tables ({len(news)}):",
                            size=11, weight=ft.FontWeight.BOLD,
                            color="#065f46"),
                    *new_rows,
                ], spacing=3),
                padding=10, bgcolor="#d1fae5", border_radius=6,
                border=ft.Border.all(1, "#a7f3d0")))
            blocks.append(ft.Container(height=6))
        if skipped:
            blocks.append(ft.Container(
                content=ft.Column([
                    ft.Text(f"⏭️ Skipped ({len(skipped)}):",
                            size=11, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREY_600),
                    *skip_rows,
                ], spacing=3),
                padding=10, bgcolor="#f1f5f9", border_radius=6))
            blocks.append(ft.Container(height=6))

        blocks.append(ft.Text(
            "⚠️ A timestamped backup of each replaced file will be "
            "saved to /app/data/backups/ before overwrite.",
            size=10, italic=True, color=ft.Colors.GREY_600))

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.UPLOAD_FILE, size=22, color="#2563eb"),
                ft.Text("Import All — Confirm",
                        weight=ft.FontWeight.BOLD, size=15),
            ], spacing=8),
            content=ft.Container(
                content=ft.Column(blocks, spacing=4,
                                  scroll=ft.ScrollMode.AUTO),
                width=520, height=460, padding=4),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=cancel),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.CLOUD_UPLOAD, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Import All Now", color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=do_import,
                    bgcolor="#2563eb"),
            ])
        self.page_ref.show_dialog(dlg)

    # =============================================================================
    # §3.13  _execute_bulk_import
    # =============================================================================
    def _execute_bulk_import(self, plan):
        backup_dir = self.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        imported, failed = [], []
        skipped = 0

        for p in plan:
            if p["status"] == "non-csv":
                skipped += 1
                continue
            try:
                f = p["file"]
                data = getattr(f, "bytes", None)
                if not data:
                    src = getattr(f, "path", None)
                    if src and os.path.exists(src):
                        with open(src, "rb") as fh:
                            data = fh.read()
                if not data:
                    failed.append((p["base"], "empty file"))
                    continue

                new_df = pd.read_csv(io.BytesIO(data))
                target = p["target"]

                if p["status"] == "replace":
                    try:
                        old_cols = list(
                            pd.read_csv(target, nrows=0).columns)
                        new_cols = list(new_df.columns)
                        missing = [c for c in old_cols
                                   if c not in new_cols]
                        if missing:
                            failed.append((
                                p["base"],
                                f"missing cols: {', '.join(missing[:3])}"))
                            continue
                        new_df = new_df.reindex(columns=old_cols)
                    except Exception as e:
                        print(f"[DATA-ADMIN] col check skip "
                              f"{p['base']}: {e}")

                    shutil.copy2(
                        target,
                        backup_dir / f"{p['base']}.{stamp}.pre-import.bak")

                new_df.to_csv(target, index=False, encoding="utf-8-sig")
                imported.append((p["base"], len(new_df),
                                 "replaced" if p["status"] == "replace"
                                 else "created"))
            except Exception as ex:
                print(f"[DATA-ADMIN] import error {p.get('base')}: {ex}")
                failed.append((p.get("base", "?"), str(ex)))

        try:
            if hasattr(self.db, "reload_all"):
                self.db.reload_all()
            elif hasattr(self.db, "reload"):
                self.db.reload()
        except Exception:
            pass

        self.refresh()

        parts = []
        if imported: parts.append(f"✅ {len(imported)} imported")
        if failed:   parts.append(f"❌ {len(failed)} failed")
        if skipped:  parts.append(f"⏭️ {skipped} skipped")
        self._snack("  ·  ".join(parts) if parts else "Nothing imported",
                    ft.Colors.GREEN_700 if imported else ft.Colors.RED_500)

        if failed:
            fail_lines = [f"• {n}: {err}" for n, err in failed[:20]]
            self.page_ref.show_dialog(ft.AlertDialog(
                modal=True,
                title=ft.Text("⚠️ Some files failed"),
                content=ft.Text("\n".join(fail_lines), size=11,
                                selectable=True),
                actions=[ft.TextButton(
                    content=ft.Text("OK"),
                    on_click=lambda e: self.page_ref.pop_dialog())],
            ))

    # =============================================================================
    # §3.14  _download_csv
    # =============================================================================
    def _download_csv(self, name):
        try:
            path = self.data_dir / name
            if not path.exists():
                self._snack(f"⚠️ {name} not found")
                return
            url = send_file_to_user(self.page_ref, str(path), name)
            self._snack(f"⬇️ Downloading {name}", ft.Colors.BLUE_700)
            if url:
                try:
                    self.page_ref.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            print(f"[DATA-ADMIN] download error: {ex}")
            self._snack(f"❌ {ex}", ft.Colors.RED_500)

    # =============================================================================
    # §3.15  export_all_zip
    # =============================================================================
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

    # =============================================================================
    # §3.16  create_backup
    # =============================================================================
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

    # =============================================================================
    # §3.17  _preview_csv — Loads FULL CSV with a ListView scrollbar
    # =============================================================================
    def _preview_csv(self, name):
        try:
            path = self.data_dir / name
            if not path.exists():
                self._snack(f"⚠️ {name} not found")
                return
            
            df = pd.read_csv(path)
            total_rows = len(df)

            header_text = " | ".join(str(c) for c in df.columns)
            lines = [header_text, "─" * 80]
            
            for _, row in df.iterrows():
                row_str = " | ".join(str(v)[:30].ljust(30) for v in row.values)
                lines.append(row_str)

            narrow = self._is_narrow()

            preview_list = ft.ListView(
                controls=[
                    ft.Text(line, size=10, font_family="Consolas", 
                            selectable=True, no_wrap=True)
                    for line in lines
                ],
                spacing=0,
                expand=True
            )

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text(f"👁️ {name} — Full Preview ({total_rows} rows)",
                              weight=ft.FontWeight.BOLD,
                              size=13 if narrow else 14),
                content=ft.Container(
                    content=preview_list,
                    width=None if narrow else 900,
                    height=None if narrow else 600,
                    expand=narrow,
                    padding=10,
                    bgcolor=ft.Colors.WHITE,
                    border=ft.Border.all(1, ft.Colors.GREY_300),
                    border_radius=8
                ),
                actions=[
                    ft.TextButton(
                        content=ft.Text("Close"),
                        on_click=lambda e: self.page_ref.pop_dialog()),
                ])
            self.page_ref.show_dialog(dialog)
        except Exception as ex:
            print(f"[DATA-ADMIN] preview error: {ex}")
            traceback.print_exc()
            self._snack(f"❌ {ex}", ft.Colors.RED_500)

    # =============================================================================
    # §3.18  _upload_csv
    # =============================================================================
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
                ft.Text(f"You are about to REPLACE the entire contents "
                        f"of '{name}'.", size=12),
                ft.Container(height=6),
                ft.Container(
                    content=ft.Text(
                        f"Current: {current_rows} rows\n\n"
                        f"⚠️ A timestamped backup will be created "
                        f"in /app/data/backups/ before replacing.",
                        size=11, color="#991b1b"),
                    padding=10, bgcolor="#fee2e2", border_radius=6),
            ], spacing=6, tight=True),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=cancel),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.UPLOAD, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Choose File", color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=do_pick,
                    bgcolor="#dc2626"),
            ])
        self.page_ref.show_dialog(dialog)

    # =============================================================================
    # §3.19  _do_upload
    # =============================================================================
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
            self._snack(f"❌ Upload failed: {ex}", ft.Colors.RED_500)
        finally:
            self._pending_upload_table = None

    # =============================================================================
    # §3.20  _show_status
    # =============================================================================
    def _show_status(self, message, color=ft.Colors.GREY_700):
        try:
            if self.status_label is not None:
                self.status_label.value = message
                self.status_label.color = color
        except Exception:
            pass
        self._safe_update()

    # =============================================================================
    # §3.21  _snack
    # =============================================================================
    def _snack(self, msg, color=ft.Colors.GREEN_700):
        try:
            self.page_ref.show_dialog(
                ft.SnackBar(content=ft.Text(msg), bgcolor=color))
        except Exception:
            pass

    # =============================================================================
    # §3.22  _safe_update
    # =============================================================================
    def _safe_update(self):
        try:
            if self.root is not None:
                self.root.update()
        except Exception:
            pass

    # =============================================================================
    # §3.23  _build_documents_section
    # =============================================================================
    def _build_documents_section(self):
        narrow = self._is_narrow()

        # ---- Header row with live stats ----
        def stat_chip(key, icon, color):
            value = ft.Text("—", size=12,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE)
            self.docs_stats_labels[key] = value
            return ft.Container(
                content=ft.Row([
                    ft.Text(icon, size=12),
                    value,
                ], spacing=4, tight=True),
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                bgcolor=color, border_radius=8)

        stats_row = ft.Row([
            stat_chip("folders", "👥", "#0d9488"),
            stat_chip("files",   "📎", "#0891b2"),
            stat_chip("size",    "💾", "#7c3aed"),
        ], spacing=6, wrap=True)

        # ---- Action buttons ----
        def _act_btn(label, icon, color, handler):
            return ft.Button(
                content=ft.Row([
                    ft.Icon(icon, size=14, color=ft.Colors.WHITE),
                    ft.Text(label, size=11, color=ft.Colors.WHITE,
                            weight=ft.FontWeight.BOLD),
                ], spacing=5, tight=True),
                on_click=handler,
                height=38, bgcolor=color,
                style=ft.ButtonStyle(
                    shape=ft.RoundedRectangleBorder(radius=8)))

        actions_row = ft.Row([
            _act_btn("Upload Folder (No ZIP)", ft.Icons.DRIVE_FOLDER_UPLOAD,
                     "#0284c7", self._documents_upload_folder),
            _act_btn("Download All (ZIP)", ft.Icons.DOWNLOAD,
                     "#0891b2", self._documents_export_zip),
            _act_btn("Import ZIP (Restore)", ft.Icons.UPLOAD_FILE,
                     "#7c3aed", self._documents_import_zip),
            _act_btn("Backup Now", ft.Icons.SAVE,
                     "#059669", self._documents_create_backup),
            _act_btn("Refresh", ft.Icons.REFRESH,
                     "#2563eb", lambda e: self._documents_refresh()),
        ], spacing=6, wrap=True)

        # ---- Container for the per-traveler list ----
        self.docs_folders_container = ft.Column(spacing=4)

        # ---- Container for the recent backups ----
        self.docs_backups_container = ft.Column(spacing=2)

        # ---- Assemble ----
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("📁", size=16),
                    ft.Column([
                        ft.Text("Traveler Documents",
                                size=13, weight=ft.FontWeight.BOLD,
                                color="#1e40af"),
                        ft.Text("Passports, photos, aadhaar, PAN, "
                                "vaccine certs — persisted on the "
                                "Railway Volume",
                                size=10, color=ft.Colors.GREY_600,
                                italic=True),
                    ], spacing=2, expand=True),
                ], spacing=8),
                ft.Divider(height=1, color="#e2e8f0"),
                stats_row,
                ft.Container(height=4),
                actions_row,
                ft.Container(height=6),
                ft.Text("📂 Traveler folders:",
                        size=11, weight=ft.FontWeight.BOLD,
                        color="#0f172a"),
                self.docs_folders_container,
                ft.Container(height=6),
                ft.Text("💾 Recent backups:",
                        size=11, weight=ft.FontWeight.BOLD,
                        color="#0f172a"),
                self.docs_backups_container,
            ], spacing=8),
            padding=12,
            bgcolor=ft.Colors.WHITE,
            border_radius=12,
            border=ft.Border.all(1, "#e2e8f0"))

    # =============================================================================
    # §3.24  _documents_refresh
    # =============================================================================
    def _documents_refresh(self):
        try:
            self.documents_dir.mkdir(parents=True, exist_ok=True)

            # --- VERIFY FOLDERS AGAINST DB ---
            travelers = self.db.get_travelers()
            valid_folders = {}
            for t in travelers:
                tid = t.get("id", "")
                if tid:
                    clean_name = tid.replace('/', '_').replace('\\', '_')
                    valid_folders[clean_name] = f"{t.get('first_name', '')} {t.get('last_name', '')}".strip()

            folders = []
            try:
                for item in sorted(self.documents_dir.iterdir()):
                    if not item.is_dir():
                        continue
                    
                    is_linked = item.name in valid_folders
                    t_name = valid_folders.get(item.name, "")
                    
                    size, count = _dir_size(item)
                    folders.append({
                        "name": item.name,
                        "path": item,
                        "size": size,
                        "files": count,
                        "mtime": datetime.fromtimestamp(item.stat().st_mtime),
                        "is_linked": is_linked,
                        "traveler_name": t_name
                    })
            except Exception as e:
                print(f"[DATA-ADMIN] documents iter failed: {e}")

            total_size, total_files = _dir_size(self.documents_dir)

            try:
                self.docs_stats_labels["folders"].value = str(len(folders))
                self.docs_stats_labels["files"].value = str(total_files)
                self.docs_stats_labels["size"].value = _human_size(total_size)
            except Exception:
                pass

            if self.docs_folders_container is not None:
                self.docs_folders_container.controls.clear()

                if not folders:
                    self.docs_folders_container.controls.append(
                        ft.Text("No traveler folders yet.",
                                size=10, color=ft.Colors.GREY_600,
                                italic=True))
                else:
                    for f in folders:
                        self.docs_folders_container.controls.append(
                            self._documents_folder_row(f))

            if self.docs_backups_container is not None:
                self.docs_backups_container.controls.clear()

                backups = []
                try:
                    for b in self.data_dir.glob("documents_backup_*.tar.gz"):
                        backups.append((b.stat().st_mtime, b))
                    for b in self.data_dir.glob("documents_backup_*.zip"):
                        backups.append((b.stat().st_mtime, b))
                except Exception:
                    pass

                backups.sort(reverse=True)

                if not backups:
                    self.docs_backups_container.controls.append(
                        ft.Text("No backups yet.",
                                size=10, color=ft.Colors.GREY_600,
                                italic=True))
                else:
                    for mtime, b in backups[:10]: # Show up to 10 backups
                        size_str = _human_size(b.stat().st_size)
                        
                        def _dl_backup(e, _p=b):
                            url = send_file_to_user(self.page_ref, str(_p), _p.name)
                            if url:
                                try:
                                    self.page_ref.launch_url(url)
                                except Exception:
                                    pass
                                    
                        def _del_backup(e, _p=b):
                            self._documents_delete_backup(_p)
                                    
                        self.docs_backups_container.controls.append(
                            ft.Row([
                                ft.Icon(ft.Icons.ARCHIVE, size=12,
                                        color="#0891b2"),
                                ft.Text(b.name, size=10,
                                        color="#0f172a",
                                        expand=True,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(size_str, size=9,
                                        color=ft.Colors.GREY_600),
                                ft.Text(datetime.fromtimestamp(mtime)
                                        .strftime("%d-%m-%Y %H:%M"),
                                        size=9,
                                        color=ft.Colors.GREY_600),
                                ft.IconButton(
                                    icon=ft.Icons.DOWNLOAD,
                                    icon_color="#0891b2",
                                    icon_size=16,
                                    tooltip="Download Backup",
                                    on_click=_dl_backup),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    icon_color="#dc2626",
                                    icon_size=16,
                                    tooltip="Delete Backup",
                                    on_click=_del_backup),
                            ], spacing=6))
        except Exception as ex:
            print(f"[DATA-ADMIN] documents refresh failed: {ex}")
            traceback.print_exc()

    # =============================================================================
    # §3.25  _documents_folder_row
    # =============================================================================
    def _documents_folder_row(self, folder):
        name = folder["name"]
        size = folder["size"]
        files = folder["files"]
        mtime = folder["mtime"]
        is_linked = folder.get("is_linked", True)
        traveler_name = folder.get("traveler_name", "")

        def _view(e, _name=name): self._documents_view_folder(_name)
        def _upload(e, _name=name): self._documents_upload_to_folder(_name)
        def _dl(e, _name=name): self._documents_download_one(_name)
        def _del(e, _name=name): self._documents_delete_folder(_name)

        if is_linked:
            name_control = ft.Row([
                ft.Icon(ft.Icons.FOLDER, size=14, color="#f59e0b"),
                ft.Text(name, size=10, weight=ft.FontWeight.BOLD, color="#0f172a", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"({traveler_name})", size=9, color=ft.Colors.GREY_600, italic=True)
            ], spacing=4, expand=True)
            
            btn_upload = ft.IconButton(
                icon=ft.Icons.UPLOAD,
                icon_color="#059669",
                icon_size=16,
                tooltip="Upload File",
                on_click=_upload)
        else:
            name_control = ft.Row([
                ft.Icon(ft.Icons.FOLDER_OFF, size=14, color="#dc2626"),
                ft.Text(name, size=10, weight=ft.FontWeight.BOLD, color="#dc2626", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text("(Unlinked / Mismatch)", size=9, color="#dc2626", weight=ft.FontWeight.BOLD)
            ], spacing=4, expand=True)
            
            btn_upload = ft.IconButton(
                icon=ft.Icons.UPLOAD,
                icon_color="#d1d5db",
                icon_size=16,
                tooltip="Upload disabled (Unlinked folder)",
                disabled=True)

        return ft.Container(
            content=ft.Row([
                name_control,
                ft.Text(f"{files} file{'s' if files != 1 else ''}", size=9, color=ft.Colors.GREY_600),
                ft.Container(
                    content=ft.Text(_human_size(size), size=9, color=ft.Colors.GREY_700),
                    padding=ft.Padding.symmetric(horizontal=5, vertical=2),
                    bgcolor="#f1f5f9" if is_linked else "#fee2e2", 
                    border_radius=6),
                ft.Text(mtime.strftime("%d-%m-%Y"), size=9, color=ft.Colors.GREY_500),
                ft.Row([
                    ft.IconButton(
                        icon=ft.Icons.VISIBILITY,
                        icon_color="#3498db",
                        icon_size=16,
                        tooltip="View Files",
                        on_click=_view),
                    btn_upload,
                    ft.IconButton(
                        icon=ft.Icons.DOWNLOAD,
                        icon_color="#0891b2",
                        icon_size=16,
                        tooltip="Download ZIP",
                        on_click=_dl),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_color="#dc2626",
                        icon_size=16,
                        tooltip="Delete Folder",
                        on_click=_del),
                ], spacing=0)
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=6, 
            bgcolor="#f8fafc" if is_linked else "#fef2f2",
            border=ft.Border.all(1, "#e2e8f0" if is_linked else "#fecaca"),
            border_radius=8)

    # =============================================================================
    # §3.26  _documents_export_zip
    # =============================================================================
    def _documents_export_zip(self, e=None):
        try:
            if not self.documents_dir.exists():
                self._snack("⚠️ No documents directory found")
                return

            _, count = _dir_size(self.documents_dir)
            if count == 0:
                self._snack("⚠️ No documents to export",
                            ft.Colors.ORANGE_700)
                return

            out_dir = Path("/tmp/alhudha_docs")
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            bundle = out_dir / f"traveler_documents_{stamp}.zip"

            with zipfile.ZipFile(bundle, "w",
                                 zipfile.ZIP_DEFLATED) as z:
                for f in self.documents_dir.rglob("*"):
                    if f.is_file():
                        arc = f.relative_to(self.documents_dir)
                        z.write(f, arcname=str(arc))

            url = send_file_to_user(self.page_ref, str(bundle),
                                    "Traveler documents")
            size_str = _human_size(bundle.stat().st_size)
            self._snack(
                f"✅ Exported {count} file(s) as {bundle.name} ({size_str})",
                ft.Colors.GREEN_700)
            if url:
                try:
                    self.page_ref.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            print(f"[DATA-ADMIN] documents export error: {ex}")
            traceback.print_exc()
            self._snack(f"❌ Export failed: {ex}", ft.Colors.RED_500)

    # =============================================================================
    # §3.27  _documents_download_one
    # =============================================================================
    def _documents_download_one(self, folder_name):
        try:
            folder_path = self.documents_dir / folder_name
            if not folder_path.exists() or not folder_path.is_dir():
                self._snack(f"⚠️ '{folder_name}' not found",
                            ft.Colors.RED_500)
                return

            _, count = _dir_size(folder_path)
            if count == 0:
                self._snack(f"⚠️ '{folder_name}' is empty",
                            ft.Colors.ORANGE_700)
                return

            out_dir = Path("/tmp/alhudha_docs")
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            bundle = out_dir / f"{folder_name}_{stamp}.zip"

            with zipfile.ZipFile(bundle, "w",
                                 zipfile.ZIP_DEFLATED) as z:
                for f in folder_path.rglob("*"):
                    if f.is_file():
                        arc = f.relative_to(folder_path)
                        z.write(f, arcname=str(arc))

            url = send_file_to_user(self.page_ref, str(bundle),
                                    f"{folder_name} documents")
            size_str = _human_size(bundle.stat().st_size)
            self._snack(
                f"✅ {folder_name}: {count} file(s) → "
                f"{bundle.name} ({size_str})",
                ft.Colors.GREEN_700)
            if url:
                try:
                    self.page_ref.launch_url(url)
                except Exception:
                    pass
        except Exception as ex:
            print(f"[DATA-ADMIN] documents download-one error: {ex}")
            traceback.print_exc()
            self._snack(f"❌ Download failed: {ex}", ft.Colors.RED_500)

    # =============================================================================
    # §3.28  _documents_import_zip
    # =============================================================================
    def _documents_import_zip(self, e=None):
        async def _pick():
            try:
                files = await self.file_picker.pick_files(
                    allow_multiple=False,
                    with_data=True,
                    allowed_extensions=["zip"],
                )
                if not files:
                    return
                self._do_import_documents_zip(files[0])
            except Exception as ex:
                print(f"[DATA-ADMIN] documents picker error: {ex}")
                traceback.print_exc()
                self._snack(f"❌ Picker error: {ex}", ft.Colors.RED_500)

        try:
            self.page_ref.run_task(_pick)
        except Exception as ex:
            self._snack(f"⚠️ {ex}", ft.Colors.RED_500)

    def _do_import_documents_zip(self, file_obj):
        try:
            data = getattr(file_obj, "bytes", None)
            fname = getattr(file_obj, "name", "documents.zip")
            if not data:
                src = getattr(file_obj, "path", None)
                if src and os.path.exists(src):
                    with open(src, "rb") as fh:
                        data = fh.read()
            if not data:
                self._snack("⚠️ Empty ZIP", ft.Colors.RED_500)
                return

            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
            except Exception as e:
                self._snack(f"❌ Not a valid ZIP: {e}",
                            ft.Colors.RED_500)
                return

            names = zf.namelist()
            unsafe = [n for n in names
                      if n.startswith("/") or ".." in Path(n).parts]
            if unsafe:
                self._snack(
                    f"❌ ZIP contains unsafe paths "
                    f"({len(unsafe)} entries)", ft.Colors.RED_500)
                return

            top = set()
            for n in names:
                parts = Path(n).parts
                if parts:
                    top.add(parts[0])

            total_size = sum(
                (info.file_size for info in zf.infolist()
                 if not info.is_dir()), 0)
            file_count = sum(
                1 for info in zf.infolist() if not info.is_dir())

            def do_import(ev):
                try:
                    self.page_ref.pop_dialog()
                except Exception:
                    pass
                self._apply_documents_zip(data)

            def cancel(ev):
                try:
                    self.page_ref.pop_dialog()
                except Exception:
                    pass

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Row([
                    ft.Icon(ft.Icons.UPLOAD_FILE, size=22,
                            color="#7c3aed"),
                    ft.Text("Import Documents ZIP — Confirm",
                            weight=ft.FontWeight.BOLD, size=15),
                ], spacing=8),
                content=ft.Column([
                    ft.Text(f"ZIP: {fname}", size=11,
                            weight=ft.FontWeight.BOLD),
                    ft.Text(f"Contains {len(top)} top-level folder(s), "
                            f"{file_count} file(s), "
                            f"{_human_size(total_size)}",
                            size=11),
                    ft.Container(height=6),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Top-level folders found:",
                                    size=10,
                                    weight=ft.FontWeight.BOLD,
                                    color="#7c3aed"),
                            *[ft.Text(f"  • {t}", size=10)
                              for t in sorted(top)[:10]],
                        ], spacing=2),
                        padding=8, bgcolor="#f3e8ff",
                        border_radius=6),
                    ft.Container(height=6),
                    ft.Container(
                        content=ft.Text(
                            "⚠️ Before applying, a full timestamped "
                            "backup of the CURRENT documents will be "
                            "saved to /app/data/.\n\n"
                            "Files with matching paths will be "
                            "OVERWRITTEN. New files will be ADDED. "
                            "Nothing is deleted.",
                            size=10, color="#991b1b"),
                        padding=8, bgcolor="#fee2e2",
                        border_radius=6),
                ], spacing=6, tight=True),
                actions=[
                    ft.TextButton(content=ft.Text("Cancel"),
                                  on_click=cancel),
                    ft.Button(
                        content=ft.Row([
                            ft.Icon(ft.Icons.CLOUD_UPLOAD, size=16,
                                    color=ft.Colors.WHITE),
                            ft.Text("Backup & Import",
                                    color=ft.Colors.WHITE,
                                    weight=ft.FontWeight.BOLD),
                        ], spacing=6, tight=True),
                        on_click=do_import,
                        bgcolor="#7c3aed"),
                ])
            self.page_ref.show_dialog(dlg)
        except Exception as ex:
            print(f"[DATA-ADMIN] documents import error: {ex}")
            traceback.print_exc()
            self._snack(f"❌ Import failed: {ex}", ft.Colors.RED_500)

    # =============================================================================
    # §3.29  _apply_documents_zip
    # =============================================================================
    def _apply_documents_zip(self, data: bytes):
        try:
            backup_name = None
            if self.documents_dir.exists():
                try:
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_path = (self.data_dir /
                                   f"documents_backup_{stamp}.zip")
                    with zipfile.ZipFile(backup_path, "w",
                                         zipfile.ZIP_DEFLATED) as z:
                        for f in self.documents_dir.rglob("*"):
                            if f.is_file():
                                arc = f.relative_to(self.documents_dir)
                                z.write(f, arcname=str(arc))
                    backup_name = backup_path.name
                    print(f"[DATA-ADMIN] pre-import backup: "
                          f"{backup_path}")
                except Exception as e:
                    print(f"[DATA-ADMIN] pre-import backup failed: {e}")

            self.documents_dir.mkdir(parents=True, exist_ok=True)
            extracted = 0
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    parts = Path(info.filename).parts
                    if not parts or ".." in parts:
                        continue
                    dest = self.documents_dir / info.filename
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted += 1

            self._documents_refresh()
            self._safe_update()

            msg = f"✅ Imported {extracted} file(s)"
            if backup_name:
                msg += f"\n💾 Pre-import backup: {backup_name}"
            self._snack(msg, ft.Colors.GREEN_700)
        except Exception as ex:
            print(f"[DATA-ADMIN] apply documents zip error: {ex}")
            traceback.print_exc()
            self._snack(f"❌ Apply failed: {ex}", ft.Colors.RED_500)

    # =============================================================================
    # §3.30  _documents_create_backup
    # =============================================================================
    def _documents_create_backup(self, e=None):
        try:
            if not self.documents_dir.exists():
                self._snack("⚠️ No documents directory",
                            ft.Colors.ORANGE_700)
                return

            _, count = _dir_size(self.documents_dir)
            if count == 0:
                self._snack("⚠️ Nothing to backup",
                            ft.Colors.ORANGE_700)
                return

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = (self.data_dir /
                           f"documents_backup_{stamp}.zip")

            with zipfile.ZipFile(backup_path, "w",
                                 zipfile.ZIP_DEFLATED) as z:
                for f in self.documents_dir.rglob("*"):
                    if f.is_file():
                        arc = f.relative_to(self.documents_dir)
                        z.write(f, arcname=str(arc))

            size_str = _human_size(backup_path.stat().st_size)
            self._snack(
                f"✅ Backup created: {backup_path.name} "
                f"({count} files, {size_str})",
                ft.Colors.GREEN_700)
            self._documents_refresh()
            self._safe_update()
        except Exception as ex:
            print(f"[DATA-ADMIN] documents backup error: {ex}")
            traceback.print_exc()
            self._snack(f"❌ Backup failed: {ex}", ft.Colors.RED_500)

    # =============================================================================
    # §3.31  _documents_view_folder
    # =============================================================================
    def _documents_view_folder(self, folder_name):
        try:
            folder_path = self.documents_dir / folder_name
            if not folder_path.exists() or not folder_path.is_dir():
                self._snack(f"⚠️ '{folder_name}' not found", ft.Colors.RED_500)
                return

            files_list = []
            for f in folder_path.rglob("*"):
                if f.is_file():
                    rel_path = f.relative_to(folder_path)
                    files_list.append({
                        "rel": str(rel_path),
                        "abs": f,
                        "size": f.stat().st_size
                    })
            
            files_list.sort(key=lambda x: x["rel"])

            if not files_list:
                self._snack(f"📂 Folder '{folder_name}' is empty.", ft.Colors.BLUE_700)
                return

            rows = []
            for item in files_list:
                def _dl_file(e, _path=item["abs"]):
                    url = send_file_to_user(self.page_ref, str(_path), _path.name)
                    if url:
                        try:
                            self.page_ref.launch_url(url)
                        except Exception:
                            pass

                rows.append(
                    ft.Row([
                        ft.Icon(ft.Icons.INSERT_DRIVE_FILE, size=16, color="#3498db"),
                        ft.Text(item["rel"], size=11, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(_human_size(item["size"]), size=10, color=ft.Colors.GREY_600),
                        ft.IconButton(
                            icon=ft.Icons.DOWNLOAD,
                            icon_color="#0891b2",
                            icon_size=16,
                            tooltip="Download File",
                            on_click=_dl_file
                        )
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                )

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Row([
                    ft.Icon(ft.Icons.FOLDER_OPEN, color="#f59e0b"),
                    ft.Text(f"Files in {folder_name}", weight=ft.FontWeight.BOLD),
                ], spacing=8),
                content=ft.Container(
                    content=ft.Column(rows, spacing=4, scroll=ft.ScrollMode.AUTO),
                    width=500, height=400, padding=4
                ),
                actions=[
                    ft.TextButton(content=ft.Text("Close"), on_click=lambda e: self.page_ref.pop_dialog())
                ]
            )
            self.page_ref.show_dialog(dlg)

        except Exception as ex:
            print(f"[DATA-ADMIN] view folder error: {ex}")
            self._snack(f"❌ Could not view folder: {ex}", ft.Colors.RED_500)

    # =============================================================================
    # §3.32  _documents_upload_to_folder
    # =============================================================================
    def _documents_upload_to_folder(self, folder_name):
        # --- VERIFY FOLDER IS LINKED ---
        travelers = self.db.get_travelers()
        valid_folders = [t.get("id", "").replace('/', '_').replace('\\', '_') for t in travelers]
        if folder_name not in valid_folders:
            self._snack(f"❌ Cannot upload: '{folder_name}' is an unlinked or mismatched folder.", ft.Colors.RED_500)
            return

        async def _pick():
            try:
                files = await self.file_picker.pick_files(
                    allow_multiple=False,
                    with_data=True
                )
                if not files:
                    return
                
                f = files[0]
                data = getattr(f, 'bytes', None)
                if not data:
                    src = getattr(f, 'path', None)
                    if src and os.path.exists(src):
                        with open(src, 'rb') as fh:
                            data = fh.read()
                            
                if not data:
                    self._snack("⚠️ Empty file", ft.Colors.RED_500)
                    return

                dest_dir = self.documents_dir / folder_name / "uploads"
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / f.name
                
                with open(dest_path, "wb") as fh:
                    fh.write(data)
                
                self._documents_refresh()
                self._safe_update()
                self._snack(f"✅ Uploaded {f.name} to {folder_name}", ft.Colors.GREEN_700)

            except Exception as ex:
                print(f"[DATA-ADMIN] upload to folder error: {ex}")
                traceback.print_exc()
                self._snack(f"❌ Upload failed: {ex}", ft.Colors.RED_500)

        try:
            self.page_ref.run_task(_pick)
        except Exception as ex:
            self._snack(f"⚠️ Could not start file picker: {ex}", ft.Colors.RED_500)

    # =============================================================================
    # §3.33  _documents_delete_backup
    # =============================================================================
    def _documents_delete_backup(self, backup_path: Path):
        def do_delete(e):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
                
            try:
                if backup_path.exists():
                    backup_path.unlink()
                    self._snack(f"🗑️ Deleted backup: {backup_path.name}", ft.Colors.GREEN_700)
                else:
                    self._snack("⚠️ Backup file not found", ft.Colors.ORANGE_700)
            except Exception as ex:
                print(f"[DATA-ADMIN] delete backup error: {ex}")
                self._snack(f"❌ Delete failed: {ex}", ft.Colors.RED_500)
                
            self._documents_refresh()
            self._safe_update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, color="#dc2626"),
                ft.Text("Delete Backup?", weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Text(f"Are you sure you want to delete {backup_path.name}?\n\nThis cannot be undone.", size=12),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=lambda e: self.page_ref.pop_dialog()),
                ft.Button(content=ft.Text("Delete"), on_click=do_delete, bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE)
            ]
        )
        self.page_ref.show_dialog(dlg)

    # =============================================================================
    # §3.34  _documents_delete_folder
    # =============================================================================
    def _documents_delete_folder(self, folder_name):
        def do_delete(e):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

            folder_path = self.documents_dir / folder_name
            try:
                if folder_path.exists() and folder_path.is_dir():
                    shutil.rmtree(folder_path)
                    self._snack(f"🗑️ Deleted folder: {folder_name}", ft.Colors.GREEN_700)
                else:
                    self._snack("⚠️ Folder not found", ft.Colors.ORANGE_700)
            except Exception as ex:
                print(f"[DATA-ADMIN] delete folder error: {ex}")
                self._snack(f"❌ Delete failed: {ex}", ft.Colors.RED_500)

            self._documents_refresh()
            self._safe_update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, color="#dc2626"),
                ft.Text("Delete Folder?", weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Text(f"Are you sure you want to delete the entire folder '{folder_name}'?\n\nAll files inside this folder will be permanently deleted. This action cannot be undone.", size=12),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=lambda e: self.page_ref.pop_dialog()),
                ft.Button(content=ft.Text("Delete"), on_click=do_delete, bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE)
            ]
        )
        self.page_ref.show_dialog(dlg)

    # =============================================================================
    # §3.35  _documents_upload_folder (NEW)
    # =============================================================================
    def _documents_upload_folder(self, e=None):
        async def _pick():
            try:
                self._show_status("⏳ Waiting for folder selection...", ft.Colors.BLUE_600)
                self._safe_update()
                
                folder_path = await self.file_picker.get_directory_path()
                if not folder_path:
                    self._show_status("Ready.", ft.Colors.GREY_700)
                    return
                
                await self._process_folder_upload(folder_path)
            except Exception as ex:
                print(f"[DATA-ADMIN] folder upload error: {ex}")
                self._show_status("Ready.", ft.Colors.GREY_700)
                self._snack(f"❌ Folder picker error: {ex}", ft.Colors.RED_500)
        
        try:
            self.page_ref.run_task(_pick)
        except Exception as ex:
            self._snack(f"⚠️ Could not start folder picker: {ex}", ft.Colors.RED_500)

    async def _process_folder_upload(self, source_dir_str):
        source_dir = Path(source_dir_str)
        folder_name = source_dir.name
        
        self._show_status(f"⏳ Copying folder '{folder_name}'...", ft.Colors.BLUE_600)
        self._safe_update()
        await asyncio.sleep(0.1)
        
        try:
            dest_base = self.documents_dir / folder_name
            dest_base.mkdir(parents=True, exist_ok=True)
            
            file_count = 0
            for root, dirs, files in os.walk(source_dir):
                rel_path = os.path.relpath(root, source_dir)
                dest_dir = dest_base if rel_path == "." else dest_base / rel_path
                dest_dir.mkdir(parents=True, exist_ok=True)
                
                for file in files:
                    src_file = Path(root) / file
                    dest_file = dest_dir / file
                    shutil.copy2(src_file, dest_file)
                    file_count += 1
                    
                    # Prevent WebSocket timeout on large folders
                    if file_count % 10 == 0:
                        await asyncio.sleep(0.01)
                        
            self._documents_refresh()
            self._show_status(f"✅ Uploaded folder '{folder_name}' ({file_count} files).", ft.Colors.GREEN_700)
            self._snack(f"✅ Uploaded folder '{folder_name}' ({file_count} files).", ft.Colors.GREEN_700)
        except Exception as ex:
            traceback.print_exc()
            self._show_status(f"❌ Folder upload failed: {ex}", ft.Colors.RED_500)
            self._snack(f"❌ Folder upload failed: {ex}", ft.Colors.RED_500)


# =================================================================================
# §4  ALIASES
# =================================================================================
DataAdminView = DataAdminTab


# =================================================================================
# SECTION END
# =================================================================================
