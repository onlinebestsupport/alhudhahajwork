"""Passport scan discovery, OCR, MRZ parsing, and export-row preparation.

OCR is assistive only. Every row carries validation/review status; results must
be checked against the scan before ticket or visa use.
"""
# ===============================================================================
# SECTION 1 — PASSPORT READER ENGINE
# ===============================================================================
# Maintenance index
#   1.1  Constants and normalization helpers
#   1.2  Passport-file discovery
#   1.3  ICAO/MRZ parsing and validation
#   1.4  PDF/JPEG OCR and page handling
#   1.5  Traveler scan orchestration
#
# Safety rule: OCR is assistive only. Never issue a ticket or visa without
# comparing VALIDATED or REVIEW rows with the original passport scan.
# ===============================================================================
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps, ImageFilter

from core.helpers import get_app_base_path
from core.runtime_logging import log_event, log_exception

_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
_MRZ_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<"
_WEIGHT = (7, 3, 1)


# [1.1] _clean — normalize persisted values
def _clean(value):
    return str(value or "").strip()


# [1.2] _folder_id — derive safe traveler folder token
def _folder_id(traveler_id):
    return _clean(traveler_id).replace("/", "_").replace("\\", "_")


# [1.3] discover_passport_files — find PDF/JPEG scans
def discover_passport_files(traveler: dict, base_path=None) -> list[Path]:
    base = Path(base_path or get_app_base_path()).resolve()
    # HajDatabase.data_dir is the durable directory itself; otherwise callers
    # may pass the application root. Prefer data/documents on Railway.
    if base.name == "data":
        docs = (base / "documents").resolve()
        legacy_docs = (base.parent / "documents").resolve()
    else:
        docs = (base / "data" / "documents").resolve()
        legacy_docs = (base / "documents").resolve()
    found = []
    # Both columns exist in the persisted CSV. Older records use
    # passport_scan; newer document-management flows may use
    # passport_scan_path. Resolve Windows separators without writing/migrating.
    stored_values = {
        _clean(traveler.get("passport_scan")),
        _clean(traveler.get("passport_scan_path")),
    }
    for stored in stored_values - {""}:
        normalized = stored.replace("\\", "/")
        raw = Path(normalized)
        candidates = [raw] if raw.is_absolute() else [base / raw,
                                                        base.parent / raw]
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate.is_file() and candidate.suffix.lower() in _EXTENSIONS:
                found.append(candidate)

    # Folder layout used by Data Admin: documents/<traveler-token>/passports.
    tokens = {_folder_id(traveler.get("id"))}
    file_reference = _clean(traveler.get("file_reference"))
    if file_reference:
        tokens.add(_folder_id(file_reference))
    for token in {token for token in tokens if token}:
        for documents_root in (docs, legacy_docs):
            folder = documents_root / token / "passports"
            if folder.is_dir():
                found.extend(p for p in sorted(folder.rglob("*"))
                             if p.is_file() and p.suffix.lower() in _EXTENSIONS)
            # Compatibility for an additional nesting level used by older
            # imports; only exact token folder names are accepted.
            for p in documents_root.glob(f"**/{token}/passports/*"):
                if p.is_file() and p.suffix.lower() in _EXTENSIONS:
                    found.append(p)
    unique = []
    seen = set()
    seen_content = set()
    for p in found:
        try:
            p = p.resolve()
            identity = (p.name.lower(), p.stat().st_size)
            if p not in seen and identity not in seen_content:
                unique.append(p); seen.add(p); seen_content.add(identity)
        except OSError:
            pass
    log_event("PASSPORT_READER", "DISCOVERY_RESULT",
              traveler_id=_clean(traveler.get("id")),
              base=str(base), documents=str(docs), legacy_documents=str(legacy_docs),
              file_count=len(unique), files=[str(path) for path in unique])
    return unique


# [1.4] _check_digit — calculate ICAO MRZ check digit
def _check_digit(text: str) -> str:
    total = 0
    for i, ch in enumerate(text):
        if ch not in _MRZ_CHARS:
            return "?"
        value = int(ch) if ch.isdigit() else (0 if ch == "<" else ord(ch) - 55)
        total += value * _WEIGHT[i % 3]
    return str(total % 10)


# [1.5] _valid_field — validate one MRZ field
def _valid_field(value: str, digit: str) -> bool:
    return bool(value) and digit.isdigit() and _check_digit(value) == digit


