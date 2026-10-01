# =================================================================================
# core/traveler_portal.py — Traveler authentication + data aggregation
# =================================================================================
# v1.1 — Fix for PIN stored as "1234.0" in travelers.csv
#   • _clean_number_string() helper to strip .0 suffixes
#   • Applied to: pin, mobile, emergency_phone, aadhaar, passport_no
#   • authenticate_traveler() now normalises both stored and input PIN
# =================================================================================

import os
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
    " 1234 "       → "1234"
    None           → ""
    "abc"          → "abc"
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
    # Try to normalise "1234.00" too
    if "." in s:
        try:
            f = float(s)
            if f.is_integer():
                return str(int(f))
        except (ValueError, TypeError):
            pass
    return s


# =================================================================================
# 1 — Session storage (in-memory)
# =================================================================================
_SESSIONS = {}          # token → {traveler_id, passport_no, expires_at}
_SESSION_TTL = 8 * 3600  # 8 hours


def create_session(traveler: dict) -> str:
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = {
        "traveler_id": str(traveler.get("id", "")),
        "passport_no": _clean_number_string(traveler.get("passport_no", "")),
        "expires_at": time.time() + _SESSION_TTL,
    }
    print(f"[TRAVELER] Session created for {traveler.get('id')}")
    return token


def verify_session(token: str):
    if not token:
        return None
    s = _SESSIONS.get(token)
    if not s:
        return None
    if time.time() > s.get("expires_at", 0):
        _SESSIONS.pop(token, None)
        return None
    return s


def destroy_session(token: str):
    if token:
        _SESSIONS.pop(token, None)


def cleanup_expired():
    now = time.time()
    expired = [k for k, v in _SESSIONS.items()
               if v.get("expires_at", 0) < now]
    for k in expired:
        _SESSIONS.pop(k, None)


# =================================================================================
# 2 — Authentication
# =================================================================================
def authenticate_traveler(db, passport_no, pin):
    """
    Verify passport_no + pin against travelers.csv.
    Returns (traveler_dict, None) on success, (None, error_msg) on failure.

    Handles decimal-truncated values like "1234.0" that pandas may have
    written when saving. Normalises both the stored PIN and input PIN
    before comparison.
    """
    # ---- Normalise inputs ----
    passport_no = _clean_number_string(passport_no).upper()
    pin = _clean_number_string(pin)

    if not passport_no:
        return None, "Passport number is required."
    if not pin:
        return None, "PIN is required."

    try:
        travelers = db.get_travelers() or []
    except Exception as e:
        print(f"[TRAVELER] get_travelers failed: {e}")
        return None, "Server error. Please try again."

    # ---- Find traveler by passport number (case-insensitive) ----
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

    # ---- Clean stored PIN ----
    stored_pin = _clean_number_string(match.get("pin", ""))

    # ---- Validate PIN presence ----
    if not stored_pin or stored_pin == "0":
        return None, ("Your account is not yet activated. "
                      "Please contact the office to set your PIN.")

    # ---- Compare ----
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
    """
    Return the absolute file path for the given document key, or None.
    """
    base = _get_base_path()
    tid = _safe_str(traveler.get("id", ""))
    if not tid:
        return None

    folder = tid.replace("/", "_").replace("\\", "_")
    t_folder = os.path.join(base, "documents", folder)

    # Try the stored relative path first
    rel = _safe_str(traveler.get(doc_key, ""))
    if rel:
        rel = rel.replace("\\", os.sep).replace("/", os.sep)
        candidate = os.path.join(base, rel)
        if os.path.exists(candidate):
            return candidate

    # Fall back to scanning standard subfolders
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
    "pin",              # never send back
    "medical_notes",    # internal admin note
    "extra_fields",     # internal admin blob
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


def build_traveler_view(db, traveler: dict) -> dict:
    """
    Aggregate everything the portal shows for a traveler.
    """
    tid = _safe_str(traveler.get("id", ""))

    # ---------- 1. Sanitised profile ----------
    profile = {}
    for k, v in traveler.items():
        if k in _HIDDEN_FIELDS:
            continue
        # Clean numeric-looking strings for display
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
            b = db.get_batch_by_id(bid) if hasattr(db, "get_batch_by_id") else None
            if not b:
                for bb in (db.get_batches() or []):
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
                }
        except Exception as e:
            print(f"[TRAVELER] batch lookup failed: {e}")

    # ---------- 3. Documents ----------
    documents = []
    for key, label, _subs in _DOC_SPECS:
        path = get_document_path(db, traveler, key)
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
    try:
        raw_payments = db.get_payments(tid) if tid else []
        for p in (raw_payments or []):
            amt = _f(p.get("amount", 0))
            total_paid += amt
            payments.append({
                "id": _safe_str(p.get("id", "")),
                "date": _safe_str(p.get("payment_date", "")),
                "date_display": _fmt_date(p.get("payment_date", "")),
                "amount": amt,
                "method": _safe_str(p.get("payment_method", "") or "—"),
                "transaction_id": _clean_number_string(
                    p.get("transaction_id", "")),
                "status": _safe_str(p.get("status", "completed")
                                    or "completed"),
                "receipt_no": _safe_str(p.get("receipt_no", "")),
                "notes": _safe_str(p.get("notes", "")),
            })
    except Exception as e:
        print(f"[TRAVELER] get_payments failed: {e}")

    payments.sort(key=lambda x: x.get("date", ""), reverse=True)

    # ---------- 5. Invoice ----------
    invoice = None
    try:
        raw_invoices = db.get_invoices(tid) if tid else []
        if raw_invoices:
            raw_invoices = sorted(
                raw_invoices,
                key=lambda i: _safe_str(i.get("issue_date", "")),
                reverse=True)
            inv = raw_invoices[0]
            invoice = {
                "invoice_no": _safe_str(inv.get("invoice_no", "")),
                "issue_date": _safe_str(inv.get("issue_date", "")),
                "issue_date_display": _fmt_date(inv.get("issue_date", "")),
                "due_date": _safe_str(inv.get("due_date", "")),
                "due_date_display": _fmt_date(inv.get("due_date", "")),
                "status": _safe_str(inv.get("status", "")),
                "base_amount": _f(inv.get("amount", 0)),
                "discount_amount": _f(inv.get("discount_amount", 0)),
                "discount_percent": _f(inv.get("discount_percentage", 0)),
                "taxable_value": _f(inv.get("taxable_value", 0)),
                "gst_percentage": _f(inv.get("gst_percentage", 0)),
                "gst_amount": _f(inv.get("gst_amount", 0)),
                "tcs_percentage": _f(inv.get("tcs_percentage", 0)),
                "tcs_amount": _f(inv.get("tcs_amount", 0)),
                "total_amount": _f(inv.get("total_amount", 0)),
                "rounded_total": _f(inv.get("rounded_total", 0)),
                "notes": _safe_str(inv.get("notes", "")),
            }
    except Exception as e:
        print(f"[TRAVELER] get_invoices failed: {e}")

    # ---------- 6. Summary ----------
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

    summary = {
        "total_paid": total_paid,
        "package_price": package_price,
        "package_pending": pkg_pending,
        "invoice_total": invoice_total,
        "invoice_pending": inv_pending,
        "payment_count": len(payments),
    }

    # ---------- 7. Assemble ----------
    return {
        "traveler": profile,
        "batch": batch,
        "documents": documents,
        "payments": payments,
        "invoice": invoice,
        "summary": summary,
    }