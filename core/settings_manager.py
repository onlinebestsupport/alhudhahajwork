# core/settings_manager.py — centralized, validated application settings
import json
import math
import os
import tempfile
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

DEFAULT_GST_PERCENTAGE = Decimal("5")
DEFAULT_TCS_PERCENTAGE = Decimal("2")
MIN_TOUR_YEAR = 2020
MAX_TOUR_YEAR = 2099


def _decimal_percent(value, default):
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            raise InvalidOperation
        parsed = Decimal(str(value).strip())
        if not parsed.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError):
        parsed = default
    return max(Decimal("0"), min(Decimal("100"), parsed)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ).normalize()


def _percent_for_csv(value):
    return format(_decimal_percent(value, Decimal("0")), "f")


class SettingsManager:
    def __init__(self, db):
        self.db = db

    def _safe_read_csv(self, path):
        try:
            path = Path(path)
            if not path.exists():
                return None
            return pd.read_csv(path, encoding="utf-8-sig")
        except Exception as ex:
            print(f"[SETTINGS] read failed ({path}): {ex}")
            return None

    def _safe_write_csv(self, df, path):
        """Write atomically so a restart cannot leave a half-written CSV."""
        path = Path(path)
        tmp_path = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
            )
            os.close(fd)
            tmp_path = Path(tmp_name)
            df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
            os.replace(tmp_path, path)
            return True
        except Exception as ex:
            print(f"[SETTINGS] write failed ({path}): {ex}")
            if tmp_path:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
            return False

    def get_company_settings(self):
        if not self.db.company_settings.empty:
            company = self.db.company_settings.iloc[0].to_dict()
            bank = company.get("bank_details")
            if isinstance(bank, str):
                try:
                    company["bank_details"] = json.loads(bank)
                except Exception:
                    company["bank_details"] = {}
            return company
        return self.get_default_company_settings()

    def get_default_company_settings(self):
        return {
            "company_name": "Alhudha Haj Travel",
            "address": "",
            "phone": "",
            "email": "",
            "website": "",
            "gst_no": "",
            "tan_no": "",
            "pan_no": "",
            "logo_path": "",
            "logo_data_uri": "",
            "bank_details": {
                "bank_name": "", "account_no": "", "ifsc": "", "upi": ""
            },
        }

    def get_tax_settings(self):
        tax_file = Path(self.db.data_dir) / "tax_settings.csv"
        df = self._safe_read_csv(tax_file)
        if df is not None and not df.empty:
            row = df.iloc[0].to_dict()
            gst = _decimal_percent(row.get("gst_percentage"), DEFAULT_GST_PERCENTAGE)
            tcs = _decimal_percent(row.get("tcs_percentage"), DEFAULT_TCS_PERCENTAGE)
            return {
                "id": str(row.get("id") or uuid.uuid4()),
                "gst_percentage": format(gst, "f"),
                "tcs_percentage": format(tcs, "f"),
                "gst_description": str(row.get("gst_description") or "Goods and Services Tax"),
                "tcs_description": str(row.get("tcs_description") or "Tax Collected at Source"),
                "updated_date": str(row.get("updated_date") or ""),
                "updated_by": str(row.get("updated_by") or "system"),
            }

        tax_data = {
            "id": str(uuid.uuid4()),
            "gst_percentage": format(DEFAULT_GST_PERCENTAGE, "f"),
            "tcs_percentage": format(DEFAULT_TCS_PERCENTAGE, "f"),
            "gst_description": "Goods and Services Tax",
            "tcs_description": "Tax Collected at Source",
            "updated_date": datetime.now().isoformat(),
            "updated_by": "system",
        }
        if not self._safe_write_csv(pd.DataFrame([tax_data]), tax_file):
            print(f"[SETTINGS] unable to create default tax file: {tax_file}")
        return tax_data

    def update_tax_settings(self, gst_percentage, tcs_percentage, updated_by="system"):
        tax_file = Path(self.db.data_dir) / "tax_settings.csv"
        gst = _decimal_percent(gst_percentage, DEFAULT_GST_PERCENTAGE)
        tcs = _decimal_percent(tcs_percentage, DEFAULT_TCS_PERCENTAGE)
        tax_data = {
            "id": str(uuid.uuid4()),
            "gst_percentage": format(gst, "f"),
            "tcs_percentage": format(tcs, "f"),
            "gst_description": "Goods and Services Tax",
            "tcs_description": "Tax Collected at Source",
            "updated_date": datetime.now().isoformat(),
            "updated_by": str(updated_by or "system"),
        }
        if not self._safe_write_csv(pd.DataFrame([tax_data]), tax_file):
            raise OSError(f"Could not save tax settings to {tax_file}")
        return tax_data

    def get_tour_types(self):
        tour_file = Path(self.db.data_dir) / "tour_types.csv"
        df = self._safe_read_csv(tour_file)
        if df is not None and not df.empty:
            try:
                if "year" not in df.columns:
                    df["year"] = datetime.now().year
                    self._safe_write_csv(df, tour_file)
                return df.to_dict("records")
            except Exception as ex:
                print(f"[SETTINGS] tour parse error: {ex}")

        current_year = datetime.now().year
        tours = []
        for year in range(current_year - 2, current_year + 6):
            for name, description in (("Haj", "Haj Pilgrimage"), ("Umrah", "Umrah Pilgrimage")):
                tours.append({"id": str(uuid.uuid4()), "tour_name": name,
                              "year": year, "description": description, "is_active": True})
            if current_year - 1 <= year <= current_year + 3:
                for name, description in (("Ziyarah", "Ziyarah Tour - Visit Holy Sites"),
                                          ("UK Tour", "United Kingdom Tour")):
                    tours.append({"id": str(uuid.uuid4()), "tour_name": name,
                                  "year": year, "description": description, "is_active": True})
        if not self._safe_write_csv(pd.DataFrame(tours), tour_file):
            print(f"[SETTINGS] unable to create tour file: {tour_file}")
        return tours

    @staticmethod
    def _year(value):
        try:
            return max(MIN_TOUR_YEAR, min(MAX_TOUR_YEAR, int(value)))
        except (TypeError, ValueError):
            return datetime.now().year

    @staticmethod
    def _tour_key(name, year):
        return str(name or "").strip().casefold(), int(year)

    def add_tour_type(self, tour_name, description, year=None):
        name = str(tour_name or "").strip()
        if not name:
            raise ValueError("Tour name is required")
        year = self._year(year)
        tours = self.get_tour_types()
        if any(self._tour_key(t.get("tour_name"), t.get("year")) == self._tour_key(name, year)
               and bool(t.get("is_active", True)) for t in tours):
            raise ValueError(f"Tour '{name}' for {year} already exists")
        new_tour = {"id": str(uuid.uuid4()), "tour_name": name, "year": year,
                    "description": str(description or "").strip(), "is_active": True}
        tours.append(new_tour)
        if not self._safe_write_csv(pd.DataFrame(tours), Path(self.db.data_dir) / "tour_types.csv"):
            raise OSError("Could not save tour type")
        return new_tour

    def update_tour_type(self, tour_id, tour_name, year, description, is_active):
        target = str(tour_id or "").strip()
        tours = self.get_tour_types()
        found = False
        year = self._year(year)
        for tour in tours:
            if str(tour.get("id", "")).strip() == target:
                tour.update({"tour_name": str(tour_name or "").strip(), "year": year,
                             "description": str(description or "").strip(),
                             "is_active": bool(is_active)})
                found = True
                break
        if not found:
            raise KeyError(f"Tour type not found: {target}")
        if not self._safe_write_csv(pd.DataFrame(tours), Path(self.db.data_dir) / "tour_types.csv"):
            raise OSError("Could not save tour type")

    def delete_tour_type(self, tour_id):
        target = str(tour_id or "").strip()
        tours = self.get_tour_types()
        remaining = [t for t in tours if str(t.get("id", "")).strip() != target]
        if len(remaining) == len(tours):
            raise KeyError(f"Tour type not found: {target}")
        if not self._safe_write_csv(pd.DataFrame(remaining), Path(self.db.data_dir) / "tour_types.csv"):
            raise OSError("Could not delete tour type")

    def get_tour_type_by_name_year(self, tour_name, year):
        key = self._tour_key(tour_name, year)
        return next((t for t in self.get_tour_types()
                     if self._tour_key(t.get("tour_name"), t.get("year")) == key), None)

    def get_tour_types_by_year(self, year):
        try:
            target = int(year)
        except (TypeError, ValueError):
            return []
        return [t for t in self.get_tour_types()
                if int(t.get("year", 0)) == target and bool(t.get("is_active", True))]

    def get_tour_years(self):
        years = {int(t.get("year")) for t in self.get_tour_types()
                 if str(t.get("year", "")).isdigit()}
        return sorted(years or {datetime.now().year}, reverse=True)

    def get_active_tour_types(self):
        return [t for t in self.get_tour_types() if bool(t.get("is_active", True))]
