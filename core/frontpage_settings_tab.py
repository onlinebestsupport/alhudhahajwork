# =================================================================================
# core/frontpage_settings_tab.py — Front Page Settings
# =================================================================================
# v3.18 — Per-control .update() for All / Clear and row toggle
#   • §[5.0b] _toggle_batch_row_by_id — flushes icon, label, container
#     individually, then page.update() at the end
#   • §[5.3]  _toggle_batches         — same treatment for All / Clear
#   • Fixes: "All/Clear buttons don't refresh the visuals"
#
# v3.17 preserved:
#   • §[5.0] on_click attached to every nested element (container, row,
#     icon, label) so a tap anywhere on the row fires
#
# v3.15 preserved:
#   • ft.Icon(icon=...)  — Flet 1.0 API (not name=)
#
# v3.14 preserved:
#   • Custom clickable rows replace ft.Checkbox — no stale-value bug
#   • Authoritative self._batch_check_state dict is the source of truth
#
# SECTION INDEX
#   [0]      Class setup: __init__ / build / refresh / _load_batches / _error_ui
#   [ROOT]   _build_root
#   [H]      Shared helpers: _section_card / _field / _two_col
#   [1]      Header banner
#   [2]      Hero
#   [3]      Alert
#   [4]      Features / _add_feature_row / _add_feature_empty
#   [5]      Packages / _make_batch_row / _toggle_batch_row_by_id
#            / _on_pkg_source_change / _update_source_visibility
#            / _toggle_batches
#   [6]      About / _add_stat_row / _add_stat_empty
#   [7]      Contact
#   [8]      Social
#   [9]      Footer
#   [11]     Gallery / _rebuild_gallery_lists / _gallery_stats_text
#            / _gallery_item_row / _pick_gallery_files / _upload_files
#            / _remove_gallery_item / _register_pickers / _save_silent
#   [10]     Action bar
#   [A]      Actions: _collect_config / _save / _reset_confirm
#            / _open_preview / _set_status / _snack / _safe_update
# =================================================================================

import asyncio
import json
import traceback
from datetime import datetime

import flet as ft

from core.frontpage_config import (
    DEFAULT_CONFIG, load_config, save_config, _deep_merge,
    gallery_dir, gallery_summary)


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


