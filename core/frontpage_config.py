# =================================================================================
# core/frontpage_config.py — Front page configuration storage
# =================================================================================
# v2.2 — _normalize_id now handles "123.0" strings correctly
#   • "123.0"  → "123"
#   • "123.00" → "123"
#   • "123.5"  → "123.5" (unchanged — not whole number)
#   • Preserves all other v2.1 behavior
# =================================================================================

import os
import json
import tempfile
from datetime import datetime


MAX_PACKAGES_SHOWN_DEFAULT = 9
MAX_PACKAGES_SHOWN_HARD_CAP = 30


# =================================================================================
# DEFAULT CONFIG
# =================================================================================
DEFAULT_CONFIG = {
    "hero": {
        "heading": "Your Journey to the Holy Land",
        "subheading": (
            "Experience the spiritual journey of a lifetime with our "
            "premium Haj and Umrah packages. Book early for best prices!"
        ),
        "button_text": "View Packages",
        "whatsapp_text": "Chat on WhatsApp",
    },
    "alert": {
        "enabled": False,
        "message": (
            "Important: Visa requirements updated for 2026 Hajj. "
            "Please submit documents by March 15th."
        ),
        "link": "#",
        "color": "#f39c12",
        "style": "pulse",
    },
    "contact": {
        "phone": "+91 98765 43210",
        "phone2": "",
        "email": "info@alhudha.com",
        "whatsapp": "919876543210",
        "address_line1": "123, Haj House",
        "address_line2": "Mumbai - 400001, India",
    },
    "social": {
        "facebook": "",
        "instagram": "",
        "twitter": "",
    },
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
    "packages": {
        "title": "Our Haj & Umrah Packages",
        "subtitle": (
            "Choose from our carefully designed packages for a blessed journey"
        ),
        "source": "batches",
        "selected_batch_ids": [],
        "max_shown": MAX_PACKAGES_SHOWN_DEFAULT,
        "manual": [],
    },
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
    "footer": {
        "about_text": (
            "Your trusted partner for Haj and Umrah since 1998. "
            "We provide comprehensive services for pilgrims."
        ),
        "copyright": (
            f"(c) {datetime.now().year} Alhudha Haj Travel System. "
            f"All rights reserved."
        ),
    },
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
# PATH RESOLUTION
# =================================================================================
def _data_dir() -> str:
    try:
        from core.helpers import get_app_base_path
        base = get_app_base_path()
    except Exception:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "data")
    os.makedirs(d, exist_ok=True)
    return d


def _config_path() -> str:
    return os.path.join(_data_dir(), "frontpage_config.json")


# =================================================================================
# DEEP MERGE
# =================================================================================
def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base or {})
    if not override:
        return result
    for k, v in override.items():
        if v is None:
            continue
        if (k in result
                and isinstance(result[k], dict)
                and isinstance(v, dict)):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# =================================================================================
# ID NORMALIZATION (v2.2 — handles "123.0" strings)
# =================================================================================
def _normalize_id(x) -> str:
    """
    Canonical string form for any batch ID.

    Handles:
        int 123        -> "123"
        float 123.0    -> "123"
        float 123.5    -> "123.5"
        str "123"      -> "123"
        str "  123  "  -> "123"
        str "123.0"    -> "123"     ← NEW in v2.2
        str "123.00"   -> "123"     ← NEW in v2.2
        str "123.5"    -> "123.5"   (not whole, unchanged)
        None           -> ""
    """
    if x is None:
        return ""
    if isinstance(x, bool):
        return str(x)

    # Direct numeric types
    if isinstance(x, float):
        try:
            if x.is_integer():
                return str(int(x))
        except Exception:
            pass
    if isinstance(x, int):
        return str(x)

    # String handling
    try:
        s = str(x).strip()
    except Exception:
        return ""

    if not s:
        return ""

    # NEW v2.2: if string looks like "123.0" or "123.00", strip the .0
    if "." in s:
        try:
            f = float(s)
            if f.is_integer():
                return str(int(f))
        except Exception:
            pass

    return s


# =================================================================================
# PUBLIC API
# =================================================================================
def load_config() -> dict:
    path = _config_path()
    if not os.path.exists(path):
        print(f"[FP-CFG] no config at {path} — creating defaults")
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = _deep_merge(DEFAULT_CONFIG, data)
        try:
            ids = merged.get("packages", {}).get("selected_batch_ids", []) or []
            ms = merged.get("packages", {}).get("max_shown", 0)
            print(f"[FP-CFG] loaded · {len(ids)} selected · max_shown={ms}")
        except Exception:
            pass
        return merged
    except Exception as e:
        print(f"[FP-CFG] load failed ({path}): {e}")
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> bool:
    """Atomic write: temp file + os.replace()."""
    path = _config_path()
    tmp_path = None
    try:
        merged = _deep_merge(DEFAULT_CONFIG, cfg or {})

        # Sanitise batch IDs (applies _normalize_id)
        try:
            pkg = merged.setdefault("packages", {})
            raw = pkg.get("selected_batch_ids", []) or []
            pkg["selected_batch_ids"] = [
                _normalize_id(x) for x in raw if _normalize_id(x)
            ]
        except Exception as e:
            print(f"[FP-CFG] warn: batch id cleanup failed: {e}")

        d = os.path.dirname(path)
        os.makedirs(d, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            prefix=".fp_cfg_", suffix=".json.tmp", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp_path, path)
            tmp_path = None
        except Exception:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise

        try:
            n = len(merged.get("packages", {})
                         .get("selected_batch_ids", []) or [])
            print(f"[FP-CFG] saved · {n} selected batch(es)")
        except Exception:
            print(f"[FP-CFG] saved")
        return True
    except Exception as e:
        print(f"[FP-CFG] save failed ({path}): {e}")
        return False


