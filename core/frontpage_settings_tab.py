# =================================================================================
# core/frontpage_settings_tab.py — Front Page Settings
# =================================================================================
# v3.31 — THE ACTUAL FIX: removed deprecated TextField/Dropdown properties
#
#   ROOT CAUSE:
#     Flet 1.0.4 deprecated TextField.border_color / border_radius /
#     focused_border_color. Every Page.update() hit those deprecated
#     props and Flet REBUILT the TextField, wiping cursor position and
#     rolling back the value to what the server last saw.
#
#   FIX:
#     • All TextFields now use the new `border=` syntax only.
#     • All Dropdowns use the new `border=` syntax only.
#     • No deprecated properties anywhere.
#
#   PRESERVED: everything else from v3.30
# =================================================================================

import os
import time
import asyncio
import traceback
from datetime import datetime

import flet as ft

from core.frontpage_config import (
    DEFAULT_CONFIG, load_config, save_config, _deep_merge,
    gallery_dir, gallery_summary,
    MAX_PACKAGES_SHOWN_DEFAULT)


# ---- Palette ----
PRIMARY      = "#1e3a8a"
PRIMARY_LT   = "#2563eb"
ACCENT       = "#7c3aed"
SUCCESS      = "#059669"
WARN         = "#d97706"
DANGER       = "#dc2626"
BORDER       = "#e2e8f0"
MUTED        = "#64748b"
SECTION_BG   = "#ffffff"
PAGE_BG      = "#f1f5f9"

TYPING_GUARD_SECONDS = 3.0


def _resolve_fit_cover():
    try:
        return ft.BoxFit.COVER
    except AttributeError:
        pass
    try:
        return ft.ImageFit.COVER
    except AttributeError:
        return None


_FIT_COVER = _resolve_fit_cover()


# ---- New border syntax helpers (Flet 1.0.4) ----
def _input_border(radius=8, width=1, color=BORDER):
    """Build an OutlineInputBorder using the new Flet 1.0 API."""
    try:
        return ft.OutlineInputBorder(
            border_radius=radius,
            border_side=ft.BorderSide(width=width, color=color),
        )
    except Exception:
        try:
            return ft.OutlineInputBorder(
                border_radius=radius,
                side=ft.BorderSide(width=width, color=color),
            )
        except Exception:
            return None


def _focused_border(radius=8):
    """Focused-state border."""
    try:
        return ft.OutlineInputBorder(
            border_radius=radius,
            border_side=ft.BorderSide(width=2, color=PRIMARY_LT),
        )
    except Exception:
        try:
            return ft.OutlineInputBorder(
                border_radius=radius,
                side=ft.BorderSide(width=2, color=PRIMARY_LT),
            )
        except Exception:
            return None


