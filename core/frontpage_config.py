# =================================================================================
# core/frontpage_config.py — Front page configuration storage
# =================================================================================
# Loads/saves the JSON file that drives the marketing front page.
# File location: <base>/data/frontpage_config.json
#
# Every value has a sensible default baked in. If the JSON file is
# missing or has missing keys, defaults fill in automatically.
#
# PATTERNS:
#   • Admin edits via core/frontpage_settings_tab.py
#   • Public front page reads via GET /api/frontpage (see main.py)
#   • Packages are drawn from real batches via GET /api/batches
# =================================================================================

import os
import json
from datetime import datetime


# =================================================================================
# 1 — DEFAULT CONFIG
# =================================================================================
DEFAULT_CONFIG = {
    # ---- Hero section ----
    "hero": {
        "heading": "Your Journey to the Holy Land",
        "subheading": (
            "Experience the spiritual journey of a lifetime with our "
            "premium Haj and Umrah packages. Book early for best prices!"
        ),
        "button_text": "View Packages",
        "whatsapp_text": "Chat on WhatsApp",
    },

    # ---- Alert banner (top of page) ----
    "alert": {
        "enabled": False,
        "message": (
            "⚠️ Important: Visa requirements updated for 2026 Hajj. "
            "Please submit documents by March 15th."
        ),
        "link": "#",
        "color": "#f39c12",
        "style": "pulse",  # "pulse" | "blink" | "none"
    },

    # ---- Contact info ----
    "contact": {
        "phone": "+91 98765 43210",
        "phone2": "",
        "email": "info@alhudha.com",
        "whatsapp": "919876543210",
        "address_line1": "123, Haj House",
        "address_line2": "Mumbai - 400001, India",
    },

    # ---- Social links ----
    "social": {
        "facebook": "",
        "instagram": "",
        "twitter": "",
    },

    # ---- Feature cards (4 recommended) ----
    "features": [
        {"icon": "fa-mosque", "title": "25+ Years Experience",
         "text": "Trusted by thousands of pilgrims worldwide"},
        {"icon": "fa-hotel", "title": "Premium Accommodation",
         "text": "Hotels near Haram for your convenience"},
        {"icon": "fa-bus", "title": "VIP Transportation",
         "text": "Comfortable travel between holy sites"},
        {"icon": "fa-users", "title": "Expert Guides",
         "text": "Knowledgeable guides throughout your journey"},
    ],

    # ---- Packages section ----
    #   source = "batches" → pull from real batches (recommended)
    #   source = "manual"  → use the manual list below
    #   selected_batch_ids = [] → show ALL open batches (up to max_shown)
    #   selected_batch_ids = ["HAJ/BCH/2027/001", ...] → only those
    "packages": {
        "title": "Our Haj & Umrah Packages",
        "subtitle": (
            "Choose from our carefully designed packages for a blessed journey"
        ),
        "source": "batches",
        "selected_batch_ids": [],
        "max_shown": 6,
        "manual": [],  # used only when source == "manual"
    },

    # ---- About section ----
    "about": {
        "heading": "About Alhudha Haj Travel",
        "paragraph1": (
            "With over 25 years of experience, Alhudha Haj Travel has been "
            "serving pilgrims with dedication and excellence. We understand "
            "the spiritual significance of this journey and strive to "
            "provide the best services to make your experience memorable."
        ),
        "paragraph2": (
            "Our team of experienced guides ensures that all your religious "
            "obligations are fulfilled with ease, while our premium "
            "accommodations and transportation services provide comfort "
            "throughout your journey."
        ),
        "stats": [
            {"number": "25+",  "label": "Years Experience"},
            {"number": "10k+", "label": "Happy Pilgrims"},
            {"number": "50+",  "label": "Expert Guides"},
            {"number": "100%", "label": "Satisfaction"},
        ],
    },

    # ---- Footer ----
    "footer": {
        "about_text": (
            "Your trusted partner for Haj and Umrah since 1998. "
            "We provide comprehensive services for pilgrims."
        ),
        "copyright": (
            f"© {datetime.now().year} Alhudha Haj Travel System. "
            f"All rights reserved."
        ),
    },
}


# =================================================================================
# 2 — PATH RESOLUTION
# =================================================================================
def _config_path() -> str:
    """Where the JSON file lives (inside the Railway Volume, persisted)."""
    try:
        from core.helpers import get_app_base_path
        base = get_app_base_path()
    except Exception:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "frontpage_config.json")


# =================================================================================
# 3 — DEEP MERGE helper
# =================================================================================
def _deep_merge(base: dict, override: dict) -> dict:
    """
    Merge `override` onto `base`, recursively for nested dicts.
    Missing keys in `override` keep their default value from `base`.
    """
    result = dict(base)
    for k, v in (override or {}).items():
        if (k in result
                and isinstance(result[k], dict)
                and isinstance(v, dict)):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# =================================================================================
# 4 — PUBLIC API
# =================================================================================
def load_config() -> dict:
    """
    Load the config from disk, merged with defaults.
    Creates the file with defaults on first run.
    """
    path = _config_path()

    if not os.path.exists(path):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _deep_merge(DEFAULT_CONFIG, data)
    except Exception as e:
        print(f"[frontpage_config] load failed: {e}")
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> bool:
    """Save the config to disk. Returns True on success."""
    path = _config_path()
    try:
        merged = _deep_merge(DEFAULT_CONFIG, cfg or {})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        print(f"[frontpage_config] saved to {path}")
        return True
    except Exception as e:
        print(f"[frontpage_config] save failed: {e}")
        return False


def public_view(cfg: dict = None) -> dict:
    """
    Return the config as seen by the public front page.
    Currently identical to the full config, but this is where you'd
    filter fields if you add admin-only data later.
    """
    if cfg is None:
        cfg = load_config()
    return cfg


# =================================================================================
# 5 — BATCH SELECTION helper
# =================================================================================
def get_selected_batches(cfg: dict, all_batches: list) -> list:
    """
    Given the config and the full list of batches (from db.get_batches()),
    return the batches that should appear as packages on the front page.

    Logic:
      • If source == "manual"  → return cfg["packages"]["manual"] list
      • If source == "batches" → filter real batches:
          - If selected_batch_ids is empty → show ALL open/closing batches
          - Otherwise → show only the selected batch IDs
          - Always limit to cfg["packages"]["max_shown"]
    """
    pcfg = (cfg or {}).get("packages", {}) or {}
    source = pcfg.get("source", "batches")
    try:
        max_shown = int(pcfg.get("max_shown", 6) or 6)
    except Exception:
        max_shown = 6

    # ---- Manual list ----
    if source == "manual":
        manual = pcfg.get("manual", []) or []
        return list(manual)[:max_shown]

    # ---- Real batches ----
    selected_ids = pcfg.get("selected_batch_ids", []) or []
    selected_ids_str = [str(x) for x in selected_ids if x]

    out = []
    for b in (all_batches or []):
        bid = str(b.get("id", ""))

        # Filter by selection if any IDs are explicitly chosen
        if selected_ids_str and bid not in selected_ids_str:
            continue

        # Only show open/closing batches on the public page
        status = str(b.get("status", "")).lower().strip()
        if status and status not in ("open", "closing soon"):
            continue

        out.append(b)
        if len(out) >= max_shown:
            break

    return out