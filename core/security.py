# core/security.py — production security helpers
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware


def generate_token(nbytes: int = 32) -> str:
    if not isinstance(nbytes, int) or nbytes < 16 or nbytes > 128:
        raise ValueError("Token size must be between 16 and 128 bytes")
    return secrets.token_urlsafe(nbytes)


class RateLimiter:
    """Thread-safe bounded sliding-window limiter for one process."""
    def __init__(self, max_requests: int, window_seconds: int, max_keys: int = 10000):
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1, int(window_seconds))
        self.max_keys = max(100, int(max_keys))
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        key = str(key or "unknown")[:300]
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            if len(self._hits) > self.max_keys:
                oldest = min(self._hits, key=lambda k: self._hits[k][-1] if self._hits[k] else now)
                self._hits.pop(oldest, None)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(str(key or "unknown"), None)


login_limiter = RateLimiter(5, 300)
upload_limiter = RateLimiter(20, 60)
api_limiter = RateLimiter(120, 60)


def client_ip(request: Request) -> str:
    """Use forwarded IP only when TRUST_PROXY_HEADERS is explicitly enabled."""
    if os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in {"1", "true", "yes"}:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()[:100]
    return (request.client.host if request.client else "unknown")[:100]


async def require_admin(request: Request) -> None:
    """Require ADMIN_API_KEY in an Authorization Bearer header."""
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or len(expected) < 32:
        raise HTTPException(status_code=503, detail="Admin API is not configured")
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    provided = auth[7:].strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def require_traveler(request: Request) -> dict:
    token = request.cookies.get("alhudha_traveler_token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")
    from core.traveler_portal import verify_session
    session = verify_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired")
    return session


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if request.url.scheme == "https" or os.getenv("FORCE_HSTS", "").lower() in {"1", "true", "yes"}:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://www.gstatic.com https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob: https:; media-src 'self' blob: https:; "
            "font-src 'self' data: https://fonts.gstatic.com https://fonts.googleapis.com; "
            "connect-src 'self' https://www.gstatic.com https://fonts.gstatic.com "
            "https://unpkg.com https://cdn.jsdelivr.net wss: ws:; "
            "worker-src 'self' blob: https://cdn.jsdelivr.net; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self';"
        )
        return response


DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitize_csv_cell(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s and s[0] in DANGEROUS_CSV_PREFIXES else s


def sanitize_row(row: dict) -> dict:
    return {k: sanitize_csv_cell(v) for k, v in row.items()}


_MAGIC_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"), (b"BM", "image/bmp"),
    (b"%PDF", "application/pdf"), (b"\x1a\x45\xdf\xa3", "video/webm"),
]


def sniff_mime(data: bytes) -> Optional[str]:
    if not data or len(data) < 4:
        return None
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for signature, mime in _MAGIC_SIGNATURES:
        if data.startswith(signature):
            return mime
    # ISO BMFF files commonly place ftyp after a variable-size first box.
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if len(data) >= 16 and data[8:12] == b"ftyp":
        return "video/mp4"
    return None


def validate_upload_content(data: bytes, allowed_mimes: set, max_bytes: int = 25 * 1024 * 1024) -> bool:
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0 or len(data) > max_bytes:
        return False
    return sniff_mime(bytes(data)) in set(allowed_mimes or set())


def validate_length(value: str, field_name: str, min_len: int = 0, max_len: int = 1000) -> str:
    s = "" if value is None else str(value).strip()
    if len(s) < min_len:
        raise HTTPException(status_code=400, detail=f"{field_name} must be at least {min_len} chars")
    if len(s) > max_len:
        raise HTTPException(status_code=400, detail=f"{field_name} must be at most {max_len} chars")
    return s


def safe_filename(name: str, max_len: int = 200) -> str:
    base = os.path.basename(str(name or ""))
    safe = "".join(c for c in base if c.isalnum() or c in "._- ").strip(". ")
    return (safe or "upload.bin")[:max_len]
