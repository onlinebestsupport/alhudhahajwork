# =================================================================================
# core/traveler_portal.py — Traveler authentication + data aggregation
# =================================================================================
# v1.3 — Fully DataFrame-safe. All DB calls wrapped in _to_list() / _to_dict()
#        so it works whether db.get_*() returns a list or a pandas DataFrame.
# =================================================================================

import os
import json
import secrets
import time
from datetime import datetime


# =================================================================================
# 0 — Helpers
# =================================================================================
def _safe_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v != v:
        return ""
    try:
        s = str(v).strip()
    except Exception:
        return ""
    if s.lower() in ("nan", "none", "nat", "null"):
        return ""
    return s


def _clean_number_string(value) -> str:
    """
    Strip trailing ".0" from numeric-looking strings.
    "1234.0"       → "1234"
    "9841186164.0" → "9841186164"
    1234.0         → "1234"
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if value != value:
            return ""
        if value.is_integer():
            return str(int(value))
        return str(value)
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat", "null"):
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    if "." in s:
        try:
            f = float(s)
            if f.is_integer():
                return str(int(f))
        except (ValueError, TypeError):
            pass
    return s


def _to_list(x) -> list:
    """
    Convert anything (list, DataFrame, None, dict, tuple) to a list of dicts.
    Safety net for when DB methods return DataFrames instead of lists.
    """
    if x is None:
        return []
    try:
        import pandas as pd
        if isinstance(x, pd.DataFrame):
            if x.empty:
                return []
            return x.to_dict(orient="records")
    except Exception:
        pass
    if isinstance(x, (list, tuple)):
        return list(x)
    if isinstance(x, dict):
        return [x]
    try:
        return list(x)
    except Exception:
        return []


def _to_dict(x) -> dict:
    """Convert anything to a dict (empty dict if conversion fails)."""
    if x is None:
        return {}
    if isinstance(x, dict):
        return x
    try:
        import pandas as pd
        if isinstance(x, pd.Series):
            return x.to_dict()
        if isinstance(x, pd.DataFrame):
            if x.empty:
                return {}
            return x.iloc[0].to_dict()
    except Exception:
        pass
    return {}


# =================================================================================
# 1 — Session storage (JSON file persisted to disk)
# =================================================================================
_SESSION_FILE = None
_SESSION_TTL = 8 * 3600  # 8 hours


def _session_file_path() -> str:
    global _SESSION_FILE
    if _SESSION_FILE is None:
        try:
            from core.helpers import get_app_base_path
            base = get_app_base_path()
        except Exception:
            base = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base, "data")
        os.makedirs(data_dir, exist_ok=True)
        _SESSION_FILE = os.path.join(data_dir, "traveler_sessions.json")
    return _SESSION_FILE


def _load_sessions() -> dict:
    path = _session_file_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        now = time.time()
        return {k: v for k, v in data.items()
                if v.get("expires_at", 0) > now}
    except Exception as e:
        print(f"[TRAVELER] session load failed: {e}")
        return {}


def _save_sessions(sessions: dict):
    try:
        path = _session_file_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2)
    except Exception as e:
        print(f"[TRAVELER] session save failed: {e}")


def create_session(traveler: dict) -> str:
    token = secrets.token_urlsafe(32)
    sessions = _load_sessions()
    sessions[token] = {
        "traveler_id": str(traveler.get("id", "")),
        "passport_no": _clean_number_string(traveler.get("passport_no", "")),
        "expires_at": time.time() + _SESSION_TTL,
    }
    _save_sessions(sessions)
    print(f"[TRAVELER] Session created for {traveler.get('id')}")
    return token


def verify_session(token: str):
    if not token:
        return None
    sessions = _load_sessions()
    s = sessions.get(token)
    if not s:
        return None
    if time.time() > s.get("expires_at", 0):
        sessions.pop(token, None)
        _save_sessions(sessions)
        return None
    return s


def destroy_session(token: str):
    if not token:
        return
    sessions = _load_sessions()
    if token in sessions:
        sessions.pop(token, None)
        _save_sessions(sessions)


def cleanup_expired():
    sessions = _load_sessions()
    _save_sessions(sessions)


# =================================================================================
# 2 — Authentication
# =================================================================================
def authenticate_traveler(db, passport_no, pin):
    """
    Verify passport_no + pin against travelers.
    Returns (traveler_dict, None) on success, (None, error_msg) on failure.
    """
    passport_no = _clean_number_string(passport_no).upper()
    pin = _clean_number_string(pin)

    if not passport_no:
        return None, "Passport number is required."
    if not pin:
        return None, "PIN is required."

    try:
        travelers = _to_list(db.get_travelers())
    except Exception as e:
        print(f"[TRAVELER] get_travelers failed: {e}")
        return None, "Server error. Please try again."

    match = None
    for t in travelers:
        stored_passport = _clean_number_string(
            t.get("passport_no", "")).upper()
        if stored_passport == passport_no:
            match = t
            break

    if not match:
        print(f"[TRAVELER] No match for passport='{passport_no}'")
        return None, "Invalid passport number or PIN."

    stored_pin = _clean_number_string(match.get("pin", ""))

    if not stored_pin or stored_pin == "0":
        return None, ("Your account is not yet activated. "
                      "Please contact the office to set your PIN.")

    if stored_pin != pin:
        print(f"[TRAVELER] Wrong PIN for passport='{passport_no}' "
              f"(stored='{stored_pin}', input='{pin}')")
        return None, "Invalid passport number or PIN."

    return dict(match), None


# =================================================================================
# 3 — Document paths
# =================================================================================
_DOC_SPECS = [
    ("photo",            "Photo",           ["photos", "photo", ""]),
    ("passport_scan",    "Passport Scan",   ["passports", "passport"]),
    ("aadhaar_scan",     "Aadhaar Card",    ["aadhaar", "aadhar"]),
    ("pan_scan",         "PAN Card",        ["pan"]),
    ("vaccine_scan",     "Vaccine Cert.",   ["vaccine", "vaccines"]),
]

_ALLOWED_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".pdf")


def _get_base_path():
    try:
        from core.helpers import get_app_base_path
        return get_app_base_path()
    except Exception:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_document_path(db, traveler, doc_key):
    base = _get_base_path()
    tid = _safe_str(traveler.get("id", ""))
    if not tid:
        return None

    folder = tid.replace("/", "_").replace("\\", "_")
    t_folder = os.path.join(base, "documents", folder)

    rel = _safe_str(traveler.get(doc_key, ""))
    if rel:
        rel = rel.replace("\\", os.sep).replace("/", os.sep)
        candidate = os.path.join(base, rel)
        if os.path.exists(candidate):
            return candidate

    spec = next((s for s in _DOC_SPECS if s[0] == doc_key), None)
    if not spec:
        return None

    subs = spec[2]
    for sub in subs:
        sub_dir = os.path.join(t_folder, sub) if sub else t_folder
        if not os.path.isdir(sub_dir):
            continue
        try:
            for fname in os.listdir(sub_dir):
                if fname.lower().endswith(_ALLOWED_EXTS):
                    return os.path.join(sub_dir, fname)
        except Exception:
            pass
    return None


def _doc_url_for(traveler_id: str, doc_key: str) -> str:
    return f"/api/traveler/document/{doc_key}"


# =================================================================================
# 4 — Build the JSON payload for the portal
# =================================================================================
_HIDDEN_FIELDS = {
    "pin",
    "medical_notes",
    "extra_fields",
}


def _f(v, default=0.0):
    try:
        x = float(v)
        if x != x:
            return default
        return x
    except (TypeError, ValueError):
        return default


def _fmt_date(s):
    if not s:
        return ""
    s = str(s)[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%d %b %Y")
        except Exception:
            continue
    return s


def _days_from_today(date_str):
    try:
        dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        delta = (dt - datetime.now()).days
        return delta
    except Exception:
        return None


def _build_personal_fields(traveler):
    t = traveler
    return [
        {"key": "id", "label": "Traveler ID", "value": _safe_str(t.get("id", ""))},
        {"key": "full_name", "label": "Full Name",
         "value": _safe_str(f"{t.get('first_name','')} {t.get('last_name','')}").strip()},
        {"key": "passport_name", "label": "Passport Name",
         "value": _safe_str(t.get("passport_name", ""))},
        {"key": "gender", "label": "Gender",
         "value": _safe_str(t.get("gender", ""))},
        {"key": "dob", "label": "Date of Birth",
         "value": _fmt_date(t.get("dob", ""))},
        {"key": "passport_no", "label": "Passport Number",
         "value": _clean_number_string(t.get("passport_no", ""))},
        {"key": "passport_issue_date", "label": "Passport Issue Date",
         "value": _fmt_date(t.get("passport_issue_date", ""))},
        {"key": "passport_expiry_date", "label": "Passport Expiry Date",
         "value": _fmt_date(t.get("passport_expiry_date", ""))},
        {"key": "passport_status", "label": "Passport Status",
         "value": _safe_str(t.get("passport_status", ""))},
        {"key": "place_of_birth", "label": "Place of Birth",
         "value": _safe_str(t.get("place_of_birth", ""))},
        {"key": "place_of_issue", "label": "Place of Issue",
         "value": _safe_str(t.get("place_of_issue", ""))},
        {"key": "mobile", "label": "Mobile",
         "value": _clean_number_string(t.get("mobile", ""))},
        {"key": "email", "label": "Email",
         "value": _safe_str(t.get("email", ""))},
        {"key": "aadhaar", "label": "Aadhaar Number",
         "value": _clean_number_string(t.get("aadhaar", ""))},
        {"key": "pan", "label": "PAN Number",
         "value": _safe_str(t.get("pan", ""))},
        {"key": "aadhaar_pan_linked", "label": "Aadhaar-PAN Linked",
         "value": _safe_str(t.get("aadhaar_pan_linked", ""))},
        {"key": "vaccine_status", "label": "Vaccine Status",
         "value": _safe_str(t.get("vaccine_status", ""))},
        {"key": "wheelchair", "label": "Wheelchair",
         "value": _safe_str(t.get("wheelchair", ""))},
        {"key": "father_name", "label": "Father's Name",
         "value": _safe_str(t.get("father_name", ""))},
        {"key": "mother_name", "label": "Mother's Name",
         "value": _safe_str(t.get("mother_name", ""))},
        {"key": "spouse_name", "label": "Spouse Name",
         "value": _safe_str(t.get("spouse_name", ""))},
        {"key": "passport_address", "label": "Passport Address",
         "value": _safe_str(t.get("passport_address", ""))},
        {"key": "mailing_address", "label": "Mailing Address",
         "value": _safe_str(t.get("mailing_address", ""))},
        {"key": "emergency_contact", "label": "Emergency Contact",
         "value": _safe_str(t.get("emergency_contact", ""))},
        {"key": "emergency_phone", "label": "Emergency Phone",
         "value": _clean_number_string(t.get("emergency_phone", ""))},
        {"key": "file_reference", "label": "File Reference",
         "value": _safe_str(t.get("file_reference", ""))},
        {"key": "registration_date", "label": "Registration Date",
         "value": _fmt_date(t.get("registration_date", ""))},
        {"key": "expected_return_date", "label": "Expected Return Date",
         "value": _fmt_date(t.get("expected_return_date", ""))},
        {"key": "status", "label": "Status",
         "value": _safe_str(t.get("status", ""))},
    ]


def _build_batch_fields(batch):
    if not batch:
        return []
    return [
        {"key": "batch_name", "label": "Batch Name",
         "value": _safe_str(batch.get("batch_name", ""))},
        {"key": "tour_type_name", "label": "Tour Type",
         "value": _safe_str(batch.get("tour_type_name", ""))},
        {"key": "year", "label": "Year",
         "value": _safe_str(batch.get("year", ""))},
        {"key": "departure_date", "label": "Departure Date",
         "value": _fmt_date(batch.get("departure_date", ""))},
        {"key": "return_date", "label": "Return Date",
         "value": _fmt_date(batch.get("return_date", ""))},
        {"key": "price", "label": "Package Price",
         "value": batch.get("price", 0), "is_currency": True},
        {"key": "status", "label": "Status",
         "value": _safe_str(batch.get("status", ""))},
    ]


def build_traveler_view(db, traveler: dict) -> dict:
    """
    Aggregate everything the portal shows for a traveler.
    Fully DataFrame-safe.
    """
    tid = _safe_str(traveler.get("id", ""))

    # ---------- 1. Sanitised profile ----------
    profile = {}
    for k, v in traveler.items():
        if k in _HIDDEN_FIELDS:
            continue
        if k in ("passport_no", "mobile", "aadhaar", "emergency_phone"):
            v = _clean_number_string(v)
        profile[k] = v

    fn = _safe_str(traveler.get("first_name", ""))
    ln = _safe_str(traveler.get("last_name", ""))
    profile["full_name"] = (f"{fn} {ln}").strip() or "Traveler"

    # ---------- 2. Batch info ----------
    batch = None
    bid = _safe_str(traveler.get("batch_id", ""))
    if bid:
        try:
            b = {}
            if hasattr(db, "get_batch_by_id"):
                b = _to_dict(db.get_batch_by_id(bid))
            if not b:
                for bb in _to_list(db.get_batches()):
                    if _safe_str(bb.get("id", "")) == bid:
                        b = bb
                        break
            if b:
                batch = {
                    "id": _safe_str(b.get("id", "")),
                    "batch_name": _safe_str(b.get("batch_name", "")),
                    "tour_type_name": _safe_str(b.get("tour_type_name", "")),
                    "year": _safe_str(b.get("year", "")),
                    "departure_date": _safe_str(b.get("departure_date", "")),
                    "return_date": _safe_str(b.get("return_date", "")),
                    "price": _f(b.get("price", 0)),
                    "status": _safe_str(b.get("status", "")),
                    "departure_display": _fmt_date(b.get("departure_date", "")),
                    "return_display": _fmt_date(b.get("return_date", "")),
                    "days_to_departure": _days_from_today(
                        b.get("departure_date", "")),
                }
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[TRAVELER] batch lookup failed: {e}")

    # ---------- 3. Documents ----------
    documents = []
    for key, label, _subs in _DOC_SPECS:
        try:
            path = get_document_path(db, traveler, key)
        except Exception:
            path = None
        exists = bool(path)
        documents.append({
            "key": key,
            "label": label,
            "exists": exists,
            "filename": os.path.basename(path) if path else "",
            "url": _doc_url_for(tid, key) if exists else None,
            "is_image": bool(
                exists and path.lower().endswith(
                    (".jpg", ".jpeg", ".png", ".bmp", ".gif"))),
        })

    # ---------- 4. Payments ----------
    payments = []
    total_paid = 0.0
    payment_by_method = {}
    payment_by_month = {}

    try:
        raw_payments = _to_list(db.get_payments(tid)) if tid else []
        for p in raw_payments:
            amt = _f(p.get("amount", 0))
            total_paid += amt

            method = _safe_str(p.get("payment_method", "") or "Other")
            payment_by_method[method] = (
                payment_by_method.get(method, 0.0) + amt)

            date_str = _safe_str(p.get("payment_date", ""))[:10]
            month_key = date_str[:7] if len(date_str) >= 7 else "Unknown"
            payment_by_month[month_key] = (
                payment_by_month.get(month_key, 0.0) + amt)

            payments.append({
                "id": _safe_str(p.get("id", "")),
                "date": date_str,
                "date_display": _fmt_date(date_str),
                "amount": amt,
                "method": method,
                "transaction_id": _clean_number_string(
                    p.get("transaction_id", "")),
                "status": _safe_str(p.get("status", "completed")
                                    or "completed"),
                "receipt_no": _safe_str(p.get("receipt_no", "")),
                "notes": _safe_str(p.get("notes", "")),
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[TRAVELER] get_payments failed: {e}")

    payments.sort(key=lambda x: x.get("date", ""), reverse=True)

    # ---------- 5. Invoice ----------
    invoice = None
    invoice_line_items = []
    try:
        raw_invoices = _to_list(db.get_invoices(tid)) if tid else []
        if raw_invoices:
            raw_invoices = sorted(
                raw_invoices,
                key=lambda i: _safe_str(i.get("issue_date", "")),
                reverse=True)
            inv = raw_invoices[0]

            base = _f(inv.get("amount", 0))
            disc_amt = _f(inv.get("discount_amount", 0))
            disc_pct = _f(inv.get("discount_percentage", 0))
            taxable = _f(inv.get("taxable_value", 0))
            gst_pct = _f(inv.get("gst_percentage", 0))
            gst_amt = _f(inv.get("gst_amount", 0))
            tcs_pct = _f(inv.get("tcs_percentage", 0))
            tcs_amt = _f(inv.get("tcs_amount", 0))
            total_amt = _f(inv.get("total_amount", 0))
            rounded = _f(inv.get("rounded_total", 0))

            invoice_line_items = [
                {"label": "Base Amount",
                 "value": base, "is_currency": True, "tone": "normal"},
                {"label": f"Discount ({disc_pct:.2f}%)",
                 "value": -disc_amt, "is_currency": True, "tone": "danger"},
                {"label": "Taxable Value",
                 "value": taxable, "is_currency": True, "tone": "normal"},
                {"label": f"GST ({gst_pct}%)",
                 "value": gst_amt, "is_currency": True, "tone": "normal"},
                {"label": f"TCS ({tcs_pct}%)",
                 "value": tcs_amt, "is_currency": True, "tone": "normal"},
                {"label": "Total",
                 "value": rounded or total_amt,
                 "is_currency": True, "tone": "total"},
            ]

            invoice = {
                "invoice_no": _safe_str(inv.get("invoice_no", "")),
                "issue_date": _safe_str(inv.get("issue_date", "")),
                "issue_date_display": _fmt_date(inv.get("issue_date", "")),
                "due_date": _safe_str(inv.get("due_date", "")),
                "due_date_display": _fmt_date(inv.get("due_date", "")),
                "status": _safe_str(inv.get("status", "")),
                "base_amount": base,
                "discount_amount": disc_amt,
                "discount_percent": disc_pct,
                "taxable_value": taxable,
                "gst_percentage": gst_pct,
                "gst_amount": gst_amt,
                "tcs_percentage": tcs_pct,
                "tcs_amount": tcs_amt,
                "total_amount": total_amt,
                "rounded_total": rounded,
                "notes": _safe_str(inv.get("notes", "")),
            }
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[TRAVELER] get_invoices failed: {e}")

    # ---------- 6. Summary / KPIs ----------
    package_price = _f(batch.get("price", 0)) if batch else 0.0
    invoice_total = 0.0
    if invoice:
        invoice_total = _f(invoice.get("rounded_total",
                                       invoice.get("total_amount", 0)))

    pkg_pending = max(0.0, package_price - total_paid) if package_price > 0 else 0.0

    inv_pending = 0.0
    if invoice:
        if _safe_str(invoice.get("status", "")).lower() == "paid":
            inv_pending = 0.0
        else:
            inv_pending = max(0.0, invoice_total - total_paid)

    paid_pct = 0.0
    if package_price > 0:
        paid_pct = min(100.0, (total_paid / package_price) * 100.0)

    kpis = [
        {"key": "total_paid", "label": "Total Paid", "icon": "rupee-sign",
         "value": total_paid, "is_currency": True, "tone": "success",
         "sub": f"{len(payments)} payment(s)"},
        {"key": "package_price", "label": "Package Price",
         "icon": "box", "value": package_price, "is_currency": True,
         "tone": "info", "sub": "Excl. GST/TCS"},
        {"key": "package_pending", "label": "Package Pending",
         "icon": "hourglass-half", "value": pkg_pending,
         "is_currency": True,
         "tone": "success" if pkg_pending <= 0 else "warn",
         "sub": "Fully paid" if pkg_pending <= 0 else "Remaining"},
        {"key": "paid_percent", "label": "Paid %",
         "icon": "chart-line", "value": round(paid_pct, 1),
         "is_currency": False, "is_percent": True,
         "tone": "success" if paid_pct >= 100 else "info",
         "sub": "of package price"},
    ]
    if invoice:
        kpis.append({
            "key": "invoice_total", "label": "Invoice Total",
            "icon": "file-invoice", "value": invoice_total,
            "is_currency": True, "tone": "accent", "sub": "Incl. GST & TCS"
        })
        kpis.append({
            "key": "invoice_pending", "label": "Invoice Pending",
            "icon": "exclamation-triangle", "value": inv_pending,
            "is_currency": True,
            "tone": "success" if inv_pending <= 0 else "danger",
            "sub": "Settled" if inv_pending <= 0 else "Due"
        })

    summary = {
        "total_paid": total_paid,
        "package_price": package_price,
        "package_pending": pkg_pending,
        "invoice_total": invoice_total,
        "invoice_pending": inv_pending,
        "payment_count": len(payments),
        "paid_percent": round(paid_pct, 1),
        "payment_by_method": [
            {"method": k, "amount": v}
            for k, v in sorted(payment_by_method.items(),
                               key=lambda x: -x[1])
        ],
    }

    # ---------- 7. Assemble dynamic sections ----------
    return {
        "traveler": profile,
        "batch": batch,
        "batch_fields": _build_batch_fields(batch),
        "personal_fields": _build_personal_fields(traveler),
        "documents": documents,
        "payments": payments,
        "invoice": invoice,
        "invoice_line_items": invoice_line_items,
        "summary": summary,
        "kpis": kpis,
    }