# =================================================================================
# §0 — class FrontPageSettingsTab
# =================================================================================
class FrontPageSettingsTab:

    def __init__(self, page, db, current_user):
        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}
        self.cfg = load_config()
        self.all_batches = []
        self.batch_checkboxes = {}

        # Widgets
        self.hero_heading = None
        self.hero_subheading = None
        self.hero_button = None
        self.hero_whatsapp = None

        self.alert_enabled = None
        self.alert_message = None
        self.alert_link = None
        self.alert_color = None
        self.alert_style = None

        self.feature_rows_container = None
        self.feature_entries = []

        self.pkg_source = None
        self.pkg_max_shown = None
        self.pkg_batch_container = None
        self.pkg_title = None
        self.pkg_subtitle = None
        self._batch_ui = None
        self._batch_check_state = {}

        self.about_heading = None
        self.about_p1 = None
        self.about_p2 = None
        self.stats_rows_container = None
        self.stat_entries = []

        self.contact_phone = None
        self.contact_phone2 = None
        self.contact_email = None
        self.contact_whatsapp = None
        self.contact_addr1 = None
        self.contact_addr2 = None

        self.social_facebook = None
        self.social_instagram = None
        self.social_twitter = None

        self.footer_about = None
        self.footer_copyright = None

        self.gallery_enabled = None
        self.gallery_title = None
        self.gallery_subtitle = None
        self.gallery_max_photos = None
        self.gallery_max_videos = None
        self.gallery_stats_label = None
        self.photo_list_container = None
        self.video_list_container = None
        self.photo_list = []
        self.video_list = []
        self.photo_picker = ft.FilePicker()
        self.video_picker = ft.FilePicker()
        self._pickers_registered = False

        self.status_label = None

        self._typing_until = 0.0
        self._saving = False

        self._inner_column = None
        self.root = None

        try:
            self._load_batches()
            self._build_root()
        except Exception as e:
            print(f"[FRONTPAGE] build failed: {e}")
            traceback.print_exc()
            self.root = self._error_ui(e)

    def build(self):
        return self.root

    def refresh(self, e=None):
        try:
            self.cfg = load_config()
            self._load_batches()
            self._build_root()
            self._safe_update(force=True)
            print("[FRONTPAGE] refresh OK")
        except Exception as ex:
            print(f"[FRONTPAGE] refresh failed: {ex}")
            traceback.print_exc()
            try:
                self._set_status(f"⚠️ Refresh failed: {ex}", DANGER)
            except Exception:
                pass

    def _load_batches(self):
        try:
            if hasattr(self.db, "reload"):
                try:
                    self.db.reload()
                except Exception:
                    pass
            self.all_batches = self.db.get_batches() or []
            print(f"[FRONTPAGE] loaded {len(self.all_batches)} batches")
        except Exception as e:
            print(f"[FRONTPAGE] get_batches failed: {e}")
            self.all_batches = []

    def _error_ui(self, exc):
        return ft.Container(
            content=ft.Column([
                ft.Icon(icon=ft.Icons.WARNING_AMBER, size=48,
                        color=ft.Colors.ORANGE_600),
                ft.Text("Front Page Settings failed to load",
                        size=18, weight=ft.FontWeight.BOLD),
                ft.Text(str(exc), size=12,
                        color=ft.Colors.RED_500, selectable=True),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=10),
            padding=40, bgcolor="#fef3c7", border_radius=12,
            alignment=ft.Alignment.CENTER, expand=True)


# =================================================================================
# §ROOT
# =================================================================================
    def _build_root(self):
        self.feature_entries = []
        self.stat_entries = []
        self.batch_checkboxes = {}

        sections = [
            self._section_1_header(),
            ft.Container(height=8),
            self._section_2_hero(),
            self._section_3_alert(),
            self._section_4_features(),
            self._section_5_packages(),
            self._section_6_about(),
            self._section_7_contact(),
            self._section_8_social(),
            self._section_9_footer(),
            self._section_11_gallery(),
            ft.Container(height=12),
            self._section_10_action_bar(),
            ft.Container(height=20),
        ]

        if self._inner_column is None:
            self._inner_column = ft.Column(
                controls=sections,
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            )
            self.root = ft.Container(
                content=self._inner_column,
                padding=10,
                bgcolor=PAGE_BG,
                expand=True,
            )
        else:
            self._inner_column.controls = sections

        self._register_pickers()


# =================================================================================
# §H — HELPERS
# =================================================================================
    def _section_card(self, icon, title, subtitle, controls, accent=PRIMARY):
        header = ft.Row([
            ft.Container(
                content=ft.Text(icon, size=16),
                width=36, height=36,
                bgcolor=ft.Colors.with_opacity(0.12, accent),
                border_radius=9,
                alignment=ft.Alignment.CENTER),
            ft.Column([
                ft.Text(title, size=13,
                        weight=ft.FontWeight.BOLD,
                        color="#0f172a",
                        no_wrap=False, max_lines=2),
                ft.Text(subtitle, size=10, color=MUTED,
                        no_wrap=False, max_lines=2),
            ], spacing=2, expand=True),
        ], spacing=10)

        body = ft.Column(controls, spacing=10)

        return ft.Container(
            content=ft.Column([
                header,
                ft.Divider(height=1, color=BORDER),
                ft.Container(content=body,
                             padding=ft.Padding.only(top=4)),
            ], spacing=10),
            padding=14,
            bgcolor=SECTION_BG,
            border=ft.Border.all(1, BORDER),
            border_radius=14,
            shadow=ft.BoxShadow(
                blur_radius=6, spread_radius=0,
                color=ft.Colors.with_opacity(0.04, "#000000"),
                offset=ft.Offset(0, 2)))

    # -----------------------------------------------------------------------------
    # §H.2 — _field  (v3.31 — new border API, no deprecation warnings)
    # -----------------------------------------------------------------------------
    def _field(self, label, value, **kwargs):
        """
        Build a TextField using the new Flet 1.0 border API only.

        We do NOT set border_color / border_radius / focused_border_color
        because those are deprecated and cause the field to be rebuilt
        on every page update.
        """
        # Build kwargs carefully — no deprecated properties.
        field_kwargs = dict(
            label=label,
            value=value or "",
            text_size=12,
        )
        # New-style border (no deprecation warning)
        b = _input_border(radius=8, width=1, color=BORDER)
        if b is not None:
            field_kwargs["border"] = b

        # Allow callers to override
        field_kwargs.update(kwargs)

        field = ft.TextField(**field_kwargs)

        def _on_change(e):
            self._typing_until = time.time() + TYPING_GUARD_SECONDS

        field.on_change = _on_change
        return field

    def _two_col(self, left, right):
        return ft.Row([
            ft.Container(content=left, expand=True),
            ft.Container(content=right, expand=True),
        ], spacing=10,
           vertical_alignment=ft.CrossAxisAlignment.START)


# =================================================================================
# §1 — HEADER
# =================================================================================
    def _section_1_header(self):
        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Text("🌐", size=22),
                    width=46, height=46,
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.WHITE),
                    border_radius=12,
                    alignment=ft.Alignment.CENTER),
                ft.Column([
                    ft.Text("Front Page Settings", size=15,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                    ft.Text("Edit your public landing page",
                            size=10, color="#c7d2fe"),
                ], spacing=2, expand=True),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(icon=ft.Icons.OPEN_IN_NEW, size=14,
                                color=ft.Colors.WHITE),
                        ft.Text("Preview", size=11,
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=5, tight=True),
                    on_click=self._open_preview,
                    height=38, bgcolor=SUCCESS,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=10))),
            ], spacing=12),
            padding=ft.Padding.symmetric(horizontal=16, vertical=14),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[PRIMARY, PRIMARY_LT, ACCENT]),
            border_radius=14)


# =================================================================================
# §2 — HERO
# =================================================================================
    def _section_2_hero(self):
        h = self.cfg.get("hero", {})
        self.hero_heading = self._field("Heading", h.get("heading", ""))
        self.hero_subheading = self._field(
            "Subheading", h.get("subheading", ""),
            multiline=True, min_lines=2, max_lines=3)
        self.hero_button = self._field(
            "Primary button text", h.get("button_text", ""))
        self.hero_whatsapp = self._field(
            "WhatsApp button text", h.get("whatsapp_text", ""))

        return self._section_card(
            "🎯", "Hero Section",
            "The big banner at the top of the page",
            [
                self.hero_heading,
                self.hero_subheading,
                self._two_col(self.hero_button, self.hero_whatsapp),
            ])


# =================================================================================
# §3 — ALERT
# =================================================================================
    def _section_3_alert(self):
        a = self.cfg.get("alert", {})
        self.alert_enabled = ft.Switch(
            label="Show alert banner",
            value=bool(a.get("enabled", False)),
            active_color=WARN)
        self.alert_message = self._field(
            "Alert message", a.get("message", ""),
            multiline=True, min_lines=2, max_lines=4)
        self.alert_link = self._field(
            "Learn-more link (URL or /path)", a.get("link", "#"))
        self.alert_color = self._field(
            "Banner color (hex)", a.get("color", "#f39c12"))
        self.alert_style = ft.Dropdown(
            label="Animation",
            value=a.get("style", "pulse"),
            options=[
                ft.dropdown.Option("none", "None"),
                ft.dropdown.Option("pulse", "Pulse"),
                ft.dropdown.Option("blink", "Blink"),
            ],
            text_size=12)

        return self._section_card(
            "⚠️", "Alert Banner",
            "Optional top-of-page announcement for visitors",
            [
                self.alert_enabled,
                self.alert_message,
                self.alert_link,
                self._two_col(self.alert_color, self.alert_style),
            ], accent=WARN)


