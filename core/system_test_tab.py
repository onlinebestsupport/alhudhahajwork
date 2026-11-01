# core/system_test_tab.py — recorded, read-only super-admin diagnostics
from __future__ import annotations

import ast
import asyncio
import csv
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from html.parser import HTMLParser

import flet as ft


class SystemTestTab:
    """Diagnostics console. Tests never create, edit, or delete business records."""

    VERSION = "2026-11-01-r11-bounded-folder-inventory"
    HISTORY_FILE = "system_test_history.csv"
    ERROR_FILE = "system_error_events.csv"
    MAX_HISTORY = 5000
    CHECK_TIMEOUT_SECONDS = 20

    def __init__(self, page, db, current_user):
        print(f"[SYSTEM-TEST] loaded version={self.VERSION}", flush=True)
        self.page = page
        self.db = db
        self.current_user = current_user or {}
        self.root = None
        self.results_column = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        self.summary = ft.Text("Loading previous diagnostics…", size=12, color="#475569")
        self.notification = ft.Text("", size=11, weight=ft.FontWeight.BOLD)
        self.last_run = ft.Text("", size=10, color="#64748b")
        self.history_label = ft.Text("", size=10, color="#64748b")
        self.progress_bar = ft.ProgressBar(value=0, color="#2563eb", bgcolor="#dbeafe")
        self.progress_text = ft.Text("Ready — no test is running", size=11, color="#475569")
        self._progress_started = None
        self.last_results = []
        self._test_running = False
        self.cleanup_candidates = []
        self.file_inventory_info = {}
        self.cleanup_checks = {}
        self.quarantine_checks = {}
        self.cleanup_confirmation = ft.Checkbox(label="I understand selected files will be moved to the quarantine/delete folder", value=False)
        self.permanent_confirmation = ft.Checkbox(label="I understand selected quarantine files will be permanently deleted", value=False)
        self.cleanup_column = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO)
        self.quarantine_column = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO)
        self.inventory_summary = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO)
        self._build_specs()
        self.setup_ui()
        self._load_previous_notification()

    def build(self):
        return self.root

    @property
    def data_dir(self):
        return Path(getattr(self.db, "data_dir", Path("data")))

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
                try:
                    os.replace(legacy, target)
                except OSError:
                    pass
        return path

    def _build_specs(self):
        self.test_specs = [
            ("API contract", "main.py / security.py", self.check_api_contract),
            ("Live API probe", "main.py / deployed URL", self.check_live_api),
            ("Front-page integrity", "index.html / frontpage_config.py", self.check_frontpage),
            ("Static HTML files", "static/**/*.html", self.check_static_html),
            ("GitHub folder layout", "core / data / documents / static / tools", self.check_repository_layout),
            ("Database file hygiene", "data/ root", self.check_data_file_hygiene),
            ("Complete project file inventory", "all folders / protected and unused files", self.check_unused_files),
            ("Database schema", "database.py", self.check_schema),
            ("Database records", "database.py / travelers / batches", self.check_database_records),
            ("ID and relationship integrity", "database.py / reports", self.check_relationships),
            ("Financial precision", "database.py / invoices_tab.py", self.check_financials),
            ("Payment and invoice status", "payments_tab.py / reports_tab.py", self.check_statuses),
            ("Tax configuration", "settings_manager.py / company_settings_dialog.py", self.check_tax),
            ("Backup integrity", "backups_tab.py / database.py", self.check_backups),
            ("Source syntax and functions", "all Python files", self.check_source),
            ("UI/button wiring", "Flet tabs and dialogs", self.check_ui_wiring),
            ("Security configuration", "security.py / main.py", self.check_security),
            ("Background error scan", "activity_log.csv / runtime logs", self.check_background_errors),
        ]

    def setup_ui(self):
        cards = []
        for title, owner, fn in self.test_specs:
            cards.append(ft.Container(
                content=ft.Column([
                    ft.Text(title, size=11, weight=ft.FontWeight.BOLD, color="#0f172a"),
                    ft.Text(owner, size=9, color="#64748b", max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Button(content=ft.Text("Run", size=10), on_click=lambda e, f=fn: self.run_one(f),
                              bgcolor="#e0f2fe", color="#075985", height=30),
                ], spacing=4), padding=8, bgcolor="#f8fafc", border_radius=8,
                border=ft.Border.all(1, "#e2e8f0"), col={"xs": 12, "sm": 6, "md": 3},
            ))
        self.root = ft.Container(
            content=ft.Column([
                ft.Container(content=ft.Row([
                    ft.Icon(ft.Icons.HEALTH_AND_SAFETY, color="#ffffff", size=26),
                    ft.Column([
                        ft.Text("System Test Center", size=18, weight=ft.FontWeight.BOLD, color="#ffffff"),
                        ft.Text("Recorded diagnostics for API, front page, database, code and background errors", size=10, color="#dbeafe"),
                    ], spacing=2, expand=True),
                    ft.Container(content=ft.Text("SUPER ADMIN", size=9, weight=ft.FontWeight.BOLD, color="#ffffff"),
                                 bgcolor="#dc2626", padding=7, border_radius=6),
                ], spacing=10), padding=16, bgcolor="#0f3b66", border_radius=12),
                ft.Container(content=ft.Column([self.notification, self.summary, self.progress_text, self.progress_bar, self.last_run, self.history_label], spacing=5),
                             padding=10, bgcolor="#eff6ff", border_radius=8),
                ft.ResponsiveRow(cards, spacing=6, run_spacing=6),
                ft.Row([
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=17), ft.Text("Run All Tests", weight=ft.FontWeight.BOLD)], tight=True),
                              on_click=self.run_all, bgcolor="#2563eb", color=ft.Colors.WHITE, height=42),
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.HISTORY, size=17), ft.Text("Show Last Run")], tight=True),
                              on_click=self.show_last_run, bgcolor="#f1f5f9", color="#334155", height=42),
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.DOWNLOAD, size=17), ft.Text("Current CSV")], tight=True),
                              on_click=self.download_current_csv, bgcolor="#dcfce7", color="#166534", height=42),
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.DOWNLOAD, size=17), ft.Text("All History CSV")], tight=True),
                              on_click=self.download_history_csv, bgcolor="#dcfce7", color="#166534", height=42),
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.CONTENT_COPY, size=17), ft.Text("Manus Prompt TXT")], tight=True),
                              on_click=self.download_manus_prompt, bgcolor="#fef3c7", color="#92400e", height=42),
                    ft.Button(content=ft.Row([ft.Icon(ft.Icons.CLEAR_ALL, size=17), ft.Text("Clear Screen")], tight=True),
                              on_click=lambda e: self.clear_screen(), bgcolor="#f1f5f9", color="#334155", height=42),
                ], spacing=8, wrap=True),
                ft.Container(content=ft.Column([
                    ft.Text("File cleanup candidates", size=13, weight=ft.FontWeight.BOLD, color="#0f172a"),
                    ft.Text("Safe project files are listed. Protected app/data files are disabled; very large protected folders are shown as protected summaries. Approved project files first move to the quarantine/delete folder; permanent deletion is a separate second step.", size=10, color="#64748b"),
                    self.inventory_summary,
                    self.cleanup_column,
                    ft.Row([self.cleanup_confirmation, ft.Button(content=ft.Text("Move Selected to Delete Folder"), on_click=self.delete_selected_cleanup, bgcolor="#d97706", color=ft.Colors.WHITE, height=38)], wrap=True),
                    ft.Text("Quarantine/delete folder", size=12, weight=ft.FontWeight.BOLD, color="#7c2d12"),
                    ft.Text("data/delete_quarantine/", size=10, color="#92400e"),
                    self.quarantine_column,
                    ft.Row([self.permanent_confirmation, ft.Button(content=ft.Text("Permanently Delete Quarantine Files"), on_click=self.delete_quarantine_files, bgcolor="#991b1b", color=ft.Colors.WHITE, height=38)], wrap=True),
                ], spacing=5), padding=10, bgcolor="#fffbeb", border=ft.Border.all(1, "#f59e0b"), border_radius=8),
                ft.Container(content=self.results_column, expand=True, padding=8,
                             border=ft.Border.all(1, "#e2e8f0"), border_radius=8),
            ], spacing=10, expand=True, scroll=ft.ScrollMode.AUTO),
            padding=12, expand=True, bgcolor="#ffffff",
        )

    # ------------------------------------------------------------------ persistence
    def _append_rows(self, filename, rows, fields):
        if not rows:
            return
        path = self.diagnostics_dir / filename
        existing = []
        if path.exists():
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as f:
                    existing = list(csv.DictReader(f))
            except Exception:
                existing = []
        existing.extend({k: str(r.get(k, "")) for k in fields} for r in rows)
        existing = existing[-self.MAX_HISTORY:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader(); writer.writerows(existing)
        os.replace(tmp, path)

    @property
    def export_dir(self):
        path = self.diagnostics_dir / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _history(self):
        path = self.diagnostics_dir / self.HISTORY_FILE
        if not path.exists():
            legacy = self.data_dir / self.HISTORY_FILE
            if legacy.exists():
                path = legacy
            else:
                return []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            return []

    def _load_previous_notification(self):
        rows = self._history()
        if not rows:
            self.notification.value = "No previous diagnostic run recorded. Run All Tests after deployment."
            self.notification.color = "#92400e"
            self.history_label.value = f"History file: {self.diagnostics_dir / self.HISTORY_FILE}"
            return
        latest_run = rows[-1].get("run_id", "")
        recent = [r for r in rows if r.get("run_id") == latest_run]
        failures = [r for r in recent if r.get("level") == "FAIL"]
        warnings = [r for r in recent if r.get("level") == "WARN"]
        self.notification.value = (f"Previous run alert: {len(failures)} failure(s), {len(warnings)} warning(s). "
                                   "Run All Tests to refresh.")
        self.notification.color = "#991b1b" if failures else "#92400e" if warnings else "#166534"
        self.history_label.value = f"Recorded runs: {len({r.get('run_id') for r in rows if r.get('run_id')})} • {self.diagnostics_dir / self.HISTORY_FILE}"
        self.summary.value = f"Previous run: {recent[-1].get('timestamp', '')} • {len(recent)} checks"

    def _plain_language(self, result):
        level = result.get("level", "FAIL")
        title = result.get("title", "System check")
        message = result.get("message", "")
        if level == "OK":
            return f"Good news: the {title.lower()} check passed. No problem was found in this area."
        if level == "WARN":
            return f"This is a warning, not necessarily a failure. The system could not fully confirm {title.lower()} or found something that should be reviewed. Details: {message}"
        return f"The system found a problem in {title.lower()}. This area may not work correctly until it is repaired. Details: {message}"

    def _manus_prompt(self, result, run_id=""):
        level = result.get("level", "FAIL")
        return (
            "Alhudha Haj Service P Ltd — System Test Center issue\n\n"
            f"Please investigate this {level} result from the website test.\n"
            f"Test: {result.get('title', '')}\n"
            f"Simple explanation: {self._plain_language(result)}\n"
            f"Technical details: {result.get('message', '')}\n"
            f"Responsible file/module: {result.get('owner', '')}\n"
            f"Recommended action: {result.get('action', '')}\n"
            f"Run ID: {run_id or result.get('run_id', '')}\n\n"
            "Please inspect the complete Alhudha Haj Service P Ltd project files, identify the exact cause, "
            "make the smallest safe correction, preserve existing traveler/payment/invoice/receipt data, "
            "and run the relevant compilation and regression tests. Explain what was changed in simple language."
        )

    def _prepare_result(self, result, run_id=""):
        result = dict(result)
        result["plain_language"] = self._plain_language(result)
        result["manus_prompt"] = self._manus_prompt(result, run_id)
        return result

    def _record(self, results, run_id):
        results = [self._prepare_result(r, run_id) for r in results]
        fields = ["run_id", "timestamp", "level", "title", "plain_language", "message", "owner", "action", "duration_ms", "user_id", "manus_prompt"]
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for r in results:
            rows.append({**r, "run_id": run_id, "timestamp": now, "user_id": self.current_user.get("id", "")})
        self._append_rows(self.HISTORY_FILE, rows, fields)
        errors = [r for r in rows if r.get("level") in {"FAIL", "WARN"}]
        self._append_rows(self.ERROR_FILE, errors, fields)

    # ------------------------------------------------------------------ execution/UI
    def _run_specs_sync(self, selected=None):
        specs = selected or self.test_specs
        results = []
        for _, _, fn in specs:
            started = time.perf_counter()
            result = self._safe_call(fn)
            result["duration_ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
            results.append(result)
        return results

    def _set_running(self, running):
        self._test_running = running
        if running:
            self._progress_started = time.perf_counter()
            self.progress_bar.value = 0
            self.progress_text.value = f"Starting tests — 0% (0/{len(self.test_specs)})"
            self.notification.value = "Tests are running in the background. The admin connection remains responsive…"
            self.notification.color = "#075985"
        else:
            self.progress_bar.value = 1
        try:
            self.progress_bar.update(); self.progress_text.update(); self.notification.update()
        except Exception:
            pass

    def _show_progress(self, completed, total, title):
        fraction = min(1, completed / total) if total else 1
        elapsed = time.perf_counter() - self._progress_started if self._progress_started else 0
        self.progress_bar.value = fraction
        self.progress_text.value = f"Checking: {title} — {fraction * 100:.0f}% ({completed}/{total}) • elapsed {elapsed:.1f}s"
        print(f"[SYSTEM-TEST] {title}: {fraction * 100:.0f}% ({completed}/{total})", flush=True)
        try:
            self.progress_bar.update(); self.progress_text.update()
        except Exception:
            pass

    async def _run_spec_with_timeout(self, spec):
        title = spec[0] or getattr(spec[2], "__name__", "selected test")
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._run_specs_sync, [spec]),
                timeout=self.CHECK_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return [self._fail(
                "Test check timed out",
                f"{title} did not finish within {self.CHECK_TIMEOUT_SECONDS} seconds.",
                "system_test_tab.py / " + title,
                "Review the named check for a slow file, network request, or locked resource",
            )]
        except Exception as ex:
            return [self._fail("Test check failed", repr(ex), "system_test_tab.py / " + title, "Review the named check and its responsible file")]

    def run_one(self, fn):
        if self._test_running:
            self.notification.value = "A test is already running. Please wait for it to finish."
            self.notification.color = "#92400e"; self.notification.update(); return
        self._set_running(True)
        try:
            self.page.run_task(self._run_one_async, fn)
        except Exception:
            self._test_running = False
            result = self._safe_call(fn)
            result["duration_ms"] = "0.0"
            self.last_results = [self._prepare_result(result)]
            self._record(self.last_results, datetime.now().strftime("%Y%m%d%H%M%S%f"))
            self._render_results(self.last_results)

    async def _run_one_async(self, fn):
        run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        try:
            self.progress_text.value = "Checking selected test — 50%"
            self.progress_bar.value = 0.5
            try: self.progress_bar.update(); self.progress_text.update()
            except Exception: pass
            results = await self._run_spec_with_timeout(("Selected test", "", fn))
            self._show_progress(1, 1, "Selected test complete")
            results = [self._prepare_result(r, run_id) for r in results]
            self._record(results, run_id)
            self.last_results = results
            self._render_results(results)
        except Exception as ex:
            result = self._prepare_result(self._fail("Test runner error", repr(ex), "system_test_tab.py", "Review the System Test Center runner"), run_id)
            self.last_results = [result]
            try: self._record([result], run_id); self._render_results([result])
            except Exception: pass
        finally:
            self._test_running = False

    def run_all(self, e=None):
        if self._test_running:
            self.notification.value = "Tests are already running. Please wait for the current run to finish."
            self.notification.color = "#92400e"; self.notification.update(); return
        self._set_running(True)
        try:
            self.page.run_task(self._run_all_async)
        except Exception:
            self._test_running = False
            results = self._run_specs_sync()
            run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
            results = [self._prepare_result(r, run_id) for r in results]
            self._record(results, run_id); self.last_results = results; self._render_results(results)

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
            result = self._prepare_result(self._fail("Test runner error", repr(ex), "system_test_tab.py", "Review the System Test Center runner"), run_id)
            self.last_results = [result]
            try: self._record([result], run_id); self._render_results([result])
            except Exception: pass
        finally:
            self._test_running = False

    def _safe_call(self, fn):
        try:
            result = fn()
            return result if isinstance(result, dict) else self._ok(fn.__name__, str(result))
        except Exception as ex:
            return self._fail("Unexpected test error", repr(ex), "system_test_tab.py")

    def clear_screen(self):
        self.results_column.controls.clear(); self.results_column.update()

    def show_last_run(self, e=None):
        rows = self._history()
        if not rows:
            self._render_results([self._warn("No history", "No completed diagnostic run is recorded yet.", "system_test_tab.py", "Run All Tests")]); return
        run_id = rows[-1].get("run_id")
        results = [{k: r.get(k, "") for k in ("level", "title", "plain_language", "message", "owner", "action", "manus_prompt", "run_id")} for r in rows if r.get("run_id") == run_id]
        self.last_results = results
        self._render_results(results)

    def _download_text_in_browser(self, filename, text, mime_type):
        """Trigger a real browser download without popup or server-navigation dependency."""
        script = (
            "(function(){"
            f"const data={json.dumps(text)};"
            f"const name={json.dumps(filename)};"
            f"const blob=new Blob([data],{{type:{json.dumps(mime_type)} }});"
            "const url=URL.createObjectURL(blob);"
            "const a=document.createElement('a');"
            "a.href=url; a.download=name; a.style.display='none';"
            "document.body.appendChild(a); a.click();"
            "setTimeout(function(){URL.revokeObjectURL(url);a.remove();},1500);"
            "})()"
        )
        try:
            runner = getattr(self.page, "run_javascript", None)
            if callable(runner):
                result = runner(script)
                if asyncio.iscoroutine(result):
                    async def _await_blob():
                        await result
                    self.page.run_task(_await_blob)
                return True
        except Exception:
            pass
        return False

    def _open_download(self, filename):
        """Open the attachment route in the same browser tab using Flet's launcher."""
        relative_url = f"/download/{filename}"
        public_base = (os.getenv("PUBLIC_BASE_URL") or os.getenv("APP_PUBLIC_URL") or "").strip().rstrip("/")
        url = f"{public_base}{relative_url}" if public_base else relative_url
        # UrlLauncher is the supported Flet web navigation API in Flet 1.0.x.
        try:
            launcher = ft.UrlLauncher()
            try:
                result = launcher.launch_url(url, web_only_window_name="_self")
            except TypeError:
                result = launcher.launch_url(url, web_window_name="_self")
            if asyncio.iscoroutine(result):
                async def _await_launch():
                    await result
                self.page.run_task(_await_launch)
            return url
        except Exception:
            pass
        # Fallback for deployments where UrlLauncher is unavailable.
        script = f"window.location.assign({json.dumps(url)});"
        try:
            runner = getattr(self.page, "run_javascript", None)
            if callable(runner):
                result = runner(script)
                if asyncio.iscoroutine(result):
                    async def _await_js():
                        await result
                    self.page.run_task(_await_js)
                return url
        except Exception:
            pass
        result = self.page.launch_url(url)
        if asyncio.iscoroutine(result):
            async def _await_page_launch():
                await result
            self.page.run_task(_await_page_launch)
        return url

    def _export_csv(self, rows, label):
        if not rows:
            self.notification.value = "Nothing to download. Run a test first."
            self.notification.color = "#92400e"
            self.notification.update()
            return
        project_static = self.project_root / "static" / "downloads"
        project_static.mkdir(parents=True, exist_ok=True)
        filename = f"system_test_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        target = project_static / filename
        persistent_target = self.export_dir / filename
        fields = ["run_id", "timestamp", "level", "title", "plain_language", "message", "owner", "action", "duration_ms", "user_id", "manus_prompt"]
        import io
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
        csv_text = buffer.getvalue()
        target.write_text(csv_text, encoding="utf-8-sig")
        persistent_target.write_text(csv_text, encoding="utf-8-sig")
        print(f"[SYSTEM-TEST] CSV_EXPORT file={filename} browser={target} persistent={persistent_target}", flush=True)
        try:
            download_url = self._open_download(filename)
            self.notification.value = f"CSV download started: {filename} ({download_url})"
            self.notification.color = "#166534"
        except Exception as ex:
            self.notification.value = f"CSV created but browser download could not start: {ex}"
            self.notification.color = "#92400e"
        self.notification.update()

    def download_current_csv(self, e=None):
        rows = self.last_results
        if not rows:
            history = self._history()
            if history:
                latest = history[-1].get("run_id")
                rows = [row for row in history if row.get("run_id") == latest]
        self._export_csv(rows, "current_run")

    def download_history_csv(self, e=None):
        self._export_csv(self._history(), "history")

    def download_manus_prompt(self, e=None):
        rows = self.last_results or self._history()
        if not rows:
            self.notification.value = "Nothing to export. Run a test first."
            self.notification.color = "#92400e"
            self.notification.update()
            return
        prompts = []
        for row in rows:
            prompt = row.get("manus_prompt") or self._manus_prompt(row, row.get("run_id", ""))
            if row.get("level") in {"FAIL", "WARN"}:
                prompts.append(prompt)
        if not prompts:
            prompts = ["Alhudha Haj Service P Ltd — All selected system checks passed. No corrective issue was reported."]
        project_static = self.project_root / "static" / "downloads"
        project_static.mkdir(parents=True, exist_ok=True)
        filename = f"alhudha_manus_prompts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        target = project_static / filename
        persistent_target = self.export_dir / filename
        prompt_text = "\n\n" + ("\n\n" + "=" * 80 + "\n\n").join(prompts)
        target.write_text(prompt_text, encoding="utf-8")
        persistent_target.write_text(prompt_text, encoding="utf-8")
        print(f"[SYSTEM-TEST] PROMPT_EXPORT file={filename} browser={target} persistent={persistent_target}", flush=True)
        try:
            download_url = self._open_download(filename)
            self.notification.value = f"Copy-ready Manus prompt file downloaded: {filename} ({download_url})"
            self.notification.color = "#166534"
        except Exception as ex:
            self.notification.value = f"Prompt file created but browser download could not start: {ex}"
            self.notification.color = "#92400e"
        self.notification.update()

    def _render_results(self, results):
        self.results_column.controls.clear()
        passed = sum(r.get("level") == "OK" for r in results)
        failed = sum(r.get("level") == "FAIL" for r in results)
        warnings = sum(r.get("level") == "WARN" for r in results)
        self.summary.value = f"Completed {len(results)} checks • Passed: {passed} • Warnings: {warnings} • Failed: {failed}"
        elapsed = time.perf_counter() - self._progress_started if self._progress_started else 0
        self.progress_bar.value = 1
        self.progress_text.value = f"Completed — 100% ({len(results)}/{len(results)}) • total time {elapsed:.1f}s"
        self.last_run.value = f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} • Results recorded • No business data modified"
        self.notification.value = (f"ATTENTION: {failed} failure(s) and {warnings} warning(s) require review." if failed or warnings else "All completed checks passed.")
        self.notification.color = "#991b1b" if failed else "#92400e" if warnings else "#166534"
        for r in results:
            level = r.get("level", "FAIL")
            color = {"OK": "#166534", "WARN": "#92400e", "FAIL": "#991b1b"}.get(level, "#334155")
            bg = {"OK": "#f0fdf4", "WARN": "#fffbeb", "FAIL": "#fef2f2"}.get(level, "#f8fafc")
            plain = r.get("plain_language") or self._plain_language(r)
            self.results_column.controls.append(ft.Container(content=ft.Column([
                ft.Row([
                    ft.Text(f"{level}  {r.get('title', '')}", size=12, weight=ft.FontWeight.BOLD, color=color),
                    ft.Container(expand=True),
                    ft.Text(r.get("owner", ""), size=9, color="#64748b"),
                ]),
                ft.Text(f"Meaning: {plain}", size=11, color="#334155", selectable=True),
                ft.Text(f"Technical details: {r.get('message', '')}", size=10, color="#475569", selectable=True),
                ft.Text(f"Action: {r.get('action', 'No action required')}", size=10, color=color, selectable=True),
            ], spacing=3), padding=10, bgcolor=bg, border_radius=7, border=ft.Border.all(1, color)))
        self.results_column.update()
        self.summary.update()
        self.progress_bar.update()
        self.progress_text.update()
        self.notification.update()
        self.last_run.update()
        self._refresh_cleanup_ui()

    # ------------------------------------------------------------------ result helpers
    @staticmethod
    def _ok(title, message="No issue detected", owner="system_test_tab.py", action="No action required"):
        return {"level":"OK", "title":title, "message":message, "action":action, "owner":owner}
    @staticmethod
    def _warn(title, message, owner, action):
        return {"level":"WARN", "title":title, "message":message, "action":action, "owner":owner}
    @staticmethod
    def _fail(title, message, owner, action="Open the named file and correct the reported condition"):
        return {"level":"FAIL", "title":title, "message":message, "action":action, "owner":owner}

    # ------------------------------------------------------------------ checks
    def check_api_contract(self):
        path=self.project_root/"main.py"
        if not path.exists(): return self._fail("API source missing", str(path), "main.py")
        text=path.read_text(encoding="utf-8", errors="replace")
        required=["/api/frontpage", "/api/batches", "/api/captcha/new", "/api/captcha/verify", "/api/traveler/login", "/api/traveler/me", "/api/admin/traveler/upload-doc", "/api/admin/traveler/upload-folder-html"]
        missing=[x for x in required if x not in text]
        if missing: return self._fail("API route contract incomplete", ", ".join(missing), "main.py", "Restore or implement the missing route")
        if "async def upload_folder_html" in text and "Depends(require_admin)" not in text[text.index("async def upload_folder_html"):text.index("async def upload_folder_html")+700]:
            return self._fail("Folder upload is not authenticated", "The folder upload route lacks Depends(require_admin)", "main.py", "Require admin authentication before accepting files")
        return self._ok("API contract", f"{len(required)} required API routes and protected upload contract found", "main.py / security.py")

    def check_live_api(self):
        base=os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        if not base:
            return self._ok("Live API probe skipped (optional)", "PUBLIC_BASE_URL is not configured; the static API contract was checked successfully. No network probe was requested.", "main.py", "Optional: set PUBLIC_BASE_URL to enable an external live probe")
        checks=[("frontpage", "/api/frontpage", 200), ("batches", "/api/batches", 200), ("admin protected", "/api/admin/frontpage/diagnose", 401)]
        failures=[]
        for name, route, expected in checks:
            try:
                req=urllib.request.Request(base+route, headers={"Accept":"application/json"})
                with urllib.request.urlopen(req, timeout=8) as res:
                    if res.status != expected: failures.append(f"{name}: HTTP {res.status}, expected {expected}")
            except urllib.error.HTTPError as ex:
                if ex.code != expected: failures.append(f"{name}: HTTP {ex.code}, expected {expected}")
            except Exception as ex: failures.append(f"{name}: {ex}")
        return self._fail("Live API probe failed", "; ".join(failures), "main.py / deployed API", "Inspect the endpoint and deployment logs") if failures else self._ok("Live API probe", f"Checked {len(checks)} endpoints at {base}", "main.py / deployed API")

    def check_frontpage(self):
        # Railway serves public assets from /app/static; accept both the source
        # root and the deployed static layout, and accept route-backed robots/sitemap.
        root = self.project_root
        static = root / "static"
        html_path = root / "index.html" if (root / "index.html").exists() else static / "index.html"
        robots_path = root / "robots.txt" if (root / "robots.txt").exists() else static / "robots.txt"
        sitemap_path = root / "sitemap.xml" if (root / "sitemap.xml").exists() else static / "sitemap.xml"
        main_text = (root / "main.py").read_text(encoding="utf-8", errors="replace") if (root / "main.py").exists() else ""
        missing=[]
        if not html_path.exists(): missing.append("index.html")
        if not robots_path.exists() and "def robots_txt" not in main_text: missing.append("robots.txt")
        if not sitemap_path.exists() and "def sitemap_xml" not in main_text: missing.append("sitemap.xml")
        if missing:
            return self._fail("Front-page files missing", ", ".join(missing), "static/ / main.py", "Deploy the missing public file or keep its FastAPI route")
        html=html_path.read_text(encoding="utf-8", errors="replace")
        markers=["viewport", "api/frontpage", "alert"]
        absent=[x for x in markers if x.lower() not in html.lower()]
        if absent:
            return self._warn("Front-page markers missing", ", ".join(absent), str(html_path.relative_to(root)), "Review mobile, API and alert rendering")
        try:
            from core.frontpage_config import load_config
            cfg=load_config(); packages=cfg.get("packages", {}) if isinstance(cfg, dict) else {}
            return self._ok("Front-page integrity", f"Public files/routes present; selected package IDs: {len(packages.get('selected_batch_ids', []))}", "static/index.html / main.py / frontpage_config.py")
        except Exception as ex:
            return self._fail("Front-page configuration error", str(ex), "frontpage_config.py", "Repair front-page configuration loading")

    def check_repository_layout(self):
        expected = [
            "core", "core/exports", "data", "data/backups", "documents",
            "flet_assets", "invoices", "logos", "seed_data", "static", "tools",
        ]
        actual = {str(path.relative_to(self.project_root)).replace("\\", "/").casefold(): path for path in self.project_root.rglob("*") if path.is_dir()}
        missing = [name for name in expected if name.casefold() not in actual]
        if missing:
            return self._warn("Expected GitHub folders missing", ", ".join(missing), "project repository layout", "Confirm the folder exists in GitHub and is included in the deployment")
        return self._ok("GitHub folder layout", f"Verified {len(expected)} expected repository folders, including core/exports and tools", "project repository layout", "No action required")

    def check_static_html(self):
        static = self.project_root / "static"
        if not static.exists():
            return self._fail("Static folder missing", str(static), "static/", "Deploy the static folder")
        html_files = sorted(static.rglob("*.html"))
        if not html_files:
            return self._warn("No static HTML files", str(static), "static/", "Confirm that the deployed static folder contains the intended pages")
        bad = []
        for path in html_files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                if "<html" not in text.lower() and "<!doctype" not in text.lower():
                    bad.append(f"{path.relative_to(self.project_root)}: no HTML document marker")
                if "<script" in text.lower() and "</script>" not in text.lower():
                    bad.append(f"{path.relative_to(self.project_root)}: unclosed script tag")
            except Exception as ex:
                bad.append(f"{path.name}: {ex}")
        if bad:
            return self._fail("Static HTML issue", " ; ".join(bad[:8]), "static/**/*.html", "Open the named HTML file and correct the reported markup")
        return self._ok("Static HTML files", f"Checked {len(html_files)} HTML file(s) under static/", "static/**/*.html")

    def _add_cleanup_candidates(self, paths, category, reason, protected_paths=None):
        protected_paths = protected_paths or set()
        for path in paths:
            resolved = Path(path).resolve()
            if any(str(resolved) == str(existing["path"]) for existing in self.cleanup_candidates):
                continue
            info = self.file_inventory_info.get(str(resolved), {})
            self.cleanup_candidates.append({"path": resolved, "category": category, "reason": reason, "protected": str(resolved) in protected_paths or bool(info.get("protected")), "classification": info.get("classification", "review candidate"), "used": info.get("used", False), "age_days": info.get("age_days", 0)})

    def check_data_file_hygiene(self):
        data = self.data_dir
        if not data.exists():
            return self._fail("Data folder missing", str(data), "imports.py / database.py", "Repair the configured data directory")
        allowed_exact = {
            "users.csv", "travelers.csv", "batches.csv", "payments.csv", "invoices.csv", "receipts.csv",
            "activity_log.csv", "backup_history.csv", "company_settings.csv", "id_counters.json",
            "tour_types.csv", "tax_settings.csv", "frontpage_config.json", "frontage_config.json",
            "system_test_history.csv", "system_error_events.csv", "traveler_sessions.json", "_cleanup.sh", ".db.lock",
        }
        allowed_prefixes = ("documents_backup_", "system_test_")
        candidates = [
            path for path in data.iterdir()
            if path.is_file()
            and not path.name.startswith(".")
            and path.name not in allowed_exact
            and not any(path.name.startswith(prefix) and path.suffix.lower() in {".zip", ".csv"} for prefix in allowed_prefixes)
        ]
        self._add_cleanup_candidates(candidates, "data", "Application data file; view-only and protected from deletion", protected_paths={str(path.resolve()) for path in candidates})
        if candidates:
            names = ", ".join(path.name for path in candidates[:8])
            return self._warn("Unrecognized data files", names, "data/ root / database.py", "Review the checkboxes; delete only files you recognize as unwanted")
        return self._ok("Database file hygiene", "Only recognized configuration, business, backup and diagnostic files are present", "data/ root / database.py")

    @property
    def quarantine_dir(self):
        path = self.data_dir / "delete_quarantine"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def check_unused_files(self):
        root = self.project_root
        excluded_names = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
        protected_names = {"data", "documents", "invoices", "logos", "flet_assets", "seed_data", "backups", "downloads", "delete_quarantine"}
        protected_files = {"main.py", "index.html", "robots.txt", "sitemap.xml", "requirements.txt", "pyproject.toml", "nixpacks.toml"}
        text_extensions = {".py", ".html", ".js", ".css", ".json", ".toml", ".ini", ".yaml", ".yml", ".md", ".txt"}
        files=[]; text_parts=[]; total_text_bytes=0

        def add_record(path, protected, folder_summary=False):
            nonlocal total_text_bytes
            try:
                stat=path.stat(); age_days=max(0, int((time.time()-stat.st_mtime)/86400))
            except OSError:
                return
            relative=path.relative_to(root)
            if path.is_file() and path.suffix.lower() in text_extensions and total_text_bytes < 20_000_000:
                try:
                    text=path.read_text(encoding="utf-8", errors="ignore")[:500_000]
                    text_parts.append(text); total_text_bytes += len(text)
                except OSError:
                    pass
            files.append({"path":path, "relative":relative, "age_days":age_days, "in_protected_dir":protected, "folder_summary":folder_summary})

        # Fully scan the deployable source tree, pruning large/private runtime trees.
        for current, dirnames, filenames in os.walk(root, topdown=True):
            current_path=Path(current)
            relative=current_path.relative_to(root)
            if any(str(part).casefold() in excluded_names for part in relative.parts):
                dirnames[:] = []
                continue
            kept=[]
            for dirname in dirnames:
                if dirname.casefold() in protected_names:
                    continue
                kept.append(dirname)
            dirnames[:]=kept
            for filename in filenames:
                add_record(current_path / filename, filename.casefold() in {x.casefold() for x in protected_files} or current_path != root and current_path.relative_to(root).parts[0].casefold() == "core")

        # Show protected data/runtime roots without recursively opening every
        # uploaded document or large backup tree. Child folders are represented
        # as disabled protected folder summaries.
        for dirname in sorted(protected_names):
            path=root / dirname
            if not path.is_dir():
                continue
            try:
                children=[]; oversized=False
                for index, child in enumerate(path.iterdir()):
                    if index >= 2000:
                        oversized=True; break
                    children.append(child)
            except OSError:
                continue
            if oversized:
                add_record(path, True, True)
            else:
                for child in children:
                    add_record(child, True, child.is_dir())

        combined_text="\n".join(text_parts)
        self.file_inventory_info={}; protected_paths=set()
        for record in files:
            path=record["path"]; relative=record["relative"]; name=path.name
            referenced=not record["folder_summary"] and bool(name) and name in combined_text
            is_core_module=bool(relative.parts and relative.parts[0].casefold()=="core" and path.suffix.lower()==".py")
            essential=name.casefold() in {item.casefold() for item in protected_files}
            protected=record["in_protected_dir"] or is_core_module or essential or referenced or record["folder_summary"]
            classification="protected folder" if record["folder_summary"] else ("protected system file" if protected else "unused candidate")
            info={"protected":protected, "classification":classification, "used":referenced or is_core_module or essential, "age_days":record["age_days"], "folder_summary":record["folder_summary"]}
            key=str(path.resolve()); self.file_inventory_info[key]=info
            if protected: protected_paths.add(key)
        self._add_cleanup_candidates([record["path"] for record in files], "inventory", "Complete folder inventory classification", protected_paths=protected_paths)
        groups={}
        for record in files:
            folder=record["relative"].parts[0] if record["relative"].parts else "."
            info=self.file_inventory_info.get(str(record["path"].resolve()), {})
            group=groups.setdefault(folder, {"total":0,"protected":0,"used":0,"unused":0,"oldest":0})
            group["total"]+=1; group["protected"]+=int(info.get("protected",False)); group["used"]+=int(info.get("used",False)); group["unused"]+=int(not info.get("protected",False)); group["oldest"]=max(group["oldest"], record["age_days"])
        self.folder_inventory=groups
        if files:
            details="; ".join(f"{folder}: {g['total']} listed / {g['protected']} protected / {g['used']} used / {g['unused']} unused / oldest {g['oldest']}d" for folder,g in sorted(groups.items(), key=lambda item:item[0].casefold()))
            action="Review unused candidates; protected system files and protected folder summaries are disabled"
            return self._warn("Complete folder file inventory", details, "project root / all folders", action) if any(g["unused"] for g in groups.values()) else self._ok("Complete folder file inventory", details, "project root / all folders", action)
        return self._ok("Complete folder file inventory", "No files were found", "project root / all folders", "No action required")

    def _refresh_cleanup_ui(self):
        self.cleanup_column.controls.clear()
        self.cleanup_checks = {}
        self.inventory_summary.controls.clear()
        inventory_items=[item for item in self.cleanup_candidates if item.get("category") == "inventory"]
        groups={}
        for item in inventory_items:
            try: folder=str(Path(item["path"]).relative_to(self.project_root).parts[0])
            except Exception: folder="."
            group=groups.setdefault(folder, {"total":0,"protected":0,"used":0,"unused":0,"oldest":0})
            group["total"]+=1; group["protected"]+=int(item.get("protected",False)); group["used"]+=int(item.get("used",False)); group["unused"]+=int(not item.get("protected",False)); group["oldest"]=max(group["oldest"], int(item.get("age_days",0)))
        if groups:
            for folder, group in sorted(groups.items(), key=lambda item:item[0].casefold()):
                self.inventory_summary.controls.append(ft.Text(f"{folder}/ — {group['total']} total • {group['protected']} protected • {group['used']} used • {group['unused']} unused candidates • oldest modified {group['oldest']} days", size=10, color="#334155"))
        else:
            self.inventory_summary.controls.append(ft.Text("Folder summary appears after running Complete project file inventory.", size=10, color="#64748b"))
        if not self.cleanup_candidates:
            self.cleanup_column.controls.append(ft.Text("Run Complete project file inventory to list every file.", size=10, color="#64748b"))
        else:
            for item in sorted(self.cleanup_candidates, key=lambda x: str(x["path"]).casefold()):
                path=str(item["path"]); protected=bool(item.get("protected")); age=int(item.get("age_days",0)); classification=item.get("classification", "review candidate")
                label=f"{'PROTECTED — ' if protected else 'UNUSED CANDIDATE — '}{item['category'].upper()}: {path} — {classification}; modified {age} days ago"
                checkbox=ft.Checkbox(label=label, value=False, disabled=protected); self.cleanup_checks[path]=checkbox; self.cleanup_column.controls.append(checkbox)
        self.inventory_summary.update(); self.cleanup_column.update()
        self._refresh_quarantine_ui()

    def _refresh_quarantine_ui(self):
        self.quarantine_column.controls.clear()
        self.quarantine_checks = {}
        files = [path for path in self.quarantine_dir.rglob("*") if path.is_file()]
        if not files:
            self.quarantine_column.controls.append(ft.Text("No files are waiting in the quarantine/delete folder.", size=10, color="#64748b"))
        else:
            for path in sorted(files, key=lambda x: str(x).casefold()):
                checkbox = ft.Checkbox(label=str(path), value=False)
                self.quarantine_checks[str(path)] = checkbox
                self.quarantine_column.controls.append(checkbox)
        self.quarantine_column.update()

    def delete_selected_cleanup(self, e=None):
        if not self.cleanup_confirmation.value:
            self.notification.value = "Move blocked: tick the quarantine confirmation checkbox first."
            self.notification.color = "#991b1b"; self.notification.update(); return
        selected = [item for item in self.cleanup_candidates if not item.get("protected") and self.cleanup_checks.get(str(item["path"]), None) and self.cleanup_checks[str(item["path"])].value]
        if not selected:
            self.notification.value = "No selectable project file was selected."; self.notification.color = "#92400e"; self.notification.update(); return
        moved=[]; blocked=[]; batch=self.quarantine_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
        project_root=self.project_root.resolve(); data_root=self.data_dir.resolve()
        for item in selected:
            path=Path(item["path"]).resolve()
            if path == project_root or project_root not in path.parents or data_root in path.parents:
                blocked.append(f"protected/outside project: {path}"); continue
            try:
                target=batch / path.relative_to(project_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target)); moved.append(str(path))
            except Exception as ex: blocked.append(f"{path}: {ex}")
        self.cleanup_candidates=[item for item in self.cleanup_candidates if str(item["path"]) not in moved]
        self.cleanup_confirmation.value=False; self.cleanup_confirmation.update(); self._refresh_cleanup_ui()
        message=f"Moved {len(moved)} file(s) to data/delete_quarantine/."
        if blocked: message += " Blocked: " + " ; ".join(blocked[:3])
        self.notification.value=message; self.notification.color="#166534" if not blocked else "#92400e"; self.notification.update()

    def delete_quarantine_files(self, e=None):
        if not self.permanent_confirmation.value:
            self.notification.value = "Permanent deletion blocked: tick the quarantine confirmation checkbox first."
            self.notification.color = "#991b1b"; self.notification.update(); return
        selected=[Path(path) for path, checkbox in self.quarantine_checks.items() if checkbox.value]
        if not selected:
            self.notification.value="No quarantine file was selected."; self.notification.color="#92400e"; self.notification.update(); return
        root=self.quarantine_dir.resolve(); deleted=[]; blocked=[]
        for path in selected:
            path=path.resolve()
            if root not in path.parents:
                blocked.append(str(path)); continue
            try:
                if path.is_file(): path.unlink(); deleted.append(str(path))
            except Exception as ex: blocked.append(f"{path}: {ex}")
        self.permanent_confirmation.value=False; self.permanent_confirmation.update(); self._refresh_quarantine_ui()
        message=f"Permanently deleted {len(deleted)} quarantined file(s)."
        if blocked: message += " Blocked: " + " ; ".join(blocked[:3])
        self.notification.value=message; self.notification.color="#166534" if not blocked else "#92400e"; self.notification.update()

    def check_schema(self):
        expected={"users":{"id","username","role"},"travelers":{"id","batch_id"},"batches":{"id","price"},"payments":{"id","traveler_id","amount","status"},"invoices":{"id","traveler_id"},"receipts":{"id","payment_id"}}
        problems=[]
        for attr, cols in expected.items():
            df=getattr(self.db, attr, None); missing=sorted(cols-set(getattr(df,"columns",[])))
            if missing: problems.append(f"{attr}: {', '.join(missing)}")
        return self._fail("Database schema mismatch", "; ".join(problems), "database.py", "Repair the listed columns") if problems else self._ok("Database schema", "All core tables contain required columns", "database.py")

    def check_database_records(self):
        problems=[]
        for attr in ("travelers","batches","payments","invoices","receipts"):
            df=getattr(self.db, attr, None)
            if df is None: problems.append(f"{attr}: dataframe unavailable")
            elif not hasattr(df,"to_dict"): problems.append(f"{attr}: invalid dataframe")
        return self._fail("Database record load issue", "; ".join(problems), "database.py", "Reload or repair the affected CSV") if problems else self._ok("Database records", f"Loaded {len(self.db.travelers)} travelers, {len(self.db.batches)} batches, {len(self.db.payments)} payments, {len(self.db.invoices)} invoices", "database.py")

    def check_relationships(self):
        def ids(attr):
            df=getattr(self.db, attr, None); return {str(x).strip() for x in df["id"]} if df is not None and "id" in df.columns else set()
        travelers,batches,payments,invoices=ids("travelers"),ids("batches"),ids("payments"),ids("invoices")
        problems=[]
        for attr, col, target, valid in (("travelers","batch_id","batches",batches),("payments","traveler_id","travelers",travelers),("invoices","traveler_id","travelers",travelers),("payments","invoice_id","invoices",invoices)):
            df=getattr(self.db, attr, None)
            if df is None or col not in df.columns: continue
            bad=[str(x).strip() for x in df[col] if str(x).strip() and str(x).strip() not in valid]
            if bad: problems.append(f"{attr}.{col}->{target}: {len(bad)} orphan(s)")
        return self._fail("Relationship integrity issue", "; ".join(problems), "database.py / reports_tab.py", "Correct orphan IDs before using reports") if problems else self._ok("ID and relationship integrity", "No orphan traveler, batch or invoice references found", "database.py / reports_tab.py")

    def check_financials(self):
        problems=[]
        for attr, cols in (("batches",["price"]),("payments",["amount"]),("invoices",["amount","taxable_value","gst_amount","tcs_amount","total_amount","rounded_total"])):
            df=getattr(self.db,attr,None)
            if df is None: continue
            for col in cols:
                if col not in df.columns: continue
                for value in df[col].dropna():
                    try:
                        n=Decimal(str(value));
                        if not n.is_finite() or n<0: raise InvalidOperation
                    except (InvalidOperation,ValueError,TypeError): problems.append(f"{attr}.{col}: invalid {value!r}"); break
        return self._fail("Financial value issue", "; ".join(problems[:8]), "database.py / invoices_tab.py", "Correct invalid or negative amounts") if problems else self._ok("Financial precision", "Financial columns contain finite non-negative values", "database.py / invoices_tab.py")

    def check_statuses(self):
        allowed={"completed","pending","failed","refunded"}; df=self.db.payments
        bad=[] if "status" not in df.columns else [str(x) for x in df.status if str(x).strip().lower() not in allowed]
        return self._fail("Unknown payment status", ", ".join(bad[:5]), "payments_tab.py / reports_tab.py", "Normalize payment status") if bad else self._ok("Payment and invoice status", "Payment statuses are normalized and recognized", "payments_tab.py / reports_tab.py")

    def check_tax(self):
        try:
            from core.settings_manager import SettingsManager
            tax=SettingsManager(self.db).get_tax_settings(); gst=Decimal(str(tax["gst_percentage"])); tcs=Decimal(str(tax["tcs_percentage"]))
            if not (Decimal("0")<=gst<=Decimal("100") and Decimal("0")<=tcs<=Decimal("100")): raise ValueError("Tax outside 0–100%")
            return self._ok("Tax configuration", f"GST {gst}% • TCS {tcs}% • valid 0–100% range", "settings_manager.py / company_settings_dialog.py")
        except Exception as ex: return self._fail("Tax configuration issue", str(ex), "settings_manager.py", "Repair tax_settings.csv or settings manager")

    def check_backups(self):
        folder=self.data_dir/"backups"; files=list(folder.glob("*.zip")) if folder.exists() else []; bad=[p.name for p in files if not zipfile.is_zipfile(p)]
        if bad: return self._fail("Invalid backup ZIP", ", ".join(bad[:5]), "backups_tab.py / database.py", "Remove or recreate invalid backups")
        return self._warn("No backups found", str(folder), "backups_tab.py / database.py", "Create a backup before production changes") if not files else self._ok("Backup integrity", f"{len(files)} backup ZIP(s) are readable", "backups_tab.py / database.py")

    def check_source(self):
        bad=[]; functions=0
        all_files = []
        for folder in self.python_roots:
            all_files.extend(folder.glob("*.py"))
        for path in sorted(set(all_files)):
            try:
                tree=ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                functions += sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) for n in ast.walk(tree))
            except SyntaxError as ex: bad.append(f"{path.name}:{ex.lineno}")
        return self._fail("Source syntax issue", ", ".join(bad), "all Python files", "Fix the reported syntax errors") if bad else self._ok("Source syntax and functions", f"Parsed {len(set(all_files))} files and {functions} functions/methods", "all Python files")

    def check_ui_wiring(self):
        problems=[]; controls=0; handlers=0
        all_files = []
        for folder in self.python_roots:
            all_files.extend(folder.glob("*.py"))
        for path in sorted(set(all_files)):
            if path.name in {"database.py","security.py"}: continue
            text=path.read_text(encoding="utf-8", errors="replace")
            controls += text.count("on_click=") + text.count("on_change=") + text.count("on_submit=")
            handlers += text.count("def ")
            if "ft." in text and "setup_ui" not in text and "Dialog" in path.name: problems.append(f"{path.name}: no setup_ui marker")
        return self._warn("UI wiring review", "; ".join(problems), "Flet tabs and dialogs", "Review the named module") if problems else self._ok("UI/button wiring", f"Static scan found {controls} event bindings across Flet modules; {handlers} function definitions parsed", "Flet tabs and dialogs")

    def check_security(self):
        key=os.getenv("ADMIN_API_KEY", "")
        if not key or len(key)<32: return self._warn("Admin API key", "ADMIN_API_KEY is missing or shorter than 32 characters in this runtime", "security.py / main.py", "Set a random 32+ character ADMIN_API_KEY")
        main=(self.project_root/"main.py").read_text(encoding="utf-8", errors="replace")
        return self._fail("Security fallback detected", "main.py does not fail closed when security import fails", "main.py / security.py", "Keep protected endpoints returning 503") if "Security service unavailable" not in main else self._ok("Security configuration", "ADMIN_API_KEY length and fail-closed security fallback are present", "security.py / main.py")

    def check_background_errors(self):
        hits=[]; now=datetime.now(); activity=self.data_dir/"activity_log.csv"
        if activity.exists():
            try:
                with activity.open("r", encoding="utf-8-sig", errors="replace") as f:
                    for row in csv.DictReader(f):
                        text=(str(row.get("action", ""))+" "+str(row.get("details", ""))).lower()
                        if any(token in text for token in ("error","exception","traceback","failed","failure")):
                            hits.append(text[:240])
            except Exception as ex: hits.append(f"activity log unreadable: {ex}")
        for path in self.data_dir.glob("*.log"):
            try:
                if now - datetime.fromtimestamp(path.stat().st_mtime) <= timedelta(days=7):
                    text=path.read_text(encoding="utf-8", errors="replace")
                    for line in text.splitlines():
                        if any(token in line.lower() for token in ("error","exception","traceback","failed")): hits.append(f"{path.name}: {line[:200]}")
            except Exception: pass
        if hits: return self._warn("Background errors detected", " ; ".join(hits[-5:]), "activity_log.csv / runtime logs", "Open the named log and update the responsible module")
        return self._ok("Background error scan", "No recent error, exception, traceback or failure markers found", "activity_log.csv / runtime logs")