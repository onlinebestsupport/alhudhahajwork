# =================================================================================
# core/security.py — Security utilities
# =================================================================================
# v1.1 — Fixed CSP to allow Flet CanvasKit from gstatic.com
#
# SECTION INDEX
#   S1  Token generation
#   S2  Rate limiter (in-memory)
#   S3  Admin auth dependency
#   S4  Traveler auth dependency
#   S5  Security headers middleware
#   S6  CSV injection sanitizer
#   S7  Upload content validation (magic bytes)
#   S8  Input length validators
# =================================================================================

import os
import time
import hmac
import secrets
from collections import defaultdict
from typing import Optional

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


# =================================================================================
# S1 — TOKEN GENERATION
# =================================================================================
def generate_token(nbytes: int = 32) -> str:
    """Cryptographically secure token (256-bit by default)."""
    return secrets.token_hex(nbytes)


# =================================================================================
# S2 — RATE LIMITER
# =================================================================================
class RateLimiter:
    """In-memory sliding-window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits = defaultdict(list)

    def check(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]
        if len(self._hits[key]) >= self.max_requests:
            return False
        self._hits[key].append(now)
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


login_limiter = RateLimiter(max_requests=5, window_seconds=300)
upload_limiter = RateLimiter(max_requests=20, window_seconds=60)
api_limiter = RateLimiter(max_requests=120, window_seconds=60)


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =================================================================================
# S3 — ADMIN AUTH DEPENDENCY
# =================================================================================
async def require_admin(request: Request) -> None:
    """Requires a valid ADMIN_API_KEY (header or ?key= param)."""
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or len(expected) < 16:
        raise HTTPException(
            status_code=503,
            detail="Admin API not configured (ADMIN_API_KEY missing)")

    provided = ""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        provided = auth[7:].strip()
    if not provided:
        provided = request.query_params.get("key", "")

    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


# =================================================================================
# S4 — TRAVELER AUTH DEPENDENCY
# =================================================================================
async def require_traveler(request: Request) -> dict:
    token = request.cookies.get("alhudha_traveler_token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")

    from core.traveler_portal import verify_session
    session = verify_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    return session


# =================================================================================
# S5 — SECURITY HEADERS MIDDLEWARE
# =================================================================================
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers, allowing Flet CanvasKit from gstatic.com."""

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

        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://www.gstatic.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com; "
            "img-src 'self' data: blob: https:; "
            "media-src 'self' blob: https:; "
            "font-src 'self' data: "
            "https://fonts.gstatic.com https://fonts.googleapis.com; "
            "connect-src 'self' https://www.gstatic.com "
            "https://fonts.gstatic.com https://unpkg.com wss: ws:; "
            "worker-src 'self' blob:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        response.headers["Content-Security-Policy"] = csp
        return response


# =================================================================================
# S6 — CSV INJECTION SANITIZER
# =================================================================================
DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitize_csv_cell(value) -> str:
    if value is None:
        return ""
    s = str(value)
    if not s:
        return s
    if s[0] in DANGEROUS_CSV_PREFIXES:
        return "'" + s
    return s


def sanitize_row(row: dict) -> dict:
    return {k: sanitize_csv_cell(v) for k, v in row.items()}


# =================================================================================
# S7 — UPLOAD CONTENT VALIDATION (MAGIC BYTES)
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
    if not data or len(data) < 4:
        return None
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for sig, mime in _MAGIC_SIGNATURES:
        if data.startswith(sig):
            return mime
    return None


def validate_upload_content(data: bytes, allowed_mimes: set) -> bool:
    detected = sniff_mime(data)
    if detected is None:
        return False
    return detected in allowed_mimes


# =================================================================================
# S8 — INPUT LENGTH VALIDATORS
# =================================================================================
def validate_length(value: str, field_name: str,
                    min_len: int = 0, max_len: int = 1000) -> str:
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
    base = os.path.basename(str(name or ""))
    safe = "".join(c for c in base
                   if c.isalnum() or c in "._- ")
    safe = safe.strip(". ")
    if not safe:
        safe = "upload.bin"
    return safe[:max_len]