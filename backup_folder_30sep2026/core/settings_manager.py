# =================================================================================
# SECTION 3 (FLET VERSION) — SETTINGS MANAGER
# =================================================================================

# ---- 3.0 — Imports (only these change from desktop) ----
import json
import uuid
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
                except:
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
        try:
            if tax_file.exists():
                df = pd.read_csv(tax_file)
                if not df.empty:
                    row = df.iloc[0].to_dict()

                    gst_val = row.get('gst_percentage', 18)
                    if gst_val is None or (isinstance(gst_val, float)
                                           and str(gst_val) == 'nan'):
                        gst_val = 18.0
                    try:
                        gst_val = float(gst_val)
                    except:
                        gst_val = 18.0

                    tcs_val = row.get('tcs_percentage', 0.1)
                    if tcs_val is None or (isinstance(tcs_val, float)
                                           and str(tcs_val) == 'nan'):
                        tcs_val = 0.1
                    try:
                        tcs_val = float(tcs_val)
                    except:
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
            print(f"Error reading tax file: {e}")

        default_tax = {
            'id': str(uuid.uuid4()),
            'gst_percentage': 18.0,
            'tcs_percentage': 0.1,
            'gst_description': 'Goods and Services Tax',
            'tcs_description': 'Tax Collected at Source',
            'updated_date': datetime.now().isoformat(),
            'updated_by': 'system'
        }
        pd.DataFrame([default_tax]).to_csv(tax_file, index=False)
        return default_tax

    def update_tax_settings(self, gst_percentage, tcs_percentage):
        tax_file = self.db.data_dir / "tax_settings.csv"

        try:
            gst_val = float(gst_percentage)
        except:
            gst_val = 18.0

        try:
            tcs_val = float(tcs_percentage)
        except:
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
        pd.DataFrame([tax_data]).to_csv(tax_file, index=False)
        return tax_data

    # =================================================================================
    # 3.4 — TOUR TYPES (FIX #8)
    # =================================================================================
    def get_tour_types(self):
        tour_file = self.db.data_dir / "tour_types.csv"

        if tour_file.exists():
            try:
                df = pd.read_csv(tour_file)
                if 'year' not in df.columns:
                    df['year'] = datetime.now().year
                    df.to_csv(tour_file, index=False)
                return df.to_dict('records')
            except:
                pass

        current_year = datetime.now().year
        default_tours = []

        # Haj + Umrah for current_year - 2 to current_year + 5
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

            # Ziyarah + UK Tour only for current_year - 1 to current_year + 3
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

        pd.DataFrame(default_tours).to_csv(tour_file, index=False)
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
        pd.DataFrame(tours).to_csv(tour_file, index=False)
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

        pd.DataFrame(tours).to_csv(tour_file, index=False)

    def delete_tour_type(self, tour_id):
        tour_file = self.db.data_dir / "tour_types.csv"
        tours = self.get_tour_types()
        tours = [t for t in tours if t['id'] != tour_id]
        pd.DataFrame(tours).to_csv(tour_file, index=False)

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