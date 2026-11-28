"""Admin Passport Reader tab. OCR results are review-first and read-only."""
# ===============================================================================
# SECTION 2 — PASSPORT READER ADMIN TAB
# ===============================================================================
# Maintenance index
#   2.1  PassportReaderTab initialization and public build
#   2.2  Responsive controls and table rendering
#   2.3  Read-only scan action and status reporting
#   2.4  CSV/Excel/PDF export actions
#   2.5  Mobile swipe-safe result cards
# ===============================================================================
from __future__ import annotations

import csv
import asyncio
import multiprocessing
import os
import queue
import re
import traceback
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import flet as ft

from core.helpers import send_file_to_user
from core.passport_reader import scan_travelers
from core.runtime_logging import log_event, log_exception


# [2.0] _scan_worker — run native OCR/PDF work outside the long-lived Flet process
def _scan_worker(traveler, data_dir, result_queue):
    """Process one traveler and exit, releasing Tesseract/Pillow native memory."""
    try:
        result_queue.put({"ok": True, "rows": scan_travelers([traveler], data_dir)})
    except Exception as ex:
        result_queue.put({"ok": False, "error": f"{type(ex).__name__}: {ex}"})


def _scan_one_isolated(traveler, data_dir, timeout_seconds=240):
    """Return one traveler result from a disposable process.

    Tesseract and PDF rasterization can retain native allocations that Python
    garbage collection does not promptly return on Railway. A process boundary
    makes Read All bounded by one traveler rather than by the whole batch.
    """
    # fork avoids re-importing the Flet application on Railway/Linux; spawn is
    # required on Windows and remains safe because this target is top-level.
    context_name = "spawn" if os.name == "nt" else "fork"
    context = multiprocessing.get_context(context_name)
    result_queue = context.Queue(maxsize=1)
    process = context.Process(target=_scan_worker,
                              args=(traveler, data_dir, result_queue))
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(10)
        return [], f"OCR timeout after {timeout_seconds}s"
    try:
        payload = result_queue.get(timeout=5)
    except (queue.Empty, OSError, EOFError):
        payload = {"ok": False, "error": f"OCR worker exited with code {process.exitcode}"}
    finally:
        result_queue.close()
        result_queue.join_thread()
    if not payload.get("ok"):
        return [], payload.get("error", "OCR worker failed")
    return payload.get("rows", []), ""


