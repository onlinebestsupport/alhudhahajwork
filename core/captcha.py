# =================================================================================
# core/captcha.py — Self-hosted Math CAPTCHA
# =================================================================================
# No external dependencies. Works on:
#   • Flet admin portal (server-rendered)
#   • HTML traveler portal (via API)
# =================================================================================

import random
import time
import threading
from typing import Optional


_CAPTCHA_STORE = {}
_STORE_LOCK = threading.Lock()

CAPTCHA_TTL_SECONDS = 300      # 5 minutes
MAX_ATTEMPTS = 3


def _new_math_pair():
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    op = random.choice(["+", "-", "×"])
    if op == "-" and a < b:
        a, b = b, a
    if op == "+":
        answer = a + b
    elif op == "-":
        answer = a - b
    else:  # ×
        a = random.randint(2, 9)
        b = random.randint(2, 9)
        answer = a * b
    question = f"{a} {op} {b}"
    return question, answer


def _cleanup_expired():
    now = time.time()
    with _STORE_LOCK:
        expired = [
            sid for sid, info in _CAPTCHA_STORE.items()
            if now - info["created"] > CAPTCHA_TTL_SECONDS
        ]
        for sid in expired:
            _CAPTCHA_STORE.pop(sid, None)


def generate_math_captcha(session_id: str) -> dict:
    """Generate a fresh CAPTCHA for the given session."""
    if not session_id:
        raise ValueError("session_id is required")
    _cleanup_expired()
    question, answer = _new_math_pair()
    with _STORE_LOCK:
        _CAPTCHA_STORE[session_id] = {
            "answer": answer,
            "created": time.time(),
            "attempts": 0,
            "question": question,
        }
    return {
        "question": question,
        "session_id": session_id,
        "expires_in": CAPTCHA_TTL_SECONDS,
    }


def verify_math_captcha(session_id: str,
                        user_answer: Optional[str]) -> tuple[bool, str]:
    """
    Verify. Returns (ok, reason).
    reason: "ok" | "no_session" | "expired" | "too_many_tries"
            | "empty" | "wrong"
    """
    if not session_id or user_answer is None:
        return False, "empty"

    with _STORE_LOCK:
        info = _CAPTCHA_STORE.get(session_id)

    if info is None:
        return False, "no_session"

    if time.time() - info["created"] > CAPTCHA_TTL_SECONDS:
        with _STORE_LOCK:
            _CAPTCHA_STORE.pop(session_id, None)
        return False, "expired"

    if info["attempts"] >= MAX_ATTEMPTS:
        with _STORE_LOCK:
            _CAPTCHA_STORE.pop(session_id, None)
        return False, "too_many_tries"

    cleaned = str(user_answer).strip()
    if not cleaned:
        return False, "empty"

    try:
        user_int = int(cleaned)
    except ValueError:
        with _STORE_LOCK:
            if session_id in _CAPTCHA_STORE:
                _CAPTCHA_STORE[session_id]["attempts"] += 1
        return False, "wrong"

    if user_int == info["answer"]:
        with _STORE_LOCK:
            _CAPTCHA_STORE.pop(session_id, None)
        return True, "ok"

    with _STORE_LOCK:
        if session_id in _CAPTCHA_STORE:
            _CAPTCHA_STORE[session_id]["attempts"] += 1
            if _CAPTCHA_STORE[session_id]["attempts"] >= MAX_ATTEMPTS:
                _CAPTCHA_STORE.pop(session_id, None)
    return False, "wrong"


def invalidate_captcha(session_id: str):
    """Force-remove a CAPTCHA (call after successful login)."""
    if not session_id:
        return
    with _STORE_LOCK:
        _CAPTCHA_STORE.pop(session_id, None)


def get_captcha_stats() -> dict:
    """Diagnostic."""
    _cleanup_expired()
    with _STORE_LOCK:
        return {
            "pending": len(_CAPTCHA_STORE),
            "max_attempts": MAX_ATTEMPTS,
            "ttl_seconds": CAPTCHA_TTL_SECONDS,
        }
