# =================================================================================
# SECTION 2 (FLET VERSION) — DATABASE MODULE
# =================================================================================
# v5.3 — CRITICAL FIX: Whitespace-safe ID lookups & loading.
#
#   v5.3 NEW:
#     • _load_df() now strips whitespace from 'id' and 'batch_id' columns
#       for travelers and batches. This prevents lookup failures if a CSV 
#       was edited manually and accidentally saved with trailing spaces.
#     • get_traveler_by_id() and get_batch_by_id() now use .astype(str).str.strip()
#       to ensure exact matches, resolving the "Base Amount stays at 0" bug.
#
#   v5.2 (preserved):
#     • Backups saved correctly inside /app/data/backups
#     • add_payment() validates traveler + batch, auto-generates receipt.
#     • _recalculate_invoice_status() derives status from payments.
#     • _recalculate_batch_seats() ensures seats = total - booked.
# =================================================================================

import os
import sys
import json
import hashlib
import zipfile
import math
import tempfile
import threading
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    from werkzeug.security import generate_password_hash, check_password_hash
    _WERKZEUG_OK = True
except Exception:
    generate_password_hash = None
    check_password_hash = None
    _WERKZEUG_OK = False

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from core.helpers import get_app_base_path
except ImportError:
    def get_app_base_path():
        return os.path.dirname(os.path.abspath(__file__))


TRAVELER_COLUMNS = [
    'id', 'first_name', 'last_name', 'passport_name', 'batch_id',
    'passport_no', 'passport_issue_date', 'passport_expiry_date',
    'passport_status', 'gender', 'dob', 'mobile', 'email',
    'aadhaar', 'pan', 'aadhaar_pan_linked', 'vaccine_status',
    'wheelchair', 'place_of_birth', 'place_of_issue',
    'passport_address', 'mailing_address', 'father_name',
    'mother_name', 'spouse_name', 'passport_scan', 'aadhaar_scan',
    'pan_scan', 'vaccine_scan', 'photo', 'pin',
    'emergency_contact', 'emergency_phone', 'medical_notes',
    'expected_return_date', 'file_reference', 'registration_date',
    'status',
]

_REQUIRED_TRAVELER_FIELDS = (
    'first_name', 'last_name', 'passport_no', 'mobile', 'batch_id',
)

_ACTIVE_BATCH_STATUSES = {'active', 'open', 'closing soon'}


PERMISSION_CATALOG = [
    "view_dashboard", "manage_travelers", "manage_batches",
    "manage_payments", "manage_invoices", "manage_receipts",
    "view_reports", "manage_users", "manage_backups",
    "manage_settings",
]

ROLE_DEFAULT_PERMISSIONS = {
    "super_admin": set(PERMISSION_CATALOG),
    "admin":       set(p for p in PERMISSION_CATALOG if p != "manage_users"),
    "staff":       {"view_dashboard", "manage_travelers",
                    "manage_payments", "manage_receipts", "view_reports"},
    "viewer":      {"view_dashboard", "view_reports"},
}