# [2.1] PassportReaderTab — responsive admin tab
class PassportReaderTab:
    # [2.2a] _icon — resolve icon names across Flet 1.x releases
    @staticmethod
    def _icon(name, fallback="DESCRIPTION"):
        icons = getattr(ft, "Icons", None)
        value = getattr(icons, name, None) if icons is not None else None
        if value is not None:
            return value
        return getattr(icons, fallback, "description") if icons is not None else "description"

    # [2.2] __init__ — initialize read-only tab state
    def __init__(self, page: ft.Page, db, current_user):
        self.page, self.db, self.current_user = page, db, current_user
        self.rows = []
        self.travelers = []
        self._traveler_by_id = {}
        self._scan_running = False
        self.subtab_selector = None
        self.subtab_content = None
        self.traveler_search = ft.TextField(
            label="Search traveler / passport / mobile",
            hint_text="Type a name, ID, passport number, or mobile",
            dense=True,
            on_change=self._filter_travelers,
        )
        self.traveler_dropdown = ft.Dropdown(
            label="Traveler passport folder",
            hint_text="Select one traveler to read",
            options=[],
            dense=True,
            expand=True,
        )
        # Flet 1.1.x does not accept on_change in Dropdown.__init__.
        self.traveler_dropdown.on_change = self._selected_traveler_changed
        self._load_traveler_choices()
        self.table = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, expand=True)
        self.status = ft.Text("No scan run yet. Results are read-only until reviewed.", size=11, color="#475569")
        self.root = self._build()

    # [2.3] build — return tab root control
    def build(self):
        return self.root

    # [2.4a] refresh — redraw existing results without an automatic OCR scan
    def refresh(self):
        """Refresh the visible table only; scanning remains an explicit action."""
        if self.rows:
            self._render()
        log_event("PASSPORT_READER", "REFRESH_VISIBLE_ONLY", db=self.db,
                  row_count=len(self.rows))

    # [2.4aa] _status_update — update safely before/after page attachment
    def _status_update(self):
        try:
            self.status.update()
        except Exception as ex:
            log_event("PASSPORT_READER", "STATUS_UPDATE_SKIPPED",
                      db=self.db, error_type=type(ex).__name__)

    # [2.4b] _load_traveler_choices — load searchable read-only selector data
    def _load_traveler_choices(self):
        try:
            raw = self.db.get_travelers()
            self.travelers = [dict(row) for row in raw]
            self._traveler_by_id = {
                str(row.get("id", "")).strip(): row for row in self.travelers
                if str(row.get("id", "")).strip()
            }
            self._set_traveler_options(self.travelers)
            log_event("PASSPORT_READER", "TRAVELER_CHOICES_LOADED",
                      db=self.db, traveler_count=len(self.travelers))
        except Exception as ex:
            log_exception("PASSPORT_READER", "TRAVELER_CHOICES_FAILED", ex,
                          db=self.db)

    # [2.4c] _traveler_label — produce a useful mobile dropdown label
    def _traveler_label(self, row):
        traveler_id = str(row.get("id", "")).strip()
        name = " ".join(str(row.get(key, "") or "").strip()
                        for key in ("first_name", "last_name")).strip()
        passport = str(row.get("passport_no", "") or "").strip()
        return " · ".join(part for part in (name, passport, traveler_id)
                          if part) or traveler_id

    # [2.4d] _set_traveler_options — update dropdown without starting a scan
    def _set_traveler_options(self, rows):
        self.traveler_dropdown.options = [
            ft.dropdown.Option(
                key=str(row.get("id", "")).strip(),
                text=self._traveler_label(row))
            for row in rows if str(row.get("id", "")).strip()
        ]
        try:
            self.traveler_dropdown.update()
        except Exception:
            pass

    # [2.4e] _filter_travelers — filter by ID, name, passport, or mobile
    def _filter_travelers(self, e=None):
        needle = str(self.traveler_search.value or "").strip().lower()
        if not needle:
            rows = self.travelers
        else:
            rows = [row for row in self.travelers if needle in " ".join(
                str(row.get(key, "") or "") for key in
                ("id", "first_name", "last_name", "passport_no", "mobile")
            ).lower()]
        self._set_traveler_options(rows)
        log_event("PASSPORT_READER", "TRAVELER_FILTER", db=self.db,
                  query=needle, match_count=len(rows))

    # [2.4f] _selected_traveler_changed — log selected traveler only
    def _selected_traveler_changed(self, e=None):
        log_event("PASSPORT_READER", "TRAVELER_SELECTED", db=self.db,
                  traveler_id=str(self.traveler_dropdown.value or ""))

    # [2.4g] _set_subtab — switch reader/results content without swipe tabs
    def _set_subtab(self, key):
        if self.subtab_content is None:
            return
        if key == "results":
            self.subtab_content.content = self._results_panel
        else:
            self.subtab_content.content = self._reader_panel
            key = "reader"
        try:
            self.subtab_content.update()
            self.subtab_selector.value = key
            self.subtab_selector.update()
        except Exception:
            pass
        log_event("PASSPORT_READER", "SUBTAB_SELECTED", db=self.db,
                  subtab=key)

    # [2.4] _button — create labeled touch-friendly action button
    def _button(self, label, icon, color, handler):
        return ft.Button(content=ft.Row([ft.Icon(icon, size=15, color=ft.Colors.WHITE), ft.Text(label, size=11, color=ft.Colors.WHITE)], spacing=5, tight=True), on_click=handler, height=38, bgcolor=color)

    # [2.5] _build — assemble responsive tab layout
    def _build(self):
        header = ft.Text("🛂 Passport Reader", size=18,
                         weight=ft.FontWeight.BOLD, color="#1e3a8a")
        description = ft.Text(
            "Mixed Files mode reads every PDF, JPEG, and PNG in the selected traveler folder as one ordered passport-page set. Verify all OCR against the original scan.",
            size=11, color="#64748b")
        selector_row = ft.ResponsiveRow([
            ft.Container(content=self.traveler_search, col={"xs": 12, "md": 5}),
            ft.Container(content=self.traveler_dropdown, col={"xs": 12, "md": 7}),
        ], spacing=8, run_spacing=8)
        self._reader_panel = ft.Column([
            description,
            selector_row,
            ft.Row([
                self._button("Read Selected", self._icon("DOCUMENT_SCANNER"), "#2563eb", self.scan),
                self._button("Read All", self._icon("FOLDER_OPEN"), "#475569", lambda e: self.scan(e, all_travelers=True)),
            ], wrap=True, spacing=6),
        ], spacing=8, scroll=ft.ScrollMode.AUTO)
        self._results_panel = ft.Column([
            ft.Row([
                self._button("CSV", self._icon("DOWNLOAD"), "#0f766e", lambda e: self.export("csv")),
                self._button("Excel", self._icon("TABLE_VIEW", "GRID_VIEW"), "#15803d", lambda e: self.export("xlsx")),
                self._button("PDF", self._icon("PICTURE_AS_PDF", "DESCRIPTION"), "#b91c1c", lambda e: self.export("pdf")),
            ], wrap=True, spacing=6),
            self.status,
            ft.Container(content=self.table, height=360,
                         bgcolor="#ffffff", border=ft.Border.all(1, "#cbd5e1"), padding=6),
        ], spacing=8, scroll=ft.ScrollMode.AUTO)
        self.subtab_selector = ft.Dropdown(
            label="Passport Reader section",
            options=[
                ft.dropdown.Option(key="reader", text="Mixed Files Reader"),
                ft.dropdown.Option(key="results", text="Results & Downloads"),
            ], value="reader", dense=True, expand=True)
        self.subtab_selector.on_change = lambda e: self._set_subtab(
            self.subtab_selector.value)
        self.subtab_content = ft.Container(content=self._reader_panel,
                                            expand=True)
        return ft.Container(content=ft.Column([
            ft.Row([header], wrap=True),
            self.subtab_selector,
            self.subtab_content,
        ], spacing=8, scroll=ft.ScrollMode.AUTO),
            padding=12, bgcolor="#ffffff", expand=True)

    # [2.6] _cell — create a compact table cell
    def _cell(self, value, width=130):
        return ft.Container(content=ft.Text(str(value or ""), size=10, selectable=True, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS), width=width, padding=4)

    # [2.6a] _is_mobile — choose a swipe-safe result layout
    def _is_mobile(self):
        try:
            width = float(getattr(self.page, "width", 0) or 0)
        except (TypeError, ValueError):
            width = 0
        platform = str(getattr(self.page, "platform", "")).lower()
        return width == 0 or width < 700 or any(
            token in platform for token in ("ios", "android", "mobile"))

    # [2.6b] _mobile_card — render all passport details vertically
    def _mobile_card(self, row):
        status = str(row.get("status", ""))
        color = "#166534" if status == "VALIDATED" else "#b45309" if status == "REVIEW" else "#b91c1c"
        values = [
            ("Traveler", row.get("traveler_name") or row.get("traveler_id")),
            ("Passport", row.get("passport_no")),
            ("Name from MRZ", f"{row.get('surname', '')} {row.get('given_names', '')}".strip()),
            ("Date of birth", row.get("date_of_birth")),
            ("Expiry", row.get("passport_expiry")),
            ("Nationality", row.get("nationality")),
            ("Pages read", row.get("pages_read")),
            ("Page 1", row.get("page_1_status")),
            ("Last page", row.get("last_page_status")),
            ("Source file", Path(str(row.get("source_file", "")).replace("\\", "/")).name),
            ("All source files", row.get("source_files") or row.get("source_file")),
            ("Page 1 OCR text", row.get("page_1_ocr")),
            ("Last page OCR text", row.get("last_page_ocr")),
            ("Review reason", row.get("review_reason")),
        ]
        details = [
            ft.Row([
                ft.Container(content=ft.Text(label, size=10, weight=ft.FontWeight.BOLD), width=105),
                ft.Text(
                    (str(value or "—")[:1800] + "…"
                     if label.endswith("OCR text") and len(str(value or "")) > 1800
                     else str(value or "—")),
                    size=10, selectable=True, expand=True),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START)
            for label, value in values
        ]
        details.insert(0, ft.Text(status or "UNKNOWN", size=13,
                                  weight=ft.FontWeight.BOLD, color=color))
        return ft.Container(content=ft.Column(details, spacing=4),
                            bgcolor="#f8fafc", border=ft.Border.all(1, "#cbd5e1"),
                            border_radius=8, padding=8)

    # [2.7] _render — render swipe-safe mobile cards or desktop table
    def _render(self):
        self.table.controls.clear()
        headers = ["Traveler", "Passport no.", "Name from MRZ", "DOB", "Expiry", "Nationality", "Pages read", "Page 1", "Last page", "File", "Status", "Review reason"]
        if self._is_mobile():
            log_event("PASSPORT_READER", "MOBILE_RESULTS_RENDER", db=self.db,
                      row_count=len(self.rows))
            self.table.controls.append(ft.Text(
                "Passport results — scroll vertically; horizontal swipes are disabled in this view.",
                size=10, color="#475569"))
            self.table.controls.extend(self._mobile_card(row) for row in self.rows)
            try:
                self.table.update()
            except Exception:
                pass
            return
        log_event("PASSPORT_READER", "DESKTOP_RESULTS_RENDER", db=self.db,
                  row_count=len(self.rows))
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

    # [2.8] scan — queue selected/all scans without blocking the WebSocket
    def scan(self, e=None, all_travelers=False):
        if self._scan_running:
            self.status.value = "A passport scan is already running. Please wait."
            self._status_update()
            return
        selected_id = str(self.traveler_dropdown.value or "").strip()
        if not all_travelers and not selected_id:
            self.status.value = "Select a traveler from the dropdown before reading."
            self._status_update()
            log_event("PASSPORT_READER", "SCAN_SKIPPED_NO_SELECTION",
                      db=self.db)
            return
        targets = (self.travelers if all_travelers else
                   [self._traveler_by_id[selected_id]])
        self._scan_running = True
        self.status.value = (
            f"Reading {len(targets)} traveler passport folder(s) in the background…")
        self._status_update()
        # Read Selected remains on the reader screen; Read All opens the
        # accumulated results screen so progress and downloads are visible.
        if all_travelers:
            self._set_subtab("results")
        log_event("PASSPORT_READER", "SCAN_START", db=self.db,
                  selected_traveler=selected_id or "ALL",
                  traveler_count=len(targets))
        try:
            self.page.run_task(self._scan_background, targets)
        except Exception as ex:
            self._scan_running = False
            log_exception("PASSPORT_READER", "SCAN_QUEUE_FAILED", ex,
                          db=self.db)
            self.status.value = f"Passport scan could not start: {ex}"
            self._status_update()

    # [2.8a] _scan_background — OCR outside the Flet event loop
    async def _scan_background(self, targets):
        try:
            # Process one traveler at a time instead of keeping the WebSocket
            # silent while a large Read All batch performs OCR. This also makes
            # partial results visible and allows the user to see progress.
            if len(targets) > 1:
                self.rows = []
            total = len(targets)
            no_file_count = 0
            for index, traveler in enumerate(targets, start=1):
                traveler_id = str(traveler.get("id", ""))
                log_event("PASSPORT_READER", "SCAN_PROGRESS_START", db=self.db,
                          traveler_index=index, traveler_total=total,
                          traveler_id=traveler_id)
                rows, worker_error = await asyncio.to_thread(
                    _scan_one_isolated, traveler, self.db.data_dir)
                if worker_error:
                    log_event("PASSPORT_READER", "SCAN_WORKER_FAILED", db=self.db,
                              traveler_index=index, traveler_total=total,
                              traveler_id=traveler_id, error=worker_error)
                    rows = [{
                        "traveler_id": traveler_id,
                        "traveler_name": " ".join(str(traveler.get(k, "") or "").strip() for k in ("first_name", "last_name")).strip(),
                        "source_file": "", "status": "ERROR",
                        "review_required": True,
                        "review_reason": worker_error,
                    }]
                if len(targets) == 1 and rows:
                    self.rows = [r for r in self.rows
                                 if str(r.get("traveler_id", "")) != traveler_id]
                self.rows.extend(rows)
                row_status = str(rows[0].get("status", "")) if rows else "NO SCAN"
                if row_status == "NO SCAN":
                    no_file_count += 1
                    log_event("PASSPORT_READER", "NO_FILES_IN_FOLDER", db=self.db,
                              traveler_index=index, traveler_total=total,
                              traveler_id=traveler_id,
                              message="No PDF/JPEG/PNG files inside passport folder")
                log_event("PASSPORT_READER", "SCAN_PROGRESS_COMPLETE", db=self.db,
                          traveler_index=index, traveler_total=total,
                          traveler_id=traveler_id,
                          result_status=str(rows[0].get("status", "")) if rows else "NO_RESULT")
                self.status.value = (
                    f"Reading passport records… {index}/{total} completed. "
                    f"{no_file_count} folder(s) have no passport files. "
                    f"{len(self.rows)} result(s) accumulated.")
                # Rebuild the growing OCR cards in bounded batches. Updating
                # dozens of large cards after every file can overload a mobile
                # WebSocket and look like an unexpected logout.
                if index == 1 or index % 5 == 0 or index == total:
                    self._render()
                self._status_update()
                await asyncio.sleep(0)
            valid = sum(1 for r in self.rows if r.get("status") == "VALIDATED")
            review = len(self.rows) - valid
            errors = sum(1 for r in self.rows if r.get("status") == "ERROR")
            self.status.value = (
                f"Read {len(self.rows)} traveler record(s): {valid} MRZ-validated, "
                f"{review} require review, {errors} OCR errors, "
                f"{no_file_count} folder(s) with no passport files. "
                "No traveler CSV fields were changed.")
            self._render()
            if len(targets) == 1:
                self._set_subtab("reader")
            self._status_update()
            log_event("PASSPORT_READER", "SCAN_SUCCESS", db=self.db,
                      row_count=len(self.rows), validated=valid,
                      review=review, errors=errors)
        except Exception as ex:
            traceback.print_exc()
            log_exception("PASSPORT_READER", "SCAN_FAILED", ex, db=self.db)
            self.status.value = f"Passport scan failed: {ex}"
            self._status_update()
        finally:
            self._scan_running = False

    # [2.9] _export_rows — ensure current results exist
    def _export_rows(self):
        return self.rows

    # [2.10] export — create CSV, Excel, or PDF download
    def export(self, kind):
        log_event("PASSPORT_READER", "EXPORT_START", db=self.db, kind=kind)
        rows = self._export_rows()
        if not rows:
            log_event("PASSPORT_READER", "EXPORT_SKIPPED_NO_ROWS", db=self.db,
                      kind=kind)
            return
        # Keep generated artifacts on the same durable Railway volume as the
        # database and source documents.
        out = Path(self.db.data_dir) / "exports" / "passport_reader"
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fields = ["traveler_id", "traveler_name", "passport_no", "surname", "given_names", "nationality", "date_of_birth", "sex", "passport_expiry", "issuing_country", "pages_read", "page_1_status", "last_page_status", "status", "mrz_valid", "review_required", "review_reason", "source_file", "source_files", "page_1_ocr", "page_2_ocr", "last_page_ocr", "page_ocr"]
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
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
                styles = getSampleStyleSheet(); doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=8*mm, rightMargin=8*mm, topMargin=8*mm, bottomMargin=8*mm)
                visible = ["traveler_name", "passport_no", "surname", "given_names", "date_of_birth", "passport_expiry", "nationality", "pages_read", "page_1_status", "last_page_status", "status", "review_reason"]
                labels = ["Traveler", "Passport No.", "Surname", "Given Name(s)", "Date of Birth", "Date of Expiry", "Nationality", "Pages read", "Page 1", "Page 2 / last", "Status", "Review"]
                data = [[Paragraph(x, styles["BodyText"]) for x in labels]]
                for r in rows: data.append([Paragraph(str(r.get(k, "") or ""), styles["BodyText"]) for k in visible])
                table = Table(data, repeatRows=1, colWidths=[30*mm, 22*mm, 24*mm, 30*mm, 20*mm, 20*mm, 22*mm, 28*mm, 18*mm, 18*mm, 20*mm, 48*mm])
                table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1e3a8a")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.grey), ("VALIGN", (0,0), (-1,-1), "TOP"), ("FONTSIZE", (0,0), (-1,-1), 7), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")])]))
                story = [Paragraph("Passport Reader — passport fields and page-by-page reading", styles["Title"]),
                         Paragraph("English OCR only. Verify every value against the original passport scan before ticket or visa issuance.", styles["BodyText"]),
                         Spacer(1, 4), table]
                for row_index, r in enumerate(rows):
                    story.append(PageBreak())
                    traveler_title = xml_escape(str(r.get("traveler_name") or r.get("traveler_id") or "Unknown traveler"))
                    story.append(Paragraph(f"{traveler_title} — Page 1", styles["Heading2"]))
                    page1_fields = [
                        ("Surname", r.get("surname")),
                        ("Given Name(s)", r.get("given_names")),
                        ("Passport No.", r.get("passport_no")),
                        ("Nationality", r.get("nationality")),
                        ("Date of Birth", r.get("date_of_birth")),
                        ("Sex", r.get("sex")),
                        ("Date of Expiry", r.get("passport_expiry")),
                        ("Issuing Country", r.get("issuing_country")),
                    ]
                    story.append(Table([[Paragraph(xml_escape(str(k)), styles["BodyText"]),
                                         Paragraph(xml_escape(str(v or "")), styles["BodyText"])]
                                        for k, v in page1_fields], colWidths=[42*mm, 90*mm],
                                        style=TableStyle([("GRID", (0,0), (-1,-1), .25, colors.grey),
                                                          ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#e2e8f0")),
                                                          ("VALIGN", (0,0), (-1,-1), "TOP")])) )
                    story.append(Spacer(1, 8))
                    page1 = str(r.get("page_1_ocr") or "").strip()
                    page1 = "\n".join(line.strip() for line in page1.splitlines()
                                        if line.strip() and not line.strip().startswith("[MRZ OCR]"))
                    story.append(Paragraph("Page 1 — English OCR labels and printed text", styles["Heading3"]))
                    story.append(Paragraph(xml_escape(page1 or "No Page 1 OCR text captured.").replace("\n", "<br/>"), styles["BodyText"]))
                    story.append(Spacer(1, 8))
                    story.append(Paragraph("Page 2 — passport-printed text", styles["Heading2"]))
                    page2 = str(r.get("page_2_ocr") or r.get("last_page_ocr") or "").strip()
                    page2 = "\n".join(line.strip() for line in page2.splitlines()
                                        if line.strip() and not line.strip().startswith("[MRZ OCR]"))
                    story.append(Paragraph(xml_escape(page2 or "No Page 2 OCR text captured.").replace("\n", "<br/>"), styles["BodyText"]))
                doc.build(story)
            url = send_file_to_user(self.page, str(path), f"Passport Reader {kind.upper()}")
            if url:
                self.page.launch_url(url)
            self.status.value = f"Exported {len(rows)} rows to {path.name}."
            self._status_update()
            log_event("PASSPORT_READER", "EXPORT_SUCCESS", db=self.db,
                      kind=kind, row_count=len(rows), path=str(path))
        except Exception as ex:
            traceback.print_exc()
            log_exception("PASSPORT_READER", "EXPORT_FAILED", ex, db=self.db,
                          kind=kind, path=str(path))
            self.status.value = f"Export failed: {ex}"; self._status_update()
