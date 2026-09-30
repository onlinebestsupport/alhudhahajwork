# =================================================================================
# SECTION 3 (FLET VERSION) — SETTINGS MANAGER
# =================================================================================
# UPDATED — 2026-09-30 (Cloud-ready)
#   • All CSV reads/writes use encoding='utf-8-sig' (no BOM issues)
#   • Default company settings include logo_data_uri field
#   • Error logging on write failures
#   • Safe fallback if disk is read-only
# =================================================================================

import json
import uuid
import os
from datetime import datetime
import pandas as pd


# =================================================================================
# 3.1 — CLASS: SettingsManager
# =================================================================================
class SettingsManager:

    # =============================================================================
    # 3.1.1 — __init__
    # =============================================================================
    def __init__(self, db):
        self.db = db

    # =================================================================================
    # 3.1.2 — SAFE CSV HELPERS (private)
    # =================================================================================
    def _safe_read_csv(self, path):
        """Read a CSV with proper encoding; return None on failure."""
        try:
            if not os.path.exists(str(path)):
                return None
            # utf-8-sig strips any BOM at the start of the file,
            # which prevents columns like '\ufeffgst_percentage'.
            df = pd.read_csv(path, encoding='utf-8-sig')
            return df
        except Exception as ex:
            print(f"[SETTINGS] read failed ({path}): {ex}")
            return None

    def _safe_write_csv(self, df, path):
        """Write a CSV with proper encoding; return True/False."""
        try:
            # Ensure parent folder exists (fresh installs on cloud)
            parent = os.path.dirname(str(path))
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            df.to_csv(path, index=False, encoding='utf-8-sig')
            return True
        except Exception as ex:
            print(f"[SETTINGS] write failed ({path}): {ex}")
            return False

    # =================================================================================
    # 3.2 — COMPANY SETTINGS
    # =================================================================================
    def get_company_settings(self):
        if not self.db.company_settings.empty:
            company = self.db.company_settings.iloc[0].to_dict()
            if company.get('bank_details') and isinstance(
                    company['bank_details'], str):
                try:
                    company['bank_details'] = json.loads(
                        company['bank_details'])
                except Exception:
                    company['bank_details'] = {}
            return company
        return self.get_default_company_settings()

    def get_default_company_settings(self):
        return {
            'company_name': 'Alhudha Haj Travel',
            'address': '123 Pilgrim Street, Makkah Road',
            'phone': '+966 123456789',
            'email': 'info@alhudahaj.com',
            'website': 'www.alhudahaj.com',
            'gst_no': 'GST123456',
            'tan_no': 'TAN123456',
            'pan_no': 'PAN123456',
            'logo_path': '',
            'logo_data_uri': '',   # ✅ NEW — base64 logo column
            'bank_details': {
                'bank_name': 'Islamic Bank',
                'account_no': '1234567890',
                'ifsc': 'ISBK0001234',
                'upi': 'alhudha@islamic'
            }
        }

    # =================================================================================
    # 3.3 — TAX SETTINGS (GST & TCS)
    # =================================================================================
    def get_tax_settings(self):
        tax_file = self.db.data_dir / "tax_settings.csv"
        df = self._safe_read_csv(tax_file)
        if df is not None and not df.empty:
            try:
                row = df.iloc[0].to_dict()

                gst_val = row.get('gst_percentage', 18)
                if gst_val is None or (isinstance(gst_val, float)
                                       and str(gst_val) == 'nan'):
                    gst_val = 18.0
                try:
                    gst_val = float(gst_val)
                except Exception:
                    gst_val = 18.0

                tcs_val = row.get('tcs_percentage', 0.1)
                if tcs_val is None or (isinstance(tcs_val, float)
                                       and str(tcs_val) == 'nan'):
                    tcs_val = 0.1
                try:
                    tcs_val = float(tcs_val)
                except Exception:
                    tcs_val = 0.1

                return {
                    'gst_percentage': gst_val,
                    'tcs_percentage': tcs_val,
                    'gst_description': 'Goods and Services Tax',
                    'tcs_description': 'Tax Collected at Source',
                    'updated_date': datetime.now().isoformat(),
                    'updated_by': 'system'
                }
            except Exception as e:
                print(f"[SETTINGS] tax parse error: {e}")

        # Fall back to defaults
        default_tax = {
            'id': str(uuid.uuid4()),
            'gst_percentage': 18.0,
            'tcs_percentage': 0.1,
            'gst_description': 'Goods and Services Tax',
            'tcs_description': 'Tax Collected at Source',
            'updated_date': datetime.now().isoformat(),
            'updated_by': 'system'
        }
        self._safe_write_csv(pd.DataFrame([default_tax]), tax_file)
        return default_tax

    def update_tax_settings(self, gst_percentage, tcs_percentage):
        tax_file = self.db.data_dir / "tax_settings.csv"

        try:
            gst_val = float(gst_percentage)
        except Exception:
            gst_val = 18.0

        try:
            tcs_val = float(tcs_percentage)
        except Exception:
            tcs_val = 0.1

        gst_val = max(0, min(100, gst_val))
        tcs_val = max(0, min(100, tcs_val))

        tax_data = {
            'id': str(uuid.uuid4()),
            'gst_percentage': gst_val,
            'tcs_percentage': tcs_val,
            'gst_description': 'Goods and Services Tax',
            'tcs_description': 'Tax Collected at Source',
            'updated_date': datetime.now().isoformat(),
            'updated_by': 'system'
        }
        ok = self._safe_write_csv(pd.DataFrame([tax_data]), tax_file)
        if not ok:
            print(f"[SETTINGS] ⚠️ Could not save tax settings to {tax_file}")
        return tax_data

    # =================================================================================
    # 3.4 — TOUR TYPES
    # =================================================================================
    def get_tour_types(self):
        tour_file = self.db.data_dir / "tour_types.csv"
        df = self._safe_read_csv(tour_file)

        if df is not None and not df.empty:
            try:
                if 'year' not in df.columns:
                    df['year'] = datetime.now().year
                    self._safe_write_csv(df, tour_file)
                return df.to_dict('records')
            except Exception as e:
                print(f"[SETTINGS] tour parse error: {e}")

        # Generate defaults
        current_year = datetime.now().year
        default_tours = []

        for year in range(current_year - 2, current_year + 6):
            default_tours.append({
                'id': str(uuid.uuid4()),
                'tour_name': 'Haj',
                'year': year,
                'description': 'Haj Pilgrimage',
                'is_active': True
            })
            default_tours.append({
                'id': str(uuid.uuid4()),
                'tour_name': 'Umrah',
                'year': year,
                'description': 'Umrah Pilgrimage',
                'is_active': True
            })

            if current_year - 1 <= year <= current_year + 3:
                default_tours.append({
                    'id': str(uuid.uuid4()),
                    'tour_name': 'Ziyarah',
                    'year': year,
                    'description': 'Ziyarah Tour - Visit Holy Sites',
                    'is_active': True
                })
                default_tours.append({
                    'id': str(uuid.uuid4()),
                    'tour_name': 'UK Tour',
                    'year': year,
                    'description': 'United Kingdom Tour',
                    'is_active': True
                })

        self._safe_write_csv(pd.DataFrame(default_tours), tour_file)
        return default_tours

    def add_tour_type(self, tour_name, description, year=None):
        tour_file = self.db.data_dir / "tour_types.csv"
        tours = self.get_tour_types()

        if year is None:
            year = datetime.now().year

        if year < 2020:
            year = 2020
        elif year > 2099:
            year = 2099

        new_tour = {
            'id': str(uuid.uuid4()),
            'tour_name': str(tour_name),
            'year': int(year),
            'description': str(description),
            'is_active': True
        }
        tours.append(new_tour)
        self._safe_write_csv(pd.DataFrame(tours), tour_file)
        return new_tour

    def update_tour_type(self, tour_id, tour_name, year, description,
                         is_active):
        tour_file = self.db.data_dir / "tour_types.csv"
        tours = self.get_tour_types()

        if year < 2020:
            year = 2020
        elif year > 2099:
            year = 2099

        for tour in tours:
            if tour['id'] == tour_id:
                tour['tour_name'] = str(tour_name)
                tour['year'] = int(year)
                tour['description'] = str(description)
                tour['is_active'] = bool(is_active)
                break

        self._safe_write_csv(pd.DataFrame(tours), tour_file)

    def delete_tour_type(self, tour_id):
        tour_file = self.db.data_dir / "tour_types.csv"
        tours = self.get_tour_types()
        tours = [t for t in tours if t['id'] != tour_id]
        self._safe_write_csv(pd.DataFrame(tours), tour_file)

    def get_tour_type_by_name_year(self, tour_name, year):
        tours = self.get_tour_types()
        for tour in tours:
            if (tour.get('tour_name', '').upper() == tour_name.upper()
                    and tour.get('year') == year):
                return tour
        return None

    def get_tour_types_by_year(self, year):
        tours = self.get_tour_types()
        return [t for t in tours
                if t.get('year') == year and t.get('is_active', True)]

    def get_tour_years(self):
        tours = self.get_tour_types()
        years = sorted(set(
            [t.get('year', datetime.now().year) for t in tours]))

        all_years = list(range(2020, 2100))
        if not years:
            return all_years

        combined = list(set(all_years + years))
        return sorted(combined, reverse=True)

    def get_active_tour_types(self):
        tours = self.get_tour_types()
        return [t for t in tours if t.get('is_active', True)]


# =================================================================================
# SECTION 3 END (FLET VERSION)
# =================================================================================