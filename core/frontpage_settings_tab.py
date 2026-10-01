# =================================================================================
# core/frontpage_settings_tab.py — Admin UI for front page configuration
# =================================================================================
# v2.1 — fixes + polish:
#   • Preview button uses ft.UrlLauncher (Flet 1.0.3 API)
#   • Contact / Social fields stack in Column layout (fixed grey-box bug)
#   • Cleaner section cards, spacing, typography
#   • Sticky action bar with prominent Save
# =================================================================================

import json
import traceback
from datetime import datetime

import flet as ft

from core.frontpage_config import (
    DEFAULT_CONFIG, load_config, save_config, _deep_merge)


# =================================================================================
# Palette
# =================================================================================
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


# =================================================================================
# CLASS: FrontPageSettingsTab
# =================================================================================
class FrontPageSettingsTab(ft.Column):

    def __init__(self, page, db, current_user):
        super().__init__()

        self.page_ref = page
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

        self.spacing = 0
        self.expand = True
        self.scroll = ft.ScrollMode.AUTO

        try:
            self._load_batches()
            self._build()
        except Exception as e:
            print(f"[FRONTPAGE_SETTINGS] build failed: {e}")
            traceback.print_exc()
            self.controls = [self._error_ui(e)]

    # -----------------------------------------------------------------------------
    def build(self):
        return self

    # -----------------------------------------------------------------------------
    def refresh(self, e=None):
        try:
            self.cfg = load_config()
            self._load_batches()
            self.controls.clear()
            self._build()
            self._safe_update()
        except Exception as ex:
            print(f"[FRONTPAGE_SETTINGS] refresh failed: {ex}")

    def _load_batches(self):
        try:
            if hasattr(self.db, "reload"):
                try:
                    self.db.reload()
                except Exception:
                    pass
            self.all_batches = self.db.get_batches() or []
        except Exception as e:
            print(f"[FRONTPAGE_SETTINGS] get_batches failed: {e}")
            self.all_batches = []

    def _error_ui(self, exc):
        return ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.WARNING_AMBER, size=48,
                        color=ft.Colors.ORANGE_600),
                ft.Text("Front Page Settings failed to load", size=18,
                        weight=ft.FontWeight.BOLD),
                ft.Text(str(exc), size=12,
                        color=ft.Colors.RED_500, selectable=True),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
               spacing=10),
            padding=40, bgcolor="#fef3c7", border_radius=12,
            alignment=ft.Alignment.CENTER, expand=True)

    # =============================================================================
    # UI BUILD
    # =============================================================================
    def _build(self):
        self.controls = [
            self._header(),
            ft.Container(height=8),
            self._section_hero(),
            self._section_alert(),
            self._section_features(),
            self._section_packages(),
            self._section_about(),
            self._section_contact(),
            self._section_social(),
            self._section_footer(),
            ft.Container(height=12),
            self._action_bar(),
            ft.Container(height=20),
        ]

    # -----------------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------------
    def _header(self):
        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Text("🌐", size=26),
                    width=56, height=56,
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.WHITE),
                    border_radius=14,
                    alignment=ft.Alignment.CENTER),
                ft.Column([
                    ft.Text("Front Page Settings", size=20,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                    ft.Text(
                        "Edit everything visitors see at alhudhahaj.work",
                        size=11, color="#c7d2fe"),
                ], spacing=2, expand=True),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.Icons.OPEN_IN_NEW, size=16,
                                color=ft.Colors.WHITE),
                        ft.Text("Preview Site", size=12,
                                color=ft.Colors.WHITE,
                                weight=ft.FontWeight.BOLD),
                    ], spacing=6, tight=True),
                    on_click=self._open_preview,
                    height=42,
                    bgcolor=SUCCESS,
                    style=ft.ButtonStyle(
                        shape=ft.RoundedRectangleBorder(radius=10))),
            ], spacing=16),
            padding=ft.Padding.symmetric(horizontal=24, vertical=18),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[PRIMARY, PRIMARY_LT, ACCENT]),
            border_radius=14)

    # -----------------------------------------------------------------------------
    # Section wrapper (reusable card)
    # -----------------------------------------------------------------------------
    def _section_card(self, icon, title, subtitle, controls, accent=PRIMARY):
        # Header row with colored accent bar
        header = ft.Row([
            ft.Container(
                content=ft.Text(icon, size=18),
                width=40, height=40,
                bgcolor=ft.Colors.with_opacity(0.12, accent),
                border_radius=10,
                alignment=ft.Alignment.CENTER),
            ft.Column([
                ft.Text(title, size=15,
                        weight=ft.FontWeight.BOLD,
                        color="#0f172a"),
                ft.Text(subtitle, size=11, color=MUTED),
            ], spacing=2, expand=True),
        ], spacing=12)

        body = ft.Column(controls, spacing=12)

        return ft.Container(
            content=ft.Column([
                header,
                ft.Divider(height=1, color=BORDER),
                ft.Container(content=body, padding=ft.Padding.only(top=4)),
            ], spacing=12),
            padding=20,
            bgcolor=SECTION_BG,
            border=ft.Border.all(1, BORDER),
            border_radius=14,
            shadow=ft.BoxShadow(
                blur_radius=8, spread_radius=0,
                color=ft.Colors.with_opacity(0.04, "#000000"),
                offset=ft.Offset(0, 2)))

    # -----------------------------------------------------------------------------
    # Field helpers
    # -----------------------------------------------------------------------------
    def _field(self, label, value, **kwargs):
        defaults = dict(
            label=label,
            value=value or "",
            text_size=13,
            border_color=BORDER,
            focused_border_color=PRIMARY_LT,
            border_radius=8,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=12),
        )
        defaults.update(kwargs)
        return ft.TextField(**defaults)

    def _two_col(self, left, right):
        """Two fields side by side — no wrap so nothing gets lost."""
        return ft.Row(
            [ft.Container(content=left, expand=True),
             ft.Container(content=right, expand=True)],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START)

    # -----------------------------------------------------------------------------
    # Hero
    # -----------------------------------------------------------------------------
    def _section_hero(self):
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

    # -----------------------------------------------------------------------------
    # Alert
    # -----------------------------------------------------------------------------
    def _section_alert(self):
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
            "Banner color (hex)", a.get("color", "#f39c12"),
            width=180)
        self.alert_style = ft.Dropdown(
            label="Animation",
            value=a.get("style", "pulse"),
            options=[
                ft.dropdown.Option("none", "None"),
                ft.dropdown.Option("pulse", "Pulse"),
                ft.dropdown.Option("blink", "Blink"),
            ],
            text_size=13,
            border_color=BORDER,
            focused_border_color=PRIMARY_LT,
            border_radius=8,
            width=180)

        return self._section_card(
            "⚠️", "Alert Banner",
            "Optional top-of-page announcement for visitors",
            [
                self.alert_enabled,
                self.alert_message,
                self.alert_link,
                self._two_col(self.alert_color, self.alert_style),
            ],
            accent=WARN)

    # -----------------------------------------------------------------------------
    # Features
    # -----------------------------------------------------------------------------
    def _section_features(self):
        self.feature_rows_container = ft.Column(spacing=10)
        self.feature_entries = []

        for f in (self.cfg.get("features") or []):
            self._add_feature_row(
                f.get("icon", "fa-check-circle"),
                f.get("title", ""),
                f.get("text", ""))

        add_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.ADD, size=16, color=ft.Colors.WHITE),
                ft.Text("Add Feature", size=12,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6, tight=True),
            on_click=self._add_feature_empty,
            height=40, bgcolor=SUCCESS,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        return self._section_card(
            "✨", "Features / Why Choose Us",
            "Up to 6 feature cards shown on the front page",
            [self.feature_rows_container, add_btn],
            accent=SUCCESS)

    def _add_feature_row(self, icon_val, title_val, text_val):
        icon_field = self._field(
            "Icon", icon_val, width=160,
            hint_text="e.g. fa-mosque")
        title_field = self._field("Title", title_val)
        text_field = self._field("Description", text_val)

        entry = {
            "icon": icon_field,
            "title": title_field,
            "text": text_field,
            "row": None,
        }

        def remove(ev, _entry=entry):
            try:
                self.feature_entries.remove(_entry)
                self.feature_rows_container.controls.remove(_entry["row"])
                self._safe_update()
            except Exception:
                pass

        row = ft.Container(
            content=ft.Row([
                ft.Container(content=icon_field, width=170),
                ft.Container(content=title_field, expand=True),
                ft.Container(content=text_field, expand=True),
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    icon_color=DANGER,
                    tooltip="Remove",
                    on_click=remove),
            ], spacing=8,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=10, bgcolor="#f8fafc",
            border=ft.Border.all(1, BORDER),
            border_radius=10)

        entry["row"] = row
        self.feature_entries.append(entry)
        self.feature_rows_container.controls.append(row)

    def _add_feature_empty(self, e=None):
        self._add_feature_row("fa-check-circle", "", "")
        self._safe_update()

    # -----------------------------------------------------------------------------
    # Packages
    # -----------------------------------------------------------------------------
    def _section_packages(self):
        p = self.cfg.get("packages", {})

        self.pkg_title = self._field(
            "Section title", p.get("title", ""))
        self.pkg_subtitle = self._field(
            "Section subtitle", p.get("subtitle", ""))

        self.pkg_source = ft.Dropdown(
            label="Package source",
            value=p.get("source", "batches"),
            options=[
                ft.dropdown.Option("batches",
                                   "Batches (recommended)"),
                ft.dropdown.Option("manual",
                                   "Manual list (JSON, advanced)"),
            ],
            text_size=13,
            border_color=BORDER,
            focused_border_color=PRIMARY_LT,
            border_radius=8,
            expand=True)
        self.pkg_source.on_change = self._on_pkg_source_change

        self.pkg_max_shown = self._field(
            "Max packages shown",
            str(p.get("max_shown", 6)),
            width=180)

        select_all_btn = ft.TextButton(
            content=ft.Text("✓ Select All", size=11,
                            color=SUCCESS),
            on_click=lambda e: self._toggle_batches(True))
        clear_all_btn = ft.TextButton(
            content=ft.Text("✗ Clear All", size=11,
                            color=DANGER),
            on_click=lambda e: self._toggle_batches(False))

        # Build batch checkbox list
        selected_ids = set(str(x) for x in
                           (p.get("selected_batch_ids") or []))
        self.batch_checkboxes = {}
        batch_rows = []

        if not self.all_batches:
            batch_rows.append(ft.Text(
                "No batches found. Add some in the Batches tab first.",
                size=12, color=MUTED))
        else:
            for b in self.all_batches:
                bid = str(b.get("id", ""))
                name = str(b.get("batch_name", bid))
                status = str(b.get("status", ""))
                price = b.get("price", 0)
                label = f"{name}   ·   {status}   ·   ₹{price:,.0f}"

                cb = ft.Checkbox(
                    label=label,
                    value=(bid in selected_ids) if selected_ids else False,
                    label_style=ft.TextStyle(size=12))
                self.batch_checkboxes[bid] = cb
                batch_rows.append(
                    ft.Container(content=cb, padding=ft.Padding.symmetric(
                        horizontal=8, vertical=4)))

        self.pkg_batch_container = ft.Column(batch_rows, spacing=0)

        self._batch_ui = ft.Column([
            ft.Row([
                ft.Text("Batches to show as packages:",
                        size=12, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                select_all_btn,
                clear_all_btn,
            ], spacing=6),
            ft.Text(
                "Leave all unchecked to show every open batch.",
                size=11, color=MUTED, italic=True),
            ft.Container(
                content=ft.Column(
                    [self.pkg_batch_container],
                    scroll=ft.ScrollMode.AUTO),
                padding=8, bgcolor="#f8fafc",
                border=ft.Border.all(1, BORDER),
                border_radius=10,
                height=240),
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
            ],
            accent=ACCENT)

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

    # -----------------------------------------------------------------------------
    # About
    # -----------------------------------------------------------------------------
    def _section_about(self):
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
            self._add_stat_row(st.get("number", ""), st.get("label", ""))

        return self._section_card(
            "📖", "About Section",
            "The 'About Us' block with statistics",
            [
                self.about_heading,
                self.about_p1,
                self.about_p2,
                ft.Container(height=4),
                ft.Text("Statistics (4 recommended)",
                        size=13, weight=ft.FontWeight.BOLD,
                        color="#0f172a"),
                self.stats_rows_container,
            ])

    def _add_stat_row(self, number_val, label_val):
        num_field = self._field(
            "Number", number_val, width=160,
            hint_text="e.g. 25+")
        lbl_field = self._field(
            "Label", label_val,
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
                ft.Container(content=num_field, width=170),
                ft.Container(content=lbl_field, expand=True),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                              icon_color=DANGER,
                              tooltip="Remove",
                              on_click=remove),
            ], spacing=8,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=10, bgcolor="#f8fafc",
            border=ft.Border.all(1, BORDER),
            border_radius=10)

        entry["row"] = row
        self.stat_entries.append(entry)
        self.stats_rows_container.controls.append(row)

    # -----------------------------------------------------------------------------
    # Contact
    # -----------------------------------------------------------------------------
    def _section_contact(self):
        c = self.cfg.get("contact", {})
        self.contact_phone = self._field(
            "Primary phone", c.get("phone", ""))
        self.contact_phone2 = self._field(
            "Secondary phone (optional)", c.get("phone2", ""))
        self.contact_email = self._field(
            "Email", c.get("email", ""))
        self.contact_whatsapp = self._field(
            "WhatsApp (country code, no +)",
            c.get("whatsapp", ""),
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

    # -----------------------------------------------------------------------------
    # Social
    # -----------------------------------------------------------------------------
    def _section_social(self):
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

    # -----------------------------------------------------------------------------
    # Footer
    # -----------------------------------------------------------------------------
    def _section_footer(self):
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

    # -----------------------------------------------------------------------------
    # Action bar
    # -----------------------------------------------------------------------------
    def _action_bar(self):
        save_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.SAVE, size=18, color=ft.Colors.WHITE),
                ft.Text("Save Changes", size=13,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=8, tight=True),
            on_click=self._save,
            height=50, bgcolor=SUCCESS,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        reload_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.REFRESH, size=18,
                        color=ft.Colors.WHITE),
                ft.Text("Reload from Disk", size=13,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=8, tight=True),
            on_click=self.refresh,
            height=50, bgcolor="#0ea5e9",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        preview_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.OPEN_IN_NEW, size=18,
                        color=ft.Colors.WHITE),
                ft.Text("Open Front Page", size=13,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=8, tight=True),
            on_click=self._open_preview,
            height=50, bgcolor=ACCENT,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10)))

        reset_btn = ft.TextButton(
            content=ft.Text("↺ Reset to Defaults", size=12,
                            color=DANGER),
            on_click=self._reset_confirm)

        # Status label inside the action bar
        self.status_label = ft.Text(
            "Ready. Edit fields and click Save to publish.",
            size=11, color=MUTED, italic=True)

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    save_btn,
                    reload_btn,
                    preview_btn,
                    ft.Container(expand=True),
                    reset_btn,
                ], spacing=10, wrap=True),
                ft.Divider(height=1, color=BORDER),
                ft.Row([self.status_label], spacing=0),
            ], spacing=10),
            padding=20, bgcolor=SECTION_BG,
            border=ft.Border.all(1, BORDER),
            border_radius=14)

    # =============================================================================
    # ACTIONS
    # =============================================================================
    def _collect_config(self) -> dict:
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
                "icon": (entry["icon"].value or "fa-check-circle").strip(),
                "title": title,
                "text": text,
            })

        stats = []
        for entry in self.stat_entries:
            number = (entry["number"].value or "").strip()
            label = (entry["label"].value or "").strip()
            if not number and not label:
                continue
            stats.append({"number": number, "label": label})

        return {
            "hero": {
                "heading": (self.hero_heading.value or "").strip(),
                "subheading": (self.hero_subheading.value or "").strip(),
                "button_text": (self.hero_button.value or "").strip(),
                "whatsapp_text": (self.hero_whatsapp.value or "").strip(),
            },
            "alert": {
                "enabled": bool(self.alert_enabled.value),
                "message": (self.alert_message.value or "").strip(),
                "link": (self.alert_link.value or "#").strip() or "#",
                "color": (self.alert_color.value or "#f39c12").strip(),
                "style": (self.alert_style.value or "pulse"),
            },
            "features": features,
            "packages": {
                "title": (self.pkg_title.value or "").strip(),
                "subtitle": (self.pkg_subtitle.value or "").strip(),
                "source": (self.pkg_source.value or "batches"),
                "max_shown": max_shown,
                "selected_batch_ids": selected_ids,
                "manual": [],
            },
            "about": {
                "heading": (self.about_heading.value or "").strip(),
                "paragraph1": (self.about_p1.value or "").strip(),
                "paragraph2": (self.about_p2.value or "").strip(),
                "stats": stats,
            },
            "contact": {
                "phone": (self.contact_phone.value or "").strip(),
                "phone2": (self.contact_phone2.value or "").strip(),
                "email": (self.contact_email.value or "").strip(),
                "whatsapp": (self.contact_whatsapp.value or "").strip(),
                "address_line1": (self.contact_addr1.value or "").strip(),
                "address_line2": (self.contact_addr2.value or "").strip(),
            },
            "social": {
                "facebook": (self.social_facebook.value or "").strip(),
                "instagram": (self.social_instagram.value or "").strip(),
                "twitter": (self.social_twitter.value or "").strip(),
            },
            "footer": {
                "about_text": (self.footer_about.value or "").strip(),
                "copyright": (self.footer_copyright.value or "").strip(),
            },
        }

    # -----------------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------------
    def _save(self, e=None):
        try:
            cfg = self._collect_config()
            ok = save_config(cfg)
            if ok:
                self.cfg = cfg
                self._set_status(
                    f"✅ Saved at {datetime.now().strftime('%H:%M:%S')}. "
                    f"Reload the front page to see changes.",
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
                self._set_status("❌ Save failed — check server logs",
                                 DANGER)
        except Exception as ex:
            traceback.print_exc()
            self._set_status(f"❌ {ex}", DANGER)

    # -----------------------------------------------------------------------------
    # Reset
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
                ft.Icon(ft.Icons.WARNING_AMBER, color=DANGER),
                ft.Text("Reset to Defaults?",
                        weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Text(
                "This will discard your custom front-page settings and "
                "restore the original defaults.\n\nThis cannot be undone.",
                size=12),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=cancel),
                ft.Button(
                    content=ft.Text("Reset", color=ft.Colors.WHITE,
                                    weight=ft.FontWeight.BOLD),
                    on_click=do_reset,
                    bgcolor=DANGER),
            ])
        self.page_ref.show_dialog(dlg)

    # -----------------------------------------------------------------------------
    # Preview — Flet 1.0.3 fix (ft.UrlLauncher async)
    # -----------------------------------------------------------------------------
    def _open_preview(self, e=None):
        try:
            async def _do():
                try:
                    launcher = ft.UrlLauncher()
                    await launcher.launch_url("/")
                    print("[preview] opened /")
                except Exception as ex:
                    print(f"[preview] launch failed: {ex}")

            # Schedule via run_task (Flet 1.0.3 native async scheduler)
            try:
                self.page_ref.run_task(_do)
                self._set_status("🔗 Opening front page…", PRIMARY_LT)
                return
            except Exception as ex:
                print(f"[preview] run_task failed: {ex}")

            # Fallback: set page.url (also works in Flet 1.0.3)
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
            self.page_ref.show_dialog(
                ft.SnackBar(content=ft.Text(msg), bgcolor=color))
        except Exception:
            pass

    def _safe_update(self):
        try:
            self.update()
        except Exception:
            pass