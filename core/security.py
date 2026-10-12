# =================================================================================
# core/security.py — Security utilities
# =================================================================================
# v1.0 — Rate limiting, auth, headers, upload validation, CSV sanitization
#
# SECTION INDEX
#   §1  Token generation
#   §2  Rate limiter (in-memory)
#   §3  Admin auth dependency
#   §4  Traveler auth dependency
#   §5  Security headers middleware
#   §6  CSV injection sanitizer
#   §7  Upload content validation (magic bytes)
#   §8  Input length validators
# =================================================================================

import os
import time
import hmac
import secrets
from collections import defaultdict
from typing import Optional

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


# =================================================================================
# §1 — TOKEN GENERATION
# =================================================================================
def generate_token(nbytes: int = 32) -> str:
    """
    Cryptographically secure token. 32 bytes = 64 hex chars = 256 bits.

    Use this INSTEAD of uuid.uuid4().hex[:12] (which is only 48 bits —
    brute-forceable in hours on modern hardware).
    """
    return secrets.token_hex(nbytes)


# =================================================================================
# §2 — RATE LIMITER (in-memory, sliding window)
# =================================================================================
class RateLimiter:
    """
    Simple in-memory sliding-window rate limiter.

    • Single-container use — for Railway single-instance, sufficient.
    • Not persistent across restarts — acceptable for login throttling.
    • Uses client IP as key.

    Usage:
        login_limiter = RateLimiter(max_requests=5, window_seconds=300)
        if not login_limiter.check(client_ip):
            raise HTTPException(429, "Too many attempts")
    """
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict = defaultdict(list)

    def check(self, key: str) -> bool:
        """True if allowed, False if over limit."""
        now = time.time()
        cutoff = now - self.window_seconds
        # Prune old hits
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]
        if len(self._hits[key]) >= self.max_requests:
            return False
        self._hits[key].append(now)
        return True

    def reset(self, key: str) -> None:
        """Clear history for a key (e.g., on successful login)."""
        self._hits.pop(key, None)


# Module-level limiters (shared across requests)
login_limiter = RateLimiter(max_requests=5, window_seconds=300)   # 5 per 5 min
upload_limiter = RateLimiter(max_requests=20, window_seconds=60)  # 20 per min
api_limiter = RateLimiter(max_requests=120, window_seconds=60)    # 120 per min


def client_ip(request: Request) -> str:
    """Best-effort client IP. Railway puts real IP in X-Forwarded-For."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =================================================================================
# §3 — ADMIN AUTH DEPENDENCY
# =================================================================================
async def require_admin(request: Request) -> None:
    """
    FastAPI dependency that requires a valid ADMIN_API_KEY.

    Setup:
        1. Set ADMIN_API_KEY env var in Railway (32+ random chars).
        2. Flet admin passes it when opening upload pages via ?key=...
        3. JS in those pages sends it as Authorization: Bearer <key>

    Raises 401 if missing/invalid, 503 if server misconfigured.
    """
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or len(expected) < 16:
        raise HTTPException(
            status_code=503,
            detail="Admin API not configured (ADMIN_API_KEY missing)")

    # Accept from header OR query param (for direct browser use)
    provided = ""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        provided = auth[7:].strip()
    if not provided:
        provided = request.query_params.get("key", "")

    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


# =================================================================================
# §4 — TRAVELER AUTH DEPENDENCY
# =================================================================================
async def require_traveler(request: Request) -> dict:
    """
    Validates the traveler session cookie. Returns the session dict.
    """
    token = request.cookies.get("alhudha_traveler_token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")

    from core.traveler_portal import verify_session
    session = verify_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    return session


# =================================================================================
# §5 — SECURITY HEADERS MIDDLEWARE
# =================================================================================
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds security headers to every response.

    CSP allows 'unsafe-inline' for scripts/styles because Flet needs them.
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()")
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains")
                response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://www.gstatic.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' "
                "https://fonts.googleapis.com; "
            "img-src 'self' data: blob: https:; "
            "media-src 'self' blob: https:; "
            "font-src 'self' data: https://fonts.gstatic.com "
                "https://fonts.googleapis.com; "
            "connect-src 'self' https://www.gstatic.com "
                "https://fonts.gstatic.com https://unpkg.com; "
            "worker-src 'self' blob:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        return response


# =================================================================================
# §6 — CSV INJECTION SANITIZER
# =================================================================================
DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitize_csv_cell(value) -> str:
    """
    Prevent CSV/Excel formula injection.

    Excel treats cells starting with = + - @ as formulas. If a traveler's
    name is "=cmd|'/C calc'!A0", opening the CSV in Excel executes it.

    Fix: prefix dangerous cells with a single quote.
    """
    if value is None:
        return ""
    s = str(value)
    if not s:
        return s
    if s[0] in DANGEROUS_CSV_PREFIXES:
        return "'" + s
    return s


def sanitize_row(row: dict) -> dict:
    """Sanitize every cell in a CSV row dict."""
    return {k: sanitize_csv_cell(v) for k, v in row.items()}


# =================================================================================
# §7 — UPLOAD CONTENT VALIDATION (MAGIC BYTES)
# =================================================================================
_MAGIC_SIGNATURES = [
    (b"\xff\xd8\xff",         "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n",    "image/png"),
    (b"GIF87a",               "image/gif"),
    (b"GIF89a",               "image/gif"),
    (b"BM",                   "image/bmp"),
    (b"%PDF",                 "application/pdf"),
    (b"\x00\x00\x00\x18ftyp", "video/mp4"),
    (b"\x00\x00\x00\x1cftyp", "video/mp4"),
    (b"\x00\x00\x00\x20ftyp", "video/mp4"),
    (b"\x1a\x45\xdf\xa3",     "video/webm"),
]


def sniff_mime(data: bytes) -> Optional[str]:
    """Detect MIME type from magic bytes. Returns MIME or None."""
    if not data or len(data) < 4:
        return None
    # WebP needs 12 bytes to verify
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for sig, mime in _MAGIC_SIGNATURES:
        if data.startswith(sig):
            return mime
    return None


def validate_upload_content(data: bytes, allowed_mimes: set) -> bool:
    """
    Verify file content matches an allowed MIME type.
    Prevents renaming evil.html to evil.jpg or fake.pdf to fake.png.
    """
    detected = sniff_mime(data)
    if detected is None:
        return False
    return detected in allowed_mimes


# =================================================================================
# §8 — INPUT LENGTH VALIDATORS
# =================================================================================
def validate_length(value: str, field_name: str,
                    min_len: int = 0, max_len: int = 1000) -> str:
    """
    Enforce length bounds. Raises 400 if violated.
    Returns stripped value.
    """
    if value is None:
        value = ""
    s = str(value).strip()
    if len(s) < min_len:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be at least {min_len} chars")
    if len(s) > max_len:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be at most {max_len} chars")
    return s


def safe_filename(name: str, max_len: int = 200) -> str:
    """Sanitize a filename: strip path, keep only safe chars."""
    import os as _os
    base = _os.path.basename(str(name or ""))
    # Keep alphanumerics, dot, dash, underscore
    safe = "".join(c for c in base
                   if c.isalnum() or c in "._- ")
    safe = safe.strip(". ")
    if not safe:
        safe = "upload.bin"
    return safe[:max_len]