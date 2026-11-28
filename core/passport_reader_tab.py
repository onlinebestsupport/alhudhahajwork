"""Admin Passport Reader tab. OCR results are review-first and read-only."""
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
from core.passport_reader import (
    scan_travelers, read_folder, discover_files_in_folder,
    strip_mrz_text,
)
from core.runtime_logging import log_event, log_exception

_MRZ_LINE_RE = re.compile(r"^[A-Z0-9<]{30,}$")
_STATUS_PDF = {"MRZ_OK": "OK", "VALIDATED": "OK",
               "REVIEW": "REVIEW", "ERROR": "ERROR", "NO SCAN": "NO SCAN"}
_STATUS_COLOR = {
    "MRZ_OK": "#166534", "VALIDATED": "#166534",
    "REVIEW": "#b45309", "ERROR": "#b91c1c",
    "NO SCAN": "#b91c1c",
}

_SUBTAB_ITEMS = [
    ("reader", "📁 Mixed Files"),
    ("local", "💻 Local Folder"),
    ("results", "📊 Results & Downloads"),
]


def _scan_worker(traveler, data_dir, result_queue):
    try:
        result_queue.put({"ok": True,
                          "rows": scan_travelers([traveler], data_dir)})
    except Exception as ex:
        result_queue.put({"ok": False,
                          "error": f"{type(ex).__name__}: {ex}"})


def _folder_worker(folder, result_queue):
    try:
        result_queue.put({"ok": True, "rows": read_folder(folder)})
    except Exception as ex:
        result_queue.put({"ok": False,
                          "error": f"{type(ex).__name__}: {ex}"})


def _run_isolated(target, args, timeout_seconds):
    context_name = "spawn" if os.name == "nt" else "fork"
    context = multiprocessing.get_context(context_name)
    result_queue = context.Queue(maxsize=1)
    process = context.Process(target=target, args=(*args, result_queue))
    process.start()
    payload = None
    try:
        payload = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        pass
    process.join(5)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if payload is None:
            return [], f"OCR timeout after {timeout_seconds}s"
    if payload is None:
        return [], f"OCR worker exited with code {process.exitcode}"
    try:
        result_queue.close()
        result_queue.join_thread()
    except Exception:
        pass
    if not payload.get("ok"):
        return [], payload.get("error", "OCR worker failed")
    return payload.get("rows", []), ""


def _scan_one_isolated(traveler, data_dir, timeout_seconds=360):
    return _run_isolated(_scan_worker, (traveler, data_dir), timeout_seconds)


def _scan_folder_isolated(folder, timeout_seconds=600):
    return _run_isolated(_folder_worker, (folder,), timeout_seconds)


