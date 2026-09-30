# =================================================================================
# SECTION 2 (FLET VERSION) — DATABASE MODULE
# =================================================================================
# UPDATED — 2026-09-30 (Cloud-ready)
#   • Added permissions column to users.csv schema
#   • Role-based default permission sets
#   • add_user / update_user accept password OR password_hash
#   • Default admin gets all permissions
#   • Auto-migration for old users.csv (adds permissions column)
#   • New helper: get_user_permissions()
#   • 2.2.1 (UPDATED): __init__ now logs data folder + writable check
#   • 2.4.3 (UPDATED): _save_df has error handling
#   • 2.12.3 (UPDATED): create_backup notes cloud ephemeral storage
#   • 2.15 (NEW):      reload_* methods (fixes stale-cache bug)
#   • 2.16 (NEW):      file-change detection
# =================================================================================

import os
import json
import hashlib
import zipfile
import math
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

try:
    from core.helpers import get_app_base_path
except ImportError:
    def get_app_base_path():
        return os.path.dirname(os.path.abspath(__file__))


# =================================================================================
# 2.1 — PERMISSION CATALOG & ROLE DEFAULTS
# =================================================================================
PERMISSION_CATALOG = [
    "view_dashboard",
    "manage_travelers",
    "manage_batches",
    "manage_payments",
    "manage_invoices",
    "manage_receipts",
    "view_reports",
    "manage_users",
    "manage_backups",
    "manage_settings",
]

ROLE_DEFAULT_PERMISSIONS = {
    "super_admin": set(PERMISSION_CATALOG),
    "admin":       set(p for p in PERMISSION_CATALOG
                       if p != "manage_users"),
    "staff":       {"view_dashboard", "manage_travelers",
                    "manage_payments", "manage_receipts",
                    "view_reports"},
    "viewer":      {"view_dashboard", "view_reports"},
}


