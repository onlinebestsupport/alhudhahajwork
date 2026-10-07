# FLET_HAJ — Changelog & Notes

**Project root:** `C:\Users\Masood\Desktop\FLET_HAJ`
**Live deploy:** `https://alhudhahaj.work`
**Last updated:** 2026-10-07
**Maintained by:** Masood

---

## 📌 SESSION LOG

### 2026-10-07 — Front Page Fixes (v3.20 / v2.1 / v2.25 / v2.0)

**Problems reported by user:**
1. Admin → Front Page → Packages: 3 batches selected but front page showed **0**
2. `Clear All` button sometimes didn't work
3. Checkbox rows sometimes didn't respond to tap
4. Needed max **9** packages on front page with dynamic sizing
5. Admin Front Page tab **auto-scrolled to top every 5–10 seconds**

**Root causes found:**
- `_build_root()` was replacing `self.root` on every refresh, so the admin
  shell kept the OLD reference — updates went into a detached tree.
- `_rebuild_batch_rows()` on every toggle = full re-render = scroll reset.
- `max_shown = 0` was interpreted by public JS as "show 0" instead of "no cap".
- No auto-save on toggle → user had to click Save for front page to update.
- `/api/batches` gave no visibility into which IDs matched vs missed.

**Fixes deployed:**

| File | Change |
|---|---|
| `core/frontpage_config.py` | v2.1 — atomic writes, `MAX_PACKAGES_SHOWN_DEFAULT=9`, float-safe `_normalize_id`, `max_shown` clamps to 9 when ≤0 |
| `core/frontpage_settings_tab.py` | v3.20 — inner Column reused (scroll preserved), per-control `.update()` on toggle, `_auto_save_batch_state()` fires on every toggle |
| `main.py` | v2.25 — `/api/batches` logs saved vs DB IDs side-by-side; NEW `/api/admin/frontpage/why-empty` diagnostic |
| `static/gallery_upload.html` | v2.0 — real error messages, drag & drop, paste, retry failed, URL aliases |

**Deployment steps performed:**
1. Replaced 4 files on GitHub → pushed to Railway
2. Deleted stale `/app/data/frontpage_config.json` on the volume
3. Redeployed — new default `max_shown=9` took effect
4. Verified `/api/admin/frontpage/why-empty` returns `ok: true`

**Verification checklist (all passed):**
- [x] Admin Front Page — 3 batches show as ticked on load
- [x] Click a 4th batch → row turns green instantly, no scroll jump
- [x] Console logs `[FRONTPAGE] auto-saved 4 batch id(s)`
- [x] `/api/batches` returns matching count in JSON
- [x] Front page renders packages in responsive grid
- [x] Gallery upload works with drag & drop and Ctrl+V

---

## 🗂️ FILE INVENTORY (as of 2026-10-07)



---

## 🔑 KEY FUNCTIONS REFERENCE

### `core/frontpage_config.py`

| Function | Purpose |
|---|---|
| `load_config()` | Read JSON, merge with defaults, never crash |
| `save_config(cfg)` | **Atomic** write (temp file + `os.replace`) |
| `_normalize_id(x)` | Coerce `123`, `123.0`, `" 123 "` → `"123"` |
| `normalize_batch_ids(ids)` | Dedupe + strip, order-preserving |
| `get_selected_batch_ids(cfg)` | Read-only list of selected IDs |
| `get_selected_batches(cfg, all)` | Filter DB batches by selection + cap |
| `config_exists()` | True if JSON file on disk |
| `delete_config()` | Remove config (next load recreates defaults) |
| `gallery_summary()` | `{photos, videos, total_human}` |
| `MAX_PACKAGES_SHOWN_DEFAULT` | **9** (front page hard default) |
| `MAX_PACKAGES_SHOWN_HARD_CAP` | **30** (absolute max) |

### `core/frontpage_settings_tab.py`

| Method | Purpose |
|---|---|
| `_build_root()` | **Reuses** `self._inner_column` — scroll preserved |
| `_section_5_packages()` | Max shown defaults to 9 |
| `_toggle_batch_row_by_id(bid)` | Per-control update + auto-save |
| `_toggle_batches(True/False)` | All / Clear — per-control, no rebuild |
| `_auto_save_batch_state()` | **NEW** — silent partial save of batch IDs |
| `_safe_update()` | `root.update()` with fallback to `page.update()` |

### `main.py`

| Endpoint | Purpose |
|---|---|
| `/api/frontpage` | Public config JSON (no-cache) |
| `/api/batches` | Filtered packages for front page (no-cache) |
| `/api/admin/frontpage/diagnose` | Round-trip save/load test |
| `/api/admin/frontpage/why-empty` | **NEW** — "why 0 packages?" diagnostic |
| `/api/admin/gallery/upload` | Photo/video upload |
| `/api/admin/gallery/item` (DELETE) | Remove media |
| `/gallery-upload` | HTML upload page |

---

## 🚨 TROUBLESHOOTING QUICK REFERENCE

### Symptom: Front page shows 0 packages

**Step 1** — Open in browser:


**Step 2** — Read the `verdict` array:

| Verdict message | Fix |
|---|---|
| `❌ config file does not exist` | Nothing saved yet — tick batches in admin |
| `❌ no batch is checked in admin` | Open `/admin` → Front Page → tick rows |
| `⚠️ N saved ID(s) not in DB: [...]` | Batch was deleted from DB. Untick & re-tick |
| `⚠️ matched IDs exist but filter returned 0` | Check `max_shown` and `source` fields |
| `✅ would show N package(s)` | Backend is fine — check the browser cache |

**Step 3** — If backend is fine but page shows 0:
- Hard refresh: `Ctrl+Shift+R`
- Check browser DevTools → Network → `/api/batches` → response

---

### Symptom: Admin Front Page tab scrolls to top unexpectedly

**Cause:** `_build_root()` or `_rebuild_batch_rows()` recreating controls.

**Check:**
```python
# In frontpage_settings_tab.py, this must be the ONLY time inner_column is created:
if self._inner_column is None:
    self._inner_column = ft.Column(...)

# And toggles must NOT call _rebuild_batch_rows():
def _toggle_batch_row_by_id(self, batch_id):
    # ✅ calls _auto_save_batch_state()
    # ❌ does NOT call _rebuild_batch_rows()


