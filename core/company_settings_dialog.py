# =================================================================================
# SECTION 4 (FLET 1.0.0 VERSION) — COMPANY SETTINGS DIALOG
# =================================================================================
# UPDATED — 2026-09-30 (Cloud-ready)
#   • Logo stored as base64 data URI IN THE CSV — survives Railway redeploys
#   • Falls back to file path if base64 is missing (backward compat)
#   • FilePicker registered via page.services (Flet 1.0 standard)
#   • SnackBar uses page.snack_bar (Flet 1.0 correct way)
# =================================================================================

import flet as ft
import json
import uuid
import shutil
import os
import base64
from pathlib import Path
from datetime import datetime
import pandas as pd

from core.settings_manager import SettingsManager
from core.helpers import get_app_base_path


# =================================================================================
# 4.1 — CLASS: CompanySettingsDialog
# =================================================================================
class CompanySettingsDialog:

    def __init__(self, page: ft.Page, db, current_user,
                 on_save_callback=None):
        self.page = page
        self.db = db
        self.current_user = current_user
        self.settings_manager = SettingsManager(db)
        self.on_save_callback = on_save_callback
        self.logo_path = None              # absolute path (for local files)
        self.logo_data_uri = None          # base64 data URI (for cloud)
        self.dialog = None
        self.file_picker = None

        self.logo_image = None
        self.logo_placeholder = None
        self.company_name_field = None
        self.address_field = None
        self.phone_field = None
        self.email_field = None
        self.website_field = None
        self.gst_field = None
        self.tan_field = None
        self.pan_field = None
        self.bank_name_field = None
        self.account_no_field = None
        self.ifsc_field = None
        self.upi_field = None
        self.gst_percentage_field = None
        self.tcs_percentage_field = None
        self.tour_table = None
        self.tour_name_input = None
        self.tour_year_input = None
        self.tour_desc_input = None

        self.setup_ui()
        self.load_settings()

    # =============================================================================
    # setup_ui
    # =============================================================================
    def setup_ui(self):
        self.file_picker = ft.FilePicker()

        # ---- COMPANY TAB ----
        self.logo_image = ft.Image(
            src="", width=100, height=100,
            fit=ft.BoxFit.CONTAIN, border_radius=8, visible=False,
        )
        self.logo_placeholder = ft.Container(
            content=ft.Text("No Logo", color=ft.Colors.GREY_500, size=12),
            width=100, height=100,
            alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.GREY_100,
            border_radius=8,
            border=ft.Border.all(2, ft.Colors.GREY_400),
        )

        self.company_name_field = ft.TextField(
            label="🏢 Company Name *", hint_text="Enter company name", expand=True)
        self.address_field = ft.TextField(
            label="📍 Address", multiline=True, min_lines=2, max_lines=4,
            hint_text="Enter full address")
        self.phone_field = ft.TextField(label="📞 Phone", hint_text="+966 XX XXXXXXX")
        self.email_field = ft.TextField(label="📧 Email", hint_text="info@company.com")
        self.website_field = ft.TextField(label="🌐 Website", hint_text="www.company.com")
        self.gst_field = ft.TextField(label="💰 GST Number", hint_text="GSTXXXXXXXXX")
        self.tan_field = ft.TextField(label="🏛️ TAN Number", hint_text="TANXXXXXXXXX")
        self.pan_field = ft.TextField(label="📄 PAN Number", hint_text="PANXXXXXXXX")

        company_tab = ft.Column(
            controls=[
                ft.Row([
                    ft.Stack([self.logo_placeholder, self.logo_image],
                             width=100, height=100),
                    ft.Column([
                        ft.Button(content=ft.Text("📸 Upload Logo"),
                                  on_click=self.upload_logo_click,
                                  bgcolor=ft.Colors.BLUE_600,
                                  color=ft.Colors.WHITE),
                        ft.Button(content=ft.Text("🗑️ Remove Logo"),
                                  on_click=self.remove_logo_click,
                                  bgcolor=ft.Colors.RED_600,
                                  color=ft.Colors.WHITE),
                    ], spacing=8),
                ], spacing=20),
                self.company_name_field,
                self.address_field,
                ft.Row([self.phone_field, self.email_field], spacing=10),
                self.website_field,
                ft.Row([self.gst_field, self.tan_field], spacing=10),
                self.pan_field,
            ], spacing=12, scroll=ft.ScrollMode.AUTO,
        )

        # ---- BANK TAB ----
        self.bank_name_field = ft.TextField(label="🏦 Bank Name", hint_text="Name of bank")
        self.account_no_field = ft.TextField(label="💳 Account Number", hint_text="Account number")
        self.ifsc_field = ft.TextField(label="🔢 IFSC Code", hint_text="IFSC code (e.g., HDFC0001234)")
        self.upi_field = ft.TextField(label="⚡ UPI ID", hint_text="UPI ID (e.g., name@bank)")

        bank_tab = ft.Column(
            controls=[self.bank_name_field, self.account_no_field,
                      self.ifsc_field, self.upi_field],
            spacing=12, scroll=ft.ScrollMode.AUTO,
        )

        # ---- TAX TAB ----
        self.gst_percentage_field = ft.TextField(
            label="💰 GST Percentage", value="18", hint_text="e.g., 5",
            suffix=ft.Text("%"))
        self.tcs_percentage_field = ft.TextField(
            label="💰 TCS Percentage", value="0", hint_text="e.g., 2",
            suffix=ft.Text("%"))

        tax_tab = ft.Column(
            controls=[
                self.gst_percentage_field,
                self.tcs_percentage_field,
                ft.Container(
                    content=ft.Text(
                        "ℹ️ GST is calculated on Base Amount.\n"
                        "TCS is calculated on Taxable Amount (Base + GST).",
                        size=11, color=ft.Colors.GREY_700),
                    padding=10, bgcolor=ft.Colors.BLUE_50, border_radius=6),
            ], spacing=12,
        )

        # ---- TOURS TAB ----
        self.tour_name_input = ft.TextField(
            label="Tour Name", hint_text="Haj, Umrah, UK Tour", width=180)
        self.tour_year_input = ft.TextField(
            label="Year", value=str(datetime.now().year), width=100)
        self.tour_desc_input = ft.TextField(
            label="Description", hint_text="Tour description", expand=True)

        self.tour_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Tour Name")),
                ft.DataColumn(ft.Text("Year")),
                ft.DataColumn(ft.Text("Description")),
                ft.DataColumn(ft.Text("Actions")),
            ], rows=[], column_spacing=15,
            heading_row_color=ft.Colors.BLUE_GREY_900,
            heading_row_height=40, data_row_min_height=40,
        )

        tours_tab = ft.Column(
            controls=[
                ft.Container(
                    content=ft.Column([
                        ft.Text("➕ Add New Tour Type",
                                weight=ft.FontWeight.BOLD, size=13),
                        ft.Row([
                            self.tour_name_input,
                            self.tour_year_input,
                            self.tour_desc_input,
                            ft.Button(content=ft.Text("➕ Add"),
                                      on_click=self.add_tour_type_click,
                                      bgcolor=ft.Colors.GREEN_600,
                                      color=ft.Colors.WHITE, height=48),
                        ], spacing=8),
                    ], spacing=8),
                    padding=12, bgcolor=ft.Colors.GREY_50, border_radius=8,
                    border=ft.Border.all(1, ft.Colors.GREY_300)),
                ft.Text(
                    "💡 Format: PREFIX/BCH/YEAR/XXX (e.g., HAJ/BCH/2027/001)",
                    size=11, color=ft.Colors.GREY_600),
                ft.Container(
                    content=ft.Column([self.tour_table], scroll=ft.ScrollMode.AUTO),
                    expand=True,
                    border=ft.Border.all(1, ft.Colors.GREY_300),
                    border_radius=8, padding=5),
            ], spacing=10, expand=True,
        )

        # ---- TABS ----
        tabs = ft.Tabs(
            selected_index=0, animation_duration=200, length=4, expand=True,
            content=ft.Column(expand=True, controls=[
                ft.TabBar(tabs=[
                    ft.Tab(label="🏢 Company Info"),
                    ft.Tab(label="🏦 Bank Details"),
                    ft.Tab(label="💰 Tax Settings"),
                    ft.Tab(label="🎯 Tour Types"),
                ]),
                ft.TabBarView(expand=True, controls=[
                    ft.Container(content=company_tab, padding=15),
                    ft.Container(content=bank_tab, padding=15),
                    ft.Container(content=tax_tab, padding=15),
                    ft.Container(content=tours_tab, padding=15),
                ]),
            ]),
        )

        # ---- DIALOG ----
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Company Settings",
                          weight=ft.FontWeight.BOLD, size=18),
            content=ft.Container(content=tabs, width=850, height=520),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=self.on_cancel),
                ft.Button(content=ft.Text("💾 Save All Settings"),
                          on_click=self.on_save,
                          bgcolor=ft.Colors.GREEN_600,
                          color=ft.Colors.WHITE, height=42),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    # =============================================================================
    # Helper: Convert local image file to base64 data URI
    # =============================================================================
    def _get_logo_data_uri(self, file_path: str) -> str:
        """Reads an image file and returns a base64 data URI string
        that the browser can display directly (works without server routing)."""
        try:
            if not file_path or not os.path.exists(file_path):
                return ""
            ext = Path(file_path).suffix.lower().lstrip(".")
            if ext in ("jpg", "jpeg"):
                mime = "image/jpeg"
            elif ext == "png":
                mime = "image/png"
            elif ext == "gif":
                mime = "image/gif"
            elif ext == "bmp":
                mime = "image/bmp"
            else:
                mime = "image/png"
            with open(file_path, "rb") as fh:
                encoded = base64.b64encode(fh.read()).decode("ascii")
            return f"data:{mime};base64,{encoded}"
        except Exception as ex:
            print(f">>> _get_logo_data_uri failed: {ex}")
            return ""

    # =============================================================================
    # Logo Upload
    # =============================================================================
    def upload_logo_click(self, e):
        print(">>> UPLOAD LOGO CLICKED")
        try:
            self.page.run_task(self._pick_logo_async)
        except Exception as ex:
            print(f">>> run_task failed: {ex}")
            self.show_snack(f"❌ Could not open file picker: {ex}")

    async def _pick_logo_async(self):
        try:
            print(">>> Awaiting pick_files()...")
            files = None
            try:
                files = await self.file_picker.pick_files(
                    allow_multiple=False,
                    allowed_extensions=["png", "jpg", "jpeg", "bmp"],
                    with_data=True,
                )
            except TypeError:
                print(">>> with_data not supported, falling back")
                files = await self.file_picker.pick_files(
                    allow_multiple=False,
                    allowed_extensions=["png", "jpg", "jpeg", "bmp"],
                )

            print(f">>> Files returned: {files}")
            if not files:
                print(">>> User cancelled")
                return

            f = files[0]
            print(f">>> .name = {getattr(f, 'name', None)}")
            print(f">>> .size = {getattr(f, 'size', None)}")
            print(f">>> .path = {getattr(f, 'path', None)}")
            b = getattr(f, 'bytes', None)
            print(f">>> .bytes type = {type(b)}, len = {len(b) if b else 0}")

            src_path = getattr(f, 'path', None)
            if src_path and isinstance(src_path, str) and os.path.exists(src_path):
                print(f">>> Using desktop path: {src_path}")
                await self._save_logo_from_path(src_path)
                return

            data = getattr(f, 'bytes', None)
            if isinstance(data, bytes) and len(data) > 0:
                print(f">>> Got {len(data)} bytes from .bytes ✅")
                await self._save_logo_from_bytes(data, getattr(f, 'name', 'logo.png'))
                return

            file_id = getattr(f, 'id', None)
            if file_id is not None and hasattr(self.file_picker, 'get_file_bytes'):
                try:
                    print(f">>> Trying get_file_bytes(id={file_id})...")
                    result = self.file_picker.get_file_bytes(file_id)
                    if hasattr(result, '__await__'):
                        result = await result
                    if isinstance(result, bytes) and len(result) > 0:
                        print(f">>> Got {len(result)} bytes via get_file_bytes ✅")
                        await self._save_logo_from_bytes(
                            result, getattr(f, 'name', 'logo.png'))
                        return
                except Exception as ex:
                    print(f">>> get_file_bytes failed: {ex}")

            self.show_snack("⚠️ Could not read file bytes. Please try again.")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self.show_snack(f"❌ File picker error: {ex}")

    async def _save_logo_from_path(self, src_path: str):
        try:
            base = get_app_base_path()
            logos_dir = Path(base) / "logos"
            logos_dir.mkdir(exist_ok=True)
            logo_filename = (f"company_logo_"
                             f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                             f"{Path(src_path).suffix}")
            logo_dest = logos_dir / logo_filename
            try:
                from PIL import Image
                with Image.open(src_path) as img:
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    png_dest = logo_dest.with_suffix('.png')
                    img.save(png_dest, "PNG", optimize=True)
                    logo_dest = png_dest
            except Exception:
                shutil.copy(src_path, logo_dest)

            self.logo_path = str(logo_dest)

            data_uri = self._get_logo_data_uri(str(logo_dest))
            if data_uri:
                self.logo_data_uri = data_uri
                self.logo_image.src = data_uri
                print(f">>> Logo src = base64 ({len(data_uri)} chars)")
            else:
                print(">>> ⚠️ Could not create data URI")

            self.logo_image.visible = True
            self.logo_placeholder.visible = False
            self.page.update()
            self.show_snack("✅ Logo uploaded successfully!")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self.show_snack(f"❌ Could not upload logo: {ex}")

    async def _save_logo_from_bytes(self, data: bytes, filename: str):
        try:
            base = get_app_base_path()
            logos_dir = Path(base) / "logos"
            logos_dir.mkdir(exist_ok=True)

            ext = Path(filename).suffix or ".png"
            logo_filename = (f"company_logo_"
                             f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                             f"{ext}")
            logo_dest = logos_dir / logo_filename

            with open(logo_dest, "wb") as fh:
                fh.write(data)
            print(f">>> Saved {len(data)} bytes to {logo_dest}")

            try:
                from PIL import Image
                with Image.open(logo_dest) as img:
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    png_dest = logo_dest.with_suffix('.png')
                    img.save(png_dest, "PNG", optimize=True)
                    if png_dest != logo_dest:
                        try:
                            os.remove(logo_dest)
                        except Exception:
                            pass
                    logo_dest = png_dest
                print(f">>> Converted to PNG: {logo_dest}")
            except Exception as pil_ex:
                print(f">>> PIL skipped: {pil_ex}")

            self.logo_path = str(logo_dest)

            data_uri = self._get_logo_data_uri(str(logo_dest))
            if data_uri:
                self.logo_data_uri = data_uri
                self.logo_image.src = data_uri
                print(f">>> Logo src = base64 ({len(data_uri)} chars)")
            else:
                print(">>> ⚠️ Could not create data URI")

            self.logo_image.visible = True
            self.logo_placeholder.visible = False
            self.page.update()
            self.show_snack("✅ Logo uploaded successfully!")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self.show_snack(f"❌ Could not save logo: {ex}")

    def remove_logo_click(self, e):
        print(">>> REMOVE LOGO CLICKED")
        self.logo_path = None
        self.logo_data_uri = None
        self.logo_image.src = ""
        self.logo_image.visible = False
        self.logo_placeholder.visible = True
        self.page.update()
        self.show_snack("✅ Logo removed")

    # =============================================================================
    # load_settings — with base64 logo preview
    # =============================================================================
    def load_settings(self):
        try:
            company = self.settings_manager.get_company_settings()

            def s(v):
                return '' if v is None else str(v)

            self.company_name_field.value = s(company.get('company_name', ''))
            self.address_field.value = s(company.get('address', ''))
            self.phone_field.value = s(company.get('phone', ''))
            self.email_field.value = s(company.get('email', ''))
            self.website_field.value = s(company.get('website', ''))
            self.gst_field.value = s(company.get('gst_no', ''))
            self.tan_field.value = s(company.get('tan_no', ''))
            self.pan_field.value = s(company.get('pan_no', ''))

            # ---- Load existing logo ----
            # Prefer logo_data_uri column (cloud-safe), fall back to file path.
            logo_data_uri = company.get('logo_data_uri', '')
            logo_path = company.get('logo_path', '')

            # Case A: base64 data URI stored in CSV
            if (isinstance(logo_data_uri, str)
                    and logo_data_uri.startswith("data:image/")):
                self.logo_data_uri = logo_data_uri
                self.logo_image.src = logo_data_uri
                self.logo_image.visible = True
                self.logo_placeholder.visible = False
                print(f">>> Loaded logo from CSV base64 "
                      f"({len(logo_data_uri)} chars)")
            # Case B: file path stored in CSV (legacy)
            elif (isinstance(logo_path, str)
                    and logo_path
                    and os.path.exists(logo_path)):
                self.logo_path = logo_path
                data_uri = self._get_logo_data_uri(logo_path)
                if data_uri:
                    self.logo_data_uri = data_uri
                    self.logo_image.src = data_uri
                    self.logo_image.visible = True
                    self.logo_placeholder.visible = False
                    print(f">>> Loaded existing logo as base64 "
                          f"({len(data_uri)} chars)")
            else:
                # No logo available
                self.logo_image.visible = False
                self.logo_placeholder.visible = True

            bank = company.get('bank_details', {})
            if isinstance(bank, str):
                try:
                    bank = json.loads(bank)
                except Exception:
                    bank = {}
            self.bank_name_field.value = s(bank.get('bank_name', ''))
            self.account_no_field.value = s(bank.get('account_no', ''))
            self.ifsc_field.value = s(bank.get('ifsc', '') or bank.get('swift', ''))
            self.upi_field.value = s(bank.get('upi', '') or bank.get('iban', ''))

            tax = self.settings_manager.get_tax_settings()
            self.gst_percentage_field.value = str(tax.get('gst_percentage', 18))
            self.tcs_percentage_field.value = str(tax.get('tcs_percentage', 0))

            self.load_tour_types()
        except Exception as ex:
            self.show_snack(f"⚠️ Could not load settings: {ex}")

    # =============================================================================
    # Tour Types
    # =============================================================================
    def load_tour_types(self):
        try:
            tours = self.settings_manager.get_tour_types()
            active_tours = [t for t in tours if t.get('is_active', True)]
            self.tour_table.rows.clear()
            for tour in active_tours:
                row = ft.DataRow(cells=[
                    ft.DataCell(ft.Text(str(tour.get('tour_name', '')),
                                        weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(str(tour.get('year', '')))),
                    ft.DataCell(ft.Text(str(tour.get('description', '')))),
                    ft.DataCell(ft.Row([
                        ft.IconButton(icon=ft.Icons.EDIT,
                                      icon_color=ft.Colors.ORANGE_600,
                                      tooltip="Edit",
                                      on_click=lambda e, t=tour: self.edit_tour_type_click(t)),
                        ft.IconButton(icon=ft.Icons.DELETE,
                                      icon_color=ft.Colors.RED_600,
                                      tooltip="Delete",
                                      on_click=lambda e, t=tour: self.delete_tour_type_click(t)),
                    ], spacing=0)),
                ])
                self.tour_table.rows.append(row)
            self.page.update()
        except Exception as ex:
            self.show_snack(f"⚠️ Could not load tours: {ex}")

    def add_tour_type_click(self, e):
        name = (self.tour_name_input.value or '').strip()
        if not name:
            self.show_snack("⚠️ Tour Name is required")
            return
        try:
            year = int(self.tour_year_input.value or datetime.now().year)
        except Exception:
            year = datetime.now().year
        desc = (self.tour_desc_input.value or '').strip()
        try:
            self.settings_manager.add_tour_type(name, desc, year)
            self.tour_name_input.value = ''
            self.tour_desc_input.value = ''
            self.tour_year_input.value = str(datetime.now().year)
            self.load_tour_types()
            self.show_snack(f"✅ Tour '{name}' ({year}) added")
        except Exception as ex:
            self.show_snack(f"❌ Could not add tour: {ex}")

    def edit_tour_type_click(self, tour):
        name_field = ft.TextField(label="Tour Name", value=tour.get('tour_name', ''))
        year_field = ft.TextField(label="Year", value=str(tour.get('year', '')))
        desc_field = ft.TextField(label="Description", value=tour.get('description', ''))

        def do_save(ev):
            try:
                self.settings_manager.update_tour_type(
                    tour['id'], name_field.value.strip(),
                    int(year_field.value or datetime.now().year),
                    desc_field.value.strip(), True)
                self.page.pop_dialog()
                self.load_tour_types()
                self.show_snack("✅ Tour updated")
            except Exception as ex:
                self.show_snack(f"❌ {ex}")

        edit_dialog = ft.AlertDialog(
            title=ft.Text("Edit Tour Type"),
            content=ft.Column([name_field, year_field, desc_field],
                              spacing=10, tight=True),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda ev: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Save"), on_click=do_save,
                          bgcolor=ft.Colors.GREEN_600, color=ft.Colors.WHITE),
            ])
        self.page.show_dialog(edit_dialog)

    def delete_tour_type_click(self, tour):
        def confirm(ev):
            try:
                self.settings_manager.delete_tour_type(tour['id'])
                self.page.pop_dialog()
                self.load_tour_types()
                self.show_snack("✅ Tour deleted")
            except Exception as ex:
                self.show_snack(f"❌ {ex}")

        confirm_dialog = ft.AlertDialog(
            title=ft.Text("Delete Tour Type?"),
            content=ft.Text(f"Delete '{tour.get('tour_name', '')}' "
                            f"({tour.get('year', '')})?"),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda ev: self.page.pop_dialog()),
                ft.Button(content=ft.Text("Delete"), on_click=confirm,
                          bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE),
            ])
        self.page.show_dialog(confirm_dialog)

    # =============================================================================
    # Save / Cancel
    # =============================================================================
    def on_save(self, e):
        print(">>> SAVE BUTTON CLICKED")
        try:
            if not (self.company_name_field.value or '').strip():
                self.show_snack("⚠️ Company Name is required")
                return
            print(">>> Validation passed")

            if not self.db.company_settings.empty:
                company_id = self.db.company_settings.iloc[0]['id']
            else:
                company_id = str(uuid.uuid4())

            bank_details = {
                'bank_name': (self.bank_name_field.value or '').strip(),
                'account_no': (self.account_no_field.value or '').strip(),
                'ifsc': (self.ifsc_field.value or '').strip(),
                'upi': (self.upi_field.value or '').strip(),
            }

            # ✅ Include base64 logo in CSV so it survives redeploys
            logo_data_uri_value = self.logo_data_uri or ''

            company_data = {
                'id': str(company_id),
                'company_name': (self.company_name_field.value or '').strip(),
                'address': (self.address_field.value or '').strip(),
                'phone': (self.phone_field.value or '').strip(),
                'email': (self.email_field.value or '').strip(),
                'website': (self.website_field.value or '').strip(),
                'gst_no': (self.gst_field.value or '').strip(),
                'tan_no': (self.tan_field.value or '').strip(),
                'pan_no': (self.pan_field.value or '').strip(),
                'logo_path': str(self.logo_path) if self.logo_path else '',
                'logo_data_uri': logo_data_uri_value,  # ✅ New column
                'bank_details': json.dumps(bank_details),
            }

            self.db.company_settings = pd.DataFrame([company_data])
            self.db._save_df(self.db.company_settings, "company_settings.csv")
            print(f">>> Company CSV saved "
                  f"(logo_data_uri length: {len(logo_data_uri_value)})")

            try:
                gst_val = float(self.gst_percentage_field.value or 18)
            except Exception:
                gst_val = 18.0
            try:
                tcs_val = float(self.tcs_percentage_field.value or 0)
            except Exception:
                tcs_val = 0.0

            self.settings_manager.update_tax_settings(gst_val, tcs_val)
            print(f">>> Tax saved: GST={gst_val}, TCS={tcs_val}")

            try:
                self.db.log_activity(
                    self.current_user['id'], "update_settings",
                    f"GST={gst_val}%, TCS={tcs_val}%")
            except Exception:
                pass

            self.show_snack("✅ All settings saved successfully!")

            if self.on_save_callback:
                try:
                    self.on_save_callback()
                except Exception as cb_ex:
                    print(f">>> callback failed: {cb_ex}")

            self.close()
            print(">>> SAVE COMPLETE")
        except Exception as ex:
            import traceback
            traceback.print_exc()
            self.show_snack(f"❌ Could not save: {ex}")

    def on_cancel(self, e):
        print(">>> CANCEL CLICKED")
        self.close()

    # =============================================================================
    # show / close / snack
    # =============================================================================
    def show(self):
        # Register FilePicker as service (Flet 1.0 standard)
        try:
            if hasattr(self.page, 'services'):
                if self.file_picker not in self.page.services:
                    self.page.services.append(self.file_picker)
                print("[FILE PICKER] Registered via services ✅")
            else:
                # Fallback for older Flet versions
                if self.file_picker not in self.page.overlay:
                    self.page.overlay.append(self.file_picker)
                print("[FILE PICKER] Registered via overlay ✅")
        except Exception as ex:
            print(f"[FILE PICKER] registration failed: {ex}")
        self.page.show_dialog(self.dialog)

    def close(self):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def show_snack(self, message):
        print(f"[SNACK] {message}")
        try:
            self.page.snack_bar = ft.SnackBar(content=ft.Text(message))
            self.page.snack_bar.open = True
            self.page.update()
        except Exception as ex:
            print(f"[SNACK] failed: {ex}")


# =================================================================================
# SECTION 4 END (FLET 1.0.0 VERSION)
# =================================================================================