# =================================================================================
# 2.2 — CLASS: HajDatabase
# =================================================================================
class HajDatabase:

    # =============================================================================
    # 2.2.1 — METHOD: __init__   (UPDATED for web + logging + writable check)
    # =============================================================================
    def __init__(self, data_dir="data", current_user_id="system"):
        base_path = get_app_base_path()
        self.data_dir = Path(base_path) / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # ---- Cloud-friendly diagnostic logs ----
        print(f"[DB] Base path      : {base_path}")
        print(f"[DB] Data directory : {self.data_dir}")
        print(f"[DB] Data exists    : {self.data_dir.exists()}")
        print(f"[DB] Data writable  : "
              f"{os.access(str(self.data_dir), os.W_OK)}")

        # ---- Fail fast if the folder is not writable ----
        self._verify_writable()

        self._current_user_id = current_user_id
        self._ensure_dirs()

        self.id_counter_file = self.data_dir / "id_counters.json"
        self.id_counters = self._load_id_counters()

        self.users = self._load_df("users.csv")
        self.travelers = self._load_df("travelers.csv")
        self.batches = self._load_df("batches.csv")
        self.payments = self._load_df("payments.csv")
        self.invoices = self._load_df("invoices.csv")
        self.receipts = self._load_df("receipts.csv")
        self.activity_log = self._load_df("activity_log.csv")
        self.backup_history = self._load_df("backup_history.csv")
        self.company_settings = self._load_df("company_settings.csv")

        self._initialize_defaults()

        # Auto-migrate any user missing a permissions value
        self._ensure_permissions_column()

        # ---- Log row counts so you can verify in Railway logs ----
        print(f"[DB] Loaded: "
              f"{len(self.users)} users, "
              f"{len(self.travelers)} travelers, "
              f"{len(self.batches)} batches, "
              f"{len(self.payments)} payments, "
              f"{len(self.invoices)} invoices, "
              f"{len(self.receipts)} receipts")

    # =============================================================================
    # 2.2.2 — METHOD: _verify_writable  (NEW)
    # =============================================================================
    def _verify_writable(self):
        """Ensure the data folder is writable. Fails fast with clear error."""
        test_file = self.data_dir / ".write_test"
        try:
            with open(test_file, "w") as f:
                f.write("ok")
            test_file.unlink()
            print("[DB] ✓ Write test passed")
        except Exception as e:
            print(f"[DB] ✗ Write test FAILED: {e}")
            raise RuntimeError(
                f"Data folder is not writable: {self.data_dir}\n"
                f"Error: {e}\n"
                f"On Railway, attach a Volume to this path "
                f"or grant write permissions."
            )

    # =============================================================================
    # 2.2.3 — METHOD: _ensure_dirs   (UNCHANGED)
    # =============================================================================
    def _ensure_dirs(self):
        base = (self.data_dir.parent
                if self.data_dir.name == "data"
                else self.data_dir)
        folders = ["invoices", "receipts", "documents", "logos", "backups"]
        for f in folders:
            (base / f).mkdir(parents=True, exist_ok=True)


    # =================================================================================
    # 2.3 — ID COUNTERS   (UNCHANGED)
    # =================================================================================
    def _load_id_counters(self):
        if self.id_counter_file.exists():
            try:
                with open(self.id_counter_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_id_counters(self):
        with open(self.id_counter_file, 'w') as f:
            json.dump(self.id_counters, f, indent=2)

    def _get_prefix_from_name(self, name):
        if not name:
            return 'HAJ'
        special_cases = {
            'HAJ': 'HAJ', 'HJJ': 'HAJ',
            'UMRA': 'UMR', 'UMRAH': 'UMR', 'UMR': 'UMR',
            'ZIYARAH': 'ZIY', 'ZIYARAT': 'ZIY', 'ZIY': 'ZIY',
            'MADINAH': 'MAD', 'MADINA': 'MAD', 'MAD': 'MAD',
            'MAKKAH': 'MAK', 'MAK': 'MAK',
            'UK TOUR': 'UKT', 'UK': 'UKT',
            'USA TOUR': 'UST', 'USA': 'UST',
            'EUROPE TOUR': 'EUT', 'EUROPE': 'EUT',
            'DUBAI': 'DUB', 'TURKEY': 'TUR',
            'EGYPT': 'EGY', 'JORDAN': 'JOR',
            'MOROCCO': 'MOR', 'OMRAH': 'UMR',
        }
        clean_name = name.strip().upper()
        if clean_name in special_cases:
            return special_cases[clean_name]
        words_to_remove = ['TOUR', 'TRIP', 'PILGRIMAGE', 'VISIT', 'EXPEDITION']
        for word in words_to_remove:
            clean_name = clean_name.replace(word, '')
        if len(clean_name) >= 3:
            return clean_name[:3]
        elif len(clean_name) == 2:
            return clean_name + 'X'
        else:
            return clean_name + 'XX'

    def _get_next_batch_number(self, prefix, year):
        max_num = 0
        for batch in self.batches.to_dict('records'):
            batch_id = batch.get('id', '')
            if batch_id.startswith(f"{prefix}/BCH/{year}/"):
                try:
                    num = int(batch_id.split('/')[-1])
                    if num > max_num:
                        max_num = num
                except Exception:
                    pass
        return max_num + 1

    def _get_next_sequence(self, prefix, category, year):
        max_num = 0
        tables = {
            'TRV': self.travelers,
            'PAY': self.payments,
            'INV': self.invoices,
            'REC': self.receipts,
            'BCH': self.batches,
        }
        df = tables.get(category)
        if df is not None:
            for rec in df.to_dict('records'):
                rid = rec.get('id', '')
                if rid.startswith(f"{prefix}/{category}/{year}/"):
                    try:
                        num = int(rid.split('/')[-1])
                        if num > max_num:
                            max_num = num
                    except Exception:
                        pass
        return max_num

    def _generate_id(self, prefix, category, year):
        if year is None:
            year = datetime.now().strftime('%Y')
        counter_key = f"{prefix}_{category}_{year}"
        if counter_key in self.id_counters:
            next_num = self.id_counters[counter_key] + 1
        else:
            next_num = (self._get_next_sequence(prefix, category, year) + 1)
        self.id_counters[counter_key] = next_num
        self._save_id_counters()
        return f"{prefix}/{category}/{year}/{next_num:03d}"

    # =================================================================================
    # 2.4 — DATA LOADING / SAVING
    # =================================================================================
    def _load_df(self, filename):
        filepath = self.data_dir / filename
        if filepath.exists():
            try:
                df = pd.read_csv(filepath)

                if filename == "users.csv":
                    for col in ['username', 'full_name', 'email', 'role',
                                'password_hash', 'created_at',
                                'last_login', 'permissions']:
                        if col in df.columns:
                            df[col] = (df[col].astype(str)
                                       .fillna('')
                                       .replace('nan', ''))
                    if 'permissions' not in df.columns:
                        df['permissions'] = ''

                elif filename == "travelers.csv":
                    string_cols = [
                        'id', 'first_name', 'last_name', 'passport_name',
                        'batch_id', 'passport_no', 'passport_issue_date',
                        'passport_expiry_date', 'passport_status', 'gender',
                        'dob', 'mobile', 'email', 'aadhaar', 'pan',
                        'aadhaar_pan_linked', 'vaccine_status', 'wheelchair',
                        'place_of_birth', 'place_of_issue',
                        'passport_address', 'mailing_address',
                        'father_name', 'mother_name', 'spouse_name',
                        'passport_scan', 'aadhaar_scan', 'pan_scan',
                        'vaccine_scan', 'photo', 'pin',
                        'emergency_contact', 'emergency_phone',
                        'medical_notes', 'expected_return_date',
                        'file_reference', 'registration_date', 'status']
                    for col in string_cols:
                        if col in df.columns:
                            df[col] = (df[col].astype(str)
                                       .fillna('')
                                       .replace('nan', ''))

                elif filename == "batches.csv":
                    numeric_cols = ['total_seats', 'available_seats', 'price']
                    for col in numeric_cols:
                        if col in df.columns:
                            df[col] = pd.to_numeric(
                                df[col], errors='coerce').fillna(0)
                            if col in ['total_seats', 'available_seats']:
                                df[col] = df[col].astype(int)
                            elif col == 'price':
                                df[col] = df[col].astype(float)
                    string_cols = [
                        'id', 'batch_name', 'tour_type_id',
                        'tour_type_name', 'year', 'departure_date',
                        'return_date', 'status', 'description']
                    for col in string_cols:
                        if col in df.columns:
                            df[col] = (df[col].astype(str)
                                       .fillna('')
                                       .replace('nan', ''))

                elif filename == "payments.csv":
                    if 'amount' in df.columns:
                        df['amount'] = pd.to_numeric(
                            df['amount'], errors='coerce').fillna(0)
                    string_cols = [
                        'id', 'traveler_id', 'batch_id', 'payment_method',
                        'status', 'transaction_id', 'invoice_id', 'notes',
                        'payment_date']
                    for col in string_cols:
                        if col in df.columns:
                            df[col] = (df[col].astype(str)
                                       .fillna('')
                                       .replace('nan', ''))

                elif filename == "invoices.csv":
                    numeric_cols = [
                        'amount', 'discount_percentage', 'discount_amount',
                        'taxable_value', 'gst_percentage', 'gst_amount',
                        'tcs_percentage', 'tcs_amount', 'total_amount',
                        'rounded_total']
                    for col in numeric_cols:
                        if col in df.columns:
                            df[col] = pd.to_numeric(
                                df[col], errors='coerce').fillna(0)
                        else:
                            df[col] = 0.0
                    string_cols = [
                        'id', 'invoice_no', 'traveler_id', 'batch_id',
                        'issue_date', 'due_date', 'status', 'notes']
                    for col in string_cols:
                        if col in df.columns:
                            df[col] = (df[col].astype(str)
                                       .fillna('')
                                       .replace('nan', ''))

                elif filename == "receipts.csv":
                    if 'amount' in df.columns:
                        df['amount'] = pd.to_numeric(
                            df['amount'], errors='coerce').fillna(0)
                    string_cols = [
                        'id', 'receipt_no', 'payment_id', 'invoice_id',
                        'receipt_date', 'notes']
                    for col in string_cols:
                        if col in df.columns:
                            df[col] = (df[col].astype(str)
                                       .fillna('')
                                       .replace('nan', ''))

                elif filename == "activity_log.csv":
                    string_cols = [
                        'id', 'user_id', 'action', 'timestamp', 'details']
                    for col in string_cols:
                        if col in df.columns:
                            df[col] = (df[col].astype(str)
                                       .fillna('')
                                       .replace('nan', ''))

                elif filename == "backup_history.csv":
                    string_cols = [
                        'id', 'backup_date', 'backup_file', 'status']
                    for col in string_cols:
                        if col in df.columns:
                            df[col] = (df[col].astype(str)
                                       .fillna('')
                                       .replace('nan', ''))
                    if 'size' in df.columns:
                        df['size'] = pd.to_numeric(
                            df['size'], errors='coerce').fillna(0)

                elif filename == "company_settings.csv":
                    string_cols = [
                        'id', 'company_name', 'address', 'phone', 'email',
                        'website', 'gst_no', 'tan_no', 'pan_no', 'logo_path',
                        'bank_details']
                    if 'tan_no' not in df.columns:
                        df['tan_no'] = ''
                    for col in string_cols:
                        if col in df.columns:
                            df[col] = (df[col].astype(str)
                                       .fillna('')
                                       .replace('nan', ''))

                return df
            except Exception as e:
                print(f"Error loading {filename}: {e}")
                return self._create_empty_df(filename)
        else:
            print(f"[DB] {filename} not found — creating empty")
            return self._create_empty_df(filename)

    def _create_empty_df(self, filename):
        columns = {
            "users.csv": [
                'id', 'username', 'password_hash', 'full_name', 'email',
                'role', 'permissions', 'created_at', 'last_login'],
            "travelers.csv": [
                'id', 'first_name', 'last_name', 'passport_name',
                'batch_id', 'passport_no', 'passport_issue_date',
                'passport_expiry_date', 'passport_status', 'gender',
                'dob', 'mobile', 'email', 'aadhaar', 'pan',
                'aadhaar_pan_linked', 'vaccine_status', 'wheelchair',
                'place_of_birth', 'place_of_issue', 'passport_address',
                'mailing_address', 'father_name', 'mother_name',
                'spouse_name', 'passport_scan', 'aadhaar_scan',
                'pan_scan', 'vaccine_scan', 'photo', 'pin',
                'emergency_contact', 'emergency_phone', 'medical_notes',
                'expected_return_date', 'file_reference',
                'registration_date', 'status'],
            "batches.csv": [
                'id', 'batch_name', 'tour_type_id', 'tour_type_name',
                'year', 'departure_date', 'return_date', 'total_seats',
                'available_seats', 'price', 'status', 'description'],
            "payments.csv": [
                'id', 'traveler_id', 'batch_id', 'amount',
                'payment_date', 'payment_method', 'status',
                'transaction_id', 'invoice_id', 'notes'],
            "invoices.csv": [
                'id', 'invoice_no', 'traveler_id', 'batch_id', 'amount',
                'discount_percentage', 'discount_amount', 'taxable_value',
                'gst_percentage', 'gst_amount', 'tcs_percentage',
                'tcs_amount', 'total_amount', 'rounded_total',
                'issue_date', 'due_date', 'status', 'notes'],
            "receipts.csv": [
                'id', 'receipt_no', 'payment_id', 'invoice_id', 'amount',
                'receipt_date', 'notes'],
            "activity_log.csv": [
                'id', 'user_id', 'action', 'timestamp', 'details'],
            "backup_history.csv": [
                'id', 'backup_date', 'backup_file', 'size', 'status'],
            "company_settings.csv": [
                'id', 'company_name', 'address', 'phone', 'email',
                'website', 'gst_no', 'tan_no', 'pan_no', 'logo_path',
                'bank_details'],
        }
        return pd.DataFrame(columns=columns.get(filename, []))

    # -----------------------------------------------------------------------------
    # 2.4.3 — METHOD: _save_df   (UPDATED — error handling)
    # -----------------------------------------------------------------------------
    def _save_df(self, df, filename):
        """Save DataFrame to CSV with clear error logging."""
        try:
            path = self.data_dir / filename
            df.to_csv(path, index=False)
            return True
        except Exception as e:
            print(f"[DB] ❌ Failed to save {filename}: {e}")
            print(f"[DB]     Path: {self.data_dir / filename}")
            raise

    # =============================================================================
    # 2.4.4 — METHOD: _ensure_permissions_column  (UNCHANGED)
    # =============================================================================
    def _ensure_permissions_column(self):
        """Backfill any user missing permissions with role defaults."""
        try:
            if 'permissions' not in self.users.columns:
                self.users['permissions'] = ''
            changed = False
            for idx, row in self.users.iterrows():
                current = str(row.get('permissions', '') or '').strip()
                if not current:
                    role = str(row.get('role', 'staff')).lower().strip()
                    defaults = ROLE_DEFAULT_PERMISSIONS.get(
                        role, ROLE_DEFAULT_PERMISSIONS["viewer"])
                    self.users.at[idx, 'permissions'] = json.dumps(
                        sorted(defaults))
                    changed = True
            if changed:
                self._save_df(self.users, "users.csv")
                print(f"[DB] Backfilled permissions for "
                      f"{len(self.users)} users")
        except Exception as e:
            print(f"[DB] _ensure_permissions_column failed: {e}")

    # =============================================================================
    # 2.4.5 — METHOD: _initialize_defaults  (UNCHANGED)
    # =============================================================================
    def _initialize_defaults(self):
        if self.users.empty:
            admin_id = "ADMIN/USR/001"
            admin_user = pd.DataFrame([{
                'id': admin_id,
                'username': 'admin',
                'password_hash': hashlib.sha256(
                    'admin123'.encode()).hexdigest(),
                'full_name': 'System Administrator',
                'email': 'admin@hajtravel.com',
                'role': 'super_admin',
                'permissions': json.dumps(sorted(
                    ROLE_DEFAULT_PERMISSIONS["super_admin"])),
                'created_at': datetime.now().isoformat(),
                'last_login': ''
            }])
            self.users = pd.concat(
                [self.users, admin_user], ignore_index=True)
            self._save_df(self.users, "users.csv")
            print("=" * 70)
            print("⚠️  DEFAULT ADMIN USER CREATED")
            print("    Username: admin")
            print("    Password: admin123")
            print("    → CHANGE THIS PASSWORD IMMEDIATELY after first login!")
            print("=" * 70)

        if self.company_settings.empty:
            company_id = "COMP/001"
            company = pd.DataFrame([{
                'id': company_id,
                'company_name': 'Alhudha Haj Travel',
                'address': '123 Pilgrim Street, Makkah Road',
                'phone': '+966 123456789',
                'email': 'info@alhudahaj.com',
                'website': 'www.alhudahaj.com',
                'gst_no': 'GST123456',
                'tan_no': 'TAN123456',
                'pan_no': 'PAN123456',
                'logo_path': '',
                'bank_details': json.dumps({
                    'bank_name': 'Islamic Bank',
                    'account_no': '1234567890',
                    'ifsc': 'ISBK0001234',
                    'upi': 'alhudha@islamic'
                })
            }])
            self.company_settings = pd.concat(
                [self.company_settings, company], ignore_index=True)
            self._save_df(
                self.company_settings, "company_settings.csv")

    # =============================================================================
    # 2.5 — AUTHENTICATION & USER MANAGEMENT   (UNCHANGED)
    # =============================================================================
    def authenticate_user(self, username, password):
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        user = self.users[
            (self.users['username'] == username)
            & (self.users['password_hash'] == password_hash)]
        if not user.empty:
            self.users.loc[
                self.users['id'] == user.iloc[0]['id'],
                'last_login'] = str(datetime.now().isoformat())
            self._save_df(self.users, "users.csv")
            self._current_user_id = user.iloc[0]['id']
            return user.iloc[0].to_dict()
        return None

    def get_users(self):
        return self.users.to_dict('records')

    def get_user_by_id(self, user_id):
        u = self.users[self.users['id'] == user_id]
        if not u.empty:
            return u.iloc[0].to_dict()
        return None

    def add_user(self, user_data):
        data = dict(user_data)
        if 'password' in data:
            pwd = data.pop('password')
            data['password_hash'] = hashlib.sha256(
                pwd.encode()).hexdigest()
        elif 'password_hash' not in data:
            data['password_hash'] = hashlib.sha256(
                'changeme'.encode()).hexdigest()
        data['id'] = self._generate_id('ADMIN', 'USR', None)
        data['created_at'] = datetime.now().isoformat()
        data['last_login'] = ''
        role = str(data.get('role', 'staff')).lower().strip()
        perms = data.get('permissions', '').strip()
        if not perms:
            defaults = ROLE_DEFAULT_PERMISSIONS.get(
                role, ROLE_DEFAULT_PERMISSIONS["viewer"])
            data['permissions'] = json.dumps(sorted(defaults))
        if 'permissions' not in self.users.columns:
            self.users['permissions'] = ''
        new_user = pd.DataFrame([data])
        self.users = pd.concat(
            [self.users, new_user], ignore_index=True)
        self._save_df(self.users, "users.csv")
        return data['id']

    def update_user(self, user_id, user_data):
        data = dict(user_data)
        if 'password' in data:
            pwd = data.pop('password')
            if pwd:
                data['password_hash'] = hashlib.sha256(
                    pwd.encode()).hexdigest()
            else:
                data.pop('password', None)
                data.pop('password_hash', None)
        if 'role' in data and 'permissions' not in data:
            role = str(data['role']).lower().strip()
            defaults = ROLE_DEFAULT_PERMISSIONS.get(
                role, ROLE_DEFAULT_PERMISSIONS["viewer"])
            data['permissions'] = json.dumps(sorted(defaults))
        for key, value in data.items():
            self.users.loc[self.users['id'] == user_id, key] = value
        self._save_df(self.users, "users.csv")

    def delete_user(self, user_id):
        super_admins = self.users[self.users['role'] == 'super_admin']
        is_last_super_admin = (
            len(super_admins) <= 1
            and user_id in super_admins['id'].values
        )
        if is_last_super_admin:
            raise Exception(
                "Cannot delete the last super_admin account. "
                "Promote another user to super_admin first."
            )
        self.users = self.users[self.users['id'] != user_id]
        self._save_df(self.users, "users.csv")

    def get_user_permissions(self, user_id):
        u = self.get_user_by_id(user_id)
        if not u:
            return set()
        return self._parse_permissions(u.get('permissions', ''),
                                       u.get('role', 'viewer'))

    def has_permission(self, user_id, permission_key):
        return permission_key in self.get_user_permissions(user_id)

    def _parse_permissions(self, value, role):
        if pd is not None and pd.isna(value):
            value = ""
        s = str(value or "").strip()
        if not s:
            return set(ROLE_DEFAULT_PERMISSIONS.get(
                str(role).lower(),
                ROLE_DEFAULT_PERMISSIONS["viewer"]))
        try:
            if s.startswith("["):
                return set(json.loads(s))
            return set(x.strip() for x in s.split("|") if x.strip())
        except Exception:
            return set(ROLE_DEFAULT_PERMISSIONS.get(
                str(role).lower(),
                ROLE_DEFAULT_PERMISSIONS["viewer"]))

    # =================================================================================
    # 2.6 — TRAVELERS   (UNCHANGED)
    # =================================================================================
    def get_travelers(self, batch_id=None):
        if batch_id:
            return self.travelers[
                self.travelers['batch_id'] == batch_id
            ].to_dict('records')
        return self.travelers.to_dict('records')

    def get_batch_by_id(self, batch_id):
        batch = self.batches[self.batches['id'] == batch_id]
        if not batch.empty:
            return batch.iloc[0].to_dict()
        return None

    def get_traveler_by_id(self, traveler_id):
        traveler = self.travelers[self.travelers['id'] == traveler_id]
        if not traveler.empty:
            return traveler.iloc[0].to_dict()
        return None

    def add_traveler(self, traveler_data):
        batch_id = traveler_data.get('batch_id')
        year = datetime.now().year
        prefix = 'HAJ'
        if batch_id:
            batch = self.get_batch_by_id(batch_id)
            if batch:
                batch_year = batch.get('year')
                if batch_year:
                    year = batch_year
                tour_type_name = batch.get('tour_type_name', 'HAJ')
                prefix = self._get_prefix_from_name(tour_type_name)
        traveler_data['id'] = self._generate_id(
            prefix, 'TRV', str(year))
        traveler_data['registration_date'] = datetime.now().isoformat()
        if 'status' not in traveler_data:
            traveler_data['status'] = 'Active'
        for key, value in traveler_data.items():
            if value is not None:
                traveler_data[key] = str(value)
            else:
                traveler_data[key] = ''
        new_traveler = pd.DataFrame([traveler_data])
        self.travelers = pd.concat(
            [self.travelers, new_traveler], ignore_index=True)
        self._save_df(self.travelers, "travelers.csv")
        if traveler_data.get('batch_id'):
            self._update_batch_seats(traveler_data['batch_id'], -1)
        return traveler_data['id']

    def update_traveler(self, traveler_id, traveler_data):
        old_batch = self.travelers[
            self.travelers['id'] == traveler_id
        ].iloc[0]['batch_id']
        for key, value in traveler_data.items():
            if value is not None:
                traveler_data[key] = str(value)
            else:
                traveler_data[key] = ''
        for key, value in traveler_data.items():
            self.travelers.loc[
                self.travelers['id'] == traveler_id, key] = value
        self._save_df(self.travelers, "travelers.csv")
        new_batch = traveler_data.get('batch_id')
        if old_batch != new_batch:
            if old_batch and pd.notna(old_batch):
                self._update_batch_seats(old_batch, 1)
            if new_batch and pd.notna(new_batch):
                self._update_batch_seats(new_batch, -1)

    def delete_traveler(self, traveler_id):
        traveler = self.travelers[
            self.travelers['id'] == traveler_id].iloc[0]
        if traveler['batch_id'] and pd.notna(traveler['batch_id']):
            self._update_batch_seats(traveler['batch_id'], 1)
        self.travelers = self.travelers[
            self.travelers['id'] != traveler_id]
        self._save_df(self.travelers, "travelers.csv")

    # =================================================================================
    # 2.7 — BATCHES   (UNCHANGED)
    # =================================================================================
    def get_batches(self, status=None):
        if status:
            return self.batches[
                self.batches['status'] == status].to_dict('records')
        return self.batches.to_dict('records')

    def add_batch(self, batch_data):
        tour_type_name = batch_data.get('tour_type_name', 'HAJ')
        year = batch_data.get('year', datetime.now().year)
        prefix = self._get_prefix_from_name(tour_type_name)
        batch_data['id'] = self._generate_id(
            prefix, 'BCH', str(year))
        batch_data['total_seats'] = int(
            batch_data.get('total_seats', 0))
        batch_data['available_seats'] = batch_data['total_seats']
        batch_data['price'] = float(batch_data.get('price', 0))
        batch_data['year'] = str(year)
        for key, value in batch_data.items():
            if value is None:
                batch_data[key] = ''
            elif key in ['total_seats', 'available_seats']:
                batch_data[key] = int(value)
            elif key == 'price':
                batch_data[key] = float(value)
            else:
                batch_data[key] = str(value)
        new_batch = pd.DataFrame([batch_data])
        self.batches = pd.concat(
            [self.batches, new_batch], ignore_index=True)
        self._save_df(self.batches, "batches.csv")
        return batch_data['id']

    def update_batch(self, batch_id, batch_data):
        current_batch = self.get_batch_by_id(batch_id)
        if not current_batch:
            raise Exception("Batch not found")
        update_data = {}
        for key, value in batch_data.items():
            if key in ['total_seats', 'available_seats']:
                try:
                    update_data[key] = int(value)
                except Exception:
                    update_data[key] = 0
            elif key == 'price':
                try:
                    update_data[key] = float(value)
                except Exception:
                    update_data[key] = 0.0
            elif key == 'year':
                update_data[key] = str(value)
            else:
                update_data[key] = (str(value)
                                    if value is not None else '')
        for key, value in update_data.items():
            self.batches.loc[
                self.batches['id'] == batch_id, key] = value
        self._save_df(self.batches, "batches.csv")

    def delete_batch(self, batch_id):
        travelers_in_batch = self.travelers[
            self.travelers['batch_id'] == batch_id]
        if not travelers_in_batch.empty:
            raise Exception(
                "Cannot delete batch with assigned travelers")
        self.batches = self.batches[self.batches['id'] != batch_id]
        self._save_df(self.batches, "batches.csv")

    def _update_batch_seats(self, batch_id, change):
        try:
            current_seats = self.batches.loc[
                self.batches['id'] == batch_id,
                'available_seats'].iloc[0]
            if isinstance(current_seats, str):
                try:
                    current_seats = int(float(current_seats))
                except Exception:
                    current_seats = 0
            else:
                current_seats = int(current_seats)
            new_seats = int(current_seats + change)
            self.batches.loc[
                self.batches['id'] == batch_id,
                'available_seats'] = new_seats
            self._save_df(self.batches, "batches.csv")
        except Exception as e:
            print(f"Error updating batch seats: {e}")

    # =================================================================================
    # 2.8 — PAYMENTS   (UNCHANGED)
    # =================================================================================
    def get_payments(self, traveler_id=None):
        if traveler_id:
            return self.payments[
                self.payments['traveler_id'] == traveler_id
            ].to_dict('records')
        return self.payments.to_dict('records')

    def add_payment(self, payment_data):
        batch_id = payment_data.get('batch_id')
        year = datetime.now().year
        prefix = 'HAJ'
        if batch_id:
            batch = self.get_batch_by_id(batch_id)
            if batch:
                batch_year = batch.get('year')
                if batch_year:
                    year = batch_year
                tour_type_name = batch.get('tour_type_name', 'HAJ')
                prefix = self._get_prefix_from_name(tour_type_name)
        payment_data['id'] = self._generate_id(
            prefix, 'PAY', str(year))
        payment_data['payment_date'] = datetime.now().isoformat()
        invoice_id = payment_data.get('invoice_id', '')
        if (invoice_id is None
                or (isinstance(invoice_id, float)
                    and str(invoice_id) == 'nan')):
            invoice_id = ''
        payment_data['invoice_id'] = invoice_id
        payment_data['amount'] = float(payment_data.get('amount', 0))
        for key, value in payment_data.items():
            if value is None:
                payment_data[key] = ''
            elif key == 'amount':
                payment_data[key] = float(value)
            else:
                payment_data[key] = str(value)
        new_payment = pd.DataFrame([payment_data])
        self.payments = pd.concat(
            [self.payments, new_payment], ignore_index=True)
        self._save_df(self.payments, "payments.csv")
        self._generate_receipt(payment_data)
        return payment_data['id']

    def update_payment(self, payment_id, payment_data):
        try:
            mask = self.payments['id'] == payment_id
            if not mask.any():
                print(f"⚠️ Payment {payment_id} not found")
                return False
            current = self.payments.loc[mask].iloc[0].to_dict()
            updates = {}
            fields = {
                'amount': self._convert_to_float,
                'payment_date': self._parse_date,
                'payment_method': self._convert_to_string,
                'status': self._validate_status,
                'transaction_id': self._convert_to_string,
                'invoice_id': self._convert_invoice_id,
                'notes': self._convert_to_string
            }
            for field, converter in fields.items():
                if field in payment_data:
                    try:
                        updates[field] = converter(payment_data[field])
                    except Exception:
                        updates[field] = current.get(field, '')
                else:
                    updates[field] = current.get(field, '')
            for key, value in updates.items():
                self.payments.loc[mask, key] = value
            self._save_df(self.payments, "payments.csv")
            if (updates.get('status') == 'completed'
                    and updates.get('invoice_id')):
                inv_id = updates['invoice_id']
                if inv_id and inv_id in self.invoices['id'].values:
                    try:
                        self.invoices.loc[
                            self.invoices['id'] == inv_id,
                            'status'] = 'paid'
                        self._save_df(self.invoices, "invoices.csv")
                    except Exception as e:
                        print(
                            f"⚠️ Could not update invoice {inv_id}: {e}")
            try:
                self.log_activity(
                    self._current_user_id,
                    "update_payment",
                    f"Updated payment {payment_id} - "
                    f"Amount: ₹{updates.get('amount', 0):,.2f}"
                )
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"❌ Error updating payment {payment_id}: {e}")
            import traceback
            traceback.print_exc()
            return False

    # =================================================================================
    # 2.9 — PAYMENT HELPERS   (UNCHANGED)
    # =================================================================================
    def _convert_to_float(self, value):
        if value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def _convert_to_string(self, value):
        if value is None:
            return ''
        return str(value).strip()

    def _parse_date(self, date_value):
        if not date_value:
            return datetime.now().isoformat()
        if isinstance(date_value, str):
            try:
                return date_value
            except Exception:
                return datetime.now().isoformat()
        if hasattr(date_value, 'toString'):
            return date_value.toString("yyyy-MM-dd")
        if isinstance(date_value, datetime):
            return date_value.isoformat()
        return datetime.now().isoformat()

    def _validate_status(self, status):
        valid_statuses = ['completed', 'pending', 'failed', 'refunded']
        if status is None:
            return 'pending'
        status_str = str(status).lower().strip()
        return status_str if status_str in valid_statuses else 'pending'

    def _convert_invoice_id(self, invoice_id):
        if not invoice_id:
            return ''
        if isinstance(invoice_id, float):
            if pd.isna(invoice_id) or str(invoice_id) == 'nan':
                return ''
        return str(invoice_id).strip()

    def delete_payment(self, payment_id):
        receipts = self.receipts[
            self.receipts['payment_id'] == payment_id]
        if not receipts.empty:
            raise Exception(
                "Cannot delete payment with associated receipts")
        self.payments = self.payments[
            self.payments['id'] != payment_id]
        self._save_df(self.payments, "payments.csv")

    # =================================================================================
    # 2.10 — INVOICES   (UNCHANGED)
    # =================================================================================
    def get_invoices(self, traveler_id=None):
        if traveler_id:
            return self.invoices[
                self.invoices['traveler_id'] == traveler_id
            ].to_dict('records')
        return self.invoices.to_dict('records')

    def generate_invoice(self, traveler_id, batch_id, amount,
                         gst_percentage=18, tcs_percentage=0.1,
                         discount_percentage=0.0,
                         discount_amount=None):
        year = datetime.now().year
        prefix = 'HAJ'
        if batch_id:
            batch = self.get_batch_by_id(batch_id)
            if batch:
                batch_year = batch.get('year')
                if batch_year:
                    year = batch_year
                tour_type_name = batch.get('tour_type_name', 'HAJ')
                prefix = self._get_prefix_from_name(tour_type_name)
        invoice_id = self._generate_id(prefix, 'INV', str(year))
        invoice_no = (f"INV-{datetime.now().strftime('%Y%m')}-"
                      f"{len(self.invoices)+1:04d}")
        amount = float(amount)
        gst_percentage = float(gst_percentage)
        tcs_percentage = float(tcs_percentage)
        if discount_amount is not None:
            discount_amount = float(discount_amount)
            if discount_amount < 0:
                discount_amount = 0.0
            if discount_amount > amount:
                discount_amount = amount
            discount_percentage = (
                (discount_amount / amount) * 100.0
                if amount > 0 else 0.0
            )
        else:
            discount_percentage = float(discount_percentage)
            discount_amount = amount * (discount_percentage / 100.0)
        taxable_value = amount - discount_amount
        gst_amount = taxable_value * (gst_percentage / 100.0)
        taxable_with_gst = taxable_value + gst_amount
        tcs_amount = taxable_with_gst * (tcs_percentage / 100.0)
        total_amount = taxable_with_gst + tcs_amount
        rounded_total = self._round_as_per_rules(total_amount)
        invoice_data = {
            'id': invoice_id,
            'invoice_no': invoice_no,
            'traveler_id': traveler_id,
            'batch_id': batch_id,
            'amount': amount,
            'discount_percentage': discount_percentage,
            'discount_amount': discount_amount,
            'taxable_value': taxable_value,
            'gst_percentage': gst_percentage,
            'gst_amount': gst_amount,
            'tcs_percentage': tcs_percentage,
            'tcs_amount': tcs_amount,
            'total_amount': total_amount,
            'rounded_total': float(rounded_total),
            'issue_date': datetime.now().isoformat(),
            'due_date': (datetime.now() + timedelta(days=30)).isoformat(),
            'status': 'pending',
            'notes': ''
        }
        new_invoice = pd.DataFrame([invoice_data])
        self.invoices = pd.concat(
            [self.invoices, new_invoice], ignore_index=True)
        self._save_df(self.invoices, "invoices.csv")
        return invoice_id

    def delete_invoice(self, invoice_id):
        self.invoices = self.invoices[
            self.invoices['id'] != invoice_id]
        self._save_df(self.invoices, "invoices.csv")

    def _round_as_per_rules(self, amount):
        if isinstance(amount, (int, float)):
            decimal_part = amount - math.floor(amount)
            if decimal_part >= 0.50:
                return math.ceil(amount)
            else:
                return math.floor(amount)
        return amount

    # =================================================================================
    # 2.11 — RECEIPTS   (UNCHANGED)
    # =================================================================================
    def _generate_receipt(self, payment_data):
        batch_id = payment_data.get('batch_id')
        year = datetime.now().year
        prefix = 'HAJ'
        if batch_id:
            batch = self.get_batch_by_id(batch_id)
            if batch:
                batch_year = batch.get('year')
                if batch_year:
                    year = batch_year
                tour_type_name = batch.get('tour_type_name', 'HAJ')
                prefix = self._get_prefix_from_name(tour_type_name)
        receipt_id = self._generate_id(prefix, 'REC', str(year))
        receipt_no = (f"REC-{datetime.now().strftime('%Y%m')}-"
                      f"{len(self.receipts)+1:04d}")
        invoice_id = payment_data.get('invoice_id', '')
        if (invoice_id is None
                or (isinstance(invoice_id, float)
                    and (invoice_id != invoice_id
                         or str(invoice_id) == 'nan'))):
            invoice_id = ''
        receipt_data = {
            'id': receipt_id,
            'receipt_no': receipt_no,
            'payment_id': payment_data['id'],
            'invoice_id': invoice_id,
            'amount': float(payment_data['amount']),
            'receipt_date': datetime.now().isoformat(),
            'notes': payment_data.get('notes', '')
        }
        new_receipt = pd.DataFrame([receipt_data])
        self.receipts = pd.concat(
            [self.receipts, new_receipt], ignore_index=True)
        self._save_df(self.receipts, "receipts.csv")
        if (invoice_id and invoice_id != ''
                and not (isinstance(invoice_id, float)
                         and invoice_id != invoice_id)):
            try:
                mask = self.invoices['id'] == invoice_id
                if mask.any():
                    self.invoices.loc[mask, 'status'] = 'paid'
                    self._save_df(self.invoices, "invoices.csv")
            except Exception as e:
                print(f"Error updating invoice status: {e}")

    def get_receipts(self, payment_id=None):
        if payment_id:
            return self.receipts[
                self.receipts['payment_id'] == payment_id
            ].to_dict('records')
        return self.receipts.to_dict('records')

    # =================================================================================
    # 2.12 — REPORTS & OTHER
    # =================================================================================
    def get_dashboard_summary(self):
        return {
            'total_travelers': len(self.travelers),
            'active_batches': len(self.batches[
                self.batches['status'] == 'active']),
            'total_payments': (self.payments['amount'].sum()
                               if not self.payments.empty else 0),
            'pending_payments': len(self.invoices[
                self.invoices['status'] == 'pending']),
            'available_seats': (self.batches['available_seats'].sum()
                                if not self.batches.empty else 0),
            'total_receipts': len(self.receipts)
        }

    def get_financial_report(self, start_date=None, end_date=None):
        payments = self.payments.copy()
        if start_date:
            payments = payments[
                payments['payment_date'] >= start_date]
        if end_date:
            payments = payments[
                payments['payment_date'] <= end_date]
        return {
            'total_collected': (payments['amount'].sum()
                                if not payments.empty else 0),
            'payment_count': (len(payments)
                              if not payments.empty else 0),
            'by_method': (payments.groupby('payment_method')['amount']
                          .sum().to_dict()
                          if not payments.empty else {}),
            'average_payment': (payments['amount'].mean()
                                if not payments.empty else 0)
        }

    # -----------------------------------------------------------------------------
    # 2.12.3 — METHOD: create_backup   (UPDATED — cloud note)
    # -----------------------------------------------------------------------------
    def create_backup(self):
        """
        Creates a ZIP of all CSVs in data/backups/.

        ⚠️ CLOUD NOTE: On Railway's free tier, files under data/ are
        ephemeral — they reset when the container restarts. Attach a
        Railway Volume to /app/data if you need backups to survive.
        """
        backup_id = self._generate_id('BAK', 'BUP', None)
        backup_date = datetime.now()
        backup_filename = (f"backup_"
                           f"{backup_date.strftime('%Y%m%d_%H%M%S')}.zip")
        backup_dir = self.data_dir / "backups"
        backup_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(backup_dir / backup_filename, 'w') as zipf:
            for csv_file in self.data_dir.glob("*.csv"):
                zipf.write(csv_file, csv_file.name)
        backup_record = pd.DataFrame([{
            'id': backup_id,
            'backup_date': backup_date.isoformat(),
            'backup_file': str(backup_dir / backup_filename),
            'size': os.path.getsize(backup_dir / backup_filename),
            'status': 'success'
        }])
        self.backup_history = pd.concat(
            [self.backup_history, backup_record], ignore_index=True)
        self._save_df(self.backup_history, "backup_history.csv")
        print(f"[DB] Backup created: "
              f"{backup_dir / backup_filename}")
        return str(backup_dir / backup_filename)

    def restore_backup(self, backup_file):
        with zipfile.ZipFile(backup_file, 'r') as zipf:
            zipf.extractall(self.data_dir)
        self.__init__()

    def log_activity(self, user_id, action, details=""):
        if not user_id:
            user_id = self._current_user_id or 'system'
        log_id = self._generate_id('LOG', 'ACT', None)
        log_entry = pd.DataFrame([{
            'id': log_id,
            'user_id': user_id,
            'action': action,
            'timestamp': datetime.now().isoformat(),
            'details': details
        }])
        self.activity_log = pd.concat(
            [self.activity_log, log_entry], ignore_index=True)
        self._save_df(self.activity_log, "activity_log.csv")

    def get_activity_log(self, user_id=None, limit=100):
        logs = self.activity_log
        if user_id:
            logs = logs[logs['user_id'] == user_id]
        return (logs.sort_values('timestamp', ascending=False)
                .head(limit).to_dict('records'))

    # =================================================================================
    # 2.13 — CURRENT USER MANAGEMENT   (UNCHANGED)
    # =================================================================================
    def set_current_user(self, user_id):
        self._current_user_id = user_id

    def get_current_user_id(self):
        return self._current_user_id

    # =================================================================================
    # 2.14 — DATA MIGRATION   (UNCHANGED)
    # =================================================================================
    def migrate_batch_tour_types(self):
        pass

    # =================================================================================
    # 2.15 — RELOAD METHODS  (NEW — fixes stale cache)
    # =================================================================================
    # Why this matters:
    #   The DB caches all CSVs in memory at __init__. If a CSV is
    #   modified externally (e.g. via the CSV editor, or a different
    #   process), the cache goes stale and the app shows old data.
    #
    #   These methods force a fresh read of the CSVs.
    #
    # Recommended: call reload_payments() inside the Custom Report
    # dialog before generating a report, and reload_travelers() inside
    # the Travelers tab before rendering.
    # =================================================================================

    def reload_all(self):
        """Reload every CSV from disk (discards all caches)."""
        print("[DB] 🔄 Reloading all data from disk...")
        self.users = self._load_df("users.csv")
        self.travelers = self._load_df("travelers.csv")
        self.batches = self._load_df("batches.csv")
        self.payments = self._load_df("payments.csv")
        self.invoices = self._load_df("invoices.csv")
        self.receipts = self._load_df("receipts.csv")
        self.activity_log = self._load_df("activity_log.csv")
        self.backup_history = self._load_df("backup_history.csv")
        self.company_settings = self._load_df("company_settings.csv")
        self.id_counters = self._load_id_counters()
        self._ensure_permissions_column()
        print(f"[DB] ✓ Reloaded: "
              f"{len(self.users)} users, "
              f"{len(self.travelers)} travelers, "
              f"{len(self.batches)} batches, "
              f"{len(self.payments)} payments, "
              f"{len(self.invoices)} invoices, "
              f"{len(self.receipts)} receipts")

    def reload_payments(self):
        """Force reload of payments.csv only."""
        self.payments = self._load_df("payments.csv")
        print(f"[DB] ✓ Reloaded {len(self.payments)} payments")
        return self.payments

    def reload_travelers(self):
        """Force reload of travelers.csv only."""
        self.travelers = self._load_df("travelers.csv")
        print(f"[DB] ✓ Reloaded {len(self.travelers)} travelers")
        return self.travelers

    def reload_batches(self):
        """Force reload of batches.csv only."""
        self.batches = self._load_df("batches.csv")
        print(f"[DB] ✓ Reloaded {len(self.batches)} batches")
        return self.batches

    def reload_invoices(self):
        """Force reload of invoices.csv only."""
        self.invoices = self._load_df("invoices.csv")
        print(f"[DB] ✓ Reloaded {len(self.invoices)} invoices")
        return self.invoices

    def reload_receipts(self):
        """Force reload of receipts.csv only."""
        self.receipts = self._load_df("receipts.csv")
        print(f"[DB] ✓ Reloaded {len(self.receipts)} receipts")
        return self.receipts

    def reload_users(self):
        """Force reload of users.csv only."""
        self.users = self._load_df("users.csv")
        self._ensure_permissions_column()
        print(f"[DB] ✓ Reloaded {len(self.users)} users")
        return self.users

    def reload_company_settings(self):
        """Force reload of company_settings.csv only."""
        self.company_settings = self._load_df("company_settings.csv")
        return self.company_settings

    def reload_backup_history(self):
        """Force reload of backup_history.csv only."""
        self.backup_history = self._load_df("backup_history.csv")
        return self.backup_history

    def reload_activity_log(self):
        """Force reload of activity_log.csv only."""
        self.activity_log = self._load_df("activity_log.csv")
        return self.activity_log

    # =================================================================================
    # 2.16 — FILE CHANGE DETECTION  (NEW)
    # =================================================================================
    # These helpers let you check whether a CSV has changed on disk
    # since the DB was loaded. Useful for showing a "data changed —
    # refresh?" banner in the UI.
    # =================================================================================

    def _csv_mtime(self, filename):
        """Return the modification time of a CSV, or 0 if missing."""
        path = self.data_dir / filename
        if not path.exists():
            return 0
        try:
            return path.stat().st_mtime
        except Exception:
            return 0

    def has_csv_changed(self, filename):
        """
        Return True if the CSV on disk was modified AFTER the last
        reload. Tracked by comparing file mtime to a snapshot taken
        at load time.

        Note: the first call will always return True because the
        snapshot is empty. After reloading, the snapshot updates.
        """
        if not hasattr(self, "_csv_snapshots"):
            self._csv_snapshots = {}
        current_mtime = self._csv_mtime(filename)
        last_snapshot = self._csv_snapshots.get(filename, 0)
        if current_mtime > last_snapshot:
            return True
        return False

    def mark_csv_as_read(self, filename):
        """Update the snapshot for a CSV file."""
        if not hasattr(self, "_csv_snapshots"):
            self._csv_snapshots = {}
        self._csv_snapshots[filename] = self._csv_mtime(filename)

    def get_data_folder_info(self):
        """Return diagnostic info about the data folder."""
        info = {
            "base_path": str(self.data_dir.parent),
            "data_path": str(self.data_dir),
            "exists": self.data_dir.exists(),
            "writable": os.access(str(self.data_dir), os.W_OK),
            "files": [],
        }
        try:
            for f in sorted(self.data_dir.glob("*.csv")):
                stat = f.stat()
                info["files"].append({
                    "name": f.name,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(
                        stat.st_mtime).isoformat(),
                })
        except Exception as e:
            info["error"] = str(e)
        return info


# =================================================================================
# SECTION 2 END (FLET VERSION)
# =================================================================================