# =================================================================================
# [0] class FrontPageSettingsTab
# =================================================================================
class FrontPageSettingsTab:

    # -----------------------------------------------------------------------------
    # [0.1] __init__ — constructor
    # -----------------------------------------------------------------------------
    def __init__(self, page, db, current_user):
        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}
        self.cfg = load_config()
        self.all_batches = []
        self.batch_checkboxes = {}

        # ---- Form field handles (all set to None; populated by section builders) ----
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

        # Authoritative batch selection (written by _toggle_batch_row_by_id)
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

        # Gallery
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

        # Action bar
        self.status_label = None
        self.root = None

        # Build
        try:
            self._load_batches()
            self._build_root()
        except Exception as e:
            print(f"[FRONTPAGE] build failed: {e}")
            traceback.print_exc()
            self.root = self._error_ui(e)

    # -----------------------------------------------------------------------------
    # [0.2] build — return the root Container
    # -----------------------------------------------------------------------------
    def build(self):
        return self.root

    # -----------------------------------------------------------------------------
    # [0.3] refresh — reload config + batches and rebuild
    # -----------------------------------------------------------------------------
    def refresh(self, e=None):
        try:
            self.cfg = load_config()
            self._load_batches()
            self._build_root()
            self._safe_update()
        except Exception as ex:
            print(f"[FRONTPAGE] refresh failed: {ex}")
            traceback.print_exc()

    # -----------------------------------------------------------------------------
    # [0.4] _load_batches — pull batch list from DB
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # [0.5] _error_ui — fallback UI if build fails
    # -----------------------------------------------------------------------------
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

    # =============================================================================
    # [ROOT] _build_root — assemble full page in order
    # =============================================================================
    def _build_root(self):
        self.feature_entries = []
        self.stat_entries = []
        self.batch_checkboxes = {}

        inner_column = ft.Column(
            controls=[
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
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )

        self.root = ft.Container(
            content=inner_column,
            padding=10,
            bgcolor=PAGE_BG,
            expand=True,
        )

        self._register_pickers()

    # =============================================================================
    # [H] SHARED HELPERS
    # =============================================================================

    # -----------------------------------------------------------------------------
    # [H.1] _section_card — boxed section wrapper
    # -----------------------------------------------------------------------------
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
    # [H.2] _field — consistent TextField factory
    # -----------------------------------------------------------------------------
    def _field(self, label, value, **kwargs):
        defaults = dict(
            label=label,
            value=value or "",
            text_size=12,
            border_color=BORDER,
            focused_border_color=PRIMARY_LT,
            border_radius=8,
            content_padding=ft.Padding.symmetric(
                horizontal=10, vertical=10),
        )
        defaults.update(kwargs)
        return ft.TextField(**defaults)

    # -----------------------------------------------------------------------------
    # [H.3] _two_col — two controls side by side
    # -----------------------------------------------------------------------------
    def _two_col(self, left, right):
        return ft.Row([
            ft.Container(content=left, expand=True),
            ft.Container(content=right, expand=True),
        ], spacing=10,
           vertical_alignment=ft.CrossAxisAlignment.START)

    # =============================================================================
    # [1] HEADER BANNER
    # =============================================================================
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

    # =============================================================================
    # [2] HERO SECTION — heading, subheading, button text, whatsapp text
    # =============================================================================
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

    # =============================================================================
    # [3] ALERT BANNER
    # =============================================================================
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
            text_size=12,
            border_color=BORDER,
            focused_border_color=PRIMARY_LT,
            border_radius=8)

        return self._section_card(
            "⚠️", "Alert Banner",
            "Optional top-of-page announcement for visitors",
            [
                self.alert_enabled,
                self.alert_message,
                self.alert_link,
                self._two_col(self.alert_color, self.alert_style),
            ], accent=WARN)

    # =============================================================================
    # [4] FEATURES SECTION
    # =============================================================================
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

    # -----------------------------------------------------------------------------
    # [4.1] _add_feature_row
    # -----------------------------------------------------------------------------
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
                self._safe_update()
            except Exception:
                pass

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

    # -----------------------------------------------------------------------------
    # [4.2] _add_feature_empty
    # -----------------------------------------------------------------------------
    def _add_feature_empty(self, e=None):
        self._add_feature_row("fa-check-circle", "", "")
        self._safe_update()

    # =============================================================================
    # [5] PACKAGES SECTION
    # -----------------------------------------------------------------------------
    # Custom clickable rows replace ft.Checkbox. Each row's on_click is
    # attached to container, row, icon, and label — so a tap anywhere
    # fires. State lives in self._batch_check_state, never in a Flet
    # control property.
    # =============================================================================
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
            text_size=12,
            border_color=BORDER,
            focused_border_color=PRIMARY_LT,
            border_radius=8)
        self.pkg_source.on_change = self._on_pkg_source_change

        max_shown_val = p.get("max_shown", 0)
        try:
            max_shown_val_int = int(max_shown_val or 0)
        except Exception:
            max_shown_val_int = 0
        self.pkg_max_shown = self._field(
            "Max packages shown (0 = show all checked)",
            str(max_shown_val_int))

        select_all_btn = ft.TextButton(
            content=ft.Text("✓ All", size=11, color=SUCCESS),
            on_click=lambda e: self._toggle_batches(True))
        clear_all_btn = ft.TextButton(
            content=ft.Text("✗ Clear", size=11, color=DANGER),
            on_click=lambda e: self._toggle_batches(False))

        # Seed state dict from saved config
        selected_ids = set(str(x).strip() for x in
                           (p.get("selected_batch_ids") or []))
        self._batch_check_state = {}
        self.batch_checkboxes = {}

        batch_controls = []

        if not self.all_batches:
            batch_controls.append(
                ft.Text("No batches found. Add some in the "
                        "Batches tab first.", size=11, color=MUTED))
        else:
            for b in self.all_batches:
                bid = str(b.get("id", "")).strip()
                name = str(b.get("batch_name", bid))
                status = str(b.get("status", ""))
                price = b.get("price", 0)
                try:
                    price_str = f"₹{float(price):,.0f}"
                except Exception:
                    price_str = f"₹{price}"

                is_checked = (bid in selected_ids)
                self._batch_check_state[bid] = is_checked

                row = self._make_batch_row(
                    bid, name, status, price_str, is_checked)
                batch_controls.append(row)

        self.pkg_batch_container = ft.Column(batch_controls, spacing=4)

        self._batch_ui = ft.Column([
            ft.Row([
                ft.Text("Batches to show as packages:",
                        size=11, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                select_all_btn,
                clear_all_btn,
            ], spacing=4),
            ft.Text(
                "Tap a row to toggle. Nothing selected = no packages shown.",
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

    # -----------------------------------------------------------------------------
    # [5.0] _make_batch_row — build one clickable batch row
    # -----------------------------------------------------------------------------
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
        )

        # One handler, attached everywhere
        def _clicked(e, _bid=batch_id):
            self._toggle_batch_row_by_id(_bid)

        container.on_click = _clicked
        inner_row.on_click = _clicked
        icon.on_click = _clicked
        label.on_click = _clicked

        # Store references
        self.batch_checkboxes[batch_id] = {
            "container": container,
            "icon": icon,
            "label": label,
        }
        return container

    # -----------------------------------------------------------------------------
    # [5.0b] _toggle_batch_row_by_id — flip state + repaint one row
    # -----------------------------------------------------------------------------
    def _toggle_batch_row_by_id(self, batch_id):
        entry = self.batch_checkboxes.get(batch_id)
        if not entry:
            print(f"[FRONTPAGE] toggle: no entry for {batch_id}")
            return

        current = self._batch_check_state.get(batch_id, False)
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

            # Per-control flush
            for k in ("icon", "label", "container"):
                try:
                    entry[k].update()
                except Exception:
                    pass
        except Exception as e:
            print(f"[FRONTPAGE] batch row visual update failed: {e}")

        try:
            self.page_ref.update()
        except Exception:
            pass

        print(f"[FRONTPAGE] toggle batch {batch_id}: "
              f"{current} -> {new_val}")

    # -----------------------------------------------------------------------------
    # [5.1] _on_pkg_source_change
    # -----------------------------------------------------------------------------
    def _on_pkg_source_change(self, e=None):
        self._update_source_visibility()
        self._safe_update()

    # -----------------------------------------------------------------------------
    # [5.2] _update_source_visibility
    # -----------------------------------------------------------------------------
    def _update_source_visibility(self):
        try:
            is_batches = (self.pkg_source.value or "batches") == "batches"
            self._batch_ui.visible = is_batches
        except Exception:
            pass

    # -----------------------------------------------------------------------------
    # [5.3] _toggle_batches — All / Clear helper
    # -----------------------------------------------------------------------------
    def _toggle_batches(self, value):
        print(f"[FRONTPAGE] _toggle_batches("
              f"{'All' if value else 'Clear'})")
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
            except Exception as e:
                print(f"[FRONTPAGE] _toggle_batches error on {bid}: {e}")
        try:
            self.page_ref.update()
        except Exception:
            pass
        self._safe_update()

    # =============================================================================
    # [6] ABOUT SECTION
    # =============================================================================
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

    # -----------------------------------------------------------------------------
    # [6.1] _add_stat_row
    # -----------------------------------------------------------------------------
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
                self._safe_update()
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

    # -----------------------------------------------------------------------------
    # [6.2] _add_stat_empty
    # -----------------------------------------------------------------------------
    def _add_stat_empty(self, e=None):
        self._add_stat_row("", "")
        self._safe_update()

    # =============================================================================
    # [7] CONTACT INFORMATION
    # =============================================================================
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

    # =============================================================================
    # [8] SOCIAL LINKS
    # =============================================================================
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

    # =============================================================================
    # [9] FOOTER
    # =============================================================================
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

    # =============================================================================
    # [11] GALLERY SECTION
    # =============================================================================
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

    # -----------------------------------------------------------------------------
    # [11.1] _rebuild_gallery_lists
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # [11.2] _gallery_stats_text
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # [11.3] _gallery_item_row
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # [11.4] _pick_gallery_files — open /gallery-upload in NEW tab
    # -----------------------------------------------------------------------------
    def _pick_gallery_files(self, media_type):
        url = f"/gallery-upload?type={media_type}"
        print(f"[GALLERY] opening upload page in NEW tab: {url}")

        async def _go():
            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url(url,
                                        web_only_window_name="_blank")
                if asyncio.iscoroutine(r):
                    await r
                print("[GALLERY] OK new tab")
                return
            except TypeError as te:
                print(f"[GALLERY] 1.0 param rejected: {te}")
            except Exception as e:
                print(f"[GALLERY] 1.0 param raised: {e}")
            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url(url,
                                        web_window_name="_blank")
                if asyncio.iscoroutine(r):
                    await r
                print("[GALLERY] OK new tab (legacy)")
                return
            except Exception as e:
                print(f"[GALLERY] legacy param failed: {e}")
            try:
                launcher = ft.UrlLauncher()
                r = launcher.launch_url(url)
                if asyncio.iscoroutine(r):
                    await r
                print("[GALLERY] OK bare launch")
            except Exception as e:
                print(f"[GALLERY] bare failed: {e}")

        try:
            self.page_ref.run_task(_go)
        except Exception as ex:
            print(f"[GALLERY] run_task failed: {ex}")
            try:
                self._snack(f"⚠️ Could not open upload page: {ex}",
                            DANGER)
            except Exception:
                pass

    # -----------------------------------------------------------------------------
    # [11.5] _upload_files (fallback path if HTML page bypassed)
    # -----------------------------------------------------------------------------
    async def _upload_files(self, files, media_type):
        import httpx
        ok = 0
        fail = 0
        for f in files:
            try:
                data = getattr(f, "bytes", None)
                name = getattr(f, "name", "upload.bin")
                if not data:
                    src = getattr(f, "path", None)
                    if src:
                        try:
                            import os as _os
                            if _os.path.exists(src):
                                with open(src, "rb") as fh:
                                    data = fh.read()
                        except Exception:
                            pass
                if not data:
                    fail += 1
                    continue
                files_arg = {"file": (name, data)}
                form = {"media_type": media_type, "caption": ""}
                async with httpx.AsyncClient(
                        base_url="http://127.0.0.1:8080",
                        timeout=120.0) as cli:
                    r = await cli.post(
                        "/api/admin/gallery/upload",
                        files=files_arg, data=form)
                if r.status_code == 200:
                    item = r.json().get("item", {})
                    if media_type == "photos":
                        self.photo_list.append(item)
                    else:
                        self.video_list.append(item)
                    ok += 1
                else:
                    fail += 1
            except Exception as ex:
                print(f"[GALLERY] upload error {name}: {ex}")
                fail += 1
        self._rebuild_gallery_lists()
        self._safe_update()
        if ok and not fail:
            self._snack(f"✅ {ok} file(s) uploaded", SUCCESS)
        elif fail:
            self._snack("❌ Upload failed", DANGER)

    # -----------------------------------------------------------------------------
    # [11.6] _remove_gallery_item
    # -----------------------------------------------------------------------------
    def _remove_gallery_item(self, media_type, item):
        url = item.get("url", "")
        caption = item.get("caption", "") or url

        def do_delete(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
            import httpx

            async def _del():
                try:
                    async with httpx.AsyncClient(
                            base_url="http://127.0.0.1:8080",
                            timeout=30.0) as cli:
                        await cli.request(
                            "DELETE",
                            "/api/admin/gallery/item",
                            params={"media_type": media_type,
                                    "url": url})
                except Exception as ex:
                    print(f"[FRONTPAGE] delete error: {ex}")

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
            self._safe_update()
            self._snack("🗑️ Deleted", WARN)

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

    # -----------------------------------------------------------------------------
    # [11.7] _register_pickers
    # -----------------------------------------------------------------------------
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
            try:
                self.page_ref.update()
            except Exception:
                pass
            print("[FRONTPAGE] gallery pickers registered ✅")
        except Exception as ex:
            print(f"[FRONTPAGE] picker registration failed: {ex}")

    # -----------------------------------------------------------------------------
    # [11.8] _save_silent
    # -----------------------------------------------------------------------------
    def _save_silent(self):
        try:
            cfg = self._collect_config()
            save_config(cfg)
            self.cfg = cfg
        except Exception as ex:
            print(f"[FRONTPAGE] silent save failed: {ex}")

    # =============================================================================
    # [10] ACTION BAR
    # =============================================================================
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

    # =============================================================================
    # [A] ACTIONS
    # =============================================================================

    # -----------------------------------------------------------------------------
    # [A.1] _collect_config — read every field, build save payload
    # -----------------------------------------------------------------------------
    def _collect_config(self):
        def _v(field):
            try:
                return (field.value or "").strip()
            except Exception:
                return ""

        def _int(field, default):
            try:
                s = (field.value or "").strip()
                if not s:
                    return default
                return int(s)
            except Exception:
                return default

        max_shown = _int(self.pkg_max_shown, 0)
        if max_shown < 0:
            max_shown = 0

        # Batch selection: ONLY from authoritative state dict
        selected_ids = []
        try:
            for bid, checked in self._batch_check_state.items():
                if checked:
                    selected_ids.append(str(bid).strip())
        except Exception as e:
            print(f"[FRONTPAGE] _collect_config batch read failed: {e}")

        print("=" * 60)
        print("[FRONTPAGE] _collect_config")
        print(f"[FRONTPAGE]   selected batches : {len(selected_ids)}")
        for sid in selected_ids:
            print(f"[FRONTPAGE]     • {sid!r}")
        print(f"[FRONTPAGE]   max_shown        : {max_shown}")
        print(f"[FRONTPAGE]   check state      : "
              f"{self._batch_check_state}")
        print("=" * 60)

        features = []
        for entry in self.feature_entries:
            title = (entry["title"].value or "").strip()
            text = (entry["text"].value or "").strip()
            if not title and not text:
                continue
            features.append({
                "icon": (entry["icon"].value or
                         "fa-check-circle").strip(),
                "title": title, "text": text,
            })

        stats = []
        for entry in self.stat_entries:
            number = (entry["number"].value or "").strip()
            label = (entry["label"].value or "").strip()
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
                "heading": _v(self.hero_heading),
                "subheading": _v(self.hero_subheading),
                "button_text": _v(self.hero_button),
                "whatsapp_text": _v(self.hero_whatsapp),
            },
            "alert": {
                "enabled": bool(self.alert_enabled.value),
                "message": _v(self.alert_message),
                "link": _v(self.alert_link) or "#",
                "color": _v(self.alert_color) or "#f39c12",
                "style": (self.alert_style.value or "pulse"),
            },
            "features": features,
            "packages": {
                "title": _v(self.pkg_title),
                "subtitle": _v(self.pkg_subtitle),
                "source": (self.pkg_source.value or "batches"),
                "max_shown": max_shown,
                "selected_batch_ids": selected_ids,
                "manual": [],
            },
            "about": {
                "heading": _v(self.about_heading),
                "paragraph1": _v(self.about_p1),
                "paragraph2": _v(self.about_p2),
                "stats": stats,
            },
            "contact": {
                "phone": _v(self.contact_phone),
                "phone2": _v(self.contact_phone2),
                "email": _v(self.contact_email),
                "whatsapp": _v(self.contact_whatsapp),
                "address_line1": _v(self.contact_addr1),
                "address_line2": _v(self.contact_addr2),
            },
            "social": {
                "facebook": _v(self.social_facebook),
                "instagram": _v(self.social_instagram),
                "twitter": _v(self.social_twitter),
            },
            "footer": {
                "about_text": _v(self.footer_about),
                "copyright": _v(self.footer_copyright),
            },
            "gallery": {
                "enabled": bool(self.gallery_enabled.value),
                "title": _v(self.gallery_title),
                "subtitle": _v(self.gallery_subtitle),
                "layout": "grid",
                "max_photos_shown": max_photos,
                "max_videos_shown": max_videos,
                "photos": list(self.photo_list),
                "videos": list(self.video_list),
            },
        }

    # -----------------------------------------------------------------------------
    # [A.2] _save
    # -----------------------------------------------------------------------------
    def _save(self, e=None):
        try:
            cfg = self._collect_config()
            n_sel = len(cfg.get("packages", {})
                         .get("selected_batch_ids", []))
            print(f"[FRONTPAGE] _save: writing config with "
                  f"{n_sel} selected batches")
            ok = save_config(cfg)
            if ok:
                self.cfg = cfg
                self._set_status(
                    f"✅ Saved at "
                    f"{datetime.now().strftime('%H:%M:%S')}  ·  "
                    f"{n_sel} batch(es) selected", SUCCESS)
                self._snack(f"✅ Saved — {n_sel} batch(es) will "
                            f"appear on the public page")
                try:
                    self.db.log_activity(
                        self.current_user.get("id"),
                        "update_frontpage",
                        f"Updated front page ({n_sel} batches)")
                except Exception:
                    pass
            else:
                self._set_status("❌ Save failed", DANGER)
        except Exception as ex:
            traceback.print_exc()
            self._set_status(f"❌ {ex}", DANGER)

    # -----------------------------------------------------------------------------
    # [A.3] _reset_confirm
    # -----------------------------------------------------------------------------
    def _reset_confirm(self, e=None):
        def do_reset(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass
            ok = save_config(DEFAULT_CONFIG)
            if ok:
                self._snack("↺ Reset to defaults")
                self.refresh()
            else:
                self._snack("❌ Reset failed", DANGER)

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

    # -----------------------------------------------------------------------------
    # [A.4] _open_preview
    # -----------------------------------------------------------------------------
    def _open_preview(self, e=None):
        try:
            async def _do():
                try:
                    launcher = ft.UrlLauncher()
                    await launcher.launch_url("/")
                except Exception as ex:
                    print(f"[preview] launch failed: {ex}")
            try:
                self.page_ref.run_task(_do)
                self._set_status("🔗 Opening front page…", PRIMARY_LT)
                return
            except Exception as ex:
                print(f"[preview] run_task failed: {ex}")
            try:
                self.page_ref.url = "/"
                self._set_status("🔗 Opened front page", PRIMARY_LT)
                return
            except Exception as ex:
                print(f"[preview] page.url failed: {ex}")
            self._snack("⚠️ Could not open preview — visit / manually")
        except Exception as ex:
            self._snack(f"⚠️ {ex}")

    # -----------------------------------------------------------------------------
    # [A.5] _set_status
    # -----------------------------------------------------------------------------
    def _set_status(self, message, color=PRIMARY_LT):
        try:
            if self.status_label is not None:
                self.status_label.value = message
                self.status_label.color = color
        except Exception:
            pass
        self._safe_update()

    # -----------------------------------------------------------------------------
    # [A.6] _snack
    # -----------------------------------------------------------------------------
    def _snack(self, msg, color=ft.Colors.GREEN_700):
        try:
            self.page_ref.show_dialog(
                ft.SnackBar(content=ft.Text(msg), bgcolor=color))
        except Exception:
            pass

    # -----------------------------------------------------------------------------
    # [A.7] _safe_update
    # -----------------------------------------------------------------------------
    def _safe_update(self):
        try:
            if self.root is not None:
                self.root.update()
        except Exception:
            pass


# =================================================================================
# SECTION END — core/frontpage_settings_tab.py v3.18
# =================================================================================