class PassportReaderTab:
    @staticmethod
    def _icon(name, fallback="DESCRIPTION"):
        icons = getattr(ft, "Icons", None)
        value = getattr(icons, name, None) if icons is not None else None
        if value is not None:
            return value
        return getattr(icons, fallback, "description") if icons is not None \
            else "description"

    def __init__(self, page: ft.Page, db, current_user):
        self.page, self.db, self.current_user = page, db, current_user
        log_event("PASSPORT_READER", "INIT_START", db=self.db)
        self.rows = []
        self.local_rows = []
        self.travelers = []
        self._traveler_by_id = {}
        self._scan_running = False
        self._local_scan_running = False
        self._active_subtab = "reader"
        self._subtab_buttons = {}
        self.subtab_content = None

        self.traveler_search = ft.TextField(
            label="Search traveler / passport / mobile",
            hint_text="Type a name, ID, passport number, or mobile",
            dense=True, on_change=self._filter_travelers)
        self.traveler_dropdown = ft.Dropdown(
            label="Traveler passport folder",
            hint_text="Select one traveler to read",
            options=[], dense=True, expand=True)
        self.traveler_dropdown.on_change = self._selected_traveler_changed
        self._load_traveler_choices()

        self.table = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, expand=True)
        self.local_table = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO,
                                      expand=True)
        self.status = ft.Text(
            "No scan run yet. Results are read-only until reviewed.",
            size=11, color="#475569")
        self.local_status = ft.Text(
            "Enter a folder path, click Verify Files, then Read Folder.",
            size=11, color="#475569")
        self.local_folder_path = ft.TextField(
            label="Folder path on server",
            hint_text="e.g. /app/data/passport_import or C:/passports",
            dense=True, expand=True)
        self.root = self._build()
        log_event("PASSPORT_READER", "INIT_COMPLETE", db=self.db)

    def build(self):
        return self.root

    def refresh(self):
        try:
            if self.rows:
                self._render_rows(self.rows, self.table)
            if self.local_rows:
                self._render_rows(self.local_rows, self.local_table)
        except Exception as ex:
            log_exception("PASSPORT_READER", "REFRESH_FAILED", ex, db=self.db)
        log_event("PASSPORT_READER", "REFRESH_VISIBLE_ONLY", db=self.db,
                  row_count=len(self.rows),
                  local_row_count=len(self.local_rows))

    def _status_update(self):
        try:
            self.status.update()
        except Exception:
            pass

    def _local_status_update(self):
        try:
            self.local_status.update()
        except Exception:
            pass

    def _load_traveler_choices(self):
        try:
            raw = self.db.get_travelers()
            self.travelers = [dict(row) for row in raw]
            self._traveler_by_id = {
                str(row.get("id", "")).strip(): row for row in self.travelers
                if str(row.get("id", "")).strip()}
            self._set_traveler_options(self.travelers)
            log_event("PASSPORT_READER", "TRAVELER_CHOICES_LOADED",
                      db=self.db, traveler_count=len(self.travelers),
                      by_id_count=len(self._traveler_by_id))
        except Exception as ex:
            log_exception("PASSPORT_READER", "TRAVELER_CHOICES_FAILED", ex,
                          db=self.db)

    def _traveler_label(self, row):
        traveler_id = str(row.get("id", "")).strip()
        name = " ".join(str(row.get(key, "") or "").strip()
                        for key in ("first_name", "last_name")).strip()
        passport = str(row.get("passport_no", "") or "").strip()
        return " · ".join(part for part in (name, passport, traveler_id)
                          if part) or traveler_id

    def _set_traveler_options(self, rows):
        self.traveler_dropdown.options = [
            ft.dropdown.Option(key=str(row.get("id", "")).strip(),
                               text=self._traveler_label(row))
            for row in rows if str(row.get("id", "")).strip()]
        try:
            self.traveler_dropdown.update()
        except Exception:
            pass

    def _filter_travelers(self, e=None):
        needle = str(self.traveler_search.value or "").strip().lower()
        rows = self.travelers if not needle else [
            row for row in self.travelers if needle in " ".join(
                str(row.get(key, "") or "") for key in
                ("id", "first_name", "last_name", "passport_no", "mobile")
            ).lower()]
        self._set_traveler_options(rows)
        if len(rows) == 1:
            only_id = str(rows[0].get("id", "")).strip()
            if only_id:
                self.traveler_dropdown.value = only_id
                try:
                    self.traveler_dropdown.update()
                except Exception:
                    pass
        log_event("PASSPORT_READER", "TRAVELER_FILTER", db=self.db,
                  query=needle, match_count=len(rows))

    def _selected_traveler_changed(self, e=None):
        val = ""
        try:
            if e is not None and hasattr(e, "control"):
                val = str(getattr(e.control, "value", "") or "")
        except Exception:
            pass
        if not val:
            val = str(self.traveler_dropdown.value or "")
        log_event("PASSPORT_READER", "TRAVELER_SELECTED", db=self.db,
                  traveler_id=val.strip())

    def _set_subtab(self, key):
        if self.subtab_content is None:
            return
        panels = {"results": getattr(self, "_results_panel", None),
                  "local": getattr(self, "_local_panel", None),
                  "reader": getattr(self, "_reader_panel", None)}
        if key not in panels or panels[key] is None:
            key = "reader"
        self._active_subtab = key
        try:
            self.subtab_content.content = panels[key]
            self.subtab_content.update()
        except Exception:
            pass
        self._restyle_subtab_buttons()
        log_event("PASSPORT_READER", "SUBTAB_SELECTED", db=self.db,
                  subtab=key)

    def _restyle_subtab_buttons(self):
        for k, btn in self._subtab_buttons.items():
            try:
                is_active = (k == self._active_subtab)
                btn.bgcolor = "#2563eb" if is_active else "#e2e8f0"
                if isinstance(btn.content, ft.Text):
                    btn.content.color = "#ffffff" if is_active else "#1e3a8a"
                btn.update()
            except Exception:
                pass

    def _button(self, label, icon, color, handler):
        return ft.Button(
            content=ft.Row([
                ft.Icon(icon, size=15, color="#ffffff"),
                ft.Text(label, size=11, color="#ffffff"),
            ], spacing=5, tight=True),
            on_click=handler, height=38, bgcolor=color)

    def _build(self):
        log_event("PASSPORT_READER", "BUILD_START", db=self.db)

        header = ft.Text("🛂 Passport Reader", size=18,
                         weight=ft.FontWeight.BOLD, color="#1e3a8a")
        description = ft.Text(
            "Mixed Files mode reads every PDF, JPEG, and PNG in the selected "
            "traveler folder as one ordered passport-page set. Verify all OCR "
            "against the original scan.", size=11, color="#64748b")
        selector_row = ft.ResponsiveRow([
            ft.Container(content=self.traveler_search,
                         col={"xs": 12, "md": 5}),
            ft.Container(content=self.traveler_dropdown,
                         col={"xs": 12, "md": 7}),
        ], spacing=8, run_spacing=8)

        self._reader_panel = ft.Column([
            description,
            selector_row,
            ft.Row([
                self._button("Read Selected",
                             self._icon("DOCUMENT_SCANNER"),
                             "#2563eb", self.scan),
                self._button("Read All", self._icon("FOLDER_OPEN"),
                             "#475569",
                             lambda e: self.scan(e, all_travelers=True)),
                self._button("Refresh", self._icon("REFRESH", "SYNC"),
                             "#64748b", lambda e: self.refresh()),
                self._button("Clear", self._icon("DELETE", "CLEAR"),
                             "#b91c1c", self._clear_reader),
            ], wrap=True, spacing=6),
        ], spacing=8, scroll=ft.ScrollMode.AUTO)

        self._local_panel = self._build_local_panel()

        self._results_panel = ft.Column([
            ft.Row([
                self._button("CSV", self._icon("DOWNLOAD"), "#0f766e",
                             lambda e: self.export("csv")),
                self._button("Excel",
                             self._icon("TABLE_VIEW", "GRID_VIEW"),
                             "#15803d", lambda e: self.export("xlsx")),
                self._button("PDF",
                             self._icon("PICTURE_AS_PDF", "DESCRIPTION"),
                             "#b91c1c", lambda e: self.export("pdf")),
            ], wrap=True, spacing=6),
            self.status,
            ft.Container(content=self.table, height=360,
                         bgcolor="#ffffff",
                         border=ft.Border.all(1, "#cbd5e1"),
                         padding=6),
        ], spacing=8, scroll=ft.ScrollMode.AUTO)

        for key, label in _SUBTAB_ITEMS:
            chip = ft.Container(
                content=ft.Text(label, size=12, color="#1e3a8a",
                                weight=ft.FontWeight.BOLD),
                on_click=lambda e, k=key: self._set_subtab(k),
                bgcolor="#e2e8f0",
                border_radius=6,
                padding=8,
                data=key,
            )
            self._subtab_buttons[key] = chip
        subtab_row = ft.Row(list(self._subtab_buttons.values()),
                            wrap=True, spacing=6)

        self.subtab_content = ft.Container(content=self._reader_panel,
                                            expand=True)
        self._active_subtab = "reader"
        self._restyle_subtab_buttons()

        root = ft.Container(content=ft.Column([
            ft.Row([header], wrap=True),
            subtab_row,
            self.subtab_content,
        ], spacing=8, scroll=ft.ScrollMode.AUTO),
            padding=12, bgcolor="#ffffff", expand=True)
        log_event("PASSPORT_READER", "BUILD_COMPLETE", db=self.db)
        return root

    def _build_local_panel(self):
        return ft.Column([
            ft.Text("Local Folder Reader — reads an arbitrary system folder.",
                    size=12, weight=ft.FontWeight.BOLD, color="#1e3a8a"),
            ft.Text(
                "Use this for non-Haj passports stored on the server or a "
                "mounted Windows share. Verifies every PDF/JPEG/PNG in the "
                "folder, then reads them all at once. Downloads below are "
                "separate from the traveler results.", size=11,
                color="#64748b"),
            ft.ResponsiveRow([
                ft.Container(content=self.local_folder_path,
                             col={"xs": 12, "md": 9}),
                ft.Container(
                    content=self._button("Verify Files",
                                         self._icon("CHECK_CIRCLE", "CHECK"),
                                         "#0891b2",
                                         self.verify_local_folder),
                    col={"xs": 12, "md": 3}),
            ], spacing=8, run_spacing=8),
            ft.Row([
                self._button("Read Folder",
                             self._icon("DOCUMENT_SCANNER"),
                             "#2563eb", self.scan_local_folder),
                self._button("CSV", self._icon("DOWNLOAD"), "#0f766e",
                             lambda e: self.export("csv", local=True)),
                self._button("Excel",
                             self._icon("TABLE_VIEW", "GRID_VIEW"),
                             "#15803d",
                             lambda e: self.export("xlsx", local=True)),
                self._button("PDF",
                             self._icon("PICTURE_AS_PDF", "DESCRIPTION"),
                             "#b91c1c",
                             lambda e: self.export("pdf", local=True)),
                self._button("Clear", self._icon("DELETE", "CLEAR"),
                             "#b91c1c", self._clear_local),
            ], wrap=True, spacing=6),
            self.local_status,
            ft.Container(content=self.local_table, height=360,
                         bgcolor="#ffffff",
                         border=ft.Border.all(1, "#cbd5e1"),
                         padding=6),
        ], spacing=8, scroll=ft.ScrollMode.AUTO)

    def _extract_back_fields(self, row):
        """Extract specific fields from the back page OCR text based on structure."""
        text = strip_mrz_text(row.get("back_page_ocr") or row.get("page_2_ocr") or "")
        if not text:
            return "", "", "", ""
        
        # 1. Clean lines & remove OCR trailing noise (e.g., " ie", " AG", " os", " as,")
        lines = []
        for line in text.splitlines():
            line = line.strip()
            line = re.sub(r'\s+[A-Za-z]{1,3}[,=]?\s*$', '', line).strip()
            if line:
                lines.append(line)
                
        father, mother, spouse, address = "", "", "", ""
        
        # 2. Find the Address block start (usually has PIN, STREET, NAGAR, or starts with a number)
        addr_start_idx = -1
        for i, line in enumerate(lines):
            if ("PIN:" in line.upper() or 
                "STREET" in line.upper() or 
                "NAGAR" in line.upper() or
                "ROAD" in line.upper()):
                addr_start_idx = i
                break
            if re.match(r"^\d+[/A-Za-z]", line) and any(c.isalpha() for c in line):
                addr_start_idx = i
                break

        if addr_start_idx != -1:
            # 3. Extract address block
            addr_lines = []
            for line in lines[addr_start_idx:]:
                if "Old Passport" in line or "File No" in line or re.match(r"^MA\d+", line) or re.match(r"^[A-Z]\d{7}", line):
                    break
                addr_lines.append(line)
            address = ", ".join(addr_lines)
            
            # 4. Backtrack for Father, Mother, Spouse based on standard layout
            if addr_start_idx >= 3:
                spouse = lines[addr_start_idx - 1]
                mother = lines[addr_start_idx - 2]
                father = lines[addr_start_idx - 3]
            elif addr_start_idx >= 2:
                mother = lines[addr_start_idx - 1]
                father = lines[addr_start_idx - 2]
            elif addr_start_idx >= 1:
                father = lines[addr_start_idx - 1]

        # Clean up names if they accidentally caught the passport number
        if father and re.match(r"^[A-Z]\d{7}", father):
            father = ""
            
        return father, mother, spouse, address

    def _cell(self, value, width=130):
        return ft.Container(
            content=ft.Text(str(value or ""), size=10, selectable=True,
                            max_lines=3,
                            overflow=ft.TextOverflow.ELLIPSIS),
            width=width, padding=4)

    def _is_mobile(self):
        try:
            width = float(getattr(self.page, "width", 0) or 0)
        except (TypeError, ValueError):
            width = 0
        platform = str(getattr(self.page, "platform", "")).lower()
        return width == 0 or width < 700 or any(
            token in platform for token in ("ios", "android", "mobile"))

    def _mobile_card(self, row):
        status = str(row.get("status", ""))
        color = _STATUS_COLOR.get(status, "#b91c1c")
        father, mother, spouse, address = self._extract_back_fields(row)
        values = [
            ("Traveler", row.get("traveler_name") or row.get("traveler_id")),
            ("Passport", row.get("passport_no")),
            ("Name from MRZ",
             f"{row.get('surname', '')} {row.get('given_names', '')}".strip()),
            ("Date of birth", row.get("date_of_birth")),
            ("Expiry", row.get("passport_expiry")),
            ("Nationality", row.get("nationality")),
            ("Sex", row.get("sex")),
            ("Father's Name", father),
            ("Mother's Name", mother),
            ("Spouse", spouse),
            ("Address", address),
            ("Page 1 OCR text",
             strip_mrz_text(row.get("front_page_ocr")
                            or row.get("page_1_ocr") or "")),
            ("Page 2 OCR text",
             strip_mrz_text(row.get("back_page_ocr")
                            or row.get("page_2_ocr") or "")),
            ("Source file",
             Path(str(row.get("source_file", "")).replace("\\", "/")).name),
            ("Review reason", row.get("review_reason")),
        ]
        details = [
            ft.Row([
                ft.Container(content=ft.Text(label, size=10,
                                              weight=ft.FontWeight.BOLD),
                             width=105),
                ft.Text(
                    (str(value or "—")[:1800] + "…"
                     if label.endswith("OCR text")
                     and len(str(value or "")) > 1800
                     else str(value or "—")),
                    size=10, selectable=True, expand=True),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START)
            for label, value in values
        ]
        details.insert(0, ft.Text(status or "UNKNOWN", size=13,
                                  weight=ft.FontWeight.BOLD, color=color))
        return ft.Container(content=ft.Column(details, spacing=4),
                            bgcolor="#f8fafc",
                            border=ft.Border.all(1, "#cbd5e1"),
                            border_radius=8, padding=8)

    def _render_rows(self, rows, table):
        table.controls.clear()
        headers = ["Traveler", "Passport", "Surname", "Given Name", "DOB",
                   "Expiry", "Natl", "Sex", "Father", "Mother", "Spouse",
                   "Address", "Status", "Review"]
        if self._is_mobile():
            table.controls.append(ft.Text(
                "Results — scroll vertically; horizontal swipes are disabled.",
                size=10, color="#475569"))
            table.controls.extend(self._mobile_card(r) for r in rows)
            try:
                table.update()
            except Exception:
                pass
            return
        table.controls.append(ft.Row([self._cell(h, 135) for h in headers],
                                     wrap=False, scroll=ft.ScrollMode.AUTO))
        for r in rows:
            father, mother, spouse, address = self._extract_back_fields(r)
            values = [
                r.get("traveler_name") or r.get("traveler_id"),
                r.get("passport_no"),
                r.get("surname"),
                r.get("given_names"),
                r.get("date_of_birth"),
                r.get("passport_expiry"),
                r.get("nationality"),
                r.get("sex"),
                father,
                mother,
                spouse,
                address,
                r.get("status"),
                r.get("review_reason"),
            ]
            table.controls.append(ft.Row(
                [self._cell(v) for v in values],
                wrap=False, scroll=ft.ScrollMode.AUTO,
                vertical_alignment=ft.CrossAxisAlignment.START))
        try:
            table.update()
        except Exception:
            pass

    def _render(self):
        self._render_rows(self.rows, self.table)

    def scan(self, e=None, all_travelers=False):
        log_event("PASSPORT_READER", "SCAN_CLICKED", db=self.db,
                  all_travelers=all_travelers,
                  dropdown_value=str(self.traveler_dropdown.value or ""))
        if self._scan_running:
            self.status.value = "A passport scan is already running. Please wait."
            self._status_update()
            return
        selected_id = ""
        try:
            if e is not None and hasattr(e, "control"):
                ctrl_val = getattr(e.control, "value", None)
                if ctrl_val:
                    selected_id = str(ctrl_val).strip()
        except Exception:
            pass
        if not selected_id:
            selected_id = str(self.traveler_dropdown.value or "").strip()
        if not all_travelers and not selected_id:
            opts = getattr(self.traveler_dropdown, "options", []) or []
            if len(opts) == 1:
                selected_id = str(getattr(opts[0], "key", "") or "").strip()
                if selected_id:
                    self.traveler_dropdown.value = selected_id
        log_event("PASSPORT_READER", "SCAN_SELECTION_RESOLVED",
                  db=self.db, selected_id=selected_id,
                  all_travelers=all_travelers,
                  known_ids_count=len(self._traveler_by_id))
        if not all_travelers and not selected_id:
            self.status.value = "Select a traveler from the dropdown before reading."
            self._status_update()
            log_event("PASSPORT_READER", "SCAN_SKIPPED_NO_SELECTION",
                      db=self.db)
            return
        if all_travelers:
            targets = self.travelers
        else:
            traveler = self._traveler_by_id.get(selected_id)
            if not traveler:
                log_event("PASSPORT_READER", "SCAN_SELECTION_MISSING",
                          db=self.db, selected_id=selected_id,
                          sample_ids=list(self._traveler_by_id.keys())[:5])
                self.status.value = (f"Traveler '{selected_id}' not found. "
                                     "Click Refresh and try again.")
                self._status_update()
                return
            targets = [traveler]
        if not targets:
            self.status.value = "No travelers available to read."
            self._status_update()
            return
        self._scan_running = True
        self.status.value = (f"Reading {len(targets)} traveler passport "
                             "folder(s) in the background…")
        self._status_update()
        
        # Always switch to results so the user sees the progress
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

    async def _scan_background(self, targets):
        try:
            if len(targets) > 1:
                self.rows = []
            total = len(targets)
            no_file_count = 0
            for index, traveler in enumerate(targets, start=1):
                traveler_id = str(traveler.get("id", ""))
                rows, worker_error = await asyncio.to_thread(
                    _scan_one_isolated, traveler, self.db.data_dir)
                if worker_error:
                    rows = [{
                        "traveler_id": traveler_id,
                        "traveler_name": " ".join(
                            str(traveler.get(k, "") or "").strip()
                            for k in ("first_name", "last_name")).strip(),
                        "source_file": "", "status": "ERROR",
                        "review_required": True,
                        "review_reason": worker_error,
                    }]
                if len(targets) == 1 and rows:
                    self.rows = [r for r in self.rows
                                 if str(r.get("traveler_id", "")) != traveler_id]
                self.rows.extend(rows)
                if rows and rows[0].get("status") == "NO SCAN":
                    no_file_count += 1
                self.status.value = (
                    f"Reading passport records… {index}/{total} completed. "
                    f"{no_file_count} folder(s) have no passport files. "
                    f"{len(self.rows)} result(s) accumulated.")
                if index == 1 or index % 5 == 0 or index == total:
                    self._render()
                self._status_update()
                await asyncio.sleep(0)
            valid = sum(1 for r in self.rows
                        if r.get("status") in ("MRZ_OK", "VALIDATED"))
            review = sum(1 for r in self.rows
                         if r.get("status") == "REVIEW")
            errors = sum(1 for r in self.rows if r.get("status") == "ERROR")
            self.status.value = (
                f"Read {len(self.rows)} traveler record(s): {valid} MRZ-valid, "
                f"{review} require review, {errors} OCR errors, "
                f"{no_file_count} folder(s) with no passport files. "
                "No traveler CSV fields were changed.")
            self._render()
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

    def verify_local_folder(self, e=None):
        folder = str(self.local_folder_path.value or "").strip()
        if not folder:
            self.local_status.value = "Enter a folder path first."
            self._local_status_update()
            return
        try:
            files = discover_files_in_folder(folder)
        except Exception as ex:
            log_exception("PASSPORT_READER", "VERIFY_FOLDER_FAILED", ex,
                          db=self.db)
            self.local_status.value = f"Verify failed: {ex}"
            self._local_status_update()
            return
        if not files:
            self.local_status.value = (
                f"No supported PDF/JPEG/PNG files found in {folder}")
        else:
            lines = [f"Verified {len(files)} file(s) in {folder}:"]
            for p in files[:20]:
                try:
                    lines.append(
                        f"  • {p.name} ({p.stat().st_size // 1024} KB)")
                except OSError:
                    lines.append(f"  • {p.name} (unreadable)")
            if len(files) > 20:
                lines.append(f"  … and {len(files) - 20} more")
            self.local_status.value = "\n".join(lines)
        self._local_status_update()
        log_event("PASSPORT_READER", "VERIFY_LOCAL_FOLDER", db=self.db,
                  folder=folder, file_count=len(files))

    def scan_local_folder(self, e=None):
        if self._local_scan_running:
            self.local_status.value = ("A folder read is already running. "
                                       "Please wait.")
            self._local_status_update()
            return
        folder = str(self.local_folder_path.value or "").strip()
        if not folder:
            self.local_status.value = "Enter a folder path first."
            self._local_status_update()
            return
        self._local_scan_running = True
        self.local_status.value = f"Reading all files in {folder} …"
        self._local_status_update()
        log_event("PASSPORT_READER", "LOCAL_SCAN_START", db=self.db,
                  folder=folder)
        try:
            self.page.run_task(self._local_scan_background, folder)
        except Exception as ex:
            self._local_scan_running = False
            log_exception("PASSPORT_READER", "LOCAL_SCAN_QUEUE_FAILED", ex,
                          db=self.db)
            self.local_status.value = f"Folder scan could not start: {ex}"
            self._local_status_update()

    async def _local_scan_background(self, folder):
        try:
            rows, worker_error = await asyncio.to_thread(
                _scan_folder_isolated, folder)
            if worker_error:
                rows = [{
                    "traveler_id": f"local:{Path(folder).name}",
                    "traveler_name": f"Local: {Path(folder).name}",
                    "source_file": folder, "status": "ERROR",
                    "review_required": True, "review_reason": worker_error,
                }]
            self.local_rows = rows
            self._render_rows(self.local_rows, self.local_table)
            statuses = [r.get("status") for r in rows]
            valid = sum(1 for s in statuses if s in ("MRZ_OK", "VALIDATED"))
            review = sum(1 for s in statuses if s == "REVIEW")
            errors = sum(1 for s in statuses if s == "ERROR")
            no_scan = sum(1 for s in statuses if s == "NO SCAN")
            self.local_status.value = (
                f"Read {len(rows)} file set(s): {valid} MRZ-valid, "
                f"{review} review, {errors} errors, {no_scan} no-scan. "
                "Use CSV / Excel / PDF below to download.")
            self._local_status_update()
            log_event("PASSPORT_READER", "LOCAL_SCAN_SUCCESS", db=self.db,
                      folder=folder, row_count=len(rows),
                      validated=valid, review=review, errors=errors)
        except Exception as ex:
            traceback.print_exc()
            log_exception("PASSPORT_READER", "LOCAL_SCAN_FAILED", ex,
                          db=self.db)
            self.local_status.value = f"Folder scan failed: {ex}"
            self._local_status_update()
        finally:
            self._local_scan_running = False

    def _clear_reader(self, e=None):
        self.rows = []
        self.table.controls.clear()
        try:
            self.table.update()
        except Exception:
            pass
        self.status.value = "Results cleared."
        self._status_update()

    def _clear_local(self, e=None):
        self.local_rows = []
        self.local_table.controls.clear()
        try:
            self.local_table.update()
        except Exception:
            pass
        self.local_status.value = "Local folder results cleared."
        self._local_status_update()

    def _export_fields(self):
        return ["traveler_id", "traveler_name", "passport_no", "surname",
                "given_names", "nationality", "date_of_birth", "sex",
                "passport_expiry", "issuing_country", "pages_read",
                "front_status", "back_status",
                "page_1_status", "last_page_status",
                "status", "mrz_valid", "review_required", "review_reason",
                "source_file", "source_files",
                "front_page_ocr", "back_page_ocr",
                "page_1_ocr", "page_2_ocr", "last_page_ocr", "page_ocr"]

    def export(self, kind, local=False):
        log_event("PASSPORT_READER", "EXPORT_START", db=self.db,
                  kind=kind, local=local)
        rows = self.local_rows if local else self.rows
        if not rows:
            log_event("PASSPORT_READER", "EXPORT_SKIPPED_NO_ROWS", db=self.db,
                      kind=kind, local=local)
            (self.local_status if local else self.status).value = \
                "Nothing to export — run a scan first."
            (self._local_status_update if local else self._status_update)()
            return
        out = Path(self.db.data_dir) / "exports" / (
            "passport_reader_local" if local else "passport_reader")
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = "passport_reader_local" if local else "passport_reader"
        path = out / f"{prefix}_{stamp}.{kind}"
        fields = self._export_fields()
        try:
            if kind == "csv":
                with path.open("w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=fields,
                                            extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
            elif kind == "xlsx":
                from openpyxl import Workbook
                from openpyxl.styles import Font, PatternFill, Alignment
                wb = Workbook()
                ws = wb.active
                ws.title = "Passport Reader"
                ws.append(fields)
                for c in ws[1]:
                    c.font = Font(bold=True, color="FFFFFF")
                    c.fill = PatternFill("solid", fgColor="1E3A8A")
                    c.alignment = Alignment(wrap_text=True)
                for row in rows:
                    ws.append([row.get(k, "") for k in fields])
                ws.freeze_panes = "A2"
                for col in ws.columns:
                    ws.column_dimensions[col[0].column_letter].width = \
                        min(42,
                            max(14,
                                max(len(str(x.value or "")) for x in col) + 2))
                wb.save(path)
            else:
                self._export_pdf(rows, path)
            url = send_file_to_user(
                self.page, str(path),
                f"Passport Reader {kind.upper()}"
                + (" (Local Folder)" if local else ""))
            if url:
                self.page.launch_url(url)
            msg = f"Exported {len(rows)} rows to {path.name}."
            if local:
                self.local_status.value = msg
                self._local_status_update()
            else:
                self.status.value = msg
                self._status_update()
            log_event("PASSPORT_READER", "EXPORT_SUCCESS", db=self.db,
                      kind=kind, local=local, row_count=len(rows),
                      path=str(path))
        except Exception as ex:
            traceback.print_exc()
            log_exception("PASSPORT_READER", "EXPORT_FAILED", ex, db=self.db,
                          kind=kind, local=local, path=str(path))
            (self.local_status if local else self.status).value = \
                f"Export failed: {ex}"
            (self._local_status_update if local else self._status_update)()

    def _export_pdf(self, rows, path):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, LongTable, TableStyle, Paragraph, Spacer,
            PageBreak,
        )
        styles = getSampleStyleSheet()
        page_w, _ = landscape(A4)
        usable = page_w - 16 * mm
        doc = SimpleDocTemplate(str(path), pagesize=landscape(A4),
                                leftMargin=8 * mm, rightMargin=8 * mm,
                                topMargin=8 * mm, bottomMargin=8 * mm)
        
        # Explicit columns for the summary table
        visible = ["traveler_name", "passport_no", "surname", "given_names",
                   "date_of_birth", "passport_expiry", "nationality", "sex",
                   "father", "mother", "spouse", "address", "status"]
        labels = ["Traveler", "Passport", "Surname", "Given Name(s)",
                  "DOB", "Expiry", "Natl", "Sex",
                  "Father", "Mother", "Spouse", "Address", "Status"]
                  
        # Fixed weights to ensure headers don't break mid-word and text fits
        weights = [10, 8, 8, 10, 8, 8, 6, 4, 10, 10, 8, 15, 5] 
        total_weight = sum(weights)
        col_widths = [(w / total_weight) * usable for w in weights]

        data = []
        for r in rows:
            father, mother, spouse, address = self._extract_back_fields(r)
            row_data = [
                r.get("traveler_name") or r.get("traveler_id"),
                r.get("passport_no"),
                r.get("surname"),
                r.get("given_names"),
                r.get("date_of_birth"),
                r.get("passport_expiry"),
                r.get("nationality"),
                r.get("sex"),
                father,
                mother,
                spouse,
                address,
                _STATUS_PDF.get(str(r.get("status", "")), str(r.get("status", "")))
            ]
            data.append([Paragraph(xml_escape(str(x or "")), styles["BodyText"]) for x in row_data])

        header_row = [Paragraph(f"<b>{x}</b>", styles["BodyText"]) for x in labels]
            
        table = LongTable([header_row] + data, repeatRows=1, colWidths=col_widths)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("WORDWRAP", (0, 0), (-1, -1), True),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f8fafc")]),
        ]))
        
        story = [
            Paragraph("Passport Reader — Field Extraction Summary", styles["Title"]),
            Paragraph(
                "English OCR only. 'OK' means MRZ check digits and nationality passed, "
                "not that names are correct. Full OCR text is available on the detail "
                "pages below. Verify every value against the original passport scan.",
                styles["BodyText"]),
            Spacer(1, 4),
            table,
        ]

        # Keep the detailed pages for full OCR text review
        for r in rows:
            front_raw = (r.get("front_page_ocr")
                         or r.get("page_1_ocr") or "").strip()
            back_raw = (r.get("back_page_ocr")
                        or r.get("page_2_ocr")
                        or r.get("last_page_ocr") or "").strip()
            front = strip_mrz_text(front_raw)
            back = strip_mrz_text(back_raw)
            if not front and not back:
                continue
            story.append(PageBreak())
            title = xml_escape(
                str(r.get("traveler_name") or r.get("traveler_id")
                    or "Unknown traveler"))
            story.append(Paragraph(f"{title} — Full Text", styles["Heading2"]))
            if front:
                story.append(Paragraph("Page 1 OCR (Front)", styles["Heading3"]))
                story.append(Paragraph(
                    xml_escape(front).replace("\n", "<br/>"), styles["BodyText"]))
                story.append(Spacer(1, 8))
            if back:
                story.append(Paragraph("Page 2 OCR (Back)", styles["Heading3"]))
                story.append(Paragraph(
                    xml_escape(back).replace("\n", "<br/>"), styles["BodyText"]))

        doc.build(story)
