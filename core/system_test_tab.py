# core/system_test_tab.py — recorded, read-only super-admin diagnostics
from __future__ import annotations

import ast
import asyncio
import csv
import json
import os
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

    HISTORY_FILE = "system_test_history.csv"
    ERROR_FILE = "system_error_events.csv"
    MAX_HISTORY = 5000

    def __init__(self, page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user or {}
        self.root = None
        self.results_column = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        self.summary = ft.Text("Loading previous diagnostics…", size=12, color="#475569")
        self.notification = ft.Text("", size=11, weight=ft.FontWeight.BOLD)
        self.last_run = ft.Text("", size=10, color="#64748b")
        self.history_label = ft.Text("", size=10, color="#64748b")
        self.progress_bar = ft.ProgressBar(value=0, min=0, max=1, height=8, color="#2563eb", bgcolor="#dbeafe")
        self.progress_text = ft.Text("Ready — no test is running", size=11, color="#475569")
        self._progress_started = None
        self.last_results = []
        self._test_running = False
        self.cleanup_candidates = []
        self.cleanup_checks = {}
        self.cleanup_confirmation = ft.Checkbox(label="I understand selected files will be permanently deleted", value=False)
        self.cleanup_column = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO)
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
            ("Database file hygiene", "data/ root", self.check_data_file_hygiene),
            ("Project unused-file candidates", "Git workspace / project files", self.check_unused_files),
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
                    ft.Text("Candidates are only suggestions. Review each checkbox. Business CSVs, uploaded documents, backups and remote GitHub files are never deleted automatically.", size=10, color="#64748b"),
                    self.cleanup_column,
                    ft.Row([self.cleanup_confirmation, ft.Button(content=ft.Text("Delete Selected Files"), on_click=self.delete_selected_cleanup, bgcolor="#dc2626", color=ft.Colors.WHITE, height=38)], wrap=True),
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
        try:
            self.progress_bar.update(); self.progress_text.update()
        except Exception:
            pass

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
        self.progress_text.value = "Checking selected test — 50%"
        self.progress_bar.value = 0.5
        try: self.progress_bar.update(); self.progress_text.update()
        except Exception: pass
        results = await asyncio.to_thread(self._run_specs_sync, [("", "", fn)])
        self._show_progress(1, 1, "Selected test complete")
        results = [self._prepare_result(r, run_id) for r in results]
        self._record(results, run_id)
        self.last_results = results
        self._test_running = False
        self._render_results(results)

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
        total = len(self.test_specs)
        for completed, spec in enumerate(self.test_specs, start=1):
            self._show_progress(completed - 1, total, spec[0])
            result = await asyncio.to_thread(self._run_specs_sync, [spec])
            results.extend(result)
            self._show_progress(completed, total, spec[0])
        results = [self._prepare_result(r, run_id) for r in results]
        self._record(results, run_id)
        self.last_results = results
        self._test_running = False
        self._render_results(results)

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

    def _open_download(self, filename):
        relative_url = f"/download/{filename}"
        public_base = (os.getenv("PUBLIC_BASE_URL") or os.getenv("APP_PUBLIC_URL") or "").strip().rstrip("/")
        url = f"{public_base}{relative_url}" if public_base else relative_url
        script = f"window.open({json.dumps(url)}, '_blank', 'noopener,noreferrer');"
        try:
            runner = getattr(self.page, "run_javascript", None)
            if callable(runner):
                runner(script)
                return
        except Exception:
            pass
        self.page.launch_url(url)

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
        fields = ["run_id", "timestamp", "level", "title", "plain_language", "message", "owner", "action", "duration_ms", "user_id", "manus_prompt"]
        with target.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fields})
        try:
            self._open_download(filename)
            self.notification.value = f"CSV download started: {filename}"
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
        target.write_text("\n\n" + ("\n\n" + "=" * 80 + "\n\n").join(prompts), encoding="utf-8")
        try:
            self._open_download(filename)
            self.notification.value = f"Copy-ready Manus prompt file downloaded: {filename}"
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
    def _ok(title, message="No issue detected", owner="system_test_tab.py"):
        return {"level":"OK", "title":title, "message":message, "action":"No action required", "owner":owner}
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
        if not base: return self._warn("Live API probe skipped", "PUBLIC_BASE_URL is not configured; static API contract was checked instead.", "main.py", "Set PUBLIC_BASE_URL only when you want a network probe")
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
        required=["index.html", "robots.txt", "sitemap.xml"]
        missing=[x for x in required if not (self.project_root/x).exists()]
        if missing: return self._fail("Front-page files missing", ", ".join(missing), "index.html / robots.txt / sitemap.xml", "Deploy the missing public files")
        html=(self.project_root/"index.html").read_text(encoding="utf-8", errors="replace")
        markers=["viewport", "api/frontpage", "alert"]
        absent=[x for x in markers if x.lower() not in html.lower()]
        if absent: return self._warn("Front-page markers missing", ", ".join(absent), "index.html / frontpage_config.py", "Review mobile, API and alert rendering")
        try:
            from core.frontpage_config import load_config
            cfg=load_config(); packages=cfg.get("packages", {}) if isinstance(cfg, dict) else {}
            return self._ok("Front-page integrity", f"Public files present; selected package IDs: {len(packages.get('selected_batch_ids', []))}", "index.html / frontpage_config.py")
        except Exception as ex: return self._fail("Front-page configuration error", str(ex), "frontpage_config.py", "Repair front-page configuration loading")

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

    def _add_cleanup_candidates(self, paths, category, reason):
        for path in paths:
            resolved = Path(path).resolve()
            if any(str(resolved) == str(existing["path"]) for existing in self.cleanup_candidates):
                continue
            self.cleanup_candidates.append({"path": resolved, "category": category, "reason": reason})

    def check_data_file_hygiene(self):
        data = self.data_dir
        if not data.exists():
            return self._fail("Data folder missing", str(data), "imports.py / database.py", "Repair the configured data directory")
        allowed_files = {
            "users.csv", "travelers.csv", "batches.csv", "payments.csv", "invoices.csv", "receipts.csv",
            "activity_log.csv", "backup_history.csv", "company_settings.csv", "id_counters.json", ".db.lock",
        }
        ignored_dirs = {"backups", "documents", "logos", "invoices", "receipts", "system_tests"}
        candidates = [p for p in data.iterdir() if p.is_file() and p.name not in allowed_files and not p.name.startswith(".")]
        self._add_cleanup_candidates(candidates, "data", "Unrecognized file directly inside the application data folder")
        if candidates:
            names = ", ".join(p.name for p in candidates[:8])
            return self._warn("Unrecognized data files", names, "data/ root / database.py", "Review the checkboxes; delete only files you recognize as unwanted")
        return self._ok("Database file hygiene", "No unrecognized files found directly in the application data folder", "data/ root / database.py")

    def check_unused_files(self):
        candidates = []
        git_dir = self.project_root / ".git"
        tracked = []
        if git_dir.exists():
            try:
                tracked = subprocess.check_output(["git", "-C", str(self.project_root), "ls-files"], text=True, timeout=5).splitlines()
            except Exception:
                tracked = []
        files = []
        for folder in (self.project_root, self.project_root / "core", self.project_root / "static"):
            if folder.exists():
                files.extend(x for x in folder.rglob("*") if x.is_file() and ".git" not in x.parts)
        important = {"main.py", "index.html", "robots.txt", "sitemap.xml", "requirements.txt", "pyproject.toml", "nixpacks.toml"}
        for path in sorted(set(files)):
            rel = str(path.relative_to(self.project_root)).replace("\\", "/")
            if path.name in important or path.suffix in {".csv", ".db", ".zip", ".png", ".jpg", ".jpeg", ".webp", ".pdf"}:
                continue
            if path.suffix.lower() not in {".py", ".html", ".js", ".css", ".txt", ".md"}:
                continue
            text = ""
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            referenced = False
            for other in files:
                if other == path or other.suffix not in {".py", ".html", ".js", ".css", ".txt", ".md"}:
                    continue
                try:
                    if path.name in other.read_text(encoding="utf-8", errors="ignore"):
                        referenced = True; break
                except Exception:
                    pass
            if not referenced and (not tracked or rel in tracked):
                candidates.append(path)
        self._add_cleanup_candidates(candidates, "project", "Candidate file is not referenced by another scanned project file")
        if candidates:
            names = ", ".join(str(x.relative_to(self.project_root)) for x in candidates[:8])
            return self._warn("Unused-file candidates found", names, "Git workspace / project files", "Review every checkbox; this is a suggestion and may include intentionally standalone files")
        return self._ok("Project unused-file candidates", "No unused-file candidates were identified by the conservative scan", "Git workspace / project files")

    def _refresh_cleanup_ui(self):
        self.cleanup_column.controls.clear()
        if not self.cleanup_candidates:
            self.cleanup_column.controls.append(ft.Text("Run the file hygiene tests to list review candidates.", size=10, color="#64748b"))
        else:
            for item in self.cleanup_candidates:
                path = str(item["path"])
                checkbox = ft.Checkbox(label=f"{item['category'].upper()}: {path} — {item['reason']}", value=False)
                self.cleanup_checks[path] = checkbox
                self.cleanup_column.controls.append(checkbox)
        self.cleanup_column.update()

    def delete_selected_cleanup(self, e=None):
        if not self.cleanup_confirmation.value:
            self.notification.value = "Deletion blocked: tick the permanent-deletion confirmation checkbox first."
            self.notification.color = "#991b1b"; self.notification.update(); return
        selected = [item for item in self.cleanup_candidates if self.cleanup_checks.get(str(item["path"]), None) and self.cleanup_checks[str(item["path"])].value]
        if not selected:
            self.notification.value = "No cleanup candidate selected."; self.notification.color = "#92400e"; self.notification.update(); return
        deleted=[]; blocked=[]
        data_root=self.data_dir.resolve(); project_root=self.project_root.resolve()
        for item in selected:
            path=Path(item["path"]).resolve()
            # Never permit cleanup to remove core business data or uploaded content.
            if path == data_root or data_root in path.parents and path.name in {"users.csv","travelers.csv","batches.csv","payments.csv","invoices.csv","receipts.csv"}:
                blocked.append(f"protected business file: {path}"); continue
            if path == project_root or project_root not in path.parents:
                blocked.append(f"outside project root: {path}"); continue
            try:
                if path.is_file(): path.unlink(); deleted.append(str(path))
            except Exception as ex: blocked.append(f"{path}: {ex}")
        self.cleanup_candidates=[item for item in self.cleanup_candidates if str(item["path"]) not in deleted]
        self._refresh_cleanup_ui()
        self.cleanup_confirmation.value=False; self.cleanup_confirmation.update()
        message=f"Deleted {len(deleted)} selected file(s)."
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
