# ============================================================================
# core/system_test_tab.py — Professional Super-Admin Diagnostics Console
# ============================================================================
# Version: 2026-11-02-r23-git-cleanup-instructions
# Purpose: Recorded, read-only system diagnostics. Ensures no business data
#          (travelers, payments, etc.) is ever deleted or altered by tests.
# 
# TABLE OF CONTENTS:
#   01. CONSTANTS & CONFIGURATION
#   02. CLASS INITIALIZATION & PATHS
#   03. TEST SPECIFICATIONS (Registry)
#   04. UI CONSTRUCTION
#   05. PERSISTENCE (CSV History)
#   06. MANUS PROMPT & RESULT PREPARATION
#   07. EXECUTION & STATE MANAGEMENT
#   08. DOWNLOADS & EXPORTS
#   09. RESULT RENDERING & HELPERS
#   10. API & FRONTEND TESTS
#   11. INVENTORY & FILESYSTEM TESTS
#   12. DATABASE & FINANCIAL TESTS
#   13. SYSTEM, SECURITY & ENVIRONMENT TESTS
# ============================================================================
from __future__ import annotations

import ast
import asyncio
import csv
import io
import json
import os
import shutil
import stat
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import flet as ft


class SystemTestTab:
    """Diagnostics console. Tests never create, edit, or delete business records."""

    # ========================================================================
    # 01. CONSTANTS & CONFIGURATION
    # ========================================================================
    VERSION = "2026-11-02-r23-git-cleanup-instructions"
    HISTORY_FILE = "system_test_history.csv"
    ERROR_FILE = "system_error_events.csv"
    MAX_HISTORY = 5000
    CHECK_TIMEOUT_SECONDS = 25
    HISTORY_FIELDS = [
        "run_id", "timestamp", "level", "title", "plain_language",
        "message", "owner", "action", "duration_ms", "user_id",
        "manus_prompt",
    ]

    # ========================================================================
    # 02. CLASS INITIALIZATION & PATHS
    # ========================================================================
    def __init__(self, page, db, current_user):
        print(f"[SYSTEM-TEST] loaded version={self.VERSION}", flush=True)
        self.page = page
        self.db = db
        self.current_user = current_user or {}
        self.root = None
        
        # UI Components
        self.results_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
        self.summary = ft.Text("Loading previous diagnostics…", size=13, color=ft.Colors.BLUE_GREY_700)
        self.notification = ft.Text("", size=12, weight=ft.FontWeight.BOLD)
        self.last_run = ft.Text("", size=11, color=ft.Colors.BLUE_GREY_400)
        self.history_label = ft.Text("", size=11, color=ft.Colors.BLUE_GREY_400)
        self.progress_bar = ft.ProgressBar(value=0, color=ft.Colors.BLUE_600, bgcolor=ft.Colors.BLUE_50)
        self.progress_text = ft.Text("Ready — no test is running", size=12, color=ft.Colors.BLUE_GREY_600)
        
        # State
        self._progress_started = None
        self.last_results = []
        self._test_running = False
        self.run_buttons = []
        
        # Cleanup Instructions State
        self.cleanup_instructions_text = ft.Text(
            "Run the 'Complete project inventory' test to generate GitHub cleanup commands.",
            size=12, font_family="monospace", selectable=True, color=ft.Colors.BLUE_GREY_800
        )
        
        self._build_specs()
        self.setup_ui()
        self._load_previous_notification()

    def build(self):
        return self.root

    @property
    def data_dir(self):
        return Path(getattr(self.db, "data_dir", Path("data"))).resolve()

    @property
    def source_root(self):
        return Path(__file__).resolve().parent

    @property
    def project_root(self):
        candidate = self.source_root.parent
        return candidate if (candidate / "main.py").exists() else self.source_root

    @property
    def python_roots(self):
        roots = [self.project_root, self.source_root]
        return list(dict.fromkeys(r for r in roots if r.exists()))

    @property
    def diagnostics_dir(self):
        path = self.data_dir / "system_tests"
        path.mkdir(parents=True, exist_ok=True)
        for filename in (self.HISTORY_FILE, self.ERROR_FILE):
            legacy = self.data_dir / filename
            target = path / filename
            if legacy.exists() and not target.exists():
                try: os.replace(legacy, target)
                except OSError: pass
        return path

    @property
    def export_dir(self):
        path = self.diagnostics_dir / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ========================================================================
    # 03. TEST SPECIFICATIONS (Registry)
    # ========================================================================
    def _build_specs(self):
        self.test_specs = [
            ("API contract", "main.py / security.py", self.check_api_contract),             # 10.01
            ("Live API probe", "main.py / deployed URL", self.check_live_api),               # 10.02
            ("Front-page integrity", "index.html / config", self.check_frontpage),           # 10.03
            ("Static HTML files", "static/**/*.html", self.check_static_html),               # 10.04
            ("GitHub folder layout", "core / data / static / tools", self.check_repository_layout), # 10.05
            ("Database file hygiene", "data/ root", self.check_data_file_hygiene),           # 11.01
            ("Complete project inventory", "all folders / unused files", self.check_unused_files), # 11.02
            ("Database schema", "database.py", self.check_schema),                           # 12.01
            ("Database records", "database.py / travelers", self.check_database_records),    # 12.02
            ("ID and relationship integrity", "database.py / reports", self.check_relationships), # 12.03
            ("Financial precision", "database.py / invoices", self.check_financials),        # 12.04
            ("Payment and invoice status", "payments_tab.py / reports", self.check_statuses),# 12.05
            ("Tax configuration", "settings_manager.py", self.check_tax),                    # 12.06
            ("Backup integrity & age", "backups_tab.py / database.py", self.check_backups),  # 12.07
            ("Source syntax and functions", "all Python files", self.check_source),          # 13.01
            ("UI/button wiring", "Flet tabs and dialogs", self.check_ui_wiring),             # 13.02
            ("Security configuration", "security.py / main.py", self.check_security),        # 13.03
            ("Runtime storage & exports", "main.py / helpers.py / data", self.check_runtime_storage), # 13.04
            ("Background error scan", "activity_log.csv / runtime logs", self.check_background_errors), # 13.05
            ("Tools folder scripts", "tools/*.py", self.check_tools_scripts),                # 13.06
            ("Environment security", "env variables", self.check_environment_security),      # 13.07
            ("File permissions audit", "sensitive files (.env, data)", self.check_file_permissions), # 13.08
            ("Dependencies check", "requirements.txt", self.check_dependencies),             # 13.09
            ("Static assets presence", "static/", self.check_static_assets),                 # 13.10
        ]

    # ========================================================================
    # 04. UI CONSTRUCTION
    # ========================================================================
    def setup_ui(self):
        cards = []
        for title, owner, fn in self.test_specs:
            btn = ft.Button(
                content=ft.Text("Run", size=11, weight=ft.FontWeight.W_600),
                on_click=lambda e, f=fn: self.run_one(f),
                bgcolor=ft.Colors.BLUE_50, color=ft.Colors.BLUE_900, height=32,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6))
            )
            self.run_buttons.append(btn)
            
            cards.append(ft.Container(
                content=ft.Column([
                    ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_900),
                    ft.Text(owner, size=9, color=ft.Colors.BLUE_GREY_500, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Container(expand=True),
                    btn
                ], spacing=4),
                padding=10, bgcolor=ft.Colors.WHITE, border_radius=8,
                border=ft.Border.all(1, ft.Colors.BLUE_GREY_100), col={"xs": 12, "sm": 6, "md": 4, "lg": 3},
            ))

        self.btn_run_all = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=20), ft.Text("Run All Tests", weight=ft.FontWeight.BOLD)], tight=True),
            on_click=self.run_all, bgcolor=ft.Colors.BLUE_700, color=ft.Colors.WHITE, height=45,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))
        )

        self.root = ft.Container(
            content=ft.Column([
                # Header
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.SECURITY, color=ft.Colors.WHITE, size=32),
                        ft.Column([
                            ft.Text("System Diagnostics Center", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                            ft.Text("Professional read-only diagnostic suite", size=12, color=ft.Colors.BLUE_100),
                        ], spacing=2, expand=True),
                        ft.Container(content=ft.Text("SUPER ADMIN", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE), bgcolor=ft.Colors.RED_600, padding=8, border_radius=6),
                    ], spacing=12), padding=20, bgcolor=ft.Colors.BLUE_GREY_900, border_radius=12
                ),
                # Status Board
                ft.Container(
                    content=ft.Column([self.notification, self.summary, self.progress_text, self.progress_bar, self.last_run, self.history_label], spacing=6),
                    padding=15, bgcolor=ft.Colors.BLUE_50, border_radius=8, border=ft.Border.all(1, ft.Colors.BLUE_100)
                ),
                # Action Bar
                ft.Row([
                    self.btn_run_all,
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.REFRESH, size=18), ft.Text("Refresh")], tight=True), on_click=self.refresh_status, bgcolor=ft.Colors.WHITE, color=ft.Colors.BLUE_GREY_800),
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.HISTORY, size=18), ft.Text("Last Run")], tight=True), on_click=self.show_last_run, bgcolor=ft.Colors.WHITE, color=ft.Colors.BLUE_GREY_800),
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.DOWNLOAD, size=18), ft.Text("CSV")], tight=True), on_click=self.download_current_csv, bgcolor=ft.Colors.GREEN_50, color=ft.Colors.GREEN_900),
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.CONTENT_COPY, size=18), ft.Text("Manus TXT")], tight=True), on_click=self.download_manus_prompt, bgcolor=ft.Colors.AMBER_50, color=ft.Colors.AMBER_900),
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.CLEAR_ALL, size=18), ft.Text("Clear Screen")], tight=True), on_click=lambda e: self.clear_screen(), bgcolor=ft.Colors.WHITE, color=ft.Colors.BLUE_GREY_800),
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.DELETE_SWEEP, size=18), ft.Text("Reset")], tight=True), on_click=lambda e: self.confirm_reset_csv_history(), bgcolor=ft.Colors.RED_50, color=ft.Colors.RED_900),
                ], spacing=10, wrap=True),
                
                ft.Divider(height=1, color=ft.Colors.BLUE_GREY_100),
                # Test Cards Grid
                ft.Text("Available Diagnostics", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_900),
                ft.ResponsiveRow(cards, spacing=10, run_spacing=10),
                
                ft.Divider(height=1, color=ft.Colors.BLUE_GREY_100),
                # Results Area
                ft.Text("Diagnostic Results", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_900),
                ft.Container(content=self.results_column, expand=True, padding=10, border=ft.Border.all(1, ft.Colors.BLUE_GREY_100), border_radius=8, bgcolor=ft.Colors.WHITE),
                
                ft.Divider(height=1, color=ft.Colors.BLUE_GREY_100),
                # Repository Cleanup Section
                ft.Container(
                    content=ft.Column([
                        ft.Text("GitHub Repository Cleanup", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_900),
                        ft.Text("Railway containers are ephemeral. To permanently remove unused files, you must delete them from your GitHub repository. Copy the command below and run it in your local project terminal.", size=12, color=ft.Colors.BLUE_GREY_600),
                        ft.Container(
                            content=self.cleanup_instructions_text,
                            padding=15, bgcolor=ft.Colors.GREY_100, border_radius=6, border=ft.Border.all(1, ft.Colors.GREY_300)
                        )
                    ], spacing=10),
                    padding=20, bgcolor=ft.Colors.WHITE, border_radius=8, border=ft.Border.all(1, ft.Colors.BLUE_GREY_100)
                ),
            ], spacing=15, expand=True, scroll=ft.ScrollMode.AUTO),
            padding=20, expand=True, bgcolor=ft.Colors.BLUE_GREY_50,
        )

    # ========================================================================
    # 05. PERSISTENCE (CSV History)
    # ========================================================================
    def _append_rows(self, filename, rows, fields):
        if not rows: return
        path = self.diagnostics_dir / filename
        existing = []
        if path.exists():
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as f:
                    existing = list(csv.DictReader(f))
            except Exception: pass
        existing.extend({k: str(r.get(k, "")) for k in fields} for r in rows)
        existing = existing[-self.MAX_HISTORY:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(existing)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try: tmp.unlink()
                except OSError: pass

    def _history(self):
        path = self.diagnostics_dir / self.HISTORY_FILE
        if not path.exists(): return []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
        except Exception: return []

    def _load_previous_notification(self):
        rows = self._history()
        if not rows:
            self.notification.value = "No previous diagnostic run recorded. Run All Tests to start."
            self.notification.color = ft.Colors.ORANGE_700
            self.history_label.value = f"History: {self.diagnostics_dir / self.HISTORY_FILE}"
            return
        latest_run = rows[-1].get("run_id", "")
        recent = [r for r in rows if r.get("run_id") == latest_run]
        if not recent: return
        failures = [r for r in recent if r.get("level") == "FAIL"]
        warnings = [r for r in recent if r.get("level") == "WARN"]
        self.notification.value = f"Previous run: {len(failures)} failure(s), {len(warnings)} warning(s)."
        self.notification.color = ft.Colors.RED_700 if failures else ft.Colors.ORANGE_700 if warnings else ft.Colors.GREEN_700
        self.history_label.value = f"Recorded runs: {len({r.get('run_id') for r in rows if r.get('run_id')})}"
        self.summary.value = f"Previous run: {recent[-1].get('timestamp', '')} • {len(recent)} checks"

    def _record(self, results, run_id):
        results = [self._prepare_result(r, run_id) for r in results]
        now = datetime.now().isoformat(timespec="seconds")
        rows = [{**r, "run_id": run_id, "timestamp": now, "user_id": self.current_user.get("id", "")} for r in results]
        self._append_rows(self.HISTORY_FILE, rows, self.HISTORY_FIELDS)
        errors = [r for r in rows if r.get("level") in {"FAIL", "WARN"}]
        self._append_rows(self.ERROR_FILE, errors, self.HISTORY_FIELDS)

    def confirm_reset_csv_history(self, e=None):
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Reset diagnostic history?", weight=ft.FontWeight.BOLD),
            content=ft.Text("This clears system_test_history.csv and system_error_events.csv. Business data is never touched."),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=lambda ev: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Reset History"), bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE, on_click=self.reset_csv_history),
            ],
        )
        self.page.show_dialog(dialog)

    def reset_csv_history(self, e=None):
        try:
            directory = self.diagnostics_dir
            for filename in (self.HISTORY_FILE, self.ERROR_FILE):
                target = directory / filename
                with target.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=self.HISTORY_FIELDS)
                    writer.writeheader()
            self.last_results = []
            self.results_column.controls.clear()
            self.notification.value = "Diagnostic history reset successfully."
            self.notification.color = ft.Colors.GREEN_700
            self.summary.value = "No previous diagnostic run recorded."
            self.history_label.value = f"History: {directory / self.HISTORY_FILE}"
            self.page.pop_dialog()
            self._render_results([])
        except Exception as ex:
            self.notification.value = f"Reset failed: {ex}"
            self.notification.color = ft.Colors.RED_700
            try: self.page.pop_dialog()
            except Exception: pass
            self.notification.update()

    def refresh_status(self, e=None):
        if self._test_running: return
        self._load_previous_notification()
        self.show_last_run()
        self.notification.value = "Status refreshed."
        self.notification.color = ft.Colors.GREEN_700
        self.notification.update()

    def show_last_run(self, e=None):
        rows = self._history()
        if not rows:
            self._render_results([self._warn("No history", "No completed diagnostic run recorded yet.", "system_test_tab.py", "Run All Tests")])
            return
        run_id = rows[-1].get("run_id")
        results = [{k: r.get(k, "") for k in self.HISTORY_FIELDS} for r in rows if r.get("run_id") == run_id]
        if results:
            self.last_results = results
            self._render_results(results)

    # ========================================================================
    # 06. MANUS PROMPT & RESULT PREPARATION
    # ========================================================================
    def _plain_language(self, result):
        level, title, message = result.get("level", "FAIL"), result.get("title", "System check"), result.get("message", "")
        if level == "OK": return f"Good news: the {title.lower()} check passed."
        if level == "WARN": return f"Warning: The system found something to review in {title.lower()}. Details: {message}"
        return f"Problem found in {title.lower()}. This area may not work correctly. Details: {message}"

    def _manus_prompt(self, result, run_id=""):
        level = result.get("level", "FAIL")
        return (
            "Alhudha Haj Service P Ltd — System Test Center issue\n\n"
            f"Please investigate this {level} result.\n"
            f"Test: {result.get('title', '')}\n"
            f"Simple explanation: {self._plain_language(result)}\n"
            f"Technical details: {result.get('message', '')}\n"
            f"Responsible file: {result.get('owner', '')}\n"
            f"Recommended action: {result.get('action', '')}\n"
            f"Run ID: {run_id or result.get('run_id', '')}\n\n"
            "Please inspect the project files, identify the cause, make the smallest safe correction, "
            "preserve existing data, and run the relevant tests."
        )

    def _prepare_result(self, result, run_id=""):
        result = dict(result)
        result["plain_language"] = self._plain_language(result)
        result["manus_prompt"] = self._manus_prompt(result, run_id)
        result["run_id"] = run_id
        result["timestamp"] = datetime.now().isoformat(timespec="seconds")
        return result

    # ========================================================================
    # 07. EXECUTION & STATE MANAGEMENT
    # ========================================================================
    def _set_ui_running(self, running: bool):
        self._test_running = running
        if hasattr(self, "btn_run_all") and self.btn_run_all:
            self.btn_run_all.disabled = running
            self.btn_run_all.update()
        for btn in self.run_buttons:
            btn.disabled = running
            try: btn.update()
            except Exception: pass
        
        if running:
            self._progress_started = time.perf_counter()
            self.progress_bar.value = 0
            self.progress_text.value = f"Starting tests — 0% (0/{len(self.test_specs)})"
            self.notification.value = "Tests are running in the background..."
            self.notification.color = ft.Colors.BLUE_700
        else:
            self.progress_bar.value = 1.0
            
        try:
            self.progress_bar.update()
            self.progress_text.update()
            self.notification.update()
        except Exception: pass

    def _show_progress(self, completed, total, title):
        fraction = min(1, completed / total) if total else 1
        elapsed = time.perf_counter() - self._progress_started if self._progress_started else 0
        self.progress_bar.value = fraction
        self.progress_text.value = f"Checking: {title} — {fraction * 100:.0f}% ({completed}/{total}) • {elapsed:.1f}s"
        try:
            self.progress_bar.update()
            self.progress_text.update()
        except Exception: pass

    def _run_specs_sync(self, selected=None):
        specs = selected or self.test_specs
        results = []
        for _, _, fn in specs:
            started = time.perf_counter()
            result = self._safe_call(fn)
            result["duration_ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
            results.append(result)
        return results

    async def _run_spec_with_timeout(self, spec):
        title = spec[0] or getattr(spec[2], "__name__", "selected test")
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._run_specs_sync, [spec]), timeout=self.CHECK_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return [self._fail("Test timed out", f"{title} did not finish within {self.CHECK_TIMEOUT_SECONDS} seconds.", "system_test_tab.py", "Review for slow files or network")]
        except Exception as ex:
            return [self._fail("Test failed", repr(ex), "system_test_tab.py", "Review named check")]

    def run_all(self, e=None):
        if self._test_running: return
        self._set_ui_running(True)
        self.page.run_task(self._run_all_async)

    async def _run_all_async(self):
        run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        results = []
        try:
            total = len(self.test_specs)
            for completed, spec in enumerate(self.test_specs, start=1):
                self._show_progress(completed - 1, total, spec[0])
                result = await self._run_spec_with_timeout(spec)
                results.extend(result)
                self._show_progress(completed, total, spec[0])
            results = [self._prepare_result(r, run_id) for r in results]
            self._record(results, run_id)
            self.last_results = results
            self._render_results(results)
        except Exception as ex:
            result = self._prepare_result(self._fail("Test runner error", repr(ex), "system_test_tab.py", "Review runner"), run_id)
            self.last_results = [result]
            self._record([result], run_id)
            self._render_results([result])
        finally:
            self._set_ui_running(False)

    def run_one(self, fn):
        if self._test_running: return
        self._set_ui_running(True)
        self.page.run_task(self._run_one_async, fn)

    async def _run_one_async(self, fn):
        run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        try:
            results = await self._run_spec_with_timeout(("Selected test", "", fn))
            results = [self._prepare_result(r, run_id) for r in results]
            self._record(results, run_id)
            self.last_results = results
            self._render_results(results)
        except Exception as ex:
            result = self._prepare_result(self._fail("Test runner error", repr(ex), "system_test_tab.py", "Review runner"), run_id)
            self.last_results = [result]
            self._record([result], run_id)
            self._render_results([result])
        finally:
            self._set_ui_running(False)

    def _safe_call(self, fn):
        try:
            result = fn()
            return result if isinstance(result, dict) else self._ok(fn.__name__, str(result))
        except Exception as ex:
            return self._fail("Unexpected error", repr(ex), "system_test_tab.py")

    def clear_screen(self):
        if self._test_running:
            self.notification.value = "A test is running. Clear Screen is available after it finishes."
            self.notification.color = ft.Colors.RED_700
            self.notification.update()
            return
        self.last_results = []
        self._progress_started = None
        self.progress_bar.value = 0
        self.progress_text.value = "Ready — no test is running"
        self.summary.value = "Screen cleared — press Run All Tests to start a new run."
        self.notification.value = ""
        self.last_run.value = ""
        self.history_label.value = "Saved CSV history was not deleted. Press Refresh Status to load it again."
        self.results_column.controls.clear()
        self.cleanup_instructions_text.value = "Run the 'Complete project inventory' test to generate GitHub cleanup commands."
        for control in (self.progress_bar, self.progress_text, self.summary, self.notification, self.last_run, self.history_label, self.results_column, self.cleanup_instructions_text):
            try: control.update()
            except Exception: pass

    # ========================================================================
    # 08. DOWNLOADS & EXPORTS
    # ========================================================================
    def _open_download(self, filename):
        url = f"/download/{filename}"
        public_base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        if public_base: url = f"{public_base}{url}"
        try:
            launcher = ft.UrlLauncher()
            result = launcher.launch_url(url, web_only_window_name="_self")
            if asyncio.iscoroutine(result): self.page.run_task(asyncio.create_task(result))
            return url
        except Exception:
            pass
        try: self.page.launch_url(url)
        except Exception: pass
        return url

    def _export_csv(self, rows, label):
        if not rows:
            self.notification.value = "Nothing to download."
            self.notification.update()
            return
        try:
            project_static = self.project_root / "static" / "downloads"
            project_static.mkdir(parents=True, exist_ok=True)
            filename = f"system_test_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=self.HISTORY_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in rows: writer.writerow({key: row.get(key, "") for key in self.HISTORY_FIELDS})
            
            (project_static / filename).write_text(buffer.getvalue(), encoding="utf-8-sig")
            (self.export_dir / filename).write_text(buffer.getvalue(), encoding="utf-8-sig")
            
            download_url = self._open_download(filename)
            self.notification.value = f"Download started: {filename}"
            self.notification.color = ft.Colors.GREEN_700
        except Exception as ex:
            self.notification.value = f"Export failed: {ex}"
            self.notification.color = ft.Colors.RED_700
        self.notification.update()

    def download_current_csv(self, e=None):
        rows = self.last_results
        if not rows:
            history = self._history()
            if history: rows = [row for row in history if row.get("run_id") == history[-1].get("run_id")]
        self._export_csv(rows, "current_run")

    def download_history_csv(self, e=None):
        self._export_csv(self._history(), "history")

    def download_manus_prompt(self, e=None):
        rows = self.last_results or self._history()
        if not rows: return
        prompts = [row.get("manus_prompt") or self._manus_prompt(row, row.get("run_id", "")) for row in rows if row.get("level") in {"FAIL", "WARN"}]
        if not prompts: prompts = ["Alhudha Haj Service P Ltd — All selected system checks passed."]
        try:
            project_static = self.project_root / "static" / "downloads"
            project_static.mkdir(parents=True, exist_ok=True)
            filename = f"manus_prompts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            text = "\n\n" + ("\n\n" + "=" * 80 + "\n\n").join(prompts)
            (project_static / filename).write_text(text, encoding="utf-8")
            (self.export_dir / filename).write_text(text, encoding="utf-8")
            self._open_download(filename)
            self.notification.value = f"Prompt file downloaded: {filename}"
            self.notification.color = ft.Colors.GREEN_700
        except Exception as ex:
            self.notification.value = f"Prompt export failed: {ex}"
            self.notification.color = ft.Colors.RED_700
        self.notification.update()

    # ========================================================================
    # 09. RESULT RENDERING & HELPERS
    # ========================================================================
    def _render_results(self, results):
        self.results_column.controls.clear()
        passed = sum(r.get("level") == "OK" for r in results)
        failed = sum(r.get("level") == "FAIL" for r in results)
        warnings = sum(r.get("level") == "WARN" for r in results)
        
        self.summary.value = f"Completed {len(results)} checks • Passed: {passed} • Warnings: {warnings} • Failed: {failed}"
        self.last_run.value = f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        self.notification.value = (f"ATTENTION: {failed} failure(s) and {warnings} warning(s) require review." if failed or warnings else "All completed checks passed.")
        self.notification.color = ft.Colors.RED_700 if failed else ft.Colors.ORANGE_700 if warnings else ft.Colors.GREEN_700
        
        for r in results:
            level = r.get("level", "FAIL")
            color = {"OK": ft.Colors.GREEN_700, "WARN": ft.Colors.ORANGE_700, "FAIL": ft.Colors.RED_700}.get(level, ft.Colors.BLUE_GREY_700)
            bg = {"OK": ft.Colors.GREEN_50, "WARN": ft.Colors.ORANGE_50, "FAIL": ft.Colors.RED_50}.get(level, ft.Colors.BLUE_GREY_50)
            
            self.results_column.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.CHECK_CIRCLE if level == "OK" else ft.Icons.WARNING if level == "WARN" else ft.Icons.ERROR, color=color, size=20),
                            ft.Text(r.get('title', ''), size=14, weight=ft.FontWeight.BOLD, color=color),
                            ft.Container(expand=True),
                            ft.Text(r.get("owner", ""), size=11, color=ft.Colors.BLUE_GREY_500),
                        ]),
                        ft.Text(f"Meaning: {r.get('plain_language', '')}", size=12, color=ft.Colors.BLUE_GREY_800),
                        ft.Text(f"Details: {r.get('message', '')}", size=11, color=ft.Colors.BLUE_GREY_600, font_family="monospace"),
                        ft.Text(f"Action: {r.get('action', 'No action required')}", size=11, weight=ft.FontWeight.W_500, color=color),
                    ], spacing=6),
                    padding=15, bgcolor=bg, border_radius=8, border=ft.Border.all(1, color)
                )
            )
            
        try:
            self.results_column.update()
            self.summary.update()
            self.notification.update()
            self.last_run.update()
        except Exception: pass

    def _ok(self, title, message="No issue detected", owner="system_test_tab.py", action="No action required"):
        return {"level": "OK", "title": title, "message": message, "action": action, "owner": owner}

    def _warn(self, title, message, owner, action):
        return {"level": "WARN", "title": title, "message": message, "action": action, "owner": owner}

    def _fail(self, title, message, owner, action="Open the named file and correct the condition"):
        return {"level": "FAIL", "title": title, "message": message, "action": action, "owner": owner}

    # ========================================================================
    # 10. API & FRONTEND TESTS
    # ========================================================================
    def check_api_contract(self):
        """10.01. Verifies required API routes exist and uploads are protected."""
        path = self.project_root / "main.py"
        if not path.exists(): return self._fail("API source missing", str(path), "main.py")
        text = path.read_text(encoding="utf-8", errors="replace")
        required = ["/api/frontpage", "/api/batches", "/api/captcha/new", "/api/captcha/verify", "/api/traveler/login", "/api/traveler/me", "/api/admin/traveler/upload-doc", "/api/admin/traveler/upload-folder-html"]
        missing = [x for x in required if x not in text]
        if missing: return self._fail("API route contract incomplete", ", ".join(missing), "main.py", "Restore missing routes")
        if "async def upload_folder_html" in text and "Depends(require_admin)" not in text[text.rfind("async def upload_folder_html"):]:
            return self._fail("Folder upload lacks auth", "The folder upload route lacks Depends(require_admin)", "main.py", "Require admin authentication")
        return self._ok("API contract", "Required API routes and protected uploads verified", "main.py / security.py")

    def check_live_api(self):
        """10.02. Probes the live deployment URL to ensure endpoints respond correctly."""
        base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        if not base: return self._ok("Live API probe skipped", "PUBLIC_BASE_URL is not configured.", "main.py", "Optional: set PUBLIC_BASE_URL")
        checks = [("frontpage", "/api/frontpage", 200), ("batches", "/api/batches", 200), ("admin", "/api/admin/frontpage/diagnose", 401)]
        failures = []
        for name, route, expected in checks:
            try:
                req = urllib.request.Request(base + route, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as res:
                    if res.status != expected: failures.append(f"{name}: HTTP {res.status}, expected {expected}")
            except urllib.error.HTTPError as ex:
                if ex.code != expected: failures.append(f"{name}: HTTP {ex.code}, expected {expected}")
            except Exception as ex: failures.append(f"{name}: {ex}")
        if failures: return self._fail("Live API probe failed", "; ".join(failures), "main.py", "Inspect deployment logs")
        return self._ok("Live API probe", f"Checked {len(checks)} endpoints at {base}", "main.py")

    def check_frontpage(self):
        """10.03. Validates index.html, robots.txt, sitemap.xml, and frontpage config."""
        root = self.project_root
        static = root / "static"
        html_path = root / "index.html" if (root / "index.html").exists() else static / "index.html"
        robots_path = root / "robots.txt" if (root / "robots.txt").exists() else static / "robots.txt"
        sitemap_path = root / "sitemap.xml" if (root / "sitemap.xml").exists() else static / "sitemap.xml"
        main_text = (root / "main.py").read_text(encoding="utf-8", errors="replace") if (root / "main.py").exists() else ""
        
        missing = []
        if not html_path.exists(): missing.append("index.html")
        if not robots_path.exists() and "def robots_txt" not in main_text: missing.append("robots.txt")
        if not sitemap_path.exists() and "def sitemap_xml" not in main_text: missing.append("sitemap.xml")
        if missing: return self._fail("Front-page files missing", ", ".join(missing), "static/", "Deploy missing files")
            
        html = html_path.read_text(encoding="utf-8", errors="replace")
        absent = [x for x in ["viewport", "api/frontpage", "alert"] if x.lower() not in html.lower()]
        if absent: return self._warn("Front-page markers missing", ", ".join(absent), str(html_path), "Review HTML structure")
        try:
            from core.frontpage_config import load_config
            cfg = load_config()
            packages = cfg.get("packages", {}) if isinstance(cfg, dict) else {}
            return self._ok("Front-page integrity", f"Selected packages: {len(packages.get('selected_batch_ids', []))}", "static/index.html")
        except Exception as ex:
            return self._fail("Front-page config error", str(ex), "frontpage_config.py", "Repair loading logic")

    def check_static_html(self):
        """10.04. Scans all static HTML files for basic structural integrity."""
        static = self.project_root / "static"
        if not static.exists(): return self._fail("Static folder missing", str(static), "static/", "Deploy static folder")
        html_files = sorted(static.rglob("*.html"))
        if not html_files: return self._warn("No static HTML files", str(static), "static/", "Confirm pages are deployed")
        bad = []
        for path in html_files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                if "<html" not in text.lower() and "<!doctype" not in text.lower(): bad.append(f"{path.name}: no HTML marker")
                if "<script" in text.lower() and "</script>" not in text.lower(): bad.append(f"{path.name}: unclosed script")
            except Exception as e: bad.append(f"{path.name}: {e}")
        if bad: return self._fail("Static HTML issue", " ; ".join(bad[:5]), "static/", "Fix markup")
        return self._ok("Static HTML files", f"Checked {len(html_files)} files", "static/")

    def check_repository_layout(self):
        """10.05. Verifies the expected GitHub folder structure is present."""
        expected = ["core", "data", "data/backups", "documents", "flet_assets", "logos", "seed_data", "static", "tools"]
        actual = {str(path.relative_to(self.project_root)).replace("\\", "/").casefold(): path for path in self.project_root.rglob("*") if path.is_dir()}
        missing = [name for name in expected if name.casefold() not in actual]
        if missing: return self._warn("Expected folders missing", ", ".join(missing), "repository layout", "Confirm GitHub deployment")
        return self._ok("GitHub folder layout", f"Verified {len(expected)} required folders", "repository layout")

    # ========================================================================
    # 11. INVENTORY & FILESYSTEM TESTS
    # ========================================================================
    def check_data_file_hygiene(self):
        """11.01. Ensures only recognized application files exist in data/ root."""
        data = self.data_dir
        if not data.exists(): return self._fail("Data folder missing", str(data), "database.py", "Repair directory")
        allowed = {"users.csv", "travelers.csv", "batches.csv", "payments.csv", "invoices.csv", "receipts.csv", "activity_log.csv", "backup_history.csv", "company_settings.csv", "id_counters.json", "tour_types.csv", "tax_settings.csv", "frontpage_config.json", "system_test_history.csv", "system_error_events.csv", "traveler_sessions.json", "_cleanup.sh", ".db.lock"}
        candidates = [path for path in data.iterdir() if path.is_file() and not path.name.startswith(".") and path.name not in allowed and not path.name.startswith("documents_backup_")]
        if candidates: return self._warn("Unrecognized data files", ", ".join(p.name for p in candidates[:5]), "data/", "Review data folder contents")
        return self._ok("Database file hygiene", "Only recognized configuration and data files present", "data/")

    def check_unused_files(self):
        """11.02. Generates a full inventory classifying files as used, protected, or unused, and provides a git rm command."""
        root = self.project_root
        protected_names = {"data", "documents", "logos", "flet_assets", "seed_data", "backups", "downloads", "delete_quarantine"}
        generated_export_extensions = {".pdf", ".xls", ".xlsx", ".csv"}
        protected_files = {"main.py", "index.html", "robots.txt", "sitemap.xml", "requirements.txt", "pyproject.toml", "nixpacks.toml"}
        documentation_extensions = {".md", ".txt"}
        documentation_files = {"README.md", "CHANGELOG.md", "FLET_HAJ_CHANGELOG.md", "LAYOUT_PLAN.txt"}
        review_root_names = {"add_traveler_test.py", "export_buttons_test.py", "system_check.py", "system_test.py"}
        
        files, text_parts, total_text_bytes = [], [], 0

        def add_record(path, protected, folder_summary=False, review_artifact=False, documentation=False):
            nonlocal total_text_bytes
            try:
                stat = path.stat()
                age_days = max(0, int((time.time() - stat.st_mtime) / 86400))
            except OSError: return
            relative = path.relative_to(root)
            if path.is_file() and path.suffix.lower() in {".py", ".html", ".js", ".css", ".json", ".toml", ".ini", ".yaml", ".yml", ".md", ".txt"} and total_text_bytes < 12_000_000:
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")[:300_000]
                    text_parts.append(text)
                    total_text_bytes += len(text)
                except OSError: pass
            files.append({"path": path, "relative": relative, "age_days": age_days, "in_protected_dir": protected, "folder_summary": folder_summary, "review_artifact": review_artifact, "documentation": documentation})

        def scan_source_tree(base):
            if not base.is_dir(): return
            for current, dirnames, filenames in os.walk(base, topdown=True):
                current_path = Path(current)
                dirnames[:] = [d for d in dirnames if d.casefold() not in protected_names and d.casefold() not in {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}]
                for filename in filenames:
                    path = current_path / filename
                    relative = path.relative_to(root)
                    in_core_exports = (len(relative.parts) >= 2 and relative.parts[0].casefold() == "core" and relative.parts[1].casefold() == "exports")
                    generated = in_core_exports and path.suffix.casefold() in generated_export_extensions
                    add_record(path, (current_path != root and current_path.relative_to(root).parts[0].casefold() == "core") and not generated)

        try:
            for child in root.iterdir():
                if child.is_file():
                    is_doc = child.suffix.casefold() in documentation_extensions or child.name.casefold() in {n.casefold() for n in documentation_files}
                    is_review = child.name.casefold() in {name.casefold() for name in review_root_names}
                    add_record(child, (child.name.casefold() in {name.casefold() for name in protected_files} or is_doc) and not is_review, review_artifact=is_review, documentation=is_doc)
        except OSError: pass

        scan_source_tree(root / "core")
        scan_source_tree(root / "tools")

        static = root / "static"
        if static.is_dir():
            try:
                for child in static.iterdir():
                    if child.is_file():
                        generated = (child.suffix.casefold() in generated_export_extensions)
                        add_record(child, (child.suffix.lower() in {".html", ".css", ".js"} or child.name.casefold() in {n.casefold() for n in protected_files}) and not generated)
                    elif child.is_dir(): add_record(child, True, True)
            except OSError: pass

        for dirname in sorted(protected_names):
            path = root / dirname
            if not path.is_dir(): continue
            try:
                children = list(path.iterdir())[:2000]
                if len(children) >= 2000: add_record(path, True, True)
                else:
                    for child in children: add_record(child, True, child.is_dir())
            except OSError: continue

        combined_text = "\n".join(text_parts)
        self.file_inventory_info = {}
        unused_files = []
        
        for record in files:
            path = record["path"]
            name = path.name
            referenced = (not record["folder_summary"]) and bool(name) and name in combined_text
            core_module = bool(record["relative"].parts and record["relative"].parts[0].casefold() == "core" and path.suffix.lower() == ".py")
            essential = name.casefold() in {n.casefold() for n in protected_files}
            is_doc = record.get("documentation", False)
            review_artifact = record.get("review_artifact", False)
            
            protected = (not review_artifact and (record["in_protected_dir"] or record["folder_summary"] or core_module or essential or referenced or is_doc))
            info = {
                "protected": protected,
                "classification": (
                    "protected folder" if record["folder_summary"] else "documentation" if is_doc else "review candidate" if review_artifact else "protected system file" if protected else "unused candidate"
                ),
                "used": (not review_artifact and (referenced or core_module or essential or is_doc)),
                "age_days": record["age_days"],
                "folder_summary": record["folder_summary"],
            }
            key = str(path.resolve())
            self.file_inventory_info[key] = info
            if not protected and path.is_file():
                unused_files.append(str(record["relative"]))

        groups = {}
        for record in files:
            folder = record["relative"].parts[0] if record["relative"].parts else "."
            info = self.file_inventory_info.get(str(record["path"].resolve()), {})
            group = groups.setdefault(folder, {"total": 0, "protected": 0, "used": 0, "unused": 0, "oldest": 0})
            group["total"] += 1
            group["protected"] += int(info.get("protected", False))
            group["used"] += int(info.get("used", False))
            group["unused"] += int(not info.get("protected", False))
            group["oldest"] = max(group["oldest"], record["age_days"])
            
        self.folder_inventory = groups
        details = "; ".join(f"{folder}: {g['total']} listed / {g['protected']} protected / {g['unused']} unused" for folder, g in sorted(groups.items()))
        
        # Build the git command
        if unused_files:
            cmd = "git rm " + " ".join(f'"{f}"' for f in unused_files)
            cmd += "\n\ngit commit -m 'Clean up unused files'\ngit push origin main"
            self.cleanup_instructions_text.value = cmd
            self.cleanup_instructions_text.color = ft.Colors.RED_700
        else:
            self.cleanup_instructions_text.value = "No unused files detected. Repository is clean."
            self.cleanup_instructions_text.color = ft.Colors.GREEN_700
        try: self.cleanup_instructions_text.update()
        except Exception: pass

        if unused_files:
            return self._warn("Complete folder file inventory", details, "project root", "Use the GitHub cleanup command to remove unused files")
        return self._ok("Complete folder file inventory", details or "No files found", "project root", "No action required")

    # ========================================================================
    # 12. DATABASE & FINANCIAL TESTS
    # ========================================================================
    def check_schema(self):
        """12.01. Verifies all necessary columns exist in the DataFrames."""
        expected = {"users": {"id", "username", "role"}, "travelers": {"id", "batch_id"}, "batches": {"id", "price"}, "payments": {"id", "traveler_id", "amount", "status"}, "invoices": {"id", "traveler_id"}, "receipts": {"id", "payment_id"}}
        problems = []
        for attr, cols in expected.items():
            df = getattr(self.db, attr, None)
            missing = sorted(cols - set(getattr(df, "columns", [])))
            if missing: problems.append(f"{attr}: {', '.join(missing)}")
        if problems: return self._fail("Database schema mismatch", "; ".join(problems), "database.py", "Repair columns")
        return self._ok("Database schema", "All core tables contain required columns", "database.py")

    def check_database_records(self):
        """12.02. Ensures DataFrames load correctly and reports record counts."""
        problems = []
        for attr in ("travelers", "batches", "payments", "invoices", "receipts"):
            df = getattr(self.db, attr, None)
            if df is None: problems.append(f"{attr}: unavailable")
            elif not hasattr(df, "to_dict"): problems.append(f"{attr}: invalid")
        if problems: return self._fail("Database record load issue", "; ".join(problems), "database.py", "Reload CSV")
        return self._ok("Database records", f"Loaded {len(self.db.travelers)} travelers, {len(self.db.batches)} batches, {len(self.db.payments)} payments, {len(self.db.invoices)} invoices", "database.py")

    def check_relationships(self):
        """12.03. Checks for orphaned IDs in relationships (traveler->batch, payment->traveler)."""
        def ids(attr):
            df = getattr(self.db, attr, None)
            return {str(x).strip() for x in df["id"]} if df is not None and "id" in df.columns else set()
        travelers, batches, payments, invoices = ids("travelers"), ids("batches"), ids("payments"), ids("invoices")
        problems = []
        for attr, col, target, valid in (("travelers", "batch_id", "batches", batches), ("payments", "traveler_id", "travelers", travelers), ("invoices", "traveler_id", "travelers", travelers), ("payments", "invoice_id", "invoices", invoices)):
            df = getattr(self.db, attr, None)
            if df is None or col not in df.columns: continue
            bad = [str(x).strip() for x in df[col] if str(x).strip() and str(x).strip() not in valid]
            if bad: problems.append(f"{attr}.{col}->{target}: {len(bad)} orphan(s)")
        if problems: return self._fail("Relationship integrity issue", "; ".join(problems), "database.py", "Correct orphan IDs")
        return self._ok("ID and relationship integrity", "No orphan references found", "database.py")

    def check_financials(self):
        """12.04. Validates that financial columns contain non-negative finite numbers."""
        problems = []
        for attr, cols in (("batches", ["price"]), ("payments", ["amount"]), ("invoices", ["amount", "taxable_value", "gst_amount", "tcs_amount", "total_amount", "rounded_total"])):
            df = getattr(self.db, attr, None)
            if df is None: continue
            for col in cols:
                if col not in df.columns: continue
                for value in df[col].dropna():
                    try:
                        n = Decimal(str(value))
                        if not n.is_finite() or n < 0: raise InvalidOperation
                    except (InvalidOperation, ValueError, TypeError):
                        problems.append(f"{attr}.{col}: invalid {value!r}")
                        break
        if problems: return self._fail("Financial value issue", "; ".join(problems[:5]), "database.py", "Correct invalid amounts")
        return self._ok("Financial precision", "Financial columns contain valid non-negative numbers", "database.py")

    def check_statuses(self):
        """12.05. Ensures payment statuses are standardized."""
        df = getattr(self.db, "payments", None)
        if df is None: return self._warn("Payment status not checked", "payments dataframe unavailable", "payments_tab.py", "Confirm database.py exposes payments")
        allowed = {"completed", "pending", "failed", "refunded"}
        bad = [] if "status" not in df.columns else [str(x) for x in df.status if str(x).strip().lower() not in allowed]
        if bad: return self._fail("Unknown payment status", ", ".join(bad[:5]), "payments_tab.py", "Normalize statuses")
        return self._ok("Payment and invoice status", "Statuses are normalized", "payments_tab.py")

    def check_tax(self):
        """12.06. Confirms Tax settings exist and are within 0-100% bounds."""
        try:
            from core.settings_manager import SettingsManager
            tax = SettingsManager(self.db).get_tax_settings()
            gst, tcs = Decimal(str(tax["gst_percentage"])), Decimal(str(tax["tcs_percentage"]))
            if not (Decimal("0") <= gst <= Decimal("100") and Decimal("0") <= tcs <= Decimal("100")): raise ValueError("Tax outside 0–100%")
            return self._ok("Tax configuration", f"GST {gst}% • TCS {tcs}%", "settings_manager.py")
        except Exception as ex: return self._fail("Tax configuration issue", str(ex), "settings_manager.py", "Repair tax_settings.csv")

    def check_backups(self):
        """12.07. Ensures backups are valid ZIPs and checks the age of the latest one."""
        folder = self.data_dir / "backups"
        if not folder.is_dir(): return self._warn("No backup folder", str(folder), "backups_tab.py", "Create a backup")
        try: files = list(folder.glob("*.zip"))
        except OSError as ex: return self._fail("Backup folder unreadable", str(ex), "backups_tab.py", "Check permissions")
        if not files: return self._warn("No backups found", str(folder), "backups_tab.py", "Create a backup")
        bad = [p.name for p in files if not zipfile.is_zipfile(p)]
        if bad: return self._fail("Invalid backup ZIP", ", ".join(bad[:5]), "backups_tab.py", "Remove invalid backups")
        latest = max(files, key=lambda f: f.stat().st_mtime)
        age_hours = (time.time() - latest.stat().st_mtime) / 3600
        if age_hours > 48: return self._warn("Backup is stale", f"Latest backup is {age_hours:.1f} hours old", "backups_tab.py", "Create a new backup")
        return self._ok("Backup integrity & age", f"{len(files)} backups readable; latest is {age_hours:.1f}h old", "backups_tab.py")

    # ========================================================================
    # 13. SYSTEM, SECURITY & ENVIRONMENT TESTS
    # ========================================================================
    def _should_scan(self, path: Path) -> bool:
        """Helper to exclude virtual environments and caches from slow scans."""
        excluded = {".venv", "venv", "env", "site-packages", "dist-packages", 
                    "__pycache__", ".git", ".pytest_cache", ".mypy_cache", 
                    "node_modules", "data", "documents", "logos", "flet_assets", "seed_data"}
        return not any(part.casefold() in excluded for part in path.parts)

    def check_source(self):
        """13.01. Parses all Python files to ensure there are no syntax errors."""
        bad, functions, all_files = [], 0, []
        for folder in self.python_roots:
            try:
                for path in folder.rglob("*.py"):
                    if self._should_scan(path):
                        all_files.append(path)
            except OSError: pass
        for path in sorted(set(all_files)):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                functions += sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))
            except SyntaxError as ex: bad.append(f"{path.name}:{ex.lineno}")
            except Exception as ex: bad.append(f"{path.name}: {ex}")
        if bad: return self._fail("Source syntax issue", ", ".join(bad), "Python files", "Fix syntax errors")
        return self._ok("Source syntax and functions", f"Parsed {len(set(all_files))} files and {functions} functions", "Python files")

    def check_ui_wiring(self):
        """13.02. Scans Flet code for event bindings and missing setup_ui markers."""
        problems, controls, handlers, all_files = [], 0, 0, []
        for folder in self.python_roots:
            try:
                for path in folder.rglob("*.py"):
                    if self._should_scan(path):
                        all_files.append(path)
            except OSError: pass
        for path in sorted(set(all_files)):
            if path.name in {"database.py", "security.py"}: continue
            text = path.read_text(encoding="utf-8", errors="replace")
            controls += text.count("on_click=") + text.count("on_change=") + text.count("on_submit=")
            handlers += text.count("def ")
            if "ft." in text and "setup_ui" not in text and "Dialog" in path.name: problems.append(f"{path.name}: no setup_ui marker")
        if problems: return self._warn("UI wiring review", "; ".join(problems), "UI files", "Review named modules")
        return self._ok("UI/button wiring", f"Found {controls} event bindings; {handlers} function definitions", "UI files")

    def check_security(self):
        """13.03. Verifies ADMIN_API_KEY strength and fail-closed security logic."""
        key = os.getenv("ADMIN_API_KEY", "")
        if not key or len(key) < 32: return self._warn("Admin API key", "ADMIN_API_KEY missing or < 32 chars", "security.py", "Set a random 32+ char key")
        main_text = (self.project_root / "main.py").read_text(encoding="utf-8", errors="replace")
        if "Security service unavailable" not in main_text: return self._fail("Security fallback missing", "main.py does not fail closed on security import failure", "main.py", "Keep endpoints returning 503")
        return self._ok("Security configuration", "Admin API key length and fail-closed fallback are present", "security.py")

    def check_runtime_storage(self):
        """13.04. Ensures necessary runtime directories exist and are writable."""
        data = self.data_dir
        required = {"data": data, "documents": data / "documents", "backups": data / "backups", "static downloads": self.project_root / "static" / "downloads", "flet assets": self.project_root / "flet_assets"}
        missing = [name for name, path in required.items() if not path.is_dir()]
        if missing: return self._warn("Runtime folders missing", ", ".join(missing), "main.py", "Check deployment configuration")
        if not os.access(str(data), os.W_OK): return self._fail("Data folder not writable", str(data), "database.py", "Mount writable volume")
        return self._ok("Runtime storage and exports", "All required runtime folders are present and writable", "main.py")

    def check_background_errors(self):
        """13.05. Scans activity_log.csv and *.log files for recent errors."""
        hits, now = [], datetime.now()
        activity = self.data_dir / "activity_log.csv"
        if activity.exists():
            try:
                with activity.open("r", encoding="utf-8-sig", errors="replace") as f:
                    for row in csv.DictReader(f):
                        text = (str(row.get("action", "")) + " " + str(row.get("details", ""))).lower()
                        if any(token in text for token in ("error", "exception", "traceback", "failed", "failure")): hits.append(text[:240])
            except Exception as ex: hits.append(f"activity log unreadable: {ex}")
        for path in self.data_dir.glob("*.log"):
            try:
                if now - datetime.fromtimestamp(path.stat().st_mtime) <= timedelta(days=7):
                    text = path.read_text(encoding="utf-8", errors="replace")
                    for line in text.splitlines():
                        if any(token in line.lower() for token in ("error", "exception", "traceback", "failed")): hits.append(f"{path.name}: {line[:200]}")
            except Exception: pass
        if hits: return self._warn("Background errors detected", " ; ".join(hits[-5:]), "logs", "Open logs and fix responsible modules")
        return self._ok("Background error scan", "No recent errors detected in logs", "logs")

    def check_tools_scripts(self):
        """13.06. Verifies the integrity of the tools/ folder and its scripts."""
        tools = self.project_root / "tools"
        if not tools.is_dir(): return self._warn("Tools folder missing", str(tools), "tools/", "Create the tools folder for standalone tests")
        required = ["full_functional_test.py", "full_ui_test.py", "health_check.py", "master_test.py", "security_audit.py", "test_frontpage_features.py"]
        missing = [f for f in required if not (tools / f).exists()]
        if missing: return self._warn("Missing tools scripts", ", ".join(missing), "tools/", "Restore the missing test scripts")
        bad = []
        for script in required:
            try: ast.parse((tools / script).read_text(encoding="utf-8"))
            except SyntaxError as e: bad.append(f"{script}:{e.lineno}")
        if bad: return self._fail("Tools syntax error", ", ".join(bad), "tools/", "Fix syntax in the listed tools scripts")
        return self._ok("Tools scripts integrity", f"Verified {len(required)} tools scripts", "tools/")

    def check_environment_security(self):
        """13.07. Checks environment variables for safe production settings."""
        problems = []
        if not os.getenv("ADMIN_API_KEY", "") or len(os.getenv("ADMIN_API_KEY", "")) < 32: problems.append("ADMIN_API_KEY missing or < 32 chars")
        if not os.getenv("PORT", ""): problems.append("PORT env not set")
        if os.getenv("DEBUG", "false").lower() in ("true", "1", "yes"): problems.append("DEBUG mode is enabled in production")
        if problems: return self._warn("Environment security issues", "; ".join(problems), "env", "Review environment variables for production readiness")
        return self._ok("Environment security", "ADMIN_API_KEY, PORT, and DEBUG variables are safely configured", "env")

    def check_file_permissions(self):
        """13.08. Audits sensitive files for world-readable/writable permissions."""
        if os.name == "nt": return self._ok("File permissions", "Skipped on Windows", "system_test_tab.py")
        sensitive = [self.data_dir / "users.csv", self.data_dir / "travelers.csv", self.data_dir / "payments.csv", self.project_root / ".env"]
        problems = []
        for path in sensitive:
            if path.exists():
                try:
                    mode = path.stat().st_mode
                    if mode & stat.S_IROTH: problems.append(f"{path.name} is world-readable")
                    if mode & stat.S_IWOTH: problems.append(f"{path.name} is world-writable")
                except Exception as e: problems.append(f"{path.name}: {e}")
        if problems: return self._warn("File permission issues", "; ".join(problems), "data/", "Restrict file permissions (chmod 600)")
        return self._ok("File permissions", "Sensitive files are not world-readable or world-writable", "data/")

    def check_dependencies(self):
        """13.09. Ensures required packages are listed in requirements.txt."""
        req_file = self.project_root / "requirements.txt"
        if not req_file.exists(): return self._warn("requirements.txt missing", str(req_file), "requirements.txt", "Create a requirements.txt file")
        text = req_file.read_text(encoding="utf-8", errors="replace").lower()
        required_packages = ["flet", "fastapi", "uvicorn", "pandas"]
        missing = [pkg for pkg in required_packages if pkg not in text]
        if missing: return self._fail("Missing dependencies", ", ".join(missing), "requirements.txt", "Add missing packages to requirements.txt")
        return self._ok("Dependencies", "All required packages are listed in requirements.txt", "requirements.txt")

    def check_static_assets(self):
        """13.10. Ensures primary static assets (CSS/JS) exist recursively or inline."""
        static = self.project_root / "static"
        if not static.is_dir(): 
            return self._fail("Static folder missing", str(static), "static/", "Deploy the static folder")
        
        has_css = any(static.rglob("*.css"))
        has_js = any(static.rglob("*.js"))
        
        has_inline = False
        for html in static.rglob("*.html"):
            try:
                text = html.read_text(encoding="utf-8", errors="ignore").lower()
                if "<style" in text or "<script" in text:
                    has_inline = True
                    break
            except Exception:
                pass
                
        missing = []
        if not has_css and not has_inline: 
            missing.append("CSS files (*.css) or inline <style>")
        if not has_js and not has_inline: 
            missing.append("JS files (*.js) or inline <script>")
        
        if missing: 
            return self._warn("Missing static assets", ", ".join(missing), "static/", "Ensure CSS/JS files or inline styles are present")
        return self._ok("Static assets", "Primary static assets (CSS/JS) or inline styles detected", "static/")
