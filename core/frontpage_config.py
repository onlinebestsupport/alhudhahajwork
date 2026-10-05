# =================================================================================
# core/frontpage_config.py — Front page configuration storage
# =================================================================================
# v1.1 — Dynamic gallery (photos + videos for pilgrim attractions)
#
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
#   • Gallery media is served from /media/gallery/{photos|videos}/{file}
#
# SECTION INDEX
#   1     DEFAULT_CONFIG (all default values)
#   1.1     Hero
#   1.2     Alert banner
#   1.3     Contact info
#   1.4     Social links
#   1.5     Features
#   1.6     Packages
#   1.7     About
#   1.8     Footer
#   1.9     NEW — Gallery
#   2     Path resolution (_config_path)
#   3     Deep merge helper (_deep_merge)
#   4     Public API (load_config, save_config, public_view)
#   5     Batch selection helper (get_selected_batches)
#   6     NEW — Gallery storage helpers
#   6.1     gallery_dir()
#   6.2     add_gallery_item()
#   6.3     remove_gallery_item()
#   6.4     list_gallery_items()
#   6.5     gallery_summary()
# =================================================================================

import os
import json
from datetime import datetime


# =================================================================================
# 1 — DEFAULT CONFIG
# =================================================================================
DEFAULT_CONFIG = {

    # -----------------------------------------------------------------------------
    # 1.1 — Hero section (top banner)
    # -----------------------------------------------------------------------------
    "hero": {
        "heading": "Your Journey to the Holy Land",
        "subheading": (
            "Experience the spiritual journey of a lifetime with our "
            "premium Haj and Umrah packages. Book early for best prices!"
        ),
        "button_text": "View Packages",
        "whatsapp_text": "Chat on WhatsApp",
    },

    # -----------------------------------------------------------------------------
    # 1.2 — Alert banner (optional top-of-page announcement)
    # -----------------------------------------------------------------------------
    "alert": {
        "enabled": False,
        "message": (
            "⚠️ Important: Visa requirements updated for 2026 Hajj. "
            "Please submit documents by March 15th."
        ),
        "link": "#",
        "color": "#f39c12",
        "style": "pulse",          # "pulse" | "blink" | "none"
    },

    # -----------------------------------------------------------------------------
    # 1.3 — Contact info (top bar, contact section, footer)
    # -----------------------------------------------------------------------------
    "contact": {
        "phone": "+91 98765 43210",
        "phone2": "",
        "email": "info@alhudha.com",
        "whatsapp": "919876543210",
        "address_line1": "123, Haj House",
        "address_line2": "Mumbai - 400001, India",
    },

    # -----------------------------------------------------------------------------
    # 1.4 — Social links (empty string hides the network)
    # -----------------------------------------------------------------------------
    "social": {
        "facebook": "",
        "instagram": "",
        "twitter": "",
    },

    # -----------------------------------------------------------------------------
    # 1.5 — Feature cards (4-6 recommended)
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # 1.6 — Packages section
    #   source = "batches" → pull from real batches (recommended)
    #   source = "manual"  → use the manual list below
    #   selected_batch_ids = [] → show ALL open batches (up to max_shown)
    #   selected_batch_ids = ["HAJ/BCH/2027/001", ...] → only those
    # -----------------------------------------------------------------------------
    "packages": {
        "title": "Our Haj & Umrah Packages",
        "subtitle": (
            "Choose from our carefully designed packages for a blessed journey"
        ),
        "source": "batches",
        "selected_batch_ids": [],
        "max_shown": 6,
        "manual": [],               # used only when source == "manual"
    },

    # -----------------------------------------------------------------------------
    # 1.7 — About section
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # 1.8 — Footer
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # 1.9 — NEW — Gallery (photos + videos)
    #   Files live at /app/data/gallery/{photos,videos}/ on the Railway Volume.
    #   Each item in photos[] / videos[] looks like:
    #     {
    #       "url":         "/media/gallery/photos/abc123.jpg",
    #       "caption":     "Pilgrims at Masjid al-Haram",
    #       "uploaded_at": "2026-10-05T10:31:00",
    #       "size":        428193,          # bytes
    #       "original_name": "mecca-2026.jpg"
    #     }
    # -----------------------------------------------------------------------------
    "gallery": {
        "enabled": True,
        "title": "Sacred Places & Pilgrim Attractions",
        "subtitle": "Glimpses from our blessed journeys",
        "layout": "grid",                       # "grid" | "carousel"
        "max_photos_shown": 12,
        "max_videos_shown": 6,
        "photos": [],
        "videos": [],
    },
}


# =================================================================================
# 2 — PATH RESOLUTION
# =================================================================================
def _config_path() -> str:
    """
    Where the JSON file lives (inside the Railway Volume, persisted).

    Falls back to <base>/data/ if core.helpers.get_app_base_path() is
    unavailable for any reason.
    """
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

    - Missing keys in `override` keep their default value from `base`.
    - Lists are NOT merged — the override list replaces the base list.
      This is intentional: an empty `photos: []` in the saved config
      must be respected as "no photos", not silently refilled with
      any defaults.
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

