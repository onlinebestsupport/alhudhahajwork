# =================================================================================
# core/frontpage_settings_tab.py — Admin UI for front page configuration
# =================================================================================
# Lets the admin edit every part of the marketing front page:
#   • Hero text
#   • Alert banner (enable/disable, message, color, animation)
#   • Feature cards
#   • Package source (real batches vs manual)
#   • About section
#   • Contact info
#   • Social links
#   • Footer
#
# On "Save":
#   → Writes data/frontpage_config.json (persisted on the Railway Volume)
#   → Front page reloads the config on next visit
# =================================================================================

import json
import traceback
from datetime import datetime

import flet as ft

from core.frontpage_config import (
    DEFAULT_CONFIG, load_config, save_config, _deep_merge)


# =================================================================================
# 4.1 — CLASS: FrontPageSettingsTab
# =================================================================================
class FrontPageSettingsTab(ft.Column):

    # -----------------------------------------------------------------------------
    # 4.1.1 — __init__
    # -----------------------------------------------------------------------------
    def __init__(self, page, db, current_user):
        super().__init__()

        self.page_ref = page
        self.db = db
        self.current_user = current_user or {}
        self.cfg = load_config()
        self.all_batches = []
        self.batch_checkboxes = {}

        # UI refs
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
        self.pkg_select_all_btn = None
        self.pkg_clear_all_btn = None
        self.pkg_batch_container = None
        self.pkg_title = None
        self.pkg_subtitle = None

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

        self.spacing = 14
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
    # 4.1.2 — build() (required by main_window)
    # -----------------------------------------------------------------------------
    def build(self):
        return self

    # -----------------------------------------------------------------------------
    # 4.1.3 — refresh
    # -----------------------------------------------------------------------------
    def refresh(self, e=None):
        """Reload config + batches and rebuild the UI."""
        try:
            self.cfg = load_config()
            self._load_batches()
            self.controls.clear()
            self._build()
            self._safe_update()
        except Exception as ex:
            print(f"[FRONTPAGE_SETTINGS] refresh failed: {ex}")

    # -----------------------------------------------------------------------------
    # 4.1.4 — _load_batches
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
            print(f"[FRONTPAGE_SETTINGS] get_batches failed: {e}")
            self.all_batches = []

    # -----------------------------------------------------------------------------
    # 4.1.5 — _error_ui
    # -----------------------------------------------------------------------------
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
    # 4.2 — UI BUILD
    # =============================================================================
    def _build(self):
        self.controls = [
            self._header(),
            self._status_bar(),
            self._section_hero(),
            self._section_alert(),
            self._section_features(),
            self._section_packages(),
            self._section_about(),
            self._section_contact(),
            self._section_social(),
            self._section_footer(),
            self._action_bar(),
        ]

    # -----------------------------------------------------------------------------
    # 4.2.1 — Header
    # -----------------------------------------------------------------------------
    def _header(self):
        return ft.Container(
            content=ft.Row([
                ft.Text("🌐", size=28),
                ft.Column([
                    ft.Text("Front Page Settings", size=17,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE),
                    ft.Text(
                        "Edit everything visitors see at alhudhahaj.work",
                        size=11, color=ft.Colors.BLUE_100),
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
                    height=40, bgcolor="#059669"),
            ], spacing=14),
            padding=ft.Padding.symmetric(horizontal=22, vertical=14),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=["#1e3a8a", "#2563eb", "#7c3aed"]),
            border_radius=12)

    # -----------------------------------------------------------------------------
    # 4.2.2 — Status bar
    # -----------------------------------------------------------------------------
    def _status_bar(self):
        self.status_label = ft.Text(
            "Ready. Edit fields and click Save to publish.",
            size=11, color=ft.Colors.GREY_600, italic=True)
        return ft.Container(
            content=self.status_label,
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            bgcolor=ft.Colors.GREY_100, border_radius=8)

    # -----------------------------------------------------------------------------
    # 4.2.3 — Section wrapper
    # -----------------------------------------------------------------------------
    def _section_card(self, icon, title, controls, subtitle=None):
        rows = [
            ft.Row([
                ft.Text(icon, size=20),
                ft.Column([
                    ft.Text(title, size=14,
                            weight=ft.FontWeight.BOLD,
                            color="#1e40af"),
                    ft.Text(subtitle or "", size=10,
                            color=ft.Colors.GREY_600),
                ], spacing=1),
            ], spacing=10),
            ft.Divider(height=1, color=ft.Colors.GREY_200),
        ] + controls
        return ft.Container(
            content=ft.Column(rows, spacing=10),
            padding=16, bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, "#e2e8f0"),
            border_radius=12)

    # -----------------------------------------------------------------------------
    # 4.2.4 — Hero section
    # -----------------------------------------------------------------------------
    def _section_hero(self):
        h = self.cfg.get("hero", {})
        self.hero_heading = ft.TextField(
            label="Heading",
            value=h.get("heading", ""),
            text_size=12)
        self.hero_subheading = ft.TextField(
            label="Subheading", value=h.get("subheading", ""),
            multiline=True, min_lines=2, max_lines=3, text_size=12)
        self.hero_button = ft.TextField(
            label="Primary button text",
            value=h.get("button_text", ""),
            text_size=12)
        self.hero_whatsapp = ft.TextField(
            label="WhatsApp button text",
            value=h.get("whatsapp_text", ""),
            text_size=12)

        return self._section_card(
            "🎯", "Hero Section",
            [
                self.hero_heading,
                self.hero_subheading,
                ft.Row([self.hero_button, self.hero_whatsapp],
                       spacing=10),
            ],
            subtitle="The big banner at the top of the page")

    # -----------------------------------------------------------------------------
    # 4.2.5 — Alert section
    # -----------------------------------------------------------------------------
    def _section_alert(self):
        a = self.cfg.get("alert", {})
        self.alert_enabled = ft.Switch(
            label="Show alert banner",
            value=bool(a.get("enabled", False)))
        self.alert_message = ft.TextField(
            label="Alert message",
            value=a.get("message", ""),
            multiline=True, min_lines=2, max_lines=4, text_size=12)
        self.alert_link = ft.TextField(
            label="Learn-more link (URL or /path)",
            value=a.get("link", "#"),
            text_size=12)
        self.alert_color = ft.TextField(
            label="Banner color (hex)",
            value=a.get("color", "#f39c12"),
            width=160, text_size=12)
        self.alert_style = ft.Dropdown(
            label="Animation",
            value=a.get("style", "pulse"),
            options=[
                ft.dropdown.Option("none", "None"),
                ft.dropdown.Option("pulse", "Pulse"),
                ft.dropdown.Option("blink", "Blink"),
            ],
            width=180, text_size=12)

        return self._section_card(
            "⚠️", "Alert Banner",
            [
                self.alert_enabled,
                self.alert_message,
                ft.Row([self.alert_link,
                        self.alert_color,
                        self.alert_style], spacing=10, wrap=True),
            ],
            subtitle="Optional top-of-page announcement for visitors")

    # -----------------------------------------------------------------------------
    # 4.2.6 — Features section
    # -----------------------------------------------------------------------------
    def _section_features(self):
        self.feature_rows_container = ft.Column(spacing=8)
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
            height=38, bgcolor="#059669")

        return self._section_card(
            "✨", "Features / Why Choose Us",
            [self.feature_rows_container, add_btn],
            subtitle="Up to 6 feature cards shown on the front page")

    def _add_feature_row(self, icon_val, title_val, text_val):
        idx = len(self.feature_entries)
        icon_field = ft.TextField(
            label="Icon", value=icon_val,
            width=160, text_size=12,
            hint_text="e.g. fa-mosque")
        title_field = ft.TextField(
            label="Title", value=title_val,
            expand=True, text_size=12)
        text_field = ft.TextField(
            label="Description", value=text_val,
            expand=True, text_size=12)

        entry = {
            "icon": icon_field,
            "title": title_field,
            "text": text_field,
            "row": None,
        }

        def remove(ev, _idx=idx, _entry=entry):
            try:
                self.feature_entries.remove(_entry)
                self.feature_rows_container.controls.remove(_entry["row"])
                self._safe_update()
            except Exception:
                pass

        row = ft.Row([
            icon_field, title_field, text_field,
            ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE,
                icon_color="#dc2626",
                tooltip="Remove",
                on_click=remove),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        entry["row"] = row
        self.feature_entries.append(entry)
        self.feature_rows_container.controls.append(row)

    def _add_feature_empty(self, e=None):
        self._add_feature_row("fa-check-circle", "", "")
        self._safe_update()

    # -----------------------------------------------------------------------------
    # 4.2.7 — Packages section
    # -----------------------------------------------------------------------------
    def _section_packages(self):
        p = self.cfg.get("packages", {})

        self.pkg_title = ft.TextField(
            label="Section title", value=p.get("title", ""),
            text_size=12)
        self.pkg_subtitle = ft.TextField(
            label="Section subtitle", value=p.get("subtitle", ""),
            text_size=12)

        self.pkg_source = ft.Dropdown(
            label="Package source",
            value=p.get("source", "batches"),
            options=[
                ft.dropdown.Option("batches",
                                   "Batches (recommended)"),
                ft.dropdown.Option("manual",
                                   "Manual list (JSON, advanced)"),
            ],
            text_size=12, width=280)
        self.pkg_source.on_change = self._on_pkg_source_change

        self.pkg_max_shown = ft.TextField(
            label="Max packages shown",
            value=str(p.get("max_shown", 6)),
            width=180, text_size=12)

        self.pkg_select_all_btn = ft.TextButton(
            content=ft.Text("✓ Select All", size=11),
            on_click=lambda e: self._toggle_batches(True))
        self.pkg_clear_all_btn = ft.TextButton(
            content=ft.Text("✗ Clear All", size=11),
            on_click=lambda e: self._toggle_batches(False))

        # ---- Build batch checkbox list ----
        selected_ids = set(str(x) for x in
                           (p.get("selected_batch_ids") or []))
        self.batch_checkboxes = {}
        batch_rows = []

        if not self.all_batches:
            batch_rows.append(ft.Text(
                "No batches found. Add some in the Batches tab first.",
                size=11, color=ft.Colors.GREY_600))
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
                batch_rows.append(cb)

        self.pkg_batch_container = ft.Column(batch_rows, spacing=2)

        # Toggle visibility based on source
        batch_ui = ft.Column([
            ft.Row([
                ft.Text("Batches to show as packages:",
                        size=12, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                self.pkg_select_all_btn,
                self.pkg_clear_all_btn,
            ], spacing=6),
            ft.Text(
                "Leave all unchecked to show every open batch.",
                size=10, color=ft.Colors.GREY_600, italic=True),
            ft.Container(
                content=self.pkg_batch_container,
                padding=10, bgcolor="#f8fafc",
                border=ft.Border.all(1, "#e2e8f0"),
                border_radius=8,
                height=220),
        ], spacing=6)

        self._batch_ui = batch_ui
        self._update_source_visibility()

        return self._section_card(
            "📦", "Packages Section",
            [
                self.pkg_title,
                self.pkg_subtitle,
                ft.Row([self.pkg_source, self.pkg_max_shown],
                       spacing=10),
                self._batch_ui,
            ],
            subtitle="Packages drawn from real batches (auto-updated)")

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
    # 4.2.8 — About section
    # -----------------------------------------------------------------------------
    def _section_about(self):
        a = self.cfg.get("about", {})
        self.about_heading = ft.TextField(
            label="Heading", value=a.get("heading", ""),
            text_size=12)
        self.about_p1 = ft.TextField(
            label="Paragraph 1",
            value=a.get("paragraph1", ""),
            multiline=True, min_lines=3, max_lines=5, text_size=12)
        self.about_p2 = ft.TextField(
            label="Paragraph 2",
            value=a.get("paragraph2", ""),
            multiline=True, min_lines=3, max_lines=5, text_size=12)

        # Stats (4 number/label pairs)
        self.stats_rows_container = ft.Column(spacing=6)
        self.stat_entries = []

        for st in (a.get("stats") or []):
            self._add_stat_row(st.get("number", ""), st.get("label", ""))

        return self._section_card(
            "📖", "About Section",
            [self.about_heading, self.about_p1, self.about_p2,
             ft.Text("Statistics (4 recommended)",
                     size=12, weight=ft.FontWeight.BOLD),
             self.stats_rows_container],
            subtitle="The 'About Us' block with numbers")

    def _add_stat_row(self, number_val, label_val):
        num_field = ft.TextField(
            label="Number", value=number_val,
            width=140, text_size=12,
            hint_text="e.g. 25+")
        lbl_field = ft.TextField(
            label="Label", value=label_val,
            expand=True, text_size=12,
            hint_text="e.g. Years Experience")

        entry = {"number": num_field, "label": lbl_field, "row": None}

        def remove(ev, _entry=entry):
            try:
                self.stat_entries.remove(_entry)
                self.stats_rows_container.controls.remove(_entry["row"])
                self._safe_update()
            except Exception:
                pass

        row = ft.Row([
            num_field, lbl_field,
            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                          icon_color="#dc2626",
                          tooltip="Remove",
                          on_click=remove),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        entry["row"] = row
        self.stat_entries.append(entry)
        self.stats_rows_container.controls.append(row)

    # -----------------------------------------------------------------------------
    # 4.2.9 — Contact section
    # -----------------------------------------------------------------------------
    def _section_contact(self):
        c = self.cfg.get("contact", {})
        self.contact_phone = ft.TextField(
            label="Primary phone", value=c.get("phone", ""),
            expand=True, text_size=12)
        self.contact_phone2 = ft.TextField(
            label="Secondary phone (optional)",
            value=c.get("phone2", ""),
            expand=True, text_size=12)
        self.contact_email = ft.TextField(
            label="Email", value=c.get("email", ""),
            expand=True, text_size=12)
        self.contact_whatsapp = ft.TextField(
            label="WhatsApp (with country code, no +)",
            value=c.get("whatsapp", ""),
            expand=True, text_size=12,
            hint_text="e.g. 919876543210")
        self.contact_addr1 = ft.TextField(
            label="Address line 1",
            value=c.get("address_line1", ""),
            expand=True, text_size=12)
        self.contact_addr2 = ft.TextField(
            label="Address line 2",
            value=c.get("address_line2", ""),
            expand=True, text_size=12)

        return self._section_card(
            "📞", "Contact Information",
            [
                ft.Row([self.contact_phone, self.contact_phone2],
                       spacing=10, wrap=True),
                ft.Row([self.contact_email, self.contact_whatsapp],
                       spacing=10, wrap=True),
                ft.Row([self.contact_addr1, self.contact_addr2],
                       spacing=10, wrap=True),
            ],
            subtitle="Shown in top bar, contact section, and footer")

    # -----------------------------------------------------------------------------
    # 4.2.10 — Social section
    # -----------------------------------------------------------------------------
    def _section_social(self):
        s = self.cfg.get("social", {})
        self.social_facebook = ft.TextField(
            label="Facebook URL", value=s.get("facebook", ""),
            expand=True, text_size=12)
        self.social_instagram = ft.TextField(
            label="Instagram URL", value=s.get("instagram", ""),
            expand=True, text_size=12)
        self.social_twitter = ft.TextField(
            label="Twitter / X URL", value=s.get("twitter", ""),
            expand=True, text_size=12)

        return self._section_card(
            "🔗", "Social Links",
            [
                ft.Row([self.social_facebook, self.social_instagram],
                       spacing=10, wrap=True),
                self.social_twitter,
            ],
            subtitle="Leave empty to hide a network")

    # -----------------------------------------------------------------------------
    # 4.2.11 — Footer section
    # -----------------------------------------------------------------------------
    def _section_footer(self):
        f = self.cfg.get("footer", {})
        self.footer_about = ft.TextField(
            label="Footer about text",
            value=f.get("about_text", ""),
            multiline=True, min_lines=2, max_lines=3, text_size=12)
        self.footer_copyright = ft.TextField(
            label="Copyright text",
            value=f.get("copyright", ""),
            text_size=12)

        return self._section_card(
            "📝", "Footer",
            [self.footer_about, self.footer_copyright],
            subtitle="Bottom-of-page content")

    # -----------------------------------------------------------------------------
    # 4.2.12 — Action bar (save, reload, reset)
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
            height=48, bgcolor="#059669")

        reload_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.REFRESH, size=18,
                        color=ft.Colors.WHITE),
                ft.Text("Reload from Disk", size=13,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=8, tight=True),
            on_click=self.refresh,
            height=48, bgcolor="#0ea5e9")

        reset_btn = ft.TextButton(
            content=ft.Text("↺ Reset to Defaults", size=12,
                            color="#dc2626"),
            on_click=self._reset_confirm)

        preview_btn = ft.Button(
            content=ft.Row([
                ft.Icon(ft.Icons.OPEN_IN_NEW, size=18,
                        color=ft.Colors.WHITE),
                ft.Text("Open Front Page", size=13,
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD),
            ], spacing=8, tight=True),
            on_click=self._open_preview,
            height=48, bgcolor="#7c3aed")

        return ft.Container(
            content=ft.Row([
                save_btn,
                reload_btn,
                preview_btn,
                ft.Container(expand=True),
                reset_btn,
            ], spacing=10, wrap=True),
            padding=16, bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, "#e2e8f0"),
            border_radius=12)

    # =============================================================================
    # 4.3 — ACTIONS
    # =============================================================================
    def _collect_config(self) -> dict:
        """Read all fields → build a config dict."""
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
    # 4.3.1 — Save
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
                    "#059669")
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
                                 "#dc2626")
        except Exception as ex:
            traceback.print_exc()
            self._set_status(f"❌ {ex}", "#dc2626")

    # -----------------------------------------------------------------------------
    # 4.3.2 — Reset to defaults
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
                self._snack("❌ Reset failed", "#dc2626")

        def cancel(ev):
            try:
                self.page_ref.pop_dialog()
            except Exception:
                pass

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, color="#dc2626"),
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
                    bgcolor="#dc2626"),
            ])
        self.page_ref.show_dialog(dlg)

    # -----------------------------------------------------------------------------
    # 4.3.3 — Preview
    # -----------------------------------------------------------------------------
    def _open_preview(self, e=None):
        try:
            self.page_ref.launch_url("/")
        except Exception:
            try:
                self.page_ref.launch_url("/", web_only_window_name="_blank")
            except Exception as ex:
                self._snack(f"⚠️ {ex}")

    # -----------------------------------------------------------------------------
    # 4.3.4 — Helpers
    # -----------------------------------------------------------------------------
    def _set_status(self, message, color="#1e40af"):
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