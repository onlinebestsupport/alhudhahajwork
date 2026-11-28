"""Passport scan discovery, OCR, MRZ parsing, and export-row preparation."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps, ImageFilter

from core.helpers import get_app_base_path
from core.runtime_logging import log_event, log_exception

_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
_MRZ_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<"
_WEIGHT = (7, 3, 1)

_ISO3_CODES = {
    "AFG","ALB","DZA","ASM","AND","AGO","AIA","ATA","ATG","ARG","ARM","ABW",
    "AUS","AUT","AZE","BHS","BHR","BGD","BRB","BLR","BEL","BLZ","BEN","BMU",
    "BTN","BOL","BES","BIH","BWA","BVT","BRA","IOT","BRN","BGR","BFA","BDI",
    "CPV","KHM","CMR","CAN","CYM","CAF","TCD","CHL","CHN","CXR","CCK","COL",
    "COM","COG","COD","COK","CRI","CIV","HRV","CUB","CUW","CYP","CZE","DNK",
    "DJI","DMA","DOM","ECU","EGY","SLV","GNQ","ERI","EST","SWZ","ETH","FLK",
    "FRO","FJI","FIN","FRA","GUF","PYF","ATF","GAB","GMB","GEO","DEU","GHA",
    "GIB","GRC","GRL","GRD","GLP","GUM","GTM","GGY","GIN","GNB","GUY","HTI",
    "HMD","VAT","HND","HKG","HUN","ISL","IND","IDN","IRN","IRQ","IRL","IMN",
    "ISR","ITA","JAM","JPN","JEY","JOR","KAZ","KEN","KIR","PRK","KOR","KWT",
    "KGZ","LAO","LVA","LBN","LSO","LBR","LBY","LIE","LTU","LUX","MAC","MDG",
    "MWI","MYS","MDV","MLI","MLT","MHL","MTQ","MRT","MUS","MYT","MEX","FSM",
    "MDA","MCO","MNG","MNE","MSR","MAR","MOZ","MMR","NAM","NRU","NPL","NLD",
    "NCL","NZL","NIC","NER","NGA","NIU","NFK","MKD","MNP","NOR","OMN","PAK",
    "PLW","PSE","PAN","PNG","PRY","PER","PHL","PCN","POL","PRT","PRI","QAT",
    "REU","ROU","RUS","RWA","BLM","SHN","KNA","LCA","MAF","SPM","VCT","WSM",
    "SMR","STP","SAU","SEN","SRB","SYC","SLE","SGP","SXM","SVK","SVN","SLB",
    "SOM","ZAF","SGS","SSD","ESP","LKA","SDN","SUR","SJM","SWE","CHE","SYR",
    "TWN","TJK","TZA","THA","TLS","TGO","TKL","TON","TTO","TUN","TUR","TKM",
    "TCA","TUV","UGA","UKR","ARE","GBR","USA","UMI","URY","UZB","VUT","VEN",
    "VNM","VGB","VIR","WLF","ESH","YEM","ZMB","ZWE",
}

_MRZ_LINE_RE = re.compile(r"^[A-Z0-9<]{30,}$")

# Keywords to check for correct rotation
_KEYWORDS = [
    "EMIGRATION", "FATHER", "MOTHER", "ADDRESS", "PIN", "REPUBLIC", 
    "INDIA", "SURNAME", "BIRTH", "PASSPORT", "NATIONALITY", "GUARDIAN"
]


def _clean(value):
    return str(value or "").strip()


def _folder_id(traveler_id):
    return _clean(traveler_id).replace("/", "_").replace("\\", "_")


def _fix_country(code: str) -> str:
    if not code:
        return ""
    table = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B",
                           "2": "Z", "6": "G", "4": "A"})
    return code.upper().replace("<", "").translate(table)[:3]


def _clean_name(segment: str) -> str:
    if not segment:
        return ""
    seg = re.sub(r"<{1,}", "<<", segment)
    seg = re.sub(r"([A-Z])\1{3,}", r"\1", seg)
    return seg.strip("<")


def discover_passport_files(traveler: dict, base_path=None) -> list[Path]:
    base = Path(base_path or get_app_base_path()).resolve()
    if base.name == "data":
        docs = (base / "documents").resolve()
        legacy_docs = (base.parent / "documents").resolve()
    else:
        docs = (base / "data" / "documents").resolve()
        legacy_docs = (base / "documents").resolve()
    found = []
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
            for p in documents_root.glob(f"**/{token}/passports/*"):
                if p.is_file() and p.suffix.lower() in _EXTENSIONS:
                    found.append(p)
    unique, seen, seen_content = [], set(), set()
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
              base=str(base), documents=str(docs),
              legacy_documents=str(legacy_docs),
              file_count=len(unique),
              files=[str(path) for path in unique])
    return unique


def discover_files_in_folder(folder_path) -> list[Path]:
    folder = Path(_clean(folder_path)).expanduser()
    if not folder.is_dir():
        log_event("PASSPORT_READER", "LOCAL_FOLDER_MISSING",
                  folder=str(folder))
        return []
    found = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in _EXTENSIONS:
            continue
        try:
            p.resolve().stat()
            found.append(p.resolve())
        except OSError:
            continue
    log_event("PASSPORT_READER", "LOCAL_FOLDER_DISCOVERY",
              folder=str(folder), file_count=len(found),
              files=[str(p) for p in found])
    return found


def _check_digit(text: str) -> str:
    total = 0
    for i, ch in enumerate(text):
        if ch not in _MRZ_CHARS:
            return "?"
        value = int(ch) if ch.isdigit() else (0 if ch == "<" else ord(ch) - 55)
        total += value * _WEIGHT[i % 3]
    return str(total % 10)


def _valid_field(value: str, digit: str) -> bool:
    return bool(value) and digit.isdigit() and _check_digit(value) == digit


def _date(value: str) -> str:
    if not re.fullmatch(r"\d{6}", value or ""):
        return ""
    yy, mm, dd = int(value[:2]), value[2:4], value[4:]
    year = 2000 + yy if yy <= (datetime.now().year % 100 + 20) else 1900 + yy
    try:
        return datetime(year, int(mm), int(dd)).strftime("%d-%m-%Y")
    except ValueError:
        return ""


def _normalize_line(line):
    line = re.sub(r"[^A-Za-z0-9<]", "", line.upper())
    return line.replace(" ", "")


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
        raw_names = line1[5:44].split("<<", 1)
        surname = _clean_name(raw_names[0]).replace("<", " ").strip()
        given = _clean_name(raw_names[1] if len(raw_names) > 1 else "").replace("<", " ").strip()
        passport_no = line2[0:9].replace("<", "")
        passport_check = line2[9]
        nationality = _fix_country(line2[10:13])
        issuing_country = _fix_country(line1[2:5])
        dob, dob_check = line2[13:19], line2[19]
        sex = line2[20].replace("<", "X")
        expiry, expiry_check = line2[21:27], line2[27]
        personal, personal_check = line2[28:42], line2[42]
        checks = {
            "passport_no": _valid_field(passport_no, passport_check),
            "dob": _valid_field(dob, dob_check),
            "expiry": _valid_field(expiry, expiry_check),
            "composite": _valid_field(
                line2[:10] + line2[13:20] + line2[21:43], line2[43]),
            "nationality": nationality in _ISO3_CODES,
            "issuing_country": issuing_country in _ISO3_CODES,
            "nat_eq_issuing": (nationality == issuing_country),
            "names": bool(surname) and bool(given)
                     and not re.search(r"([A-Z])\1{3,}", surname + given),
        }
        valid = all(checks.values())
        parsed = {
            "document_code": line1[:2].replace("<", ""),
            "issuing_country": issuing_country,
            "surname": surname, "given_names": given,
            "passport_no": passport_no,
            "nationality": nationality,
            "date_of_birth": _date(dob),
            "sex": sex, "passport_expiry": _date(expiry),
            "personal_no": personal.replace("<", "").strip(),
            "mrz_valid": valid,
            "mrz_checks": "; ".join(k for k, v in checks.items() if v),
            "review_required": not valid,
            "review_reason": "" if valid else
                "MRZ check failed: "
                + ", ".join(k for k, v in checks.items() if not v),
            "mrz_raw": f"{line1}\n{line2}",
        }
        best = best or parsed
        if valid:
            return parsed
    return best


def _enhance_image(image):
    image = ImageOps.exif_transpose(image).convert("L")
    image = ImageOps.autocontrast(image)
    image = image.resize((int(image.width * 1.6), int(image.height * 1.6)))
    return image.filter(ImageFilter.SHARPEN)


def _run_ocr(img, pytesseract):
    enhanced = _enhance_image(img)
    try:
        full_text = pytesseract.image_to_string(
            enhanced, lang="eng", config="--oem 3 --psm 6", timeout=90)
    except Exception as ex:
        log_exception("PASSPORT_READER", "OCR_FULL_FAILED", ex)
        full_text = ""
    crop = enhanced.crop((0, int(enhanced.height * 0.60),
                          enhanced.width, enhanced.height))
    try:
        mrz_text = pytesseract.image_to_string(
            crop, lang="eng", timeout=90,
            config=("--oem 3 --psm 6 "
                    "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"),
        )
    except Exception as ex:
        log_exception("PASSPORT_READER", "OCR_MRZ_FAILED", ex)
        mrz_text = ""
    return f"{full_text}\n\n[MRZ OCR]\n{mrz_text}"


def _ocr_page_image(image) -> str:
    try:
        import pytesseract
    except ImportError as ex:
        raise RuntimeError(
            "OCR engine unavailable: install pytesseract and tesseract") from ex

    # 1. Try Tesseract OSD
    try:
        osd = pytesseract.image_to_osd(image)
        match = re.search(r"Rotate: (\d+)", osd)
        if match:
            angle = int(match.group(1))
            if angle == 90:
                image = image.rotate(-90, expand=True)
            elif angle == 180:
                image = image.rotate(180, expand=True)
            elif angle == 270:
                image = image.rotate(-270, expand=True)
    except Exception:
        pass

    # 2. Run OCR on the (hopefully corrected) image
    text = _run_ocr(image, pytesseract)
    
    # If we found English keywords (or a valid MRZ), it's upright!
    if any(k in text.upper() for k in _KEYWORDS) or re.search(r"^[A-Z0-9<]{30,}$", text, re.MULTILINE):
        return text

    # 3. Fallback: Try 180 degrees (upside down)
    text_180 = _run_ocr(image.rotate(180, expand=True), pytesseract)
    if any(k in text_180.upper() for k in _KEYWORDS) or re.search(r"^[A-Z0-9<]{30,}$", text_180, re.MULTILINE):
        return text_180

    # 4. Fallback: Try 90 degrees
    text_90 = _run_ocr(image.rotate(-90, expand=True), pytesseract)
    if any(k in text_90.upper() for k in _KEYWORDS) or re.search(r"^[A-Z0-9<]{30,}$", text_90, re.MULTILINE):
        return text_90

    # 5. Fallback: Try 270 degrees
    text_270 = _run_ocr(image.rotate(-270, expand=True), pytesseract)
    if any(k in text_270.upper() for k in _KEYWORDS) or re.search(r"^[A-Z0-9<]{30,}$", text_270, re.MULTILINE):
        return text_270

    # If none worked, return the one with the most text
    return max([text, text_180, text_90, text_270], key=len)


def _ocr_image(path: Path) -> str:
    with Image.open(path) as image:
        return _ocr_page_image(image)


def _pdf_page_count(path: Path) -> int:
    try:
        result = subprocess.run(["pdfinfo", str(path)], capture_output=True,
                                text=True, timeout=20, check=False)
        match = re.search(r"^Pages:\s*(\d+)", result.stdout, re.MULTILINE)
        return max(1, int(match.group(1))) if match else 1
    except Exception:
        return 1


def _ocr_pdf_pages(path: Path) -> list[tuple[str, str]]:
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as ex:
        raise RuntimeError(
            "PDF OCR dependencies unavailable: install pdf2image, pytesseract, tesseract") from ex
    count = _pdf_page_count(path)
    chunks = []
    for page_number in range(1, count + 1):
        pages = convert_from_path(str(path), dpi=150,
                                  first_page=page_number,
                                  last_page=page_number, thread_count=1)
        if not pages:
            continue
        page = pages[0]
        try:
            chunks.append((f"page_{page_number}", _ocr_page_image(page)))
        finally:
            page.close()
            pages.clear()
            del pages
    return chunks


def _ocr_mixed_files(paths: list[Path]) -> list[tuple[str, str]]:
    chunks, page_index = [], 0
    for source in paths:
        if source.suffix.lower() == ".pdf":
            source_chunks = _ocr_pdf_pages(source)
        else:
            source_chunks = [("image_1", _ocr_image(source))]
        for _, text in source_chunks:
            page_index += 1
            chunks.append((f"page_{page_index}", text))
    return chunks


def strip_mrz_text(text: str) -> str:
    if not text:
        return ""
    out, skipping = [], False
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("[MRZ OCR]"):
            skipping = True
            continue
        if skipping:
            if _MRZ_LINE_RE.match(s):
                continue
            skipping = False
        if _MRZ_LINE_RE.match(s):
            continue
        out.append(line)
    return "\n".join(out)


def read_passport(traveler: dict, path: Path, page_paths=None) -> dict:
    row = {
        "traveler_id": _clean(traveler.get("id")),
        "traveler_name": " ".join(
            x for x in [_clean(traveler.get("first_name")),
                        _clean(traveler.get("last_name"))] if x),
        "source_file": str(path), "source_files": str(path),
        "status": "ERROR", "review_required": True,
        "review_reason": "", "ocr_text": "", "mrz_valid": False,
        "pages_read": "",
        "front_status": "NOT READ", "back_status": "NOT READ",
        "front_page_ocr": "", "back_page_ocr": "",
        "page_1_status": "NOT READ", "last_page_status": "NOT READ",
        "page_1_ocr": "", "last_page_ocr": "", "page_2_ocr": "",
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
            front = page_texts[0][1][:6000]
            row["front_page_ocr"] = front
            row["front_status"] = "READ"
            row["page_1_ocr"] = front
            row["page_1_status"] = "READ"
            if len(page_texts) > 1:
                back = page_texts[1][1][:6000]
                row["back_page_ocr"] = back
                row["back_status"] = "READ"
                row["page_2_ocr"] = back
                row["last_page_ocr"] = page_texts[-1][1][:6000]
                row["last_page_status"] = "READ"
            else:
                row["back_status"] = "NOT READ"
            row["page_ocr"] = "\n\n".join(
                f"--- {label.upper()} ---\n{text[:6000]}"
                for label, text in page_texts
            )
        row["status"] = "MRZ_OK" if parsed.get("mrz_valid") else "REVIEW"
        if not parsed.get("mrz_valid"):
            row["review_required"] = True
        return row
    except Exception as ex:
        row["review_reason"] = str(ex)
        log_exception("PASSPORT_READER", "read", ex,
                      traveler_id=row["traveler_id"], file=path.name)
        return row


def scan_travelers(travelers: list[dict], data_dir=None) -> list[dict]:
    rows, found_count, missing_count = [], 0, 0
    for traveler in travelers:
        files = discover_passport_files(traveler, data_dir)
        if not files:
            missing_count += 1
            rows.append({
                "traveler_id": _clean(traveler.get("id")),
                "traveler_name": " ".join(
                    x for x in [_clean(traveler.get("first_name")),
                                _clean(traveler.get("last_name"))] if x),
                "source_file": "", "status": "NO SCAN",
                "review_required": True,
                "review_reason": "Passport PDF/JPEG not found",
                "mrz_valid": False,
            })
        else:
            found_count += 1
            rows.append(read_passport(traveler, files[0], files))
    log_event("PASSPORT_READER", "DISCOVERY_SUMMARY",
              traveler_count=len(travelers), found=found_count,
              missing=missing_count, data_dir=str(data_dir or ""))
    return rows


def read_folder(folder_path, file_paths=None) -> list[dict]:
    sources = file_paths if file_paths is not None else discover_files_in_folder(folder_path)
    folder = Path(_clean(folder_path)).expanduser()
    if not sources:
        return [{
            "traveler_id": f"local:{folder.name or 'folder'}",
            "traveler_name": f"Local: {folder.name or 'folder'}",
            "source_file": str(folder), "source_files": "",
            "status": "NO SCAN", "review_required": True,
            "review_reason": "No PDF/JPEG/PNG files found in folder",
            "mrz_valid": False, "pages_read": "",
            "front_status": "NOT READ", "back_status": "NOT READ",
            "front_page_ocr": "", "back_page_ocr": "",
            "page_1_status": "NOT READ", "last_page_status": "NOT READ",
            "page_1_ocr": "", "last_page_ocr": "", "page_2_ocr": "",
            "page_ocr": "",
        }]
    synthetic = {
        "id": f"local:{folder.name or 'folder'}",
        "first_name": "Local",
        "last_name": folder.name or "folder",
    }
    row = read_passport(synthetic, sources[0], sources)
    row["traveler_id"] = synthetic["id"]
    row["traveler_name"] = f"Local: {folder.name or 'folder'}"
    return [row]