def public_view(cfg: dict = None) -> dict:
    if cfg is None:
        cfg = load_config()
    return cfg


def config_exists() -> bool:
    try:
        return os.path.exists(_config_path())
    except Exception:
        return False


def delete_config() -> bool:
    path = _config_path()
    try:
        if os.path.exists(path):
            os.remove(path)
            print(f"[FP-CFG] deleted {path}")
        return True
    except Exception as e:
        print(f"[FP-CFG] delete failed ({path}): {e}")
        return False


# =================================================================================
# BATCH SELECTION HELPERS
# =================================================================================
def normalize_batch_ids(ids) -> list:
    """Clean, dedupe, order-preserving list of batch IDs."""
    out = []
    seen = set()
    for x in (ids or []):
        s = _normalize_id(x)
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def get_selected_batch_ids(cfg: dict = None) -> list:
    if cfg is None:
        cfg = load_config()
    pkg = (cfg or {}).get("packages", {}) or {}
    return normalize_batch_ids(pkg.get("selected_batch_ids", []) or [])


def set_selected_batch_ids(cfg: dict, ids) -> dict:
    if not isinstance(cfg, dict):
        cfg = load_config()
    pkg = cfg.setdefault("packages", {})
    pkg["selected_batch_ids"] = normalize_batch_ids(ids)
    return cfg


def count_selected_batches(cfg: dict = None) -> int:
    return len(get_selected_batch_ids(cfg))


def get_selected_batches(cfg: dict, all_batches: list) -> list:
    """Return batches that should appear on the public front page."""
    pcfg = (cfg or {}).get("packages", {}) or {}
    source = pcfg.get("source", "batches")

    try:
        max_shown = int(pcfg.get("max_shown", 0) or 0)
    except Exception:
        max_shown = 0
    if max_shown <= 0:
        max_shown = MAX_PACKAGES_SHOWN_DEFAULT
    if max_shown > MAX_PACKAGES_SHOWN_HARD_CAP:
        max_shown = MAX_PACKAGES_SHOWN_HARD_CAP
    cap_enabled = max_shown > 0

    # ---- Manual list ----
    if source == "manual":
        manual = pcfg.get("manual", []) or []
        result = list(manual)[:max_shown] if cap_enabled else list(manual)
        print(f"[FP-BATCH] source=manual -> {len(result)} batch(es)")
        return result

    # ---- Real batches ----
    selected_ids = get_selected_batch_ids(cfg)
    all_batches = all_batches or []

    print("=" * 60)
    print(f"[FP-BATCH] source          : {source}")
    print(f"[FP-BATCH] max_shown       : {max_shown}")
    print(f"[FP-BATCH] selected ids    : {len(selected_ids)}")
    for sid in selected_ids:
        print(f"[FP-BATCH]   - {sid!r}")
    print(f"[FP-BATCH] DB batches      : {len(all_batches)}")

    db_ids = []
    for b in all_batches:
        bid = _normalize_id(b.get("id"))
        db_ids.append(bid)
        print(f"[FP-BATCH]   - {bid!r} name={b.get('batch_name')!r}")

    missing = [sid for sid in selected_ids if sid not in db_ids]
    if missing:
        print(f"[FP-BATCH] Warning: {len(missing)} selected ID(s) NOT in DB:")
        for sid in missing:
            print(f"[FP-BATCH]     - {sid!r}")

    if not selected_ids:
        print("[FP-BATCH] -> nothing selected, returning []")
        print("=" * 60)
        return []

    out = []
    wanted = set(selected_ids)
    for b in all_batches:
        bid = _normalize_id(b.get("id"))
        if bid not in wanted:
            continue
        out.append(b)
        if len(out) >= max_shown:
            print(f"[FP-BATCH] -> capped at {max_shown}")
            break

    print(f"[FP-BATCH] -> returning {len(out)} batch(es)")
    print("=" * 60)
    return out


# =================================================================================
# GALLERY HELPERS
# =================================================================================
def gallery_dir() -> str:
    d = os.path.join(_data_dir(), "gallery")
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
        print(f"[FP-CFG] add_gallery_item failed: {e}")
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
        print(f"[FP-CFG] remove_gallery_item failed: {e}")
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


def gallery_media_path(media_type: str, filename: str) -> str:
    if media_type not in ("photos", "videos"):
        raise ValueError(f"bad media_type: {media_type!r}")
    if not filename:
        raise ValueError("filename is required")
    filename = os.path.basename(str(filename))
    return os.path.join(gallery_dir(), media_type, filename)


def gallery_media_url(media_type: str, filename: str) -> str:
    if media_type not in ("photos", "videos"):
        raise ValueError(f"bad media_type: {media_type!r}")
    if not filename:
        raise ValueError("filename is required")
    filename = os.path.basename(str(filename))
    return f"/media/gallery/{media_type}/{filename}"


# =================================================================================
# SECTION END — core/frontpage_config.py v2.2
# =================================================================================