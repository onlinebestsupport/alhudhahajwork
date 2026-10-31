# core/system_test_tab.py — read-only super-admin diagnostics
from __future__ import annotations

import ast
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import flet as ft


class SystemTestTab:
    """Safe diagnostics for the deployed application; never creates business records."""

    def __init__(self, page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user or {}
        self.root = None
        self.results_column = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        self.summary = ft.Text("Ready to test", size=12, color="#475569")
        self.last_run = ft.Text("", size=10, color="#64748b")
        self.test_specs = self._build_specs()
        self.setup_ui()

    def build(self):
        return self.root

    def _build_specs(self):
        return [
            ("Storage & folders", "imports.py / database.py", self.check_storage),
            ("CSV schema", "database.py", self.check_schema),
            ("ID integrity", "database.py / travelers_tab.py / batches_tab.py", self.check_ids),
            ("Financial values", "database.py / invoices_tab.py", self.check_financials),
            ("Payment status", "payments_tab.py / reports_tab.py", self.check_payments),
            ("Invoice links", "database.py / custom_report_dialog.py", self.check_invoice_links),
            ("Tax configuration", "settings_manager.py / company_settings_dialog.py", self.check_tax),
            ("Backup integrity", "backups_tab.py / database.py", self.check_backups),
            ("Source syntax", "all retained Python files", self.check_source_syntax),
            ("Public files", "index.html / robots.txt / sitemap.xml", self.check_public_files),
            ("Security configuration", "security.py / main.py", self.check_security),
        ]

    def setup_ui(self):
        buttons = []
        for title, _, fn in self.test_specs:
            buttons.append(ft.Button(
                content=ft.Text(title, size=11, weight=ft.FontWeight.BOLD),
                on_click=lambda e, f=fn: self.run_one(f),
                bgcolor="#e0f2fe", color="#075985", height=38,
            ))
        run_all = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=17), ft.Text("Run All Tests", weight=ft.FontWeight.BOLD)], tight=True),
            on_click=self.run_all, bgcolor="#2563eb", color=ft.Colors.WHITE, height=42,
        )
        clear = ft.Button(
            content=ft.Row([ft.Icon(ft.Icons.CLEAR_ALL, size=17), ft.Text("Clear Results")], tight=True),
            on_click=lambda e: self.clear_results(), bgcolor="#f1f5f9", color="#334155", height=42,
        )
        test_cards = []
        for title, owner, _ in self.test_specs:
            test_cards.append(ft.Container(
                content=ft.Column([
                    ft.Text(title, size=12, weight=ft.FontWeight.BOLD, color="#0f172a"),
                    ft.Text(f"Owner: {owner}", size=9, color="#64748b"),
                ], spacing=2), padding=8, bgcolor="#f8fafc", border_radius=8,
                border=ft.Border.all(1, "#e2e8f0"), expand=True,
            ))
        self.root = ft.Container(
            content=ft.Column([
                ft.Container(content=ft.Row([
                    ft.Icon(ft.Icons.HEALTH_AND_SAFETY, color="#ffffff", size=26),
                    ft.Column([
                        ft.Text("System Test Center", size=18, weight=ft.FontWeight.BOLD, color="#ffffff"),
                        ft.Text("Read-only diagnostics for data, finance, security and deployment", size=10, color="#dbeafe"),
                    ], spacing=2, expand=True),
                    ft.Container(content=ft.Text("SUPER ADMIN", size=9, weight=ft.FontWeight.BOLD, color="#ffffff"),
                                 bgcolor="#dc2626", padding=7, border_radius=6),
                ], spacing=10), padding=16, bgcolor="#0f3b66", border_radius=12),
                ft.ResponsiveRow(test_cards, spacing=6, run_spacing=6),
                ft.Row([run_all, clear], spacing=8),
                ft.Container(content=ft.Column([self.summary, self.last_run], spacing=2), padding=10,
                             bgcolor="#eff6ff", border_radius=8),
                ft.Container(content=self.results_column, expand=True, padding=8,
                             border=ft.Border.all(1, "#e2e8f0"), border_radius=8),
            ], spacing=10, expand=True, scroll=ft.ScrollMode.AUTO),
            padding=12, expand=True, bgcolor="#ffffff",
        )

    def clear_results(self):
        self.results_column.controls.clear()
        self.summary.value = "Ready to test"
        self.last_run.value = ""
        self.results_column.update()
        self.summary.update()

    def run_one(self, fn):
        result = self._safe_call(fn)
        self._render_results([result])

    def run_all(self, e=None):
        results = [self._safe_call(fn) for _, _, fn in self.test_specs]
        self._render_results(results)

    def _safe_call(self, fn):
        try:
            result = fn()
            return result if isinstance(result, dict) else self._ok(str(result))
        except Exception as ex:
            return self._fail("Unexpected test error", str(ex), "system_test_tab.py")

    def _render_results(self, results):
        self.results_column.controls.clear()
        passed = sum(r.get("level") == "OK" for r in results)
        failed = sum(r.get("level") == "FAIL" for r in results)
        warnings = sum(r.get("level") == "WARN" for r in results)
        self.summary.value = f"Completed {len(results)} checks  •  Passed: {passed}  •  Warnings: {warnings}  •  Failed: {failed}"
        self.last_run.value = f"Last run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  •  No business data was modified"
        for r in results:
            level = r.get("level", "FAIL")
            color = {"OK": "#166534", "WARN": "#92400e", "FAIL": "#991b1b"}.get(level, "#334155")
            bg = {"OK": "#f0fdf4", "WARN": "#fffbeb", "FAIL": "#fef2f2"}.get(level, "#f8fafc")
            self.results_column.controls.append(ft.Container(
                content=ft.Column([
                    ft.Row([ft.Text(f"{level}  {r.get('title', '')}", size=12, weight=ft.FontWeight.BOLD, color=color), ft.Container(expand=True), ft.Text(r.get("owner", ""), size=9, color="#64748b")]),
                    ft.Text(r.get("message", ""), size=11, color="#334155", selectable=True),
                    ft.Text(f"Action: {r.get('action', 'No action required')}", size=10, color=color, selectable=True),
                ], spacing=3), padding=10, bgcolor=bg, border_radius=7,
                border=ft.Border.all(1, color),
            ))
        self.results_column.update(); self.summary.update(); self.last_run.update()

    @staticmethod
    def _ok(title, message="No issue detected", owner="system_test_tab.py"):
        return {"level": "OK", "title": title, "message": message, "action": "No action required", "owner": owner}

    @staticmethod
    def _warn(title, message, owner, action):
        return {"level": "WARN", "title": title, "message": message, "action": action, "owner": owner}

    @staticmethod
    def _fail(title, message, owner, action="Open the named file and correct the reported condition"):
        return {"level": "FAIL", "title": title, "message": message, "action": action, "owner": owner}

    def check_storage(self):
        data_dir = Path(getattr(self.db, "data_dir", ""))
        if not data_dir.exists(): return self._fail("Storage path missing", str(data_dir), "imports.py / database.py")
        if not os.access(data_dir, os.R_OK | os.W_OK): return self._fail("Storage not writable", str(data_dir), "imports.py / database.py")
        required = ["users.csv", "travelers.csv", "batches.csv", "payments.csv", "invoices.csv", "receipts.csv"]
        missing = [x for x in required if not (data_dir / x).exists()]
        return self._fail("Required CSV missing", ", ".join(missing), "database.py", "Restore the missing CSV or run database initialization") if missing else self._ok("Storage & folders", f"Data directory is readable and writable: {data_dir}", "imports.py / database.py")

    def check_schema(self):
        expected = {"users": {"id", "username", "role"}, "travelers": {"id", "batch_id"}, "batches": {"id", "price"}, "payments": {"id", "traveler_id", "amount", "status"}, "invoices": {"id", "traveler_id"}, "receipts": {"id", "payment_id"}}
        problems=[]
        for attr, cols in expected.items():
            df=getattr(self.db, attr, None)
            missing=sorted(cols-set(getattr(df, "columns", [])))
            if missing: problems.append(f"{attr}: missing {', '.join(missing)}")
        return self._fail("CSV schema mismatch", "; ".join(problems), "database.py", "Repair the listed table schema") if problems else self._ok("CSV schema", "All core tables contain required columns", "database.py")

    def check_ids(self):
        problems=[]
        for attr in ("travelers", "batches", "payments", "invoices", "receipts"):
            df=getattr(self.db, attr, None)
            if df is None or "id" not in getattr(df, "columns", []): continue
            ids=df["id"].astype(str).str.strip()
            if ids.duplicated().any(): problems.append(f"{attr}: duplicate IDs")
            if (ids == "").any() or ids.isin({"nan", "None"}).any(): problems.append(f"{attr}: blank IDs")
        return self._fail("ID integrity issue", "; ".join(problems), "database.py / travelers_tab.py / batches_tab.py") if problems else self._ok("ID integrity", "No duplicate or blank business IDs found", "database.py / travelers_tab.py / batches_tab.py")

    def check_financials(self):
        problems=[]
        for attr, cols in (("batches", ["price"]), ("payments", ["amount"]), ("invoices", ["base_amount", "total_amount"])):
            df=getattr(self.db, attr, None)
            if df is None: continue
            for col in cols:
                if col not in df.columns: continue
                for value in df[col].dropna():
                    try:
                        number=Decimal(str(value))
                        if not number.is_finite() or number < 0: raise InvalidOperation
                    except (InvalidOperation, ValueError, TypeError):
                        problems.append(f"{attr}.{col}: invalid value {value!r}"); break
        return self._fail("Financial value issue", "; ".join(problems[:5]), "database.py / invoices_tab.py") if problems else self._ok("Financial values", "Amounts are finite and non-negative", "database.py / invoices_tab.py")

    def check_payments(self):
        allowed={"completed", "pending", "failed", "refunded"}
        df=getattr(self.db, "payments", None)
        bad=[] if df is None or "status" not in df.columns else [str(x) for x in df["status"] if str(x).strip().lower() not in allowed]
        return self._fail("Unknown payment status", ", ".join(bad[:5]), "payments_tab.py / reports_tab.py", "Normalize the payment status to completed, pending, failed or refunded") if bad else self._ok("Payment status", "All payment statuses are recognized", "payments_tab.py / reports_tab.py")

    def check_invoice_links(self):
        travelers={str(x).strip() for x in getattr(self.db.travelers, "id", []).tolist()} if hasattr(self.db, "travelers") else set()
        if not hasattr(self.db, "invoices") or "traveler_id" not in self.db.invoices.columns: return self._warn("Invoice links", "Invoice traveler_id column is unavailable", "database.py / custom_report_dialog.py", "Repair the invoice schema")
        orphan=[str(x) for x in self.db.invoices["traveler_id"] if str(x).strip() and str(x).strip() not in travelers]
        return self._fail("Orphan invoice link", ", ".join(orphan[:5]), "database.py / custom_report_dialog.py", "Correct the traveler_id before generating reports") if orphan else self._ok("Invoice links", "Every invoice points to an existing traveler", "database.py / custom_report_dialog.py")

    def check_tax(self):
        try:
            from core.settings_manager import SettingsManager
            tax=SettingsManager(self.db).get_tax_settings()
            gst=Decimal(str(tax.get("gst_percentage"))); tcs=Decimal(str(tax.get("tcs_percentage")))
            if not (Decimal("0") <= gst <= Decimal("100") and Decimal("0") <= tcs <= Decimal("100")): raise ValueError
            return self._ok("Tax configuration", f"GST {gst}% • TCS {tcs}% • valid range 0–100%", "settings_manager.py / company_settings_dialog.py")
        except Exception as ex: return self._fail("Tax configuration issue", str(ex), "settings_manager.py / company_settings_dialog.py")

    def check_backups(self):
        folder=Path(getattr(self.db, "data_dir", ".")) / "backups"
        files=list(folder.glob("*.zip")) if folder.exists() else []
        bad=[p.name for p in files if not zipfile.is_zipfile(p)]
        if bad: return self._fail("Invalid backup ZIP", ", ".join(bad[:5]), "backups_tab.py / database.py", "Remove or recreate the invalid backup")
        return self._warn("No backups found", str(folder), "backups_tab.py / database.py", "Create a backup before production changes") if not files else self._ok("Backup integrity", f"{len(files)} ZIP backup(s) are readable", "backups_tab.py / database.py")

    def check_source_syntax(self):
        root=Path(__file__).resolve().parent
        bad=[]
        for path in sorted(root.glob("*.py")):
            try: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as ex: bad.append(f"{path.name}:{ex.lineno}")
        return self._fail("Source syntax issue", ", ".join(bad), "all retained Python files") if bad else self._ok("Source syntax", "All retained Python files parse successfully", "all retained Python files")

    def check_public_files(self):
        root=Path(__file__).resolve().parent
        missing=[x for x in ("index.html", "robots.txt", "sitemap.xml") if not (root/x).exists()]
        return self._fail("Public file missing", ", ".join(missing), "index.html / robots.txt / sitemap.xml") if missing else self._ok("Public files", "Landing page, robots and sitemap files are present", "index.html / robots.txt / sitemap.xml")

    def check_security(self):
        key=os.getenv("ADMIN_API_KEY", "")
        if not key or len(key)<32: return self._warn("Admin API key", "ADMIN_API_KEY is missing or shorter than 32 characters in this runtime", "security.py / main.py", "Set a long random ADMIN_API_KEY in Railway environment variables")
        return self._ok("Security configuration", "ADMIN_API_KEY is configured with an acceptable length", "security.py / main.py")
