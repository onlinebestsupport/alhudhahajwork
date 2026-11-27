"""Admin Passport Reader tab. OCR results are review-first and read-only."""
# ===============================================================================
# SECTION 2 — PASSPORT READER ADMIN TAB
# ===============================================================================
# Maintenance index
#   2.1  PassportReaderTab initialization and public build
#   2.2  Responsive controls and table rendering
#   2.3  Read-only scan action and status reporting
#   2.4  CSV/Excel/PDF export actions
# ===============================================================================
from __future__ import annotations

import csv
import os
import traceback
from datetime import datetime
from pathlib import Path

import flet as ft

from core.helpers import send_file_to_user
from core.passport_reader import scan_travelers


# [2.1] PassportReaderTab — responsive admin tab
class PassportReaderTab:
    # [2.2] __init__ — initialize read-only tab state
    def __init__(self, page: ft.Page, db, current_user):
        self.page, self.db, self.current_user = page, db, current_user
        self.rows = []
        self.table = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, expand=True)
        self.status = ft.Text("No scan run yet. Results are read-only until reviewed.", size=11, color="#475569")
        self.root = self._build()

    # [2.3] build — return tab root control
    def build(self):
        return self.root

    # [2.4] _button — create labeled touch-friendly action button
    def _button(self, label, icon, color, handler):
        return ft.Button(content=ft.Row([ft.Icon(icon, size=15, color=ft.Colors.WHITE), ft.Text(label, size=11, color=ft.Colors.WHITE)], spacing=5, tight=True), on_click=handler, height=38, bgcolor=color)

    # [2.5] _build — assemble responsive tab layout
    def _build(self):
        return ft.Container(content=ft.Column([
            ft.Row([ft.Text("🛂 Passport Reader", size=18, weight=ft.FontWeight.BOLD, color="#1e3a8a"), ft.Container(expand=True), self._button("Scan PDF/JPEG", ft.Icons.DOCUMENT_SCANNER, "#2563eb", self.scan)], wrap=True),
            ft.Text("Reads the first passport PDF/JPEG in each traveler folder. MRZ check digits are validated; every non-validated result must be manually checked against the scan before ticket or visa use.", size=11, color="#64748b"),
            ft.Row([self._button("CSV", ft.Icons.DOWNLOAD, "#0f766e", lambda e: self.export("csv")), self._button("Excel", ft.Icons.TABLE_VIEW, "#15803d", lambda e: self.export("xlsx")), self._button("PDF", ft.Icons.PICTURE_AS_PDF, "#b91c1c", lambda e: self.export("pdf"))], wrap=True, spacing=6),
            self.status,
            ft.Container(content=self.table, expand=True, border=ft.Border.all(1, "#cbd5e1"), padding=6),
        ], spacing=8, expand=True), padding=12, expand=True)

    # [2.6] _cell — create a compact table cell
    def _cell(self, value, width=130):
        return ft.Container(content=ft.Text(str(value or ""), size=10, selectable=True, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS), width=width, padding=4)

    # [2.7] _render — render page coverage and validation rows
    def _render(self):
        self.table.controls.clear()
        headers = ["Traveler", "Passport no.", "Name from MRZ", "DOB", "Expiry", "Nationality", "Pages read", "Page 1", "Last page", "File", "Status", "Review reason"]
        self.table.controls.append(ft.Row([self._cell(h, 135) for h in headers], wrap=False, scroll=ft.ScrollMode.AUTO))
        for r in self.rows:
            status = r.get("status", "")
            color = "#166534" if status == "VALIDATED" else "#b45309" if status == "REVIEW" else "#b91c1c"
            values = [r.get("traveler_name") or r.get("traveler_id"), r.get("passport_no"), f"{r.get('surname','')} {r.get('given_names','')}".strip(), r.get("date_of_birth"), r.get("passport_expiry"), r.get("nationality"), r.get("pages_read"), r.get("page_1_status"), r.get("last_page_status"), Path(r.get("source_file", "")).name, status, r.get("review_reason")]
            self.table.controls.append(ft.Row([self._cell(v) for v in values], wrap=False, scroll=ft.ScrollMode.AUTO, vertical_alignment=ft.CrossAxisAlignment.START))
        try:
            self.table.update()
        except Exception:
            pass

    # [2.8] scan — read scans without modifying traveler records
    def scan(self, e=None):
        try:
            self.status.value = "Reading passport scans… this may take time for PDF files."
            self.status.update()
            self.rows = scan_travelers(self.db.get_travelers(), self.db.data_dir)
            valid = sum(1 for r in self.rows if r.get("status") == "VALIDATED")
            review = len(self.rows) - valid
            self.status.value = f"Read {len(self.rows)} traveler record(s): {valid} MRZ-validated, {review} require manual review. No traveler CSV fields were changed."
            self._render()
            self.status.update()
        except Exception as ex:
            traceback.print_exc()
            self.status.value = f"Passport scan failed: {ex}"
            self.status.update()

    # [2.9] _export_rows — ensure current results exist
    def _export_rows(self):
        if not self.rows:
            self.scan()
        return self.rows

    # [2.10] export — create CSV, Excel, or PDF download
    def export(self, kind):
        rows = self._export_rows()
        if not rows:
            return
        # Keep generated artifacts on the same durable Railway volume as the
        # database and source documents.
        out = Path(self.db.data_dir) / "exports" / "passport_reader"
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fields = ["traveler_id", "traveler_name", "passport_no", "surname", "given_names", "nationality", "date_of_birth", "sex", "passport_expiry", "issuing_country", "pages_read", "page_1_status", "last_page_status", "status", "mrz_valid", "review_required", "review_reason", "source_file"]
        path = out / f"passport_reader_{stamp}.{kind}"
        try:
            if kind == "csv":
                with path.open("w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                    writer.writeheader(); writer.writerows(rows)
            elif kind == "xlsx":
                from openpyxl import Workbook
                from openpyxl.styles import Font, PatternFill, Alignment
                wb = Workbook(); ws = wb.active; ws.title = "Passport Reader"
                ws.append(fields)
                for c in ws[1]: c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1E3A8A"); c.alignment = Alignment(wrap_text=True)
                for row in rows: ws.append([row.get(k, "") for k in fields])
                ws.freeze_panes = "A2"
                for col in ws.columns:
                    ws.column_dimensions[col[0].column_letter].width = min(42, max(14, max(len(str(x.value or "")) for x in col) + 2))
                wb.save(path)
            else:
                from reportlab.lib import colors
                from reportlab.lib.pagesizes import landscape, A4
                from reportlab.lib.styles import getSampleStyleSheet
                from reportlab.lib.units import mm
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
                styles = getSampleStyleSheet(); doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=8*mm, rightMargin=8*mm, topMargin=8*mm, bottomMargin=8*mm)
                visible = ["traveler_name", "passport_no", "surname", "given_names", "date_of_birth", "passport_expiry", "nationality", "pages_read", "page_1_status", "last_page_status", "status", "review_reason"]
                labels = ["Traveler", "Passport", "Surname", "Given names", "DOB", "Expiry", "Nationality", "Pages read", "Page 1", "Last page", "Status", "Review"]
                data = [[Paragraph(x, styles["BodyText"]) for x in labels]]
                for r in rows: data.append([Paragraph(str(r.get(k, "") or ""), styles["BodyText"]) for k in visible])
                table = Table(data, repeatRows=1, colWidths=[30*mm, 22*mm, 24*mm, 30*mm, 20*mm, 20*mm, 22*mm, 28*mm, 18*mm, 18*mm, 20*mm, 48*mm])
                table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1e3a8a")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.grey), ("VALIGN", (0,0), (-1,-1), "TOP"), ("FONTSIZE", (0,0), (-1,-1), 7), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")])]))
                doc.build([Paragraph("Passport Reader — manual verification required", styles["Title"]), Spacer(1, 4), table])
            url = send_file_to_user(self.page, str(path), f"Passport Reader {kind.upper()}")
            if url:
                self.page.launch_url(url)
            self.status.value = f"Exported {len(rows)} rows to {path.name}."
            self.status.update()
        except Exception as ex:
            traceback.print_exc(); self.status.value = f"Export failed: {ex}"; self.status.update()