# ---------------------------------------------------------------------------------
# 4.1 — load_config
# ---------------------------------------------------------------------------------
def load_config() -> dict:
    """
    Load the config from disk, merged with defaults.

    - If the file doesn't exist, one is created with the defaults.
    - If reading fails, defaults are returned so the front page
      never crashes because of a corrupt JSON file.
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


# ---------------------------------------------------------------------------------
# 4.2 — save_config
# ---------------------------------------------------------------------------------
def save_config(cfg: dict) -> bool:
    """
    Save the config to disk (merged with defaults so a partial
    payload never truncates the schema).

    Returns True on success, False on failure.
    """
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


# ---------------------------------------------------------------------------------
# 4.3 — public_view
# ---------------------------------------------------------------------------------
def public_view(cfg: dict = None) -> dict:
    """
    Return the config as seen by the public front page.

    Currently identical to the full config. Kept as a seam so you can
    later strip admin-only fields without changing call sites.
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


# =================================================================================
# 6 — NEW — GALLERY STORAGE HELPERS
# =================================================================================

# ---------------------------------------------------------------------------------
# 6.1 — gallery_dir
# ---------------------------------------------------------------------------------
def gallery_dir() -> str:
    """
    Persistent directory for uploaded media (inside the Railway Volume).

    Creates:
        <base>/data/gallery/
        <base>/data/gallery/photos/
        <base>/data/gallery/videos/

    Returns the top-level gallery path (not the sub-folder).
    """
    try:
        from core.helpers import get_app_base_path
        base = get_app_base_path()
    except Exception:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    d = os.path.join(base, "data", "gallery")
    os.makedirs(os.path.join(d, "photos"), exist_ok=True)
    os.makedirs(os.path.join(d, "videos"), exist_ok=True)
    return d


# ---------------------------------------------------------------------------------
# 6.2 — add_gallery_item
# ---------------------------------------------------------------------------------
def add_gallery_item(media_type: str, item: dict) -> bool:
    """
    Append one item to cfg["gallery"][media_type] and save.

    media_type must be 'photos' or 'videos'.
    item is expected to already contain url/caption/uploaded_at/size.

    Returns True on success.
    """
    if media_type not in ("photos", "videos"):
        print(f"[frontpage_config] add_gallery_item: bad media_type "
              f"{media_type!r}")
        return False

    if not isinstance(item, dict) or not item.get("url"):
        print("[frontpage_config] add_gallery_item: item missing url")
        return False

    try:
        cfg = load_config()
        gal = cfg.setdefault("gallery", {})
        gal.setdefault(media_type, [])
        gal[media_type].append(item)
        return save_config(cfg)
    except Exception as e:
        print(f"[frontpage_config] add_gallery_item failed: {e}")
        return False


# ---------------------------------------------------------------------------------
# 6.3 — remove_gallery_item
# ---------------------------------------------------------------------------------
def remove_gallery_item(media_type: str, url: str) -> bool:
    """
    Remove any item from cfg["gallery"][media_type] whose url matches.

    This removes the *config entry only*. The file on disk is handled
    by the caller (main.py §21.5.11).

    Returns True on success (even if no match was found).
    """
    if media_type not in ("photos", "videos"):
        return False

    try:
        cfg = load_config()
        gal = cfg.setdefault("gallery", {})
        lst = gal.get(media_type, []) or []
        gal[media_type] = [x for x in lst if x.get("url") != url]
        return save_config(cfg)
    except Exception as e:
        print(f"[frontpage_config] remove_gallery_item failed: {e}")
        return False


# ---------------------------------------------------------------------------------
# 6.4 — list_gallery_items
# ---------------------------------------------------------------------------------
def list_gallery_items(media_type: str = None) -> list:
    """
    Return all gallery items, optionally filtered by media_type.

    Usage:
        list_gallery_items()          → all items (photos + videos)
        list_gallery_items("photos")  → photos only
        list_gallery_items("videos")  → videos only
    """
    cfg = load_config()
    gal = cfg.get("gallery", {}) or {}

    if media_type == "photos":
        return list(gal.get("photos", []) or [])
    if media_type == "videos":
        return list(gal.get("videos", []) or [])

    return (list(gal.get("photos", []) or [])
            + list(gal.get("videos", []) or []))


# ---------------------------------------------------------------------------------
# 6.5 — gallery_summary
# ---------------------------------------------------------------------------------
def gallery_summary() -> dict:
    """
    Small helper for the admin UI:
        {
            "photos": 3,
            "videos": 1,
            "total_bytes": 4291837,
            "total_human": "4.1 MB",
        }
    """
    cfg = load_config()
    gal = cfg.get("gallery", {}) or {}
    photos = gal.get("photos", []) or []
    videos = gal.get("videos", []) or []

    total = sum(int(x.get("size", 0) or 0) for x in photos + videos)

    def _human(n):
        try:
            n = float(n)
        except Exception:
            return "?"
        if n < 1024:
            return f"{int(n)} B"
        if n < 1024 * 1024:
            return f"{n/1024:.1f} KB"
        if n < 1024 * 1024 * 1024:
            return f"{n/(1024*1024):.2f} MB"
        return f"{n/(1024*1024*1024):.2f} GB"

    return {
        "photos": len(photos),
        "videos": len(videos),
        "total_bytes": total,
        "total_human": _human(total),
    }


# =================================================================================
# SECTION END
# =================================================================================