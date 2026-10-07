# =================================================================================
# core/frontpage_config.py — Front page configuration storage
# =================================================================================
# v1.3 — Verbose batch-selection logging
#   • get_selected_batches() now logs every step so we can pinpoint why
#     N checkboxes produce M<N cards on the public page.
#   • Strict checkbox semantics preserved (v1.2):
#       Checked   → shown (regardless of batch status)
#       Unchecked → hidden
#       Nothing   → 0 packages shown
#
# SECTION INDEX
#   1     DEFAULT_CONFIG
#   2     _config_path
#   3     _deep_merge
#   4     Public API (load_config / save_config / public_view)
#   5     get_selected_batches   ← updated with logging
#   6     Gallery helpers
# =================================================================================

import os
import json
from datetime import datetime


# =================================================================================
# 1 — DEFAULT CONFIG
# =================================================================================
DEFAULT_CONFIG = {

    # ---- 1.1 Hero ----
    "hero": {
        "heading": "Your Journey to the Holy Land",
        "subheading": (
            "Experience the spiritual journey of a lifetime with our "
            "premium Haj and Umrah packages. Book early for best prices!"
        ),
        "button_text": "View Packages",
        "whatsapp_text": "Chat on WhatsApp",
    },

    # ---- 1.2 Alert ----
    "alert": {
        "enabled": False,
        "message": (
            "⚠️ Important: Visa requirements updated for 2026 Hajj. "
            "Please submit documents by March 15th."
        ),
        "link": "#",
        "color": "#f39c12",
        "style": "pulse",
    },

    # ---- 1.3 Contact ----
    "contact": {
        "phone": "+91 98765 43210",
        "phone2": "",
        "email": "info@alhudha.com",
        "whatsapp": "919876543210",
        "address_line1": "123, Haj House",
        "address_line2": "Mumbai - 400001, India",
    },

    # ---- 1.4 Social ----
    "social": {
        "facebook": "",
        "instagram": "",
        "twitter": "",
    },

    # ---- 1.5 Features ----
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

    # ---- 1.6 Packages ----
    #   selected_batch_ids: the IDs of batches that should appear on
    #   the public page. [] = none shown.
    #   max_shown: safety cap. Set to 0 or omit to show ALL selected.
    "packages": {
        "title": "Our Haj & Umrah Packages",
        "subtitle": (
            "Choose from our carefully designed packages for a blessed journey"
        ),
        "source": "batches",
        "selected_batch_ids": [],
        "max_shown": 0,          # 0 = no cap (show all checked batches)
        "manual": [],
    },

    # ---- 1.7 About ----
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

    # ---- 1.8 Footer ----
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

    # ---- 1.9 Gallery ----
    "gallery": {
        "enabled": True,
        "title": "Sacred Places & Pilgrim Attractions",
        "subtitle": "Glimpses from our blessed journeys",
        "layout": "grid",
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
    try:
        from core.helpers import get_app_base_path
        base = get_app_base_path()
    except Exception:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "frontpage_config.json")


# =================================================================================
# 3 — DEEP MERGE
# =================================================================================
def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override onto base; lists replace, dicts merge."""
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
    if cfg is None:
        cfg = load_config()
    return cfg


# =================================================================================
# 5 — BATCH SELECTION (v1.3 — verbose logging)
# =================================================================================
def get_selected_batches(cfg: dict, all_batches: list) -> list:
    """
    Return the batches to show on the public front page.

    STRICT CHECKBOX SEMANTICS:
        Checked   → appears on front page
        Unchecked → hidden
        Nothing   → 0 packages shown

    max_shown:
        0 or negative → no cap (show all checked)
        N > 0         → hard cap at N batches

    Prints verbose [FP-BATCH] lines so we can trace the exact path
    when the count doesn't match what the admin expected.
    """
    pcfg = (cfg or {}).get("packages", {}) or {}
    source = pcfg.get("source", "batches")

    try:
        max_shown = int(pcfg.get("max_shown", 0) or 0)
    except Exception:
        max_shown = 0
    # 0 or negative = no cap
    cap_enabled = max_shown > 0

    # ---- Manual list path ----
    if source == "manual":
        manual = pcfg.get("manual", []) or []
        result = list(manual) if not cap_enabled else list(manual)[:max_shown]
        print(f"[FP-BATCH] source=manual  → {len(result)} batch(es)")
        return result

    # ---- Real batches path ----
    raw_ids = pcfg.get("selected_batch_ids", []) or []
    selected_ids_str = [str(x).strip() for x in raw_ids if x]

    print("=" * 60)
    print(f"[FP-BATCH] source          : {source}")
    print(f"[FP-BATCH] cap_enabled     : {cap_enabled} "
          f"(max_shown={max_shown})")
    print(f"[FP-BATCH] selected ids    : {len(selected_ids_str)}")
    for sid in selected_ids_str:
        print(f"[FP-BATCH]   • {sid!r}")
    print(f"[FP-BATCH] DB batches      : {len(all_batches or [])}")
    for b in (all_batches or []):
        print(f"[FP-BATCH]   • {str(b.get('id','')).strip()!r}  "
              f"name={b.get('batch_name')!r}  "
              f"status={b.get('status')!r}")

    if not selected_ids_str:
        print("[FP-BATCH] → nothing selected, returning []")
        print("=" * 60)
        return []

    out = []
    for b in (all_batches or []):
        bid = str(b.get("id", "")).strip()
        if bid not in selected_ids_str:
            continue
        out.append(b)
        if cap_enabled and len(out) >= max_shown:
            print(f"[FP-BATCH] → capped at max_shown={max_shown}")
            break

    print(f"[FP-BATCH] → returning {len(out)} batch(es)")
    print("=" * 60)
    return out


# =================================================================================
# 6 — GALLERY HELPERS
# =================================================================================
def gallery_dir() -> str:
    try:
        from core.helpers import get_app_base_path
        base = get_app_base_path()
    except Exception:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "data", "gallery")
    os.makedirs(os.path.join(d, "photos"), exist_ok=True)
    os.makedirs(os.path.join(d, "videos"), exist_ok=True)
    return d


def add_gallery_item(media_type: str, item: dict) -> bool:
    if media_type not in ("photos", "videos"):
        return False
    if not isinstance(item, dict) or not item.get("url"):
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


def remove_gallery_item(media_type: str, url: str) -> bool:
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


def list_gallery_items(media_type: str = None) -> list:
    cfg = load_config()
    gal = cfg.get("gallery", {}) or {}
    if media_type == "photos":
        return list(gal.get("photos", []) or [])
    if media_type == "videos":
        return list(gal.get("videos", []) or [])
    return (list(gal.get("photos", []) or [])
            + list(gal.get("videos", []) or []))


def gallery_summary() -> dict:
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