# [1.6] _date — convert YYMMDD into display date
def _date(value: str) -> str:
    if not re.fullmatch(r"\d{6}", value or ""):
        return ""
    yy, mm, dd = int(value[:2]), value[2:4], value[4:]
    # Passport MRZ years are interpreted relative to the current year window.
    year = 2000 + yy if yy <= (datetime.now().year % 100 + 20) else 1900 + yy
    try:
        return datetime(year, int(mm), int(dd)).strftime("%d-%m-%Y")
    except ValueError:
        return ""


# [1.7] _normalize_line — clean OCR text for MRZ parsing
def _normalize_line(line):
    line = re.sub(r"[^A-Za-z0-9<]", "", line.upper())
    return line.replace(" ", "")


# [1.8] parse_mrz — parse and validate passport MRZ
def parse_mrz(text: str) -> dict:
    lines = [_normalize_line(x) for x in (text or "").splitlines()]
    lines = [x for x in lines if len(x) >= 30]
    candidates = []
    for i in range(len(lines) - 1):
        a, b = lines[i], lines[i + 1]
        if (a.startswith(("P<", "P0", "P1")) and len(a) >= 40
                and len(b) >= 40):
            candidates.append((a[:44].ljust(44, "<"), b[:44].ljust(44, "<")))
    if not candidates:
        return {"mrz_valid": False, "review_required": True,
                "review_reason": "MRZ not detected", "mrz_raw": ""}
    best = None
    for line1, line2 in reversed(candidates):
        surname_given = line1[5:44].split("<<", 1)
        surname = surname_given[0].replace("<", " ").strip()
        given = (surname_given[1] if len(surname_given) > 1 else "").replace("<", " ").strip()
        passport_no, passport_check = line2[0:9], line2[9]
        nationality = line2[10:13].replace("<", "")
        dob, dob_check = line2[13:19], line2[19]
        sex = line2[20].replace("<", "X")
        expiry, expiry_check = line2[21:27], line2[27]
        personal, personal_check = line2[28:42], line2[42]
        checks = {
            "passport_no": _valid_field(passport_no, passport_check),
            "dob": _valid_field(dob, dob_check),
            "expiry": _valid_field(expiry, expiry_check),
            "composite": _valid_field(line2[:10] + line2[13:20] + line2[21:43], line2[43]),
        }
        valid = all(checks.values())
        parsed = {
            "document_code": line1[:2].replace("<", ""),
            "issuing_country": line1[2:5].replace("<", ""),
            "surname": surname, "given_names": given,
            "passport_no": passport_no.replace("<", ""),
            "nationality": nationality, "date_of_birth": _date(dob),
            "sex": sex, "passport_expiry": _date(expiry),
            "personal_no": personal.replace("<", "").strip(),
            "mrz_valid": valid, "mrz_checks": "; ".join(k for k, v in checks.items() if v),
            "review_required": not valid,
            "review_reason": "" if valid else "MRZ check digit failed; verify scan",
            "mrz_raw": f"{line1}\n{line2}",
        }
        best = best or parsed
        if valid:
            return parsed
    return best


# [1.9] _enhance_image — prepare a passport image for OCR
def _enhance_image(image):
    image = ImageOps.exif_transpose(image).convert("L")
    image = ImageOps.autocontrast(image)
    image = image.resize((image.width * 3, image.height * 3))
    return image.filter(ImageFilter.SHARPEN)


# [1.10] _ocr_page_image — OCR full page and a high-precision MRZ crop
def _ocr_page_image(image) -> str:
    try:
        import pytesseract
    except ImportError as ex:
        raise RuntimeError("OCR engine unavailable: install pytesseract and tesseract") from ex
    enhanced = _enhance_image(image)
    full_text = pytesseract.image_to_string(enhanced, config="--oem 3 --psm 6")
    # The MRZ is normally at the bottom of the biographical page. A separate
    # whitelist pass reduces I/1, O/0, and punctuation substitutions.
    crop = enhanced.crop((0, int(enhanced.height * 0.70),
                          enhanced.width, enhanced.height))
    mrz_text = pytesseract.image_to_string(
        crop,
        config=("--oem 3 --psm 6 "
                "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"),
    )
    return f"{full_text}\n\n[MRZ OCR]\n{mrz_text}"


# [1.11] _ocr_image — OCR one JPEG/PNG scan
def _ocr_image(path: Path) -> str:
    with Image.open(path) as image:
        return _ocr_page_image(image)


# [1.12] _pdf_page_count — count PDF pages safely
def _pdf_page_count(path: Path) -> int:
    try:
        result = subprocess.run(["pdfinfo", str(path)], capture_output=True,
                                text=True, timeout=20, check=False)
        match = re.search(r"^Pages:\s*(\d+)", result.stdout, re.MULTILINE)
        return max(1, int(match.group(1))) if match else 1
    except Exception:
        return 1


