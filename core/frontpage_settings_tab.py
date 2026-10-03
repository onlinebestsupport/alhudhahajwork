# =================================================================================
# core/frontpage_settings_tab.py — Front Page Settings
# =================================================================================
# v5.0 — Working PaymentsTab/UsersTab pattern
#   • Plain class (NOT ft.Column subclass)
#   • self.root = ft.Container(content=Column(...), expand=True)
#   • build() returns self.root
#   • Section methods numbered [1]..[10] for future error reports
#   • Batch list: no height, no nested scroll
# =================================================================================

import json
import traceback
from datetime import datetime

import flet as ft

from core.frontpage_config import (
    DEFAULT_CONFIG, load_config, save_config, _deep_merge)


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


class FrontPageSettingsTab:

    # -----------------------------------------------------------------------------
    # [0] __init__
    # -----------------------------------------------------------------------------
    def __init__(self, page, db, current_user):
        self.page = page
        self.db = db
        self.current_user = current_user or {}
        self.cfg = load_config()
        self.all_batches = []
        self.batch_checkboxes = {}

        # Field refs
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

        self.status_label = None
        self.root = None

        try:
            self._load_batches()
            self.setup_ui()
        except Exception as e:
            print(f"[FRONTPAGE] setup failed: {e}")
            traceback.print_exc()
            self.root = self._error_ui(e)

    # -----------------------------------------------------------------------------
    # [0.1] build
    # -----------------------------------------------------------------------------
    def build(self):
        return self.root

    # -----------------------------------------------------------------------------
    # [0.2] refresh
    # -----------------------------------------------------------------------------
    def refresh(self, e=None):
        try:
            self.cfg = load_config()
            self._load_batches()
            self.setup_ui()
            try:
                self.root.update()
            except Exception:
                pass
        except Exception as ex:
            print(f"[FRONTPAGE] refresh failed: {ex}")
            traceback.print_exc()

    # -----------------------------------------------------------------------------
    # [0.3] _load_batches
    # -----------------------------------------------------------------------------
    def _load_batches(self):
        try:
            if hasattr(self.db, "reload"):
                try:
                    self.db.reload()
                except Exception:
                    pass
            self.all_batches = self.db.get_batches() or []
        except Exception as e:
            print(f"[FRONTPAGE] get_batches failed: {e}")
            self.all_batches = []

    # -----------------------------------------------------------------------------
    # [0.4] _error_ui
    # -----------------------------------------------------------------------------
    def _error_ui(self, exc):
        return ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.WARNING_AMBER, size=48,
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
    # [ROOT] setup_ui
    # =============================================================================
    def setup_ui(self):
        self.feature_entries = []
        self.stat_entries = []
        self.batch_checkboxes = {}

        self.root = ft.Container(
            content=ft.Column(
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
                    ft.Container(height=12),
                    self._section_10_action_bar(),
                    ft.Container(height=20),
                ],
                spacing=10,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=10,
            bgcolor=PAGE_BG,
            expand=True,
        )

    # =============================================================================
    # [1] _section_1_header
    # =============================================================================
    def _section_1_header(self):
        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Text("🌐", size=22),
                    width=46, height=46,
                    bgcolor=ft.Colors.with_opacity(
                        0.15, ft.Colors.WHITE),
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
                        ft.Icon(ft.Icons.OPEN_IN_NEW, size=14,
                                color=ft.Colors.WHITE),
                        ft.Text("Preview", size=11,
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=5, tight=True),
                    on_click=self._open_preview,
                    height=38, bgcolor=SUCCESS,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(
                            radius=10))),
            ], spacing=12),
            padding=ft.Padding.symmetric(
                horizontal=16, vertical=14),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[PRIMARY, PRIMARY_LT, ACCENT]),
            border_radius=14)

    # -----------------------------------------------------------------------------
    # _section_card (helper used by sections 2-9)
    # -----------------------------------------------------------------------------
    def _section_card(self, icon, title, subtitle, controls,
                      accent=PRIMARY):
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
                        color="#0f172a"),
                ft.Text(subtitle, size=10, color=MUTED),
            ], spacing=2, expand=True),
        ], spacing=10)

        return ft.Container(
            content=ft.Column([
                header,
                ft.Divider(height=1, color=BORDER),
                ft.Column(controls, spacing=10),
            ], spacing=10),
            padding=14,
            bgcolor=SECTION_BG,
            border=ft.Border.all(1, BORDER),
            border_radius=12)

    # -----------------------------------------------------------------------------
    # Field helpers
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

    def _two_col(self, left, right):
        return ft.Row([
            ft.Container(content=left, expand=True),
            ft.Container(content=right, expand=True),
        ], spacing=10,
           vertical_alignment=ft.CrossAxisAlignment.START)

    # =============================================================================
    # [2] _section_2_hero
    # =============================================================================
    def _section_2_hero(self):
        h = self.cfg.get("hero", {})
        self.hero_heading = self._field(
            "Heading", h.get("heading", ""))
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
    # [3] _section_3_alert
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
            "Optional top-of-page announcement",
            [
                self.alert_enabled,
                self.alert_message,
                self.alert_link,
                self._two_col(self.alert_color, self.alert_style),
            ], accent=WARN)

    # =============================================================================
    # [4] _section_4_features
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
                ft.Icon(ft.Icons.ADD, size=14,
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
        icon_field = self._field(
            "Icon", icon_val, width=140,
            hint_text="fa-mosque")
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
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
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

    def _add_feature_empty(self, e=None):
        self._add_feature_row("fa-check-circle", "", "")
        self._safe_update()

    # =============================================================================
    # [5] _section_5_packages   ✅ no height, no nested scroll
    # =============================================================================
    def _section_5_packages(self):
        p = self.cfg.get("packages", {})

        self.pkg_title = self._field(
            "Section title", p.get("title", ""))
        self.pkg_subtitle = self._field(
            "Section subtitle", p.get("subtitle", ""))

        self.pkg_source = ft.Dropdown(
            label="Package source",
            value=p.get("source", "batches"),
            options=[
                ft.dropdown.Option("batches", "Batches (recommended)"),
                ft.dropdown.Option("manual", "Manual list"),
            ],
            text_size=12,
            border_color=BORDER,
            focused_border_color=PRIMARY_LT,
            border_radius=8)
        self.pkg_source.on_change = self._on_pkg_source_change

        self.pkg_max_shown = self._field(
            "Max packages shown",
            str(p.get("max_shown", 6)))

        select_all_btn = ft.TextButton(
            content=ft.Text("✓ All", size=11, color=SUCCESS),
            on_click=lambda e: self._toggle_batches(True))
        clear_all_btn = ft.TextButton(
            content=ft.Text("✗ Clear", size=11, color=DANGER),
            on_click=lambda e: self._toggle_batches(False))

        selected_ids = set(str(x) for x in
                           (p.get("selected_batch_ids") or []))
        self.batch_checkboxes = {}
        batch_controls = []

        if not self.all_batches:
            batch_controls.append(
                ft.Text("No batches found. Add some in the "
                        "Batches tab first.",
                        size=11, color=MUTED))
        else:
            for b in self.all_batches:
                bid = str(b.get("id", ""))
                name = str(b.get("batch_name", bid))
                status = str(b.get("status", ""))
                price = b.get("price", 0)
                label = f"{name}  ·  {status}  ·  ₹{price:,.0f}"

                cb = ft.Checkbox(
                    label=label,
                    value=(bid in selected_ids) if selected_ids else False,
                    label_style=ft.TextStyle(size=11))
                self.batch_checkboxes[bid] = cb
                batch_controls.append(cb)

        self.pkg_batch_container = ft.Column(
            batch_controls, spacing=4)

        self._batch_ui = ft.Column([
            ft.Row([
                ft.Text("Batches to show as packages:",
                        size=11, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                select_all_btn,
                clear_all_btn,
            ], spacing=4, wrap=True),
            ft.Text("Leave all unchecked to show every open batch.",
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

    def _on_pkg_source_change(self, e=None):
        self._update_source_visibility()
        self._safe_update()

    def _update_source_visibility(self):
        try:
            is_batches = (self.pkg_source.value or "batches") == "batches"
            self._batch_ui.visible = is_batches
        except Exception:
            pass

    def _toggle_batches(self, value):
        for cb in self.batch_checkboxes.values():
            cb.value = value
        self._safe_update()

    # =============================================================================
    # [6] _section_6_about
    # =============================================================================
    def _section_6_about(self):
        a = self.cfg.get("about", {})
        self.about_heading = self._field(
            "Heading", a.get("heading", ""))
        self.about_p1 = self._field(
            "Paragraph 1", a.get("paragraph1", ""),
            multiline=True, min_lines=3, max_lines=5)
        self.about_p2 = self._field(
            "Paragraph 2", a.get("paragraph2", ""),
            multiline=True, min_lines=3, max_lines=5)

        self.stats_rows_container = ft.Column(spacing=8)
        self.stat_entries = []

        for st in (a.get("stats") or []):
            self._add_stat_row(
                st.get("number", ""), st.get("label", ""))

        add_stat_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.ADD, size=14,
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
                ft.Text("Statistics (4 recommended)",
                        size=12, weight=ft.FontWeight.BOLD,
                        color="#0f172a"),
                self.stats_rows_container,
                add_stat_btn,
            ])

    def _add_stat_row(self, number_val, label_val):
        num_field = self._field(
            "Number", number_val, width=140,
            hint_text="25+")
        lbl_field = self._field(
            "Label", label_val,
            hint_text="Years Experience")

        entry = {"number": num_field, "label": lbl_field,
                 "row": None}

        def remove(ev, _entry=entry):
            try:
                self.stat_entries.remove(_entry)
                self.stats_rows_container.controls.remove(
                    _entry["row"])
                self._safe_update()
            except Exception:
                pass

        row = ft.Container(
            content=ft.Row([
                ft.Container(content=num_field, width=150),
                ft.Container(content=lbl_field, expand=True),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                              icon_color=DANGER,
                              on_click=remove),
            ], spacing=6,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=8, bgcolor="#f8fafc",
            border=ft.Border.all(1, BORDER),
            border_radius=10)

        entry["row"] = row
        self.stat_entries.append(entry)
        self.stats_rows_container.controls.append(row)

    def _add_stat_empty(self, e=None):
        self._add_stat_row("", "")
        self._safe_update()

    # =============================================================================
    # [7] _section_7_contact
    # =============================================================================
    def _section_7_contact(self):
        c = self.cfg.get("contact", {})
        self.contact_phone = self._field(
            "Primary phone", c.get("phone", ""))
        self.contact_phone2 = self._field(
            "Secondary phone", c.get("phone2", ""))
        self.contact_email = self._field(
            "Email", c.get("email", ""))
        self.contact_whatsapp = self._field(
            "WhatsApp (country code)",
            c.get("whatsapp", ""),
            hint_text="919876543210")
        self.contact_addr1 = self._field(
            "Address line 1", c.get("address_line1", ""))
        self.contact_addr2 = self._field(
            "Address line 2", c.get("address_line2", ""))

        return self._section_card(
            "📞", "Contact Information",
            "Shown in top bar, contact section, and footer",
            [
                self._two_col(self.contact_phone,
                              self.contact_phone2),
                self._two_col(self.contact_email,
                              self.contact_whatsapp),
                self._two_col(self.contact_addr1,
                              self.contact_addr2),
            ])

    # =============================================================================
    # [8] _section_8_social
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
    # [9] _section_9_footer
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
    # [10] _section_10_action_bar
    # =============================================================================
    def _section_10_action_bar(self):
        save_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.SAVE, size=16,
                        color=ft.Colors.WHITE),
                ft.Text("Save", size=12,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6, tight=True),
            on_click=self._save,
            height=44, bgcolor=SUCCESS,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        reload_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.REFRESH, size=16,
                        color=ft.Colors.WHITE),
                ft.Text("Reload", size=12,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6, tight=True),
            on_click=self.refresh,
            height=44, bgcolor="#0ea5e9",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        preview_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.OPEN_IN_NEW, size=16,
                        color=ft.Colors.WHITE),
                ft.Text("Preview", size=12,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6, tight=True),
            on_click=self._open_preview,
            height=44, bgcolor=ACCENT,
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
                ft.Row([
                    save_btn, reload_btn, preview_btn,
                    ft.Container(expand=True),
                    reset_btn,
                ], spacing=8, wrap=True),
                ft.Divider(height=1, color=BORDER),
                self.status_label,
            ], spacing=10),
            padding=14, bgcolor=SECTION_BG,
            border=ft.Border.all(1, BORDER),
            border_radius=12)

    # =============================================================================
    # ACTIONS
    # =============================================================================
    def _collect_config(self):
        try:
            max_shown = int(self.pkg_max_shown.value or 6)
            if max_shown < 1:
                max_shown = 6
        except Exception:
            max_shown = 6

        selected_ids = [
            bid for bid, cb in self.batch_checkboxes.items()
            if cb.value
        ]

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

        def _v(f):
            try:
                return (f.value or "").strip()
            except Exception:
                return ""

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
        }

    # -----------------------------------------------------------------------------
    # _save
    # -----------------------------------------------------------------------------
    def _save(self, e=None):
        try:
            cfg = self._collect_config()
            ok = save_config(cfg)
            if ok:
                self.cfg = cfg
                self._set_status(
                    f"✅ Saved at "
                    f"{datetime.now().strftime('%H:%M:%S')}",
                    SUCCESS)
                self._snack("✅ Front page settings saved")
                try:
                    self.db.log_activity(
                        self.current_user.get("id"),
                        "update_frontpage",
                        "Updated front page settings")
                except Exception:
                    pass
            else:
                self._set_status("❌ Save failed", DANGER)
        except Exception as ex:
            traceback.print_exc()
            self._set_status(f"❌ {ex}", DANGER)

    # -----------------------------------------------------------------------------
    # _reset_confirm
    # -----------------------------------------------------------------------------
    def _reset_confirm(self, e=None):
        def do_reset(ev):
            try:
                self.page.pop_dialog()
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
                self.page.pop_dialog()
            except Exception:
                pass

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Reset to Defaults?",
                          weight=ft.FontWeight.BOLD),
            content=ft.Text(
                "Discard custom front-page settings and restore "
                "defaults?\n\nThis cannot be undone.",
                size=12),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=cancel),
                ft.Button(
                    content=ft.Text("Reset",
                                    color=ft.Colors.WHITE,
                                    weight=ft.FontWeight.BOLD),
                    on_click=do_reset, bgcolor=DANGER),
            ])
        self.page.show_dialog(dlg)

    # -----------------------------------------------------------------------------
    # _open_preview
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
                self.page.run_task(_do)
                self._set_status("🔗 Opening…", PRIMARY_LT)
                return
            except Exception as ex:
                print(f"[preview] run_task failed: {ex}")

            try:
                self.page.url = "/"
                self._set_status("🔗 Opened", PRIMARY_LT)
                return
            except Exception as ex:
                print(f"[preview] page.url failed: {ex}")

            self._snack("⚠️ Visit / manually")
        except Exception as ex:
            self._snack(f"⚠️ {ex}")

    # -----------------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------------
    def _set_status(self, message, color=PRIMARY_LT):
        try:
            if self.status_label is not None:
                self.status_label.value = message
                self.status_label.color = color
        except Exception:
            pass
        self._safe_update()

    def _snack(self, msg, color=ft.Colors.GREEN_700):
        try:
            self.page.show_dialog(
                ft.SnackBar(content=ft.Text(msg), bgcolor=color))
        except Exception:
            pass

    def _safe_update(self):
        try:
            if self.root is not None:
                self.root.update()
        except Exception:
            pass