# =================================================================================
# §4 — FEATURES
# =================================================================================
    def _section_4_features(self):
        self.feature_rows_container = ft.Column(spacing=8)
        self.feature_entries = []

        for f in (self.cfg.get("features") or []):
            self._add_feature_row(
                f.get("icon", "fa-check-circle"),
                f.get("title", ""),
                f.get("text", ""))

        add_btn = ft.Button(
            content=ft.Row([
                ft.Icon(icon=ft.Icons.ADD, size=14,
                        color=ft.Colors.WHITE),
                ft.Text("Add Feature", size=11,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=5, tight=True),
            on_click=self._add_feature_empty,
            height=38, bgcolor=SUCCESS,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        return self._section_card(
            "✨", "Features / Why Choose Us",
            "Up to 6 feature cards shown on the front page",
            [self.feature_rows_container, add_btn],
            accent=SUCCESS)

    def _add_feature_row(self, icon_val, title_val, text_val):
        icon_field = self._field("Icon", icon_val,
                                 hint_text="e.g. fa-mosque")
        title_field = self._field("Title", title_val)
        text_field = self._field("Description", text_val)

        entry = {"icon": icon_field, "title": title_field,
                 "text": text_field, "row": None}

        def remove(ev, _entry=entry):
            try:
                self.feature_entries.remove(_entry)
                self.feature_rows_container.controls.remove(
                    _entry["row"])
                try:
                    self.feature_rows_container.update()
                except Exception:
                    pass
            except Exception as ex:
                print(f"[FRONTPAGE] remove feature failed: {ex}")

        row = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Container(content=icon_field, width=150),
                    ft.Container(content=title_field, expand=True),
                ], spacing=8),
                ft.Row([
                    ft.Container(content=text_field, expand=True),
                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                                  icon_color=DANGER,
                                  on_click=remove),
                ], spacing=6),
            ], spacing=6),
            padding=10, bgcolor="#f8fafc",
            border=ft.Border.all(1, BORDER),
            border_radius=10)

        entry["row"] = row
        self.feature_entries.append(entry)
        self.feature_rows_container.controls.append(row)
        return entry

    def _add_feature_empty(self, e=None):
        if self.feature_rows_container is None:
            self._set_status("⚠️ Feature container not ready.", DANGER)
            return
        try:
            self._add_feature_row("fa-check-circle", "", "")
            try:
                self.feature_rows_container.update()
            except Exception as ue:
                print(f"[FRONTPAGE] container.update() failed: {ue}")
        except Exception as ex:
            self._set_status(f"❌ Failed to add feature: {ex}", DANGER)