# [1.13] _ocr_pdf_pages — OCR every PDF page separately
def _ocr_pdf_pages(path: Path) -> list[tuple[str, str]]:
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as ex:
        raise RuntimeError("PDF OCR dependencies unavailable: install pdf2image, pytesseract, tesseract") from ex
    count = _pdf_page_count(path)
    # Read every page so a barcode/address page between the biographical and
    # final page is never silently omitted.
    page_numbers = list(range(1, count + 1))
    chunks = []
    for page_number in page_numbers:
        pages = convert_from_path(str(path), dpi=300,
                                  first_page=page_number,
                                  last_page=page_number)
        if not pages:
            continue
        page = pages[0]
        chunks.append((f"page_{page_number}", _ocr_page_image(page)))
    return chunks


# [1.14] _ocr_mixed_files — OCR every PDF/JPEG/PNG in folder order
def _ocr_mixed_files(paths: list[Path]) -> list[tuple[str, str]]:
    """Return one sequential page record for every supported input file.

    A folder may contain a PDF plus separate JPEG/PNG passport pages. Treating
    only the first file as the source silently dropped those extra pages, so
    all files are now read into one ordered page set.
    """
    chunks = []
    page_index = 0
    for source in paths:
        if source.suffix.lower() == ".pdf":
            source_chunks = _ocr_pdf_pages(source)
        else:
            source_chunks = [("image_1", _ocr_image(source))]
        for _, text in source_chunks:
            page_index += 1
            chunks.append((f"page_{page_index}", text))
    return chunks


# [1.15] read_passport — build one review-first result row
def read_passport(traveler: dict, path: Path, page_paths=None) -> dict:
    row = {
        "traveler_id": _clean(traveler.get("id")),
        "traveler_name": " ".join(x for x in [_clean(traveler.get("first_name")), _clean(traveler.get("last_name"))] if x),
        "source_file": str(path), "source_files": str(path),
        "status": "ERROR", "review_required": True,
        "review_reason": "", "ocr_text": "", "mrz_valid": False,
        "pages_read": "", "page_1_status": "NOT READ",
        "last_page_status": "NOT READ", "page_1_ocr": "",
        "last_page_ocr": "",
        "page_ocr": "",
    }
    try:
        sources = page_paths or [path]
        page_texts = _ocr_mixed_files(sources)
        row["source_files"] = "\n".join(str(source) for source in sources)
        text = "\n".join(text for _, text in page_texts)
        parsed = parse_mrz(text)
        row.update(parsed)
        row["ocr_text"] = text[:12000]
        row["pages_read"] = ", ".join(label for label, _ in page_texts)
        if page_texts:
            row["page_1_ocr"] = page_texts[0][1][:6000]
            row["page_1_status"] = "READ"
            row["last_page_ocr"] = page_texts[-1][1][:6000]
            row["last_page_status"] = "READ"
            row["page_ocr"] = "\n\n".join(
                f"--- {label.upper()} ---\n{text[:6000]}"
                for label, text in page_texts
            )
        row["status"] = "VALIDATED" if parsed.get("mrz_valid") else "REVIEW"
        if not parsed.get("mrz_valid"):
            row["review_required"] = True
        return row
    except Exception as ex:
        row["review_reason"] = str(ex)
        log_exception("PASSPORT_READER", "read", ex, traveler_id=row["traveler_id"], file=path.name)
        return row


# [1.14] scan_travelers — scan every traveler without database writes
def scan_travelers(travelers: list[dict], data_dir=None) -> list[dict]:
    rows = []
    found_count = 0
    missing_count = 0
    for traveler in travelers:
        files = discover_passport_files(traveler, data_dir)
        if not files:
            missing_count += 1
            rows.append({
                "traveler_id": _clean(traveler.get("id")),
                "traveler_name": " ".join(x for x in [_clean(traveler.get("first_name")), _clean(traveler.get("last_name"))] if x),
                "source_file": "", "status": "NO SCAN", "review_required": True,
                "review_reason": "Passport PDF/JPEG not found", "mrz_valid": False,
            })
        else:
            found_count += 1
            # The first path is retained as the primary source label, while
            # every PDF/JPEG/PNG discovered in the folder is OCR'd together.
            rows.append(read_passport(traveler, files[0], files))
    log_event("PASSPORT_READER", "DISCOVERY_SUMMARY",
              traveler_count=len(travelers), found=found_count,
              missing=missing_count, data_dir=str(data_dir or ""))
    return rows