class HajDatabase:

    # =============================================================================
    # 2.1 — INITIALIZATION & SETUP
    # =============================================================================
    def __init__(self, data_dir="data", current_user_id="system"):
        base_path = get_app_base_path()
        self.data_dir = Path(base_path) / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        print(f"[DB] Base path      : {base_path}")
        print(f"[DB] Data directory : {self.data_dir}")
        print(f"[DB] Data exists    : {self.data_dir.exists()}")
        print(f"[DB] Data writable  : {os.access(str(self.data_dir), os.W_OK)}")

        self._verify_writable()

        self._lock = threading.RLock()
        self._lock_file = self.data_dir / ".db.lock"
        self._csv_snapshots = {}

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
        self._ensure_permissions_column()

        # Reconcile stored seats with actual bookings on boot
        self._reconcile_all_batch_seats()

        print(f"[DB] Loaded: {len(self.users)} users, "
              f"{len(self.travelers)} travelers, {len(self.batches)} batches, "
              f"{len(self.payments)} payments, {len(self.invoices)} invoices, "
              f"{len(self.receipts)} receipts")

    def _verify_writable(self):
        test_file = self.data_dir / ".write_test"
        try:
            with open(test_file, "w") as f:
                f.write("ok")
            test_file.unlink()
            print("[DB] [OK] Write test passed")
        except Exception as e:
            print(f"[DB] [FAIL] Write test FAILED: {e}")
            raise RuntimeError(
                f"Data folder is not writable: {self.data_dir}\nError: {e}")

    def _ensure_dirs(self):
        self._backup_dir = self.data_dir / "backups"
        for f in ["invoices", "receipts", "documents", "logos", "backups"]:
            (self.data_dir / f).mkdir(parents=True, exist_ok=True)

    class _FileLock:
        def __init__(self, path: Path, thread_lock):
            self.path = path
            self.thread_lock = thread_lock
            self._fh = None

        def __enter__(self):
            self.thread_lock.acquire()
            try:
                self._fh = open(self.path, "a+")
                if fcntl is not None:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
            except Exception:
                self.thread_lock.release()
                raise
            return self

        def __exit__(self, exc_type, exc, tb):
            try:
                if self._fh is not None:
                    if fcntl is not None:
                        try:
                            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                        except Exception:
                            pass
                    self._fh.close()
            finally:
                self.thread_lock.release()

    def _file_lock(self):
        return self._FileLock(self._lock_file, self._lock)

    # =================================================================================
    # 2.2 — ID COUNTERS & GENERATORS
    # =================================================================================
    def _load_id_counters(self):
        if self.id_counter_file.exists():
            try:
                with open(self.id_counter_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[DB] id_counters load failed: {e}")
                return {}
        return {}

    def _save_id_counters(self):
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(
                prefix=".id_counters.", suffix=".json", dir=str(self.data_dir))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.id_counters, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.id_counter_file)
        except Exception as e:
            print(f"[DB] id_counters save failed: {e}")
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise

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
        for word in ['TOUR', 'TRIP', 'PILGRIMAGE', 'VISIT', 'EXPEDITION']:
            clean_name = clean_name.replace(word, '')
        if len(clean_name) >= 3:
            return clean_name[:3]
        if len(clean_name) == 2:
            return clean_name + 'X'
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
            'TRV': self.travelers, 'PAY': self.payments,
            'INV': self.invoices, 'REC': self.receipts,
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
        with self._file_lock():
            self.id_counters = self._load_id_counters() or self.id_counters
            if counter_key in self.id_counters:
                next_num = int(self.id_counters[counter_key]) + 1
            else:
                next_num = self._get_next_sequence(prefix, category, year) + 1
            self.id_counters[counter_key] = next_num
            self._save_id_counters()
        return f"{prefix}/{category}/{year}/{next_num:03d}"

    # =================================================================================
    # 2.3 — DATA LOADING / SAVING (Whitespace Safe)
    # =================================================================================
    def _load_df(self, filename):
        filepath = self.data_dir / filename
        if not filepath.exists():
            print(f"[DB] {filename} not found - creating empty")
            return self._create_empty_df(filename)
        try:
            df = pd.read_csv(filepath)

            if filename == "users.csv":
                for col in ['username', 'full_name', 'email', 'role',
                            'password_hash', 'created_at', 'last_login',
                            'permissions']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str).fillna('')
                                   .replace('nan', ''))
                if 'permissions' not in df.columns:
                    df['permissions'] = ''

            elif filename == "travelers.csv":
                keep = [c for c in TRAVELER_COLUMNS if c in df.columns]
                df = df[keep]
                for col in TRAVELER_COLUMNS:
                    if col not in df.columns:
                        df[col] = ''
                    df[col] = (df[col].astype(str).fillna('')
                               .replace('nan', ''))
                
                # CRITICAL FIX: Strip whitespace from ID columns
                df['id'] = df['id'].str.strip()
                df['batch_id'] = df['batch_id'].str.strip()

            elif filename == "batches.csv":
                for col in ['total_seats', 'available_seats', 'price']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(
                            df[col], errors='coerce').fillna(0)
                        if col in ['total_seats', 'available_seats']:
                            df[col] = df[col].astype(int)
                        elif col == 'price':
                            df[col] = df[col].astype(float)
                for col in ['id', 'batch_name', 'tour_type_id',
                            'tour_type_name', 'year', 'departure_date',
                            'return_date', 'status', 'description']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str).fillna('')
                                   .replace('nan', ''))
                
                # CRITICAL FIX: Strip whitespace from ID columns
                df['id'] = df['id'].str.strip()

            elif filename == "payments.csv":
                if 'amount' in df.columns:
                    df['amount'] = pd.to_numeric(
                        df['amount'], errors='coerce').fillna(0)
                for col in ['id', 'traveler_id', 'batch_id',
                            'payment_method', 'status', 'transaction_id',
                            'invoice_id', 'notes', 'payment_date']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str).fillna('')
                                   .replace('nan', ''))

            elif filename == "invoices.csv":
                for col in ['amount', 'discount_percentage', 'discount_amount',
                            'taxable_value', 'gst_percentage', 'gst_amount',
                            'tcs_percentage', 'tcs_amount', 'total_amount',
                            'rounded_total']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(
                            df[col], errors='coerce').fillna(0)
                    else:
                        df[col] = 0.0
                for col in ['id', 'invoice_no', 'traveler_id', 'batch_id',
                            'issue_date', 'due_date', 'status', 'notes']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str).fillna('')
                                   .replace('nan', ''))

            elif filename == "receipts.csv":
                if 'amount' in df.columns:
                    df['amount'] = pd.to_numeric(
                        df['amount'], errors='coerce').fillna(0)
                for col in ['id', 'receipt_no', 'payment_id', 'invoice_id',
                            'receipt_date', 'notes']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str).fillna('')
                                   .replace('nan', ''))

            elif filename == "activity_log.csv":
                for col in ['id', 'user_id', 'action', 'timestamp', 'details']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str).fillna('')
                                   .replace('nan', ''))

            elif filename == "backup_history.csv":
                for col in ['id', 'backup_date', 'backup_file', 'status']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str).fillna('')
                                   .replace('nan', ''))
                if 'size' in df.columns:
                    df['size'] = pd.to_numeric(
                        df['size'], errors='coerce').fillna(0)

            elif filename == "company_settings.csv":
                if 'tan_no' not in df.columns:
                    df['tan_no'] = ''
                for col in ['id', 'company_name', 'address', 'phone', 'email',
                            'website', 'gst_no', 'tan_no', 'pan_no',
                            'logo_path', 'bank_details']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str).fillna('')
                                   .replace('nan', ''))

            return df
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            import traceback
            traceback.print_exc()
            return self._create_empty_df(filename)

    def _create_empty_df(self, filename):
        columns = {
            "users.csv": ['id', 'username', 'password_hash', 'full_name',
                          'email', 'role', 'permissions', 'created_at',
                          'last_login'],
            "travelers.csv": list(TRAVELER_COLUMNS),
            "batches.csv": ['id', 'batch_name', 'tour_type_id',
                            'tour_type_name', 'year', 'departure_date',
                            'return_date', 'total_seats', 'available_seats',
                            'price', 'status', 'description'],
            "payments.csv": ['id', 'traveler_id', 'batch_id', 'amount',
                             'payment_date', 'payment_method', 'status',
                             'transaction_id', 'invoice_id', 'notes'],
            "invoices.csv": ['id', 'invoice_no', 'traveler_id', 'batch_id',
                             'amount', 'discount_percentage',
                             'discount_amount', 'taxable_value',
                             'gst_percentage', 'gst_amount', 'tcs_percentage',
                             'tcs_amount', 'total_amount', 'rounded_total',
                             'issue_date', 'due_date', 'status', 'notes'],
            "receipts.csv": ['id', 'receipt_no', 'payment_id', 'invoice_id',
                             'amount', 'receipt_date', 'notes'],
            "activity_log.csv": ['id', 'user_id', 'action', 'timestamp',
                                 'details'],
            "backup_history.csv": ['id', 'backup_date', 'backup_file',
                                   'size', 'status'],
            "company_settings.csv": ['id', 'company_name', 'address', 'phone',
                                     'email', 'website', 'gst_no', 'tan_no',
                                     'pan_no', 'logo_path', 'bank_details'],
        }
        return pd.DataFrame(columns=columns.get(filename, []))

    def _save_df(self, df, filename):
        path = self.data_dir / filename
        tmp = None
        try:
            with self._file_lock():
                fd, tmp = tempfile.mkstemp(
                    prefix=f".{filename}.", suffix=".tmp",
                    dir=str(self.data_dir), text=True)
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                    df.to_csv(f, index=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            try:
                self._csv_snapshots[filename] = path.stat().st_mtime
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[DB] [ERROR] Failed to save {filename}: {e}")
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise

    def _ensure_permissions_column(self):
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
                print(f"[DB] Backfilled permissions for {len(self.users)} users")
        except Exception as e:
            print(f"[DB] _ensure_permissions_column failed: {e}")

    def _initialize_defaults(self):
        if self.users.empty:
            initial_password = os.environ.get(
                "HAJ_ADMIN_PASSWORD", "").strip()
            using_random = False
            if not initial_password:
                import secrets
                initial_password = secrets.token_urlsafe(16)
                using_random = True

            admin_user = pd.DataFrame([{
                'id': "ADMIN/USR/001",
                'username': 'admin',
                'password_hash': self._hash_password(initial_password),
                'full_name': 'System Administrator',
                'email': 'admin@hajtravel.com',
                'role': 'super_admin',
                'permissions': json.dumps(
                    sorted(ROLE_DEFAULT_PERMISSIONS["super_admin"])),
                'created_at': datetime.now().isoformat(),
                'last_login': '',
            }])
            self.users = pd.concat(
                [self.users, admin_user], ignore_index=True)
            self._save_df(self.users, "users.csv")
            print("=" * 70)
            print("[WARN]  DEFAULT ADMIN USER CREATED")
            print("    Username: admin")
            if using_random:
                print(f"    One-time password: {initial_password}")
                print("    -> Save this now. It will not be shown again.")
            else:
                print("    Password source : HAJ_ADMIN_PASSWORD env var")
            print("    -> CHANGE THIS PASSWORD IMMEDIATELY after first login!")
            print("=" * 70)

        if self.company_settings.empty:
            company = pd.DataFrame([{
                'id': "COMP/001",
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
                    'upi': 'alhudha@islamic',
                }),
            }])
            self.company_settings = pd.concat(
                [self.company_settings, company], ignore_index=True)
            self._save_df(self.company_settings, "company_settings.csv")

    # =================================================================================
    # 2.4 — AUTHENTICATION & USER MANAGEMENT
    # =================================================================================
    def _hash_password(self, password: str) -> str:
        if _WERKZEUG_OK:
            return generate_password_hash(password)
        return hashlib.sha256(password.encode()).hexdigest()

    def _check_password(self, stored_hash: str, password: str) -> bool:
        if not stored_hash:
            return False
        if _WERKZEUG_OK and stored_hash.startswith(
                ("pbkdf2:", "scrypt:", "argon2:")):
            try:
                return check_password_hash(stored_hash, password)
            except Exception:
                return False
        return hashlib.sha256(password.encode()).hexdigest() == stored_hash

    def _is_legacy_hash(self, stored_hash: str) -> bool:
        return bool(stored_hash) and not stored_hash.startswith(
            ("pbkdf2:", "scrypt:", "argon2:"))

    def authenticate_user(self, username, password):
        user = self.users[self.users['username'] == username]
        if user.empty:
            return None
        row = user.iloc[0]
        if not self._check_password(row.get('password_hash', ''), password):
            return None
        if self._is_legacy_hash(row.get('password_hash', '')):
            try:
                new_hash = self._hash_password(password)
                self.users.loc[self.users['id'] == row['id'],
                               'password_hash'] = new_hash
                self._save_df(self.users, "users.csv")
                print(f"[DB] Upgraded legacy password hash for {row['id']}")
            except Exception as e:
                print(f"[DB] password-hash upgrade failed: {e}")

        self.users.loc[self.users['id'] == row['id'],
                       'last_login'] = datetime.now().isoformat()
        self._save_df(self.users, "users.csv")
        self._current_user_id = row['id']
        result = row.to_dict()
        result.pop('password_hash', None)
        return result

    def get_users(self):
        return self.users.to_dict('records')

    def get_user_by_id(self, user_id):
        u = self.users[self.users['id'] == user_id]
        return u.iloc[0].to_dict() if not u.empty else None

    def add_user(self, user_data):
        data = dict(user_data)
        pwd = data.pop('password', '')
        if pwd:
            data['password_hash'] = self._hash_password(pwd)
        elif 'password_hash' not in data:
            data['password_hash'] = self._hash_password('changeme')
        data['id'] = self._generate_id('ADMIN', 'USR', None)
        data['created_at'] = datetime.now().isoformat()
        data['last_login'] = ''
        role = str(data.get('role', 'staff')).lower().strip()
        if not str(data.get('permissions', '') or '').strip():
            defaults = ROLE_DEFAULT_PERMISSIONS.get(
                role, ROLE_DEFAULT_PERMISSIONS["viewer"])
            data['permissions'] = json.dumps(sorted(defaults))
        if 'permissions' not in self.users.columns:
            self.users['permissions'] = ''
        self.users = pd.concat(
            [self.users, pd.DataFrame([data])], ignore_index=True)
        self._save_df(self.users, "users.csv")
        return data['id']

    def update_user(self, user_id, user_data):
        data = dict(user_data)
        pwd = data.pop('password', '')
        if pwd:
            data['password_hash'] = self._hash_password(pwd)
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
        if (len(super_admins) <= 1
                and user_id in super_admins['id'].values):
            raise Exception(
                "Cannot delete the last super_admin account. "
                "Promote another user to super_admin first.")
        self.users = self.users[self.users['id'] != user_id]
        self._save_df(self.users, "users.csv")

    def get_user_permissions(self, user_id):
        u = self.get_user_by_id(user_id)
        if not u:
            return set()
        return self._parse_permissions(
            u.get('permissions', ''), u.get('role', 'viewer'))

    def has_permission(self, user_id, permission_key):
        return permission_key in self.get_user_permissions(user_id)

    def _parse_permissions(self, value, role):
        if pd is not None and pd.isna(value):
            value = ""
        s = str(value or "").strip()
        if not s:
            return set(ROLE_DEFAULT_PERMISSIONS.get(
                str(role).lower(), ROLE_DEFAULT_PERMISSIONS["viewer"]))
        try:
            if s.startswith("["):
                return set(json.loads(s))
            return set(x.strip() for x in s.split("|") if x.strip())
        except Exception:
            return set(ROLE_DEFAULT_PERMISSIONS.get(
                str(role).lower(), ROLE_DEFAULT_PERMISSIONS["viewer"]))

    # =================================================================================
    # 2.5 — TRAVELERS
    # =================================================================================
    def get_travelers(self, batch_id=None):
        if batch_id:
            return self.travelers[
                self.travelers['batch_id'] == batch_id].to_dict('records')
        return self.travelers.to_dict('records')

    def get_traveler_by_id(self, traveler_id):
        # CRITICAL FIX: Strip whitespace and cast to string to ensure match
        traveler_id = str(traveler_id).strip()
        traveler = self.travelers[
            self.travelers['id'].astype(str).str.strip() == traveler_id
        ]
        return traveler.iloc[0].to_dict() if not traveler.empty else None

    def _validate_traveler_data(self, data, *, is_update=False):
        if not is_update:
            missing = [f for f in _REQUIRED_TRAVELER_FIELDS
                       if not str(data.get(f, "") or "").strip()]
            if missing:
                raise ValueError(
                    "Missing required field(s): " + ", ".join(missing))

        batch_id = str(data.get("batch_id", "") or "").strip()
        if batch_id and self.get_batch_by_id(batch_id) is None:
            raise ValueError(f"Selected batch does not exist: {batch_id}")

        pin = str(data.get("pin", "") or "").strip()
        if pin and (not pin.isdigit() or len(pin) != 4):
            raise ValueError("PIN must be exactly 4 digits")

        mobile = str(data.get("mobile", "") or "").strip()
        if mobile:
            import re
            digits = re.sub(r"\D", "", mobile)
            if not (10 <= len(digits) <= 15):
                raise ValueError("Mobile must contain 10–15 digits")

    def _check_duplicate_passport(self, passport_no, exclude_id=None):
        passport_no = str(passport_no or "").strip()
        if not passport_no:
            return
        mask = (self.travelers['passport_no'].astype(str)
                .str.strip().str.upper() == passport_no.upper())
        if exclude_id is not None:
            mask &= self.travelers['id'].astype(str) != str(exclude_id)
        if bool(mask.any()):
            raise ValueError(
                f"A traveler with passport number {passport_no} "
                f"already exists")

    def _recalculate_batch_seats(self, batch_id):
        batch_mask = self.batches['id'].astype(str) == str(batch_id)
        if not batch_mask.any():
            raise ValueError(f"Batch not found: {batch_id}")

        traveler_mask = (self.travelers['batch_id'].astype(str)
                         == str(batch_id))
        booked = int(traveler_mask.sum())

        total = int(self.batches.loc[batch_mask, 'total_seats'].iloc[0] or 0)
        self.batches.loc[batch_mask, 'available_seats'] = total - booked
        self._save_df(self.batches, "batches.csv")

    def _reconcile_all_batch_seats(self):
        """One-shot boot-time reconciliation of stored available_seats."""
        try:
            for bid in self.batches['id'].tolist():
                try:
                    mask = self.batches['id'].astype(str) == str(bid)
                    traveler_mask = (self.travelers['batch_id'].astype(str)
                                     == str(bid))
                    booked = int(traveler_mask.sum())
                    total = int(self.batches.loc[
                        mask, 'total_seats'].iloc[0] or 0)
                    expected = total - booked
                    current = int(self.batches.loc[
                        mask, 'available_seats'].iloc[0] or 0)
                    if current != expected:
                        self.batches.loc[mask,
                                         'available_seats'] = expected
                        print(f"[DB] reconciled batch {bid}: "
                              f"{current} → {expected}")
                except Exception as e:
                    print(f"[DB] reconcile seats for {bid} failed: {e}")
            self._save_df(self.batches, "batches.csv")
        except Exception as e:
            print(f"[DB] _reconcile_all_batch_seats failed: {e}")

    def add_traveler(self, traveler_data):
        self._validate_traveler_data(traveler_data, is_update=False)
        self._check_duplicate_passport(traveler_data.get("passport_no"))

        batch_id = str(traveler_data.get('batch_id', '') or '').strip()
        year = datetime.now().year
        prefix = 'HAJ'
        batch = self.get_batch_by_id(batch_id) if batch_id else None
        if batch:
            batch_year = batch.get('year')
            if batch_year:
                year = batch_year
            prefix = self._get_prefix_from_name(
                batch.get('tour_type_name', 'HAJ'))

        if batch_id:
            try:
                current = int(batch.get('available_seats', 0) or 0)
            except (ValueError, TypeError):
                current = 0
            if current < 1:
                raise ValueError("No seats available in this batch")

        traveler_data = dict(traveler_data)
        traveler_data['id'] = self._generate_id(prefix, 'TRV', str(year))
        traveler_data['registration_date'] = datetime.now().isoformat()
        traveler_data.setdefault('status', 'Active')

        clean = {}
        for key in TRAVELER_COLUMNS:
            value = traveler_data.get(key, '')
            if value is None:
                clean[key] = ''
            elif isinstance(value, float) and pd.isna(value):
                clean[key] = ''
            else:
                clean[key] = str(value).strip()

        prev_travelers = self.travelers.copy()
        prev_batches = self.batches.copy()
        try:
            self.travelers = pd.concat(
                [self.travelers, pd.DataFrame([clean])], ignore_index=True)
            self._save_df(self.travelers, "travelers.csv")
            if batch_id:
                self._recalculate_batch_seats(batch_id)
            return clean['id']
        except Exception:
            self.travelers = prev_travelers
            self.batches = prev_batches
            raise

    def update_traveler(self, traveler_id, traveler_data):
        try:
            mask = self.travelers['id'].astype(str) == str(traveler_id)
            if not mask.any():
                print(f"[DB] update_traveler: {traveler_id} not found")
                return False

            old_row = self.travelers.loc[mask].iloc[0]
            old_batch = str(old_row.get('batch_id', '') or '').strip()

            self._validate_traveler_data(traveler_data, is_update=True)
            if 'passport_no' in traveler_data:
                self._check_duplicate_passport(
                    traveler_data['passport_no'], exclude_id=traveler_id)

            new_batch = str(
                traveler_data.get('batch_id', old_batch) or '').strip()

            if old_batch != new_batch and new_batch:
                b = self.get_batch_by_id(new_batch)
                if b is None:
                    raise ValueError(
                        f"Selected batch does not exist: {new_batch}")
                try:
                    cur = int(b.get('available_seats', 0) or 0)
                except (ValueError, TypeError):
                    cur = 0
                if cur < 1:
                    raise ValueError("No seats available in this batch")

            prev_travelers = self.travelers.copy()
            prev_batches = self.batches.copy()

            valid_cols = set(self.travelers.columns)
            updated = 0
            for key, value in traveler_data.items():
                if key not in valid_cols:
                    continue
                try:
                    col_dtype = self.travelers[key].dtype
                    if pd.api.types.is_numeric_dtype(col_dtype):
                        if (value is None or value == ""
                                or (isinstance(value, float)
                                    and pd.isna(value))
                                or (isinstance(value, str)
                                    and value.strip().lower()
                                    in ("nan", "none", ""))):
                            value = 0
                        else:
                            try:
                                value = float(value)
                            except (ValueError, TypeError):
                                value = 0
                    else:
                        if value is None:
                            value = ""
                        elif isinstance(value, float) and pd.isna(value):
                            value = ""
                        else:
                            value = str(value).strip()
                    self.travelers.loc[mask, key] = value
                    updated += 1
                except (ValueError, TypeError) as e:
                    print(f"[DB] update_traveler: skip {key} -> {e}")
                    continue

            try:
                self._save_df(self.travelers, "travelers.csv")
                if old_batch and old_batch != new_batch:
                    self._recalculate_batch_seats(old_batch)
                if new_batch and old_batch != new_batch:
                    self._recalculate_batch_seats(new_batch)
            except Exception:
                self.travelers = prev_travelers
                self.batches = prev_batches
                raise

            print(f"[DB] update_traveler: {traveler_id} ({updated} fields)")
            return True
        except ValueError:
            raise
        except Exception as e:
            print(f"[DB] update_traveler failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def delete_traveler(self, traveler_id):
        mask = self.travelers['id'].astype(str) == str(traveler_id)
        if not mask.any():
            raise ValueError(f"Traveler not found: {traveler_id}")

        traveler = self.travelers.loc[mask].iloc[0]
        batch_id = str(traveler.get('batch_id', '') or '').strip()

        prev_travelers = self.travelers.copy()
        prev_batches = self.batches.copy()

        try:
            self.travelers = self.travelers.loc[~mask].copy()
            self._save_df(self.travelers, "travelers.csv")
            if batch_id:
                self._recalculate_batch_seats(batch_id)
            return True
        except Exception:
            self.travelers = prev_travelers
            self.batches = prev_batches
            raise

    # =================================================================================
    # 2.6 — BATCHES
    # =================================================================================
    def get_batches(self, status=None):
        if status:
            target = str(status).strip().lower()
            mask = (self.batches['status'].astype(str)
                    .str.strip().str.lower() == target)
            return self.batches[mask].to_dict('records')
        return self.batches.to_dict('records')

    def get_batch_by_id(self, batch_id):
        # CRITICAL FIX: Strip whitespace and cast to string to ensure match
        batch_id = str(batch_id).strip()
        batch = self.batches[
            self.batches['id'].astype(str).str.strip() == batch_id
        ]
        return batch.iloc[0].to_dict() if not batch.empty else None

    def add_batch(self, batch_data):
        tour_type_name = batch_data.get('tour_type_name', 'HAJ')
        year = batch_data.get('year', datetime.now().year)
        prefix = self._get_prefix_from_name(tour_type_name)
        batch_data['id'] = self._generate_id(prefix, 'BCH', str(year))
        batch_data['total_seats'] = int(batch_data.get('total_seats', 0))
        if batch_data['total_seats'] <= 0:
            raise ValueError("total_seats must be greater than zero")
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
                batch_data[key] = str(value).strip()
        self.batches = pd.concat(
            [self.batches, pd.DataFrame([batch_data])], ignore_index=True)
        self._save_df(self.batches, "batches.csv")
        return batch_data['id']

    def update_batch(self, batch_id, batch_data):
        current_batch = self.get_batch_by_id(batch_id)
        if not current_batch:
            raise Exception("Batch not found")

        if 'total_seats' in batch_data:
            try:
                new_total = int(batch_data['total_seats'])
            except (ValueError, TypeError):
                raise ValueError("total_seats must be a valid integer")
            if new_total <= 0:
                raise ValueError("total_seats must be greater than zero")

            traveler_mask = (self.travelers['batch_id'].astype(str)
                             == str(batch_id))
            booked = int(traveler_mask.sum())
            if new_total < booked:
                raise ValueError(
                    f"Cannot reduce seats below current bookings "
                    f"({booked} traveler(s) currently assigned)")

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
                update_data[key] = (str(value).strip() if value is not None else '')

        for key, value in update_data.items():
            self.batches.loc[
                self.batches['id'] == batch_id, key] = value

        if 'total_seats' in batch_data:
            traveler_mask = (self.travelers['batch_id'].astype(str)
                             == str(batch_id))
            booked = int(traveler_mask.sum())
            new_total = int(update_data['total_seats'])
            self.batches.loc[
                self.batches['id'] == batch_id,
                'available_seats'] = new_total - booked

        self._save_df(self.batches, "batches.csv")

    def delete_batch(self, batch_id):
        travelers = self.travelers[
            self.travelers['batch_id'].astype(str) == str(batch_id)]
        if not travelers.empty:
            raise ValueError("Cannot delete batch with assigned travelers")

        invoices = self.invoices[
            self.invoices['batch_id'].astype(str) == str(batch_id)]
        if not invoices.empty:
            raise ValueError(
                f"Cannot delete batch referenced by "
                f"{len(invoices)} invoice(s)")

        payments = self.payments[
            self.payments['batch_id'].astype(str) == str(batch_id)]
        if not payments.empty:
            raise ValueError(
                f"Cannot delete batch referenced by "
                f"{len(payments)} payment(s)")

        self.batches = self.batches[
            self.batches['id'].astype(str) != str(batch_id)]
        self._save_df(self.batches, "batches.csv")

    def _update_batch_seats(self, batch_id, change):
        """
        DEPRECATED — kept only for backward compatibility.
        Redirects to _recalculate_batch_seats so any incremental call
        produces a value consistent with actual bookings.
        """
        print(f"[DB] _update_batch_seats({batch_id}, {change}) "
              f"is deprecated — recalculating instead")
        self._recalculate_batch_seats(batch_id)

    # =================================================================================
    # 2.7 — PAYMENTS
    # =================================================================================
    def get_payments(self, traveler_id=None):
        if traveler_id:
            return self.payments[
                self.payments['traveler_id'] == traveler_id
            ].to_dict('records')
        return self.payments.to_dict('records')

    def add_payment(self, payment_data):
        # validate traveler + batch
        traveler_id = str(payment_data.get('traveler_id', '') or '').strip()
        if not traveler_id:
            raise ValueError("Traveler is required for payment")
        traveler = self.get_traveler_by_id(traveler_id)
        if not traveler:
            raise ValueError(f"Traveler not found: {traveler_id}")
        if not str(traveler.get('batch_id', '') or '').strip():
            raise ValueError(
                "Traveler has no assigned batch — cannot record payment")

        batch_id = payment_data.get('batch_id') or traveler.get('batch_id')
        year = datetime.now().year
        prefix = 'HAJ'
        if batch_id:
            batch = self.get_batch_by_id(batch_id)
            if batch:
                batch_year = batch.get('year')
                if batch_year:
                    year = batch_year
                prefix = self._get_prefix_from_name(
                    batch.get('tour_type_name', 'HAJ'))

        payment_data['id'] = self._generate_id(prefix, 'PAY', str(year))
        payment_data['payment_date'] = datetime.now().isoformat()

        invoice_id = payment_data.get('invoice_id', '')
        if (invoice_id is None
                or (isinstance(invoice_id, float) and str(invoice_id) == 'nan')):
            invoice_id = ''
        payment_data['invoice_id'] = invoice_id
        payment_data['amount'] = float(payment_data.get('amount', 0))

        for key, value in payment_data.items():
            if value is None:
                payment_data[key] = ''
            elif key == 'amount':
                payment_data[key] = float(value)
            else:
                payment_data[key] = str(value).strip()

        self.payments = pd.concat(
            [self.payments, pd.DataFrame([payment_data])], ignore_index=True)
        self._save_df(self.payments, "payments.csv")

        # receipts only for completed payments
        if str(payment_data.get('status', '')).strip().lower() == 'completed':
            self._generate_receipt(payment_data)

        # reconcile linked invoice
        if invoice_id:
            self._recalculate_invoice_status(invoice_id)

        return payment_data['id']

    def update_payment(self, payment_id, payment_data):
        try:
            mask = self.payments['id'] == payment_id
            if not mask.any():
                print(f"[WARN] Payment {payment_id} not found")
                return False
            current = self.payments.loc[mask].iloc[0].to_dict()
            old_invoice_id = str(current.get('invoice_id', '') or '').strip()

            updates = {}
            fields = {
                'amount': self._convert_to_float,
                'payment_date': self._parse_date,
                'payment_method': self._convert_to_string,
                'status': self._validate_status,
                'transaction_id': self._convert_to_string,
                'invoice_id': self._convert_invoice_id,
                'notes': self._convert_to_string,
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

            new_invoice_id = str(updates.get('invoice_id', '') or '').strip()
            if old_invoice_id:
                self._recalculate_invoice_status(old_invoice_id)
            if new_invoice_id and new_invoice_id != old_invoice_id:
                self._recalculate_invoice_status(new_invoice_id)

            try:
                self.log_activity(
                    self._current_user_id, "update_payment",
                    f"Updated payment {payment_id} - "
                    f"Amount: {updates.get('amount', 0):,.2f}")
            except Exception as log_ex:
                print(f"[DB] update_payment activity log failed: {log_ex}")
            return True
        except Exception as e:
            print(f"[ERROR] Error updating payment {payment_id}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _convert_to_float(self, value):
        if value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def _convert_to_string(self, value):
        return '' if value is None else str(value).strip()

    def _parse_date(self, date_value):
        if not date_value:
            return datetime.now().isoformat()
        if isinstance(date_value, str):
            return date_value
        if isinstance(date_value, datetime):
            return date_value.isoformat()
        if hasattr(date_value, 'toString'):
            return date_value.toString("yyyy-MM-dd")
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
        receipts = self.receipts[self.receipts['payment_id'] == payment_id]
        if not receipts.empty:
            raise Exception(
                "Cannot delete payment with associated receipts")

        mask = self.payments['id'].astype(str) == str(payment_id)
        inv_id = ''
        if mask.any():
            inv_id = str(
                self.payments.loc[mask, 'invoice_id'].iloc[0] or '').strip()

        self.payments = self.payments[self.payments['id'] != payment_id]
        self._save_df(self.payments, "payments.csv")

        if inv_id:
            self._recalculate_invoice_status(inv_id)

    def delete_payment_records(self, payment_ids):
        """Delete explicitly approved payment IDs and their receipts.

        This is used only by the invoice-tab duplicate cleanup dialog after
        the administrator checks individual records. Normal payment deletion
        remains protected by delete_payment().
        """
        ids = {str(value or '').strip() for value in (payment_ids or [])}
        ids.discard('')
        if not ids:
            raise ValueError("No payment records selected")

        payment_mask = self.payments['id'].astype(str).str.strip().isin(ids)
        existing_ids = set(
            self.payments.loc[payment_mask, 'id'].astype(str).str.strip())
        if not existing_ids:
            raise ValueError("Selected payment records were not found")

        receipt_mask = (
            self.receipts['payment_id'].astype(str).str.strip().isin(existing_ids)
            if 'payment_id' in self.receipts.columns
            else pd.Series(False, index=self.receipts.index)
        )
        receipts_deleted = int(receipt_mask.sum())
        payments_deleted = int(payment_mask.sum())
        self.receipts = self.receipts.loc[~receipt_mask].copy()
        self.payments = self.payments.loc[~payment_mask].copy()
        self._save_df(self.receipts, "receipts.csv")
        self._save_df(self.payments, "payments.csv")
        return {
            'payments_deleted': payments_deleted,
            'receipts_deleted': receipts_deleted,
        }

    # =================================================================================
    # 2.8 — INVOICES
    # =================================================================================
    def get_invoices(self, traveler_id=None):
        if traveler_id:
            return self.invoices[
                self.invoices['traveler_id'] == traveler_id
            ].to_dict('records')
        return self.invoices.to_dict('records')

    def _recalculate_invoice_status(self, invoice_id):
        if not invoice_id:
            return
        inv_mask = self.invoices['id'].astype(str) == str(invoice_id)
        if not inv_mask.any():
            return

        try:
            inv_row = self.invoices.loc[inv_mask].iloc[0]
            try:
                inv_amount = float(inv_row.get('rounded_total', 0) or 0)
            except (ValueError, TypeError):
                inv_amount = 0.0
            if inv_amount <= 0:
                try:
                    inv_amount = float(inv_row.get('total_amount', 0) or 0)
                except (ValueError, TypeError):
                    inv_amount = 0.0

            paid = 0.0
            if not self.payments.empty:
                pm = (
                    (self.payments['invoice_id'].astype(str)
                     == str(invoice_id))
                    & (self.payments['status'].astype(str).str.lower()
                       == 'completed')
                )
                for _, row in self.payments.loc[pm].iterrows():
                    try:
                        paid += float(row.get('amount', 0) or 0)
                    except (ValueError, TypeError):
                        pass

            new_status = ('paid'
                          if (inv_amount > 0 and paid + 0.01 >= inv_amount)
                          else 'pending')
            current = str(inv_row.get('status', '') or '').lower()
            if current != new_status:
                self.invoices.loc[inv_mask, 'status'] = new_status
                self._save_df(self.invoices, "invoices.csv")
                print(f"[DB] invoice {invoice_id}: "
                      f"{current or 'none'} → {new_status} "
                      f"(paid={paid:.2f} / total={inv_amount:.2f})")
        except Exception as e:
            print(f"[DB] _recalculate_invoice_status failed: {e}")

    def generate_invoice(self, traveler_id, batch_id, amount,
                         gst_percentage=5, tcs_percentage=2,
                         discount_percentage=0.0, discount_amount=None):
        year = datetime.now().year
        prefix = 'HAJ'
        if batch_id:
            batch = self.get_batch_by_id(batch_id)
            if batch:
                batch_year = batch.get('year')
                if batch_year:
                    year = batch_year
                prefix = self._get_prefix_from_name(
                    batch.get('tour_type_name', 'HAJ'))
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
            discount_percentage = ((discount_amount / amount) * 100.0
                                   if amount > 0 else 0.0)
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
            'id': invoice_id, 'invoice_no': invoice_no,
            'traveler_id': traveler_id, 'batch_id': batch_id,
            'amount': amount,
            'discount_percentage': discount_percentage,
            'discount_amount': discount_amount,
            'taxable_value': taxable_value,
            'gst_percentage': gst_percentage, 'gst_amount': gst_amount,
            'tcs_percentage': tcs_percentage, 'tcs_amount': tcs_amount,
            'total_amount': total_amount,
            'rounded_total': float(rounded_total),
            'issue_date': datetime.now().isoformat(),
            'due_date': (datetime.now() + timedelta(days=30)).isoformat(),
            'status': 'pending', 'notes': '',
        }
        self.invoices = pd.concat(
            [self.invoices, pd.DataFrame([invoice_data])], ignore_index=True)
        self._save_df(self.invoices, "invoices.csv")
        return invoice_id

    def delete_invoice(self, invoice_id):
        """Delete only an invoice; preserve payments and receipts.

        Payments and receipts are independent financial records. Their
        ``invoice_id`` reference is intentionally retained so payment history
        remains available for verification even after an invoice is removed.
        """
        invoice_key = str(invoice_id or '').strip()
        if not invoice_key:
            raise ValueError("Invoice ID is required")

        invoice_mask = self.invoices['id'].astype(str).str.strip() == invoice_key
        if not invoice_mask.any():
            raise ValueError(f"Invoice not found: {invoice_key}")

        invoices_deleted = int(invoice_mask.sum())
        self.invoices = self.invoices.loc[~invoice_mask].copy()
        self._save_df(self.invoices, "invoices.csv")

        return {
            'invoice_id': invoice_key,
            'invoices_deleted': invoices_deleted,
            'payments_deleted': 0,
            'receipts_deleted': 0,
        }

    def _round_as_per_rules(self, amount):
        if isinstance(amount, (int, float)):
            decimal_part = amount - math.floor(amount)
            if decimal_part >= 0.50:
                return math.ceil(amount)
            return math.floor(amount)
        return amount

    # =================================================================================
    # 2.9 — RECEIPTS
    # =================================================================================
    def _generate_receipt(self, payment_data):
        pid = str(payment_data.get('id', '') or '').strip()
        if pid and not self.receipts.empty:
            existing = self.receipts[
                self.receipts['payment_id'].astype(str) == pid]
            if not existing.empty:
                print(f"[DB] Receipt already exists for payment {pid} "
                      f"— skipping")
                return existing.iloc[0].to_dict()

        batch_id = payment_data.get('batch_id')
        year = datetime.now().year
        prefix = 'HAJ'
        if batch_id:
            batch = self.get_batch_by_id(batch_id)
            if batch:
                batch_year = batch.get('year')
                if batch_year:
                    year = batch_year
                prefix = self._get_prefix_from_name(
                    batch.get('tour_type_name', 'HAJ'))
        receipt_id = self._generate_id(prefix, 'REC', str(year))
        receipt_no = (f"REC-{datetime.now().strftime('%Y%m')}-"
                      f"{len(self.receipts)+1:04d}")
        invoice_id = payment_data.get('invoice_id', '')
        if (invoice_id is None or (isinstance(invoice_id, float)
                                   and (invoice_id != invoice_id
                                        or str(invoice_id) == 'nan'))):
            invoice_id = ''
        receipt_data = {
            'id': receipt_id, 'receipt_no': receipt_no,
            'payment_id': payment_data['id'],
            'invoice_id': invoice_id,
            'amount': float(payment_data['amount']),
            'receipt_date': datetime.now().isoformat(),
            'notes': payment_data.get('notes', ''),
        }
        self.receipts = pd.concat(
            [self.receipts, pd.DataFrame([receipt_data])], ignore_index=True)
        self._save_df(self.receipts, "receipts.csv")

        if invoice_id:
            self._recalculate_invoice_status(invoice_id)

        return receipt_data

    def get_receipts(self, payment_id=None):
        if payment_id:
            return self.receipts[
                self.receipts['payment_id'] == payment_id
            ].to_dict('records')
        return self.receipts.to_dict('records')

    # =================================================================================
    # 2.10 — REPORTS & DASHBOARD
    # =================================================================================
    def get_dashboard_summary(self):
        statuses = self.batches['status'].astype(str).str.strip().str.lower()
        active_batches = int(statuses.isin(_ACTIVE_BATCH_STATUSES).sum())
        pending_inv = self.invoices['status'].astype(str).str.lower()
        return {
            'total_travelers': len(self.travelers),
            'active_batches': active_batches,
            'total_payments': (self.payments['amount'].sum()
                               if not self.payments.empty else 0),
            'pending_payments': int((pending_inv == 'pending').sum()),
            'available_seats': (self.batches['available_seats'].sum()
                                if not self.batches.empty else 0),
            'total_receipts': len(self.receipts),
        }

    def get_financial_report(self, start_date=None, end_date=None):
        payments = self.payments.copy()
        if start_date:
            payments = payments[payments['payment_date'] >= start_date]
        if end_date:
            payments = payments[payments['payment_date'] <= end_date]
        return {
            'total_collected': (payments['amount'].sum()
                                if not payments.empty else 0),
            'payment_count': len(payments) if not payments.empty else 0,
            'by_method': (payments.groupby('payment_method')['amount']
                          .sum().to_dict() if not payments.empty else {}),
            'average_payment': (payments['amount'].mean()
                                if not payments.empty else 0),
        }

    # =================================================================================
    # 2.11 — BACKUP / RESTORE / ACTIVITY
    # =================================================================================
    def create_backup(self):
        backup_id = self._generate_id('BAK', 'BUP', None)
        backup_date = datetime.now()
        backup_filename = (f"backup_"
                           f"{backup_date.strftime('%Y%m%d_%H%M%S')}.zip")
        backup_path = self._backup_dir / backup_filename
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for csv_file in self.data_dir.glob("*.csv"):
                zipf.write(csv_file, csv_file.name)
        record = pd.DataFrame([{
            'id': backup_id,
            'backup_date': backup_date.isoformat(),
            'backup_file': str(backup_path),
            'size': os.path.getsize(backup_path),
            'status': 'success',
        }])
        self.backup_history = pd.concat(
            [self.backup_history, record], ignore_index=True)
        self._save_df(self.backup_history, "backup_history.csv")
        print(f"[DB] Backup created: {backup_path}")
        return str(backup_path)

    @staticmethod
    def _safe_extract(zip_file, target_dir: Path):
        target = Path(target_dir).resolve()
        for member in zip_file.infolist():
            dest = (target / member.filename).resolve()
            if not str(dest).startswith(str(target) + os.sep):
                raise ValueError(
                    f"Unsafe path in backup archive: {member.filename}")
        zip_file.extractall(target)

    def restore_backup(self, backup_file):
        with zipfile.ZipFile(backup_file, 'r') as zipf:
            self._safe_extract.__func__(zipf, self.data_dir)
            staging = Path(tempfile.mkdtemp(
                prefix=".restore_", dir=str(self.data_dir.parent)))
            try:
                zipf.extractall(staging)
                for required in ("travelers.csv", "users.csv",
                                 "batches.csv"):
                    src = staging / required
                    if not src.exists():
                        raise ValueError(
                            f"Backup missing required file: {required}")
                    with open(src, "r", encoding="utf-8") as f:
                        if not f.readline().strip():
                            raise ValueError(
                                f"Backup file is empty: {required}")
                safety_dir = (self._backup_dir
                              / f"pre_restore_"
                                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                safety_dir.mkdir(parents=True, exist_ok=True)
                for csv_file in self.data_dir.glob("*.csv"):
                    shutil_copy = safety_dir / csv_file.name
                    try:
                        os.replace(str(csv_file), str(shutil_copy))
                    except OSError:
                        with open(csv_file, "rb") as fh:
                            with open(shutil_copy, "wb") as out:
                                out.write(fh.read())
                for csv_file in staging.glob("*.csv"):
                    os.replace(str(csv_file),
                               str(self.data_dir / csv_file.name))
            finally:
                import shutil
                try:
                    shutil.rmtree(staging, ignore_errors=True)
                except Exception:
                    pass
        self.reload_all()

    def log_activity(self, user_id, action, details=""):
        try:
            if not user_id:
                user_id = self._current_user_id or 'system'
            log_id = self._generate_id('LOG', 'ACT', None)
            entry = pd.DataFrame([{
                'id': log_id, 'user_id': user_id, 'action': action,
                'timestamp': datetime.now().isoformat(), 'details': details,
            }])
            self.activity_log = pd.concat(
                [self.activity_log, entry], ignore_index=True)
            self._save_df(self.activity_log, "activity_log.csv")
        except Exception as e:
            print(f"[DB] log_activity failed: {e}")

    def get_activity_log(self, user_id=None, limit=100):
        logs = self.activity_log
        if user_id:
            logs = logs[logs['user_id'] == user_id]
        return (logs.sort_values('timestamp', ascending=False)
                .head(limit).to_dict('records'))

    def set_current_user(self, user_id):
        self._current_user_id = user_id

    def get_current_user_id(self):
        return self._current_user_id

    def migrate_batch_tour_types(self):
        pass

    # =================================================================================
    # 2.12 — RELOAD METHODS
    # =================================================================================
    def reload_all(self):
        print("[DB] Reloading all data from disk...")
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
        self._reconcile_all_batch_seats()
        print(f"[DB] [OK] Reloaded: {len(self.users)} users, "
              f"{len(self.travelers)} travelers, {len(self.batches)} batches, "
              f"{len(self.payments)} payments, {len(self.invoices)} invoices, "
              f"{len(self.receipts)} receipts")

    def reload_payments(self):
        self.payments = self._load_df("payments.csv")
        return self.payments

    def reload_travelers(self):
        self.travelers = self._load_df("travelers.csv")
        return self.travelers

    def reload_batches(self):
        self.batches = self._load_df("batches.csv")
        return self.batches

    def reload_invoices(self):
        self.invoices = self._load_df("invoices.csv")
        return self.invoices

    def reload_receipts(self):
        self.receipts = self._load_df("receipts.csv")
        return self.receipts

    def reload_users(self):
        self.users = self._load_df("users.csv")
        self._ensure_permissions_column()
        return self.users

    def reload_company_settings(self):
        self.company_settings = self._load_df("company_settings.csv")
        return self.company_settings

    def reload_backup_history(self):
        self.backup_history = self._load_df("backup_history.csv")
        return self.backup_history

    def reload_activity_log(self):
        self.activity_log = self._load_df("activity_log.csv")
        return self.activity_log

    # =================================================================================
    # 2.13 — FILE CHANGE DETECTION
    # =================================================================================
    def _csv_mtime(self, filename):
        path = self.data_dir / filename
        if not path.exists():
            return 0
        try:
            return path.stat().st_mtime
        except Exception:
            return 0

    def has_csv_changed(self, filename):
        return self._csv_mtime(filename) > self._csv_snapshots.get(filename, 0)

    def mark_csv_as_read(self, filename):
        self._csv_snapshots[filename] = self._csv_mtime(filename)

    def get_data_folder_info(self):
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
# SECTION 2 END (FLET VERSION) — v5.3
# =================================================================================