# =================================================================================
# §5 — PACKAGES
# =================================================================================
    def _section_5_packages(self):
        p = self.cfg.get("packages", {})

        self.pkg_title = self._field("Section title", p.get("title", ""))
        self.pkg_subtitle = self._field("Section subtitle",
                                        p.get("subtitle", ""))

        self.pkg_source = ft.Dropdown(
            label="Package source",
            value=p.get("source", "batches"),
            options=[
                ft.dropdown.Option("batches", "Batches (recommended)"),
                ft.dropdown.Option("manual", "Manual list (JSON, advanced)"),
            ],
            text_size=12)
        self.pkg_source.on_change = self._on_pkg_source_change

        max_shown_val = p.get("max_shown", MAX_PACKAGES_SHOWN_DEFAULT)
        try:
            max_shown_val_int = int(max_shown_val or 0)
        except Exception:
            max_shown_val_int = MAX_PACKAGES_SHOWN_DEFAULT
        if max_shown_val_int <= 0:
            max_shown_val_int = MAX_PACKAGES_SHOWN_DEFAULT
        self.pkg_max_shown = self._field(
            f"Max packages shown (default {MAX_PACKAGES_SHOWN_DEFAULT})",
            str(max_shown_val_int))

        select_all_btn = ft.TextButton(
            content=ft.Text("✓ All", size=11, color=SUCCESS),
            on_click=lambda e: self._toggle_batches(True))
        clear_all_btn = ft.TextButton(
            content=ft.Text("✗ Clear", size=11, color=DANGER),
            on_click=lambda e: self._toggle_batches(False))

        selected_ids = set()
        try:
            for x in (p.get("selected_batch_ids") or []):
                selected_ids.add(str(x).strip())
        except Exception:
            pass

        self._batch_check_state = {}
        self.batch_checkboxes = {}

        for b in self.all_batches:
            bid = str(b.get("id", "")).strip()
            self._batch_check_state[bid] = (bid in selected_ids)

        self.pkg_batch_container = ft.Column(spacing=4)
        self._rebuild_batch_rows()

        self._batch_ui = ft.Column([
            ft.Row([
                ft.Text("Batches to show as packages:",
                        size=11, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                select_all_btn,
                clear_all_btn,
            ], spacing=4),
            ft.Text(
                "Tap a row to toggle. Auto-saves instantly.",
                size=10, color=MUTED, italic=True),
            self.pkg_batch_container,
        ], spacing=8)

        self._update_source_visibility()

        return self._section_card(
            "📦", "Packages Section",
            "Packages drawn from real batches (auto-updated)",
            [
                self.pkg_title,
                self.pkg_subtitle,
                self._two_col(self.pkg_source, self.pkg_max_shown),
                self._batch_ui,
            ], accent=ACCENT)

    def _make_batch_row(self, batch_id, name, status, price_str,
                        is_checked):
        icon = ft.Icon(
            icon=(ft.Icons.CHECK_BOX if is_checked
                  else ft.Icons.CHECK_BOX_OUTLINE_BLANK),
            color=SUCCESS if is_checked else MUTED,
            size=20,
        )
        label = ft.Text(
            f"{name}  ·  {status}  ·  {price_str}",
            size=11, expand=True,
            color="#0f172a" if is_checked else MUTED,
        )
        inner_row = ft.Row(
            [icon, label],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        container = ft.Container(
            content=inner_row,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            bgcolor="#ecfdf5" if is_checked else "#f8fafc",
            border=ft.Border.all(
                1, "#a7f3d0" if is_checked else "#e2e8f0"),
            border_radius=8,
            ink=True,
            on_click=lambda e, _bid=batch_id:
                self._toggle_batch_row_by_id(_bid),
        )
        self.batch_checkboxes[batch_id] = {
            "container": container,
            "icon": icon,
            "label": label,
        }
        return container

    def _rebuild_batch_rows(self):
        if self.pkg_batch_container is None:
            return

        self.pkg_batch_container.controls.clear()
        self.batch_checkboxes = {}

        if not self.all_batches:
            self.pkg_batch_container.controls.append(
                ft.Text("No batches found. Add some in the "
                        "Batches tab first.", size=11, color=MUTED))
            return

        for b in self.all_batches:
            bid = str(b.get("id", "")).strip()
            name = str(b.get("batch_name", bid))
            status = str(b.get("status", ""))
            price = b.get("price", 0)
            try:
                price_str = f"₹{float(price):,.0f}"
            except Exception:
                price_str = f"₹{price}"
            is_checked = self._batch_check_state.get(bid, False)
            row = self._make_batch_row(
                bid, name, status, price_str, is_checked)
            self.pkg_batch_container.controls.append(row)

    def _toggle_batch_row_by_id(self, batch_id):
        entry = self.batch_checkboxes.get(batch_id)
        if not entry:
            return

        current = bool(self._batch_check_state.get(batch_id, False))
        new_val = not current
        self._batch_check_state[batch_id] = new_val

        try:
            entry["icon"].icon = (
                ft.Icons.CHECK_BOX if new_val
                else ft.Icons.CHECK_BOX_OUTLINE_BLANK)
            entry["icon"].color = SUCCESS if new_val else MUTED
            entry["label"].color = "#0f172a" if new_val else MUTED
            entry["container"].bgcolor = (
                "#ecfdf5" if new_val else "#f8fafc")
            entry["container"].border = ft.Border.all(
                1, "#a7f3d0" if new_val else "#e2e8f0")

            for k in ("icon", "label", "container"):
                try:
                    entry[k].update()
                except Exception:
                    pass
        except Exception:
            pass

        self._auto_save_batch_state()
        n = sum(1 for v in self._batch_check_state.values() if v)
        self._set_status(
            f"✓ Batch toggled — {n} selected (auto-saved)", PRIMARY_LT)

    def _on_pkg_source_change(self, e=None):
        self._update_source_visibility()
        self._safe_update()

    def _update_source_visibility(self):
        try:
            is_batches = (self.pkg_source.value or "batches") == "batches"
            if self._batch_ui is not None:
                self._batch_ui.visible = is_batches
        except Exception:
            pass

    def _toggle_batches(self, value):
        for bid, entry in self.batch_checkboxes.items():
            self._batch_check_state[bid] = bool(value)
            try:
                entry["icon"].icon = (
                    ft.Icons.CHECK_BOX if value
                    else ft.Icons.CHECK_BOX_OUTLINE_BLANK)
                entry["icon"].color = SUCCESS if value else MUTED
                entry["label"].color = "#0f172a" if value else MUTED
                entry["container"].bgcolor = (
                    "#ecfdf5" if value else "#f8fafc")
                entry["container"].border = ft.Border.all(
                    1, "#a7f3d0" if value else "#e2e8f0")
                for k in ("icon", "label", "container"):
                    try:
                        entry[k].update()
                    except Exception:
                        pass
            except Exception:
                pass

        self._auto_save_batch_state()
        n = sum(1 for v in self._batch_check_state.values() if v)
        self._set_status(
            f"✓ {'All' if value else 'None'} selected — "
            f"{n} batch(es) (auto-saved)", PRIMARY_LT)

    def _auto_save_batch_state(self):
        try:
            from core.frontpage_config import (
                load_config, save_config, normalize_batch_ids)

            checked = [
                bid for bid, is_on
                in self._batch_check_state.items() if is_on
            ]
            checked = normalize_batch_ids(checked)

            cfg = load_config()
            pkg = cfg.setdefault("packages", {})
            pkg["selected_batch_ids"] = checked

            ok = save_config(cfg)
            if ok:
                try:
                    self.cfg.setdefault("packages", {})[
                        "selected_batch_ids"] = checked
                except Exception:
                    pass
        except Exception as e:
            print(f"[FRONTPAGE] auto-save error: {e}")


# =================================================================================
# §6 — ABOUT
# =================================================================================
    def _section_6_about(self):
        a = self.cfg.get("about", {})
        self.about_heading = self._field("Heading", a.get("heading", ""))
        self.about_p1 = self._field(
            "Paragraph 1", a.get("paragraph1", ""),
            multiline=True, min_lines=3, max_lines=5)
        self.about_p2 = self._field(
            "Paragraph 2", a.get("paragraph2", ""),
            multiline=True, min_lines=3, max_lines=5)

        self.stats_rows_container = ft.Column(spacing=8)
        self.stat_entries = []

        for st in (a.get("stats") or []):
            self._add_stat_row(st.get("number", ""), st.get("label", ""))

        add_stat_btn = ft.Button(
            content=ft.Row([
                ft.Icon(icon=ft.Icons.ADD, size=14,
                        color=ft.Colors.WHITE),
                ft.Text("Add Statistic", size=11,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=5, tight=True),
            on_click=self._add_stat_empty,
            height=38, bgcolor=SUCCESS,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        return self._section_card(
            "📖", "About Section",
            "The 'About Us' block with statistics",
            [
                self.about_heading,
                self.about_p1,
                self.about_p2,
                ft.Container(height=4),
                ft.Text("Statistics (4 recommended)",
                        size=12, weight=ft.FontWeight.BOLD,
                        color="#0f172a"),
                self.stats_rows_container,
                add_stat_btn,
            ])

    def _add_stat_row(self, number_val, label_val):
        num_field = self._field("Number", number_val,
                                hint_text="e.g. 25+")
        lbl_field = self._field("Label", label_val,
                                hint_text="e.g. Years Experience")

        entry = {"number": num_field, "label": lbl_field, "row": None}

        def remove(ev, _entry=entry):
            try:
                self.stat_entries.remove(_entry)
                self.stats_rows_container.controls.remove(_entry["row"])
                try:
                    self.stats_rows_container.update()
                except Exception:
                    pass
            except Exception:
                pass

        row = ft.Container(
            content=ft.Row([
                ft.Container(content=num_field, width=140),
                ft.Container(content=lbl_field, expand=True),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                              icon_color=DANGER, on_click=remove),
            ], spacing=6,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=8, bgcolor="#f8fafc",
            border=ft.Border.all(1, BORDER),
            border_radius=10)

        entry["row"] = row
        self.stat_entries.append(entry)
        self.stats_rows_container.controls.append(row)
        return entry

    def _add_stat_empty(self, e=None):
        if self.stats_rows_container is None:
            self._set_status("⚠️ Stat container not ready.", DANGER)
            return
        try:
            self._add_stat_row("", "")
            try:
                self.stats_rows_container.update()
            except Exception as ue:
                print(f"[FRONTPAGE] stats container.update() failed: {ue}")
        except Exception as ex:
            self._set_status(f"❌ Failed to add statistic: {ex}", DANGER)


# =================================================================================
# §7 — CONTACT
# =================================================================================
    def _section_7_contact(self):
        c = self.cfg.get("contact", {})
        self.contact_phone = self._field(
            "Primary phone", c.get("phone", ""))
        self.contact_phone2 = self._field(
            "Secondary phone (optional)", c.get("phone2", ""))
        self.contact_email = self._field("Email", c.get("email", ""))
        self.contact_whatsapp = self._field(
            "WhatsApp (country code, no +)", c.get("whatsapp", ""),
            hint_text="e.g. 919876543210")
        self.contact_addr1 = self._field(
            "Address line 1", c.get("address_line1", ""))
        self.contact_addr2 = self._field(
            "Address line 2", c.get("address_line2", ""))

        return self._section_card(
            "📞", "Contact Information",
            "Shown in top bar, contact section, and footer",
            [
                self._two_col(self.contact_phone, self.contact_phone2),
                self._two_col(self.contact_email, self.contact_whatsapp),
                self._two_col(self.contact_addr1, self.contact_addr2),
            ])


# =================================================================================
# §8 — SOCIAL
# =================================================================================
    def _section_8_social(self):
        s = self.cfg.get("social", {})
        self.social_facebook = self._field(
            "Facebook URL", s.get("facebook", ""))
        self.social_instagram = self._field(
            "Instagram URL", s.get("instagram", ""))
        self.social_twitter = self._field(
            "Twitter / X URL", s.get("twitter", ""))

        return self._section_card(
            "🔗", "Social Links",
            "Leave empty to hide a network",
            [
                self._two_col(self.social_facebook,
                              self.social_instagram),
                self.social_twitter,
            ])


# =================================================================================
# §9 — FOOTER
# =================================================================================
    def _section_9_footer(self):
        f = self.cfg.get("footer", {})
        self.footer_about = self._field(
            "Footer about text", f.get("about_text", ""),
            multiline=True, min_lines=2, max_lines=3)
        self.footer_copyright = self._field(
            "Copyright text", f.get("copyright", ""))

        return self._section_card(
            "📝", "Footer",
            "Bottom-of-page content",
            [self.footer_about, self.footer_copyright])


# =================================================================================
# §11 — GALLERY
# =================================================================================
    def _section_11_gallery(self):
        g = self.cfg.get("gallery", {}) or {}

        self.gallery_enabled = ft.Switch(
            label="Show gallery on front page",
            value=bool(g.get("enabled", True)),
            active_color=ACCENT)
        self.gallery_title = self._field(
            "Section title", g.get("title", ""))
        self.gallery_subtitle = self._field(
            "Section subtitle", g.get("subtitle", ""))
        self.gallery_max_photos = self._field(
            "Max photos shown", str(g.get("max_photos_shown", 12)))
        self.gallery_max_videos = self._field(
            "Max videos shown", str(g.get("max_videos_shown", 6)))

        self.photo_list = list(g.get("photos", []) or [])
        self.video_list = list(g.get("videos", []) or [])

        self.photo_list_container = ft.Column(spacing=6)
        self.video_list_container = ft.Column(spacing=6)
        self.gallery_stats_label = ft.Text(
            self._gallery_stats_text(), size=10, color=MUTED, italic=True)

        self._rebuild_gallery_lists()

        refresh_btn = ft.TextButton(
            content=ft.Row([
                ft.Icon(icon=ft.Icons.REFRESH, size=12,
                        color=PRIMARY_LT),
                ft.Text("Refresh Gallery", size=10,
                        color=PRIMARY_LT,
                        weight=ft.FontWeight.BOLD),
            ], spacing=4, tight=True),
            on_click=self._refresh_gallery_click)

        upload_photo_btn = ft.Button(
            content=ft.Row([
                ft.Icon(icon=ft.Icons.ADD_PHOTO_ALTERNATE, size=14,
                        color=ft.Colors.WHITE),
                ft.Text("Add Photos", size=11,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=5, tight=True),
            on_click=lambda e: self._pick_gallery_files("photos"),
            height=38, bgcolor=SUCCESS,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        upload_video_btn = ft.Button(
            content=ft.Row([
                ft.Icon(icon=ft.Icons.VIDEO_LIBRARY, size=14,
                        color=ft.Colors.WHITE),
                ft.Text("Add Videos", size=11,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=5, tight=True),
            on_click=lambda e: self._pick_gallery_files("videos"),
            height=38, bgcolor=ACCENT,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        photos_header = ft.Row([
            ft.Text("📷 Photos", size=12,
                    weight=ft.FontWeight.BOLD, color="#0f172a"),
            ft.Container(expand=True),
            refresh_btn,
            upload_photo_btn,
        ], spacing=8)

        videos_header = ft.Row([
            ft.Text("🎥 Videos", size=12,
                    weight=ft.FontWeight.BOLD, color="#0f172a"),
            ft.Container(expand=True),
            upload_video_btn,
        ], spacing=8)

        return self._section_card(
            "🖼️", "Gallery — Pilgrim Attractions",
            "Upload photos and videos that appear on the public page.",
            [
                self.gallery_enabled,
                self._two_col(self.gallery_title, self.gallery_subtitle),
                self._two_col(self.gallery_max_photos,
                              self.gallery_max_videos),
                self.gallery_stats_label,
                ft.Divider(height=1, color=BORDER),
                photos_header,
                self.photo_list_container,
                ft.Divider(height=1, color=BORDER),
                videos_header,
                self.video_list_container,
            ], accent=ACCENT)

    def _rebuild_gallery_lists(self):
        if self.photo_list_container is None:
            return

        self.photo_list_container.controls.clear()
        if not self.photo_list:
            self.photo_list_container.controls.append(
                ft.Text("No photos yet. Click 'Add Photos' to upload.",
                        size=10, color=MUTED, italic=True))
        else:
            for item in self.photo_list:
                self.photo_list_container.controls.append(
                    self._gallery_item_row(item, "photos"))

        self.video_list_container.controls.clear()
        if not self.video_list:
            self.video_list_container.controls.append(
                ft.Text("No videos yet. Click 'Add Videos' to upload.",
                        size=10, color=MUTED, italic=True))
        else:
            for item in self.video_list:
                self.video_list_container.controls.append(
                    self._gallery_item_row(item, "videos"))

        try:
            if self.gallery_stats_label is not None:
                self.gallery_stats_label.value = self._gallery_stats_text()
        except Exception:
            pass

    def _gallery_stats_text(self):
        total_bytes = (sum(int(x.get("size", 0) or 0)
                           for x in (self.photo_list or []))
                       + sum(int(x.get("size", 0) or 0)
                             for x in (self.video_list or [])))

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

        return (f"{len(self.photo_list)} photos · "
                f"{len(self.video_list)} videos · "
                f"{_human(total_bytes)} total")

    def _gallery_item_row(self, item, media_type):
        url = item.get("url", "")
        caption = item.get("caption", "")
        size_kb = int((item.get("size", 0) or 0) // 1024)
        original = item.get("original_name", "")

        if media_type == "photos":
            img_kwargs = dict(src=url, width=56, height=56,
                              border_radius=6)
            if _FIT_COVER is not None:
                img_kwargs["fit"] = _FIT_COVER
            thumb = ft.Container(
                content=ft.Image(**img_kwargs),
                width=56, height=56,
                border=ft.Border.all(1, BORDER), border_radius=6)
        else:
            thumb = ft.Container(
                content=ft.Icon(icon=ft.Icons.PLAY_CIRCLE_FILLED,
                                size=32, color=ACCENT),
                width=56, height=56,
                alignment=ft.Alignment.CENTER,
                bgcolor="#f1f5f9", border_radius=6,
                border=ft.Border.all(1, BORDER))

        caption_field = self._field("Caption (optional)", caption)

        def _save_caption(ev, _item=item, _field=caption_field):
            new_cap = (_field.value or "").strip()
            if new_cap != (_item.get("caption") or ""):
                _item["caption"] = new_cap
                self._save_silent()

        caption_field.on_blur = _save_caption

        def _remove(ev, _item=item, _mt=media_type):
            self._remove_gallery_item(_mt, _item)

        return ft.Container(
            content=ft.Row([
                thumb,
                ft.Column([
                    ft.Text(original or url, size=10, color=PRIMARY_LT,
                            selectable=True, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(url, size=9, color=MUTED,
                            selectable=True, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    caption_field,
                ], spacing=4, expand=True),
                ft.Column([
                    ft.Text(f"{size_kb} KB", size=9, color=MUTED),
                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                                  icon_color=DANGER, tooltip="Delete",
                                  on_click=_remove),
                ], spacing=2,
                   horizontal_alignment=ft.CrossAxisAlignment.END),
            ], spacing=8,
               vertical_alignment=ft.CrossAxisAlignment.START),
            padding=8, bgcolor="#f8fafc",
            border=ft.Border.all(1, BORDER), border_radius=10)

    def _refresh_gallery_click(self, e=None):
        try:
            self._reload_gallery_from_disk(show_toast=True, force=True)
        except Exception as ex:
            self._set_status(f"⚠️ {ex}", DANGER)

    def _reload_gallery_from_disk(self, show_toast=False, force=False):
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
        g = (cfg.get("gallery") or {}) if cfg else {}
        new_photos = list(g.get("photos", []) or [])
        new_videos = list(g.get("videos", []) or [])

        changed = (len(new_photos) != len(self.photo_list)
                   or len(new_videos) != len(self.video_list))

        if not changed and not force:
            return False

        self.photo_list = new_photos
        self.video_list = new_videos
        try:
            self.cfg.setdefault("gallery", {})
            self.cfg["gallery"]["photos"] = new_photos
            self.cfg["gallery"]["videos"] = new_videos
        except Exception:
            pass

        self._rebuild_gallery_lists()
        try:
            self.photo_list_container.update()
        except Exception:
            pass
        try:
            self.video_list_container.update()
        except Exception:
            pass
        try:
            self.gallery_stats_label.update()
        except Exception:
            pass

        if show_toast:
            if changed:
                self._set_status(
                    f"🔄 Gallery refreshed — "
                    f"{len(new_photos)} photos, "
                    f"{len(new_videos)} videos", SUCCESS)
            else:
                self._set_status(
                    f"✓ Gallery up to date — "
                    f"{len(new_photos)} photos, "
                    f"{len(new_videos)} videos", PRIMARY_LT)
        return changed

    def _pick_gallery_files(self, media_type):
        admin_key = os.getenv("ADMIN_API_KEY", "")

        if admin_key:
            url = f"/gallery-upload?type={media_type}&key={admin_key}"
        else:
            url = f"/gallery-upload?type={media_type}"

        async def _go():
            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url(url,
                                        web_only_window_name="_blank")
                if asyncio.iscoroutine(r):
                    await r
                return
            except TypeError:
                pass
            except Exception:
                pass
            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url(url,
                                        web_window_name="_blank")
                if asyncio.iscoroutine(r):
                    await r
                return
            except Exception:
                pass
            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url(url)
                if asyncio.iscoroutine(r):
                    await r
            except Exception:
                pass

        try:
            self.page_ref.run_task(_go)
        except Exception as ex:
            self._set_status(f"⚠️ Could not open upload page: {ex}",
                             DANGER)

    def _remove_gallery_item(self, media_type, item):
        url = item.get("url", "")
        caption = item.get("caption", "") or url

        def do_delete(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
            import httpx
            admin_key = os.getenv("ADMIN_API_KEY", "")
            headers = {}
            if admin_key:
                headers["Authorization"] = f"Bearer {admin_key}"

            async def _del():
                try:
                    async with httpx.AsyncClient(
                            base_url="http://127.0.0.1:8080",
                            timeout=30.0) as cli:
                        await cli.request(
                            "DELETE", "/api/admin/gallery/item",
                            params={"media_type": media_type,
                                    "url": url},
                            headers=headers)
                except Exception:
                    pass

            try:
                self.page_ref.run_task(_del)
            except Exception:
                pass

            if media_type == "photos":
                self.photo_list = [x for x in self.photo_list
                                   if x.get("url") != url]
            else:
                self.video_list = [x for x in self.video_list
                                   if x.get("url") != url]
            self._rebuild_gallery_lists()
            self._safe_update(force=True)
            self._set_status("🗑️ Deleted", WARN)

        def cancel(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(icon=ft.Icons.WARNING_AMBER, color=DANGER),
                ft.Text("Delete this item?",
                        weight=ft.FontWeight.BOLD, size=14),
            ], spacing=8),
            content=ft.Text(
                f"This will remove the file from the volume and "
                f"from the gallery config.\n\n{caption}",
                size=11),
            actions=[
                ft.TextButton(content=ft.Text("Cancel", size=11),
                              on_click=cancel),
                ft.Button(
                    content=ft.Text("Delete", size=11,
                                    color=ft.Colors.WHITE,
                                    weight=ft.FontWeight.BOLD),
                    on_click=do_delete, bgcolor=DANGER),
            ])
        self.page_ref.show_dialog(dlg)

    def _register_pickers(self):
        if self._pickers_registered:
            return
        try:
            for p in (self.photo_picker, self.video_picker):
                if hasattr(self.page_ref, "services"):
                    if p not in self.page_ref.services:
                        self.page_ref.services.append(p)
                elif hasattr(self.page_ref, "overlay"):
                    if p not in self.page_ref.overlay:
                        self.page_ref.overlay.append(p)
            self._pickers_registered = True
        except Exception as ex:
            print(f"[FRONTPAGE] picker registration failed: {ex}")

    def _save_silent(self):
        try:
            cfg = self._collect_config()
            save_config(cfg)
            self.cfg = cfg
        except Exception as ex:
            print(f"[FRONTPAGE] silent save failed: {ex}")


# =================================================================================
# §10 — ACTION BAR
# =================================================================================
    def _section_10_action_bar(self):
        save_btn = ft.Button(
            content=ft.Row([
                ft.Icon(icon=ft.Icons.SAVE, size=16,
                        color=ft.Colors.WHITE),
                ft.Text("Save", size=12, color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6, tight=True),
            on_click=self._save, height=44, bgcolor=SUCCESS,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        reload_btn = ft.Button(
            content=ft.Row([
                ft.Icon(icon=ft.Icons.REFRESH, size=16,
                        color=ft.Colors.WHITE),
                ft.Text("Reload", size=12, color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6, tight=True),
            on_click=self.refresh, height=44, bgcolor="#0ea5e9",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        preview_btn = ft.Button(
            content=ft.Row([
                ft.Icon(icon=ft.Icons.OPEN_IN_NEW, size=16,
                        color=ft.Colors.WHITE),
                ft.Text("Preview", size=12, color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6, tight=True),
            on_click=self._open_preview, height=44, bgcolor=ACCENT,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        reset_btn = ft.TextButton(
            content=ft.Text("↺ Reset", size=11, color=DANGER),
            on_click=self._reset_confirm)

        self.status_label = ft.Text(
            "Ready. Edit fields and click Save.",
            size=10, color=MUTED, italic=True)

        return ft.Container(
            content=ft.Column([
                ft.Row([save_btn, reload_btn], spacing=8),
                ft.Row([preview_btn, reset_btn], spacing=8),
                ft.Divider(height=1, color=BORDER),
                self.status_label,
            ], spacing=10),
            padding=14, bgcolor=SECTION_BG,
            border=ft.Border.all(1, BORDER), border_radius=14)


# =================================================================================
# §A — ACTIONS
# =================================================================================
    def _v(self, field):
        try:
            return (field.value or "").strip()
        except Exception:
            return ""

    def _collect_config(self):
        def _int(field, default):
            try:
                s = self._v(field)
                if not s:
                    return default
                return int(s)
            except Exception:
                return default

        max_shown = _int(self.pkg_max_shown, MAX_PACKAGES_SHOWN_DEFAULT)
        if max_shown <= 0:
            max_shown = MAX_PACKAGES_SHOWN_DEFAULT

        selected_ids = []
        try:
            for bid, checked in self._batch_check_state.items():
                if checked:
                    selected_ids.append(str(bid).strip())
        except Exception:
            pass

        features = []
        for entry in self.feature_entries:
            title = self._v(entry["title"])
            text = self._v(entry["text"])
            if not title and not text:
                continue
            features.append({
                "icon": (self._v(entry["icon"]) or
                         "fa-check-circle"),
                "title": title, "text": text,
            })

        stats = []
        for entry in self.stat_entries:
            number = self._v(entry["number"])
            label = self._v(entry["label"])
            if not number and not label:
                continue
            stats.append({"number": number, "label": label})

        max_photos = _int(self.gallery_max_photos, 12)
        if max_photos < 1:
            max_photos = 12
        max_videos = _int(self.gallery_max_videos, 6)
        if max_videos < 1:
            max_videos = 6

        return {
            "hero": {
                "heading": self._v(self.hero_heading),
                "subheading": self._v(self.hero_subheading),
                "button_text": self._v(self.hero_button),
                "whatsapp_text": self._v(self.hero_whatsapp),
            },
            "alert": {
                "enabled": bool(self.alert_enabled.value),
                "message": self._v(self.alert_message),
                "link": self._v(self.alert_link) or "#",
                "color": self._v(self.alert_color) or "#f39c12",
                "style": (self.alert_style.value or "pulse"),
            },
            "features": features,
            "packages": {
                "title": self._v(self.pkg_title),
                "subtitle": self._v(self.pkg_subtitle),
                "source": (self.pkg_source.value or "batches"),
                "max_shown": max_shown,
                "selected_batch_ids": selected_ids,
                "manual": [],
            },
            "about": {
                "heading": self._v(self.about_heading),
                "paragraph1": self._v(self.about_p1),
                "paragraph2": self._v(self.about_p2),
                "stats": stats,
            },
            "contact": {
                "phone": self._v(self.contact_phone),
                "phone2": self._v(self.contact_phone2),
                "email": self._v(self.contact_email),
                "whatsapp": self._v(self.contact_whatsapp),
                "address_line1": self._v(self.contact_addr1),
                "address_line2": self._v(self.contact_addr2),
            },
            "social": {
                "facebook": self._v(self.social_facebook),
                "instagram": self._v(self.social_instagram),
                "twitter": self._v(self.social_twitter),
            },
            "footer": {
                "about_text": self._v(self.footer_about),
                "copyright": self._v(self.footer_copyright),
            },
            "gallery": {
                "enabled": bool(self.gallery_enabled.value),
                "title": self._v(self.gallery_title),
                "subtitle": self._v(self.gallery_subtitle),
                "layout": "grid",
                "max_photos_shown": max_photos,
                "max_videos_shown": max_videos,
                "photos": list(self.photo_list),
                "videos": list(self.video_list),
            },
        }

    def _summarize_changes(self, old_cfg, new_cfg):
        friendly = {
            "hero": "hero", "alert": "alert",
            "features": "features", "packages": "packages",
            "about": "about", "contact": "contact",
            "social": "social links", "footer": "footer",
            "gallery": "gallery"}
        changes = []
        for key, label in friendly.items():
            try:
                if old_cfg.get(key) != new_cfg.get(key):
                    if key == "packages":
                        n = len((new_cfg.get("packages") or {})
                                .get("selected_batch_ids") or [])
                        changes.append(f"{n} batch(es)")
                    elif key == "gallery":
                        np = len((new_cfg.get("gallery") or {})
                                 .get("photos") or [])
                        nv = len((new_cfg.get("gallery") or {})
                                 .get("videos") or [])
                        changes.append(f"gallery ({np}p, {nv}v)")
                    else:
                        changes.append(label)
            except Exception:
                pass
        return changes

    def _save(self, e=None):
        if self._saving:
            return
        self._saving = True
        try:
            try:
                old_cfg = load_config()
            except Exception:
                old_cfg = self.cfg or {}

            cfg = self._collect_config()
            n_sel = len(cfg.get("packages", {})
                         .get("selected_batch_ids", []))
            changes = self._summarize_changes(old_cfg, cfg)

            ok = save_config(cfg)
            if ok:
                self.cfg = cfg
                if changes:
                    summary = ", ".join(changes)
                    txt = (f"✅ Saved: {summary}  ·  "
                           f"{datetime.now().strftime('%H:%M:%S')}")
                else:
                    txt = (f"✅ Saved (no changes)  ·  "
                           f"{datetime.now().strftime('%H:%M:%S')}")
                if n_sel:
                    txt += f"  ·  {n_sel} batch(es) selected"
                self._set_status(txt, SUCCESS)
                try:
                    self.db.log_activity(
                        self.current_user.get("id"),
                        "update_frontpage",
                        f"Updated front page ({', '.join(changes) or 'no changes'})")
                except Exception:
                    pass
            else:
                self._set_status("❌ Save failed", DANGER)
        except Exception as ex:
            traceback.print_exc()
            self._set_status(f"❌ {ex}", DANGER)
        finally:
            self._saving = False

    def _reset_confirm(self, e=None):
        def do_reset(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
            ok = save_config(DEFAULT_CONFIG)
            if ok:
                self._set_status("↺ Reset to defaults", SUCCESS)
                self.refresh()
            else:
                self._set_status("❌ Reset failed", DANGER)

        def cancel(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(icon=ft.Icons.WARNING_AMBER, color=DANGER),
                ft.Text("Reset to Defaults?",
                        weight=ft.FontWeight.BOLD, size=14),
            ], spacing=8),
            content=ft.Text(
                "This will discard your custom front-page settings "
                "and restore the original defaults.\n\n"
                "⚠️ The gallery will also be cleared (config only — "
                "the media files on disk are kept).\n\n"
                "This cannot be undone.", size=11),
            actions=[
                ft.TextButton(content=ft.Text("Cancel", size=11),
                              on_click=cancel),
                ft.Button(
                    content=ft.Text("Reset", size=11,
                                    color=ft.Colors.WHITE,
                                    weight=ft.FontWeight.BOLD),
                    on_click=do_reset, bgcolor=DANGER),
            ])
        self.page_ref.show_dialog(dlg)

    def _open_preview(self, e=None):
        try:
            async def _do():
                try:
                    launcher = ft.UrlLauncher()
                    await launcher.launch_url("/")
                except Exception:
                    pass
            try:
                self.page_ref.run_task(_do)
                self._set_status("🔗 Opening front page…", PRIMARY_LT)
                return
            except Exception:
                pass
            try:
                self.page_ref.url = "/"
                self._set_status("🔗 Opened front page", PRIMARY_LT)
                return
            except Exception:
                pass
            self._set_status("⚠️ Could not open preview", WARN)
        except Exception as ex:
            self._set_status(f"⚠️ {ex}", WARN)

    def _set_status(self, message, color=PRIMARY_LT):
        try:
            if self.status_label is not None:
                self.status_label.value = message
                self.status_label.color = color
                self.status_label.update()
        except Exception as e:
            print(f"[FRONTPAGE] _set_status failed: {e}")

    def _safe_update(self, force=False):
        if not force:
            remaining = self._typing_until - time.time()
            if remaining > 0:
                return

        try:
            if self._inner_column is not None:
                self._inner_column.update()
                return
        except Exception as e:
            print(f"[FRONTPAGE] inner_column.update() failed: {e}")

        try:
            if self.root is not None:
                self.root.update()
        except Exception as e:
            print(f"[FRONTPAGE] root.update() also failed: {e}")


# =================================================================================
# SECTION END — core/frontpage_settings_tab.py v3.31
# =================================================================================