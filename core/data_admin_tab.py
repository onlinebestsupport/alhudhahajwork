# =================================================================================
# core/data_admin_tab.py — Data Administration (SUPER_ADMIN ONLY)
# =================================================================================
# VERSION HISTORY
#   v1.0 — Initial release (list CSVs, download, upload, export ZIP, preview)
#   v1.1 — Added Reset Activity Log button
#   v1.2 — Added "Import All" multi-file uploader (bulk import from local system)
#
# SECTION MAP
#   §1  Module header & imports
#   §2  Module-level helpers  (_safe_str, _human_size)
#   §3  class DataAdminTab
#       §3.1  __init__                  constructor / role gate
#       §3.2  build                     Flet entry point
#       §3.3  _is_narrow                responsive breakpoint check
#       §3.4  _access_denied_ui         super_admin gate UI
#       §3.5  _error_ui                 failure fallback UI
#       §3.6  setup_ui                  full layout (header/stats/toolbar/cards)
#       §3.7  _register_picker          FilePicker registration
#       §3.8  refresh                   scan /app/data/*.csv, rebuild cards
#       §3.9  _build_table_card         one card per CSV
#       §3.10 reset_activity_log_confirm  clear activity_log.csv (with backup)
#       §3.11 import_all_files          NEW — multi-select CSV picker
#       §3.12 _do_bulk_import           NEW — preview + confirm dialog
#       §3.13 _execute_bulk_import      NEW — apply bulk plan
#       §3.14 _download_csv             single file download
#       §3.15 export_all_zip            bundle all CSVs into a ZIP
#       §3.16 create_backup             trigger db.create_backup()
#       §3.17 _preview_csv              show first 20 rows in a dialog
#       §3.18 _upload_csv               single-file replace (picker)
#       §3.19 _do_upload                apply single-file upload
#       §3.20 _show_status              write to bottom status label
#       §3.21 _snack                    transient notification
#       §3.22 _safe_update              safe wrapper around root.update()
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

        # UI handles filled by setup_ui()
        self.stats_labels = {}          # {"tables": Text, "rows": Text, ...}
        self.cards_container = None     # Column that holds one card per CSV
        self.status_label = None        # bottom-line status
        self.root = None                # top-level Container returned to caller

        # File picker plumbing (used by §3.11 and §3.18)
        self.file_picker = ft.FilePicker()
        self._picker_registered = False
        self._pending_upload_table = None   # single-file upload target

        # Role check — anything except super_admin is denied
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
    # §3.2  build — Flet entry point (returns the top-level Control)
    # -----------------------------------------------------------------------------
    def build(self):
        return self.root

    # -----------------------------------------------------------------------------
    # §3.3  _is_narrow — responsive breakpoint check
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
    # §3.4  _access_denied_ui — shown when role != super_admin
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
    # §3.5  _error_ui — shown if setup_ui() throws
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
    # §3.6  setup_ui — build the full layout
    #   §3.6.1  Header banner
    #   §3.6.2  Stats cards row
    #   §3.6.3  Toolbar (Export / Backup / Refresh / Import All / Reset Log)
    #   §3.6.4  Table cards container
    #   §3.6.5  Status label
    #   §3.6.6  Assemble root
    #   §3.6.7  Register picker
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

        # Danger button — clear activity log (§3.10)
        reset_log_btn = _btn(
            "Reset Activity Log", ft.Icons.DELETE_SWEEP,
            "#991b1b", self.reset_activity_log_confirm, expand=narrow)

        # NEW button — bulk import from local system (§3.11)
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

        # ---- §3.6.4  Table cards container ----
        self.cards_container = ft.Column(spacing=8)

        # ---- §3.6.5  Status label ----
        self.status_label = ft.Text("Ready.", size=10,
                                    color=ft.Colors.GREY_600, italic=True)

        # ---- §3.6.6  Assemble root ----
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
                    self.status_label,
                ],
                spacing=10, scroll=ft.ScrollMode.AUTO,
            ),
            padding=10, bgcolor="#f0f2f5", expand=True,
        )

        # ---- §3.6.7  Register picker ----
        self._register_picker()

    # -----------------------------------------------------------------------------
    # §3.7  _register_picker — attach FilePicker to page services/overlay
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
    # §3.8  refresh — scan /app/data/*.csv and rebuild cards + stats
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

    # =============================================================================
    # §3.9  _build_table_card — one card per CSV file
    # =============================================================================
    def _build_table_card(self, name, rows, size, cols, mtime):
        narrow = self._is_narrow()

        # §3.9.1 — column chips (first 8)
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

        # §3.9.2 — action callbacks (bound to this card's name)
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

        # §3.9.3 — assembled card
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
    # §3.10  reset_activity_log_confirm — clear activity_log.csv (with backup)
    # =============================================================================
    def reset_activity_log_confirm(self, e=None):
        log_path = self.data_dir / "activity_log.csv"

        if not log_path.exists():
            self._snack("⚠️ activity_log.csv not found",
                        ft.Colors.ORANGE_700)
            return

        # §3.10.1 — read current row count + header
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

        # §3.10.2 — confirm handler
        def do_reset(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
            try:
                # backup first
                backup_dir = self.data_dir / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"activity_log.{stamp}.pre-reset.bak"
                shutil.copy2(log_path, backup_path)
                print(f"[DATA-ADMIN] activity log backup: {backup_path}")

                # rewrite with header only
                if header_line:
                    with open(log_path, "w", encoding="utf-8") as fh:
                        fh.write(header_line + "\n")
                else:
                    with open(log_path, "w", encoding="utf-8") as fh:
                        fh.write("timestamp,user_id,action,details\n")

                # reload DB cache
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

                # log the reset itself
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

        # §3.10.3 — confirmation dialog
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
    # §3.11  import_all_files — NEW: multi-select CSV picker
    # =============================================================================
    def import_all_files(self, e=None):
        """Open a multi-select file picker and import all chosen CSVs."""
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
    # §3.12  _do_bulk_import — NEW: preview + confirm dialog
    #   §3.12.1  Classify each chosen file (replace / new / non-csv)
    #   §3.12.2  Build summary rows
    #   §3.12.3  Confirm dialog
    # =============================================================================
    def _do_bulk_import(self, files):
        # ---- §3.12.1  Classify ----
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

        # ---- §3.12.2  Summary rows ----
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

        # ---- §3.12.3  Confirm dialog ----
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
    # §3.13  _execute_bulk_import — NEW: apply the plan
    #   §3.13.1  Per-file loop (validate → backup → write)
    #   §3.13.2  Reload DB
    #   §3.13.3  Final snackbar + failure dialog
    # =============================================================================
    def _execute_bulk_import(self, plan):
        backup_dir = self.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        imported, failed = [], []
        skipped = 0

        # ---- §3.13.1  Apply each file ----
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

        # ---- §3.13.2  Reload DB cache ----
        try:
            if hasattr(self.db, "reload_all"):
                self.db.reload_all()
            elif hasattr(self.db, "reload"):
                self.db.reload()
        except Exception:
            pass

        self.refresh()

        # ---- §3.13.3  Feedback ----
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
    # §3.14  _download_csv — download a single CSV to the browser
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
    # §3.15  export_all_zip — ZIP every CSV/JSON in /app/data
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
    # §3.16  create_backup — call db.create_backup()
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
    # §3.17  _preview_csv — show first 20 rows in a dialog
    # =============================================================================
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
                                font_family="Consolas", selectable=True),
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

    # =============================================================================
    # §3.18  _upload_csv — single-file replace (opens picker)
    # =============================================================================
    def _upload_csv(self, name):
        # §3.18.1 — picker handler
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

        # §3.18.2 — current row count
        path = self.data_dir / name
        current_rows = "?"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                current_rows = max(0, sum(1 for _ in fh) - 1)
        except Exception:
            pass

        # §3.18.3 — confirm dialog
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
    # §3.19  _do_upload — apply single-file upload
    # =============================================================================
    def _do_upload(self, file_obj):
        name = self._pending_upload_table
        if not name:
            return
        try:
            # §3.19.1 — read bytes (web) or path (desktop)
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

            # §3.19.2 — column validation
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

            # §3.19.3 — backup + write
            backup_dir = self.data_dir / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if target.exists():
                shutil.copy2(
                    target,
                    backup_dir / f"{name}.{stamp}.pre-upload.bak")

            new_df.to_csv(target, index=False, encoding="utf-8-sig")

            # §3.19.4 — reload DB
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
    # §3.20  _show_status — write to bottom status label
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
    # §3.21  _snack — transient notification
    # =============================================================================
    def _snack(self, msg, color=ft.Colors.GREEN_700):
        try:
            self.page_ref.show_dialog(
                ft.SnackBar(content=ft.Text(msg), bgcolor=color))
        except Exception:
            pass

    # =============================================================================
    # §3.22  _safe_update — safe wrapper around root.update()
    # =============================================================================
    def _safe_update(self):
        try:
            if self.root is not None:
                self.root.update()
        except Exception:
            pass


# =================================================================================
# §4  ALIASES
# =================================================================================
DataAdminView = DataAdminTab


# =================================================================================
# SECTION END
# =================================================================================
