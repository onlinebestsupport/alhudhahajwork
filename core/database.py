# =================================================================================
# SECTION 2 (FLET VERSION) — DATABASE MODULE
# =================================================================================
# UPDATED — v4 — review-fix release
#   • Atomic + locked CSV writes (tempfile + fsync + os.replace + fcntl)
#   • Locked ID generation (thread + file lock)
#   • Transactional add/update/delete_traveler
#   • Batch existence + capacity validation
#   • Duplicate passport detection
#   • Werkzeug password hashing (legacy SHA-256 migration on login)
#   • Env-var-only default admin (no hardcoded password)
#   • Safe ZIP restore (path traversal guard, temp staging)
#   • Consistent backup directory
#   • Case-insensitive batch status
#
# PRESERVED FROM v3:
#   • UTF-8 stdout safety
#   • Ghost-column rejection in travelers
#   • NaN-safe update_traveler
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
    import fcntl  # POSIX file lock (Railway / Linux)
except ImportError:  # pragma: no cover — Windows fallback
    fcntl = None

try:
    from werkzeug.security import (
        generate_password_hash,
        check_password_hash,
    )
    _WERKZEUG_OK = True
except Exception:  # pragma: no cover
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


# =================================================================================
# CANONICAL TRAVELER COLUMNS
# =================================================================================
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

_ACTIVE_BATCH_STATUSES = {'active', 'open'}


# =================================================================================
# 2.1 — PERMISSIONS
# =================================================================================
PERMISSION_CATALOG = [
    "view_dashboard", "manage_travelers", "manage_batches",
    "manage_payments", "manage_invoices", "manage_receipts",
    "view_reports", "manage_users", "manage_backups",
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
    # 2.2.1 — __init__
    # =============================================================================
    def __init__(self, data_dir="data", current_user_id="system"):
        base_path = get_app_base_path()
        self.data_dir = Path(base_path) / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        print(f"[DB] Base path      : {base_path}")
        print(f"[DB] Data directory : {self.data_dir}")
        print(f"[DB] Data exists    : {self.data_dir.exists()}")
        print(f"[DB] Data writable  : "
              f"{os.access(str(self.data_dir), os.W_OK)}")

        self._verify_writable()

        # v4 — thread lock for in-process safety
        self._lock = threading.RLock()
        # v4 — separate lock file for cross-process CSV writes
        self._lock_file = self.data_dir / ".db.lock"
        # v4 — track csv snapshots for has_csv_changed()
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

        print(f"[DB] Loaded: "
              f"{len(self.users)} users, "
              f"{len(self.travelers)} travelers, "
              f"{len(self.batches)} batches, "
              f"{len(self.payments)} payments, "
              f"{len(self.invoices)} invoices, "
              f"{len(self.receipts)} receipts")

    # =============================================================================
    # 2.2.2 — _verify_writable
    # =============================================================================
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
                f"Data folder is not writable: {self.data_dir}\n"
                f"Error: {e}\n"
                f"On Railway, attach a Volume to this path "
                f"or grant write permissions."
            )

    # =============================================================================
    # 2.2.3 — _ensure_dirs  (v4 — consistent backup dir)
    # =============================================================================
    def _ensure_dirs(self):
        base = (self.data_dir.parent
                if self.data_dir.name == "data"
                else self.data_dir)
        self._backup_dir = base / "backups"
        folders = ["invoices", "receipts", "documents", "logos"]
        for f in folders:
            (base / f).mkdir(parents=True, exist_ok=True)
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    # =============================================================================
    # 2.2.4 — CROSS-PROCESS LOCK HELPER
    # =============================================================================
    class _FileLock:
        """Context manager wrapping fcntl advisory lock with a thread lock."""
        def __init__(self, path: Path, thread_lock: threading.RLock):
            self.path = path
            self.thread_lock = thread_lock
            self._fh = None

        def __enter__(self):
            self.thread_lock.acquire()
            try:
                self._fh = open(self.path, "a+")
                if fcntl is not None:
                    fcntl.flock(self._fh.fileno(),
                                fcntl.LOCK_EX)
            except Exception:
                self.thread_lock.release()
                raise
            return self

        def __exit__(self, exc_type, exc, tb):
            try:
                if self._fh is not None:
                    if fcntl is not None:
                        try:
                            fcntl.flock(self._fh.fileno(),
                                        fcntl.LOCK_UN)
                        except Exception:
                            pass
                    self._fh.close()
            finally:
                self.thread_lock.release()

    def _file_lock(self):
        return self._FileLock(self._lock_file, self._lock)

    # =================================================================================
    # 2.3 — ID COUNTERS (v4 — atomic + locked)
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
        """Atomic write of id_counters.json."""
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(
                prefix=".id_counters.",
                suffix=".json",
                dir=str(self.data_dir),
            )
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
        """v4 — locked read-modify-write so concurrent calls cannot collide."""
        if year is None:
            year = datetime.now().strftime('%Y')
        counter_key = f"{prefix}_{category}_{year}"

        # Cross-process lock — bounds the read of id_counters.json
        with self._file_lock():
            # Re-read counters under lock to see any fresh values
            self.id_counters = self._load_id_counters() or self.id_counters

            if counter_key in self.id_counters:
                next_num = int(self.id_counters[counter_key]) + 1
            else:
                next_num = self._get_next_sequence(
                    prefix, category, year) + 1

            self.id_counters[counter_key] = next_num
            self._save_id_counters()
        return f"{prefix}/{category}/{year}/{next_num:03d}"

    # =================================================================================
    # 2.4 — DATA LOADING / SAVING
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
                            'password_hash', 'created_at',
                            'last_login', 'permissions']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str)
                                   .fillna('')
                                   .replace('nan', ''))
                if 'permissions' not in df.columns:
                    df['permissions'] = ''

            elif filename == "travelers.csv":
                keep = [c for c in TRAVELER_COLUMNS if c in df.columns]
                df = df[keep]
                for col in TRAVELER_COLUMNS:
                    if col not in df.columns:
                        df[col] = ''
                for col in TRAVELER_COLUMNS:
                    df[col] = (df[col].astype(str)
                               .fillna('')
                               .replace('nan', ''))

            elif filename == "batches.csv":
                for col in ['total_seats', 'available_seats', 'price']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(
                            df[col], errors='coerce').fillna(0)
                        if col in ['total_seats', 'available_seats']:
                            df[col] = df[col].astype(int)
                        elif col == 'price':
                            df[col] = df[col].astype(float)
                for col in [
                    'id', 'batch_name', 'tour_type_id',
                    'tour_type_name', 'year', 'departure_date',
                    'return_date', 'status', 'description']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str)
                                   .fillna('')
                                   .replace('nan', ''))

            elif filename == "payments.csv":
                if 'amount' in df.columns:
                    df['amount'] = pd.to_numeric(
                        df['amount'], errors='coerce').fillna(0)
                for col in [
                    'id', 'traveler_id', 'batch_id',
                    'payment_method', 'status', 'transaction_id',
                    'invoice_id', 'notes', 'payment_date']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str)
                                   .fillna('')
                                   .replace('nan', ''))

            elif filename == "invoices.csv":
                for col in [
                    'amount', 'discount_percentage', 'discount_amount',
                    'taxable_value', 'gst_percentage', 'gst_amount',
                    'tcs_percentage', 'tcs_amount', 'total_amount',
                    'rounded_total']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(
                            df[col], errors='coerce').fillna(0)
                    else:
                        df[col] = 0.0
                for col in [
                    'id', 'invoice_no', 'traveler_id', 'batch_id',
                    'issue_date', 'due_date', 'status', 'notes']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str)
                                   .fillna('')
                                   .replace('nan', ''))

            elif filename == "receipts.csv":
                if 'amount' in df.columns:
                    df['amount'] = pd.to_numeric(
                        df['amount'], errors='coerce').fillna(0)
                for col in [
                    'id', 'receipt_no', 'payment_id', 'invoice_id',
                    'receipt_date', 'notes']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str)
                                   .fillna('')
                                   .replace('nan', ''))

            elif filename == "activity_log.csv":
                for col in ['id', 'user_id', 'action',
                            'timestamp', 'details']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str)
                                   .fillna('')
                                   .replace('nan', ''))

            elif filename == "backup_history.csv":
                for col in ['id', 'backup_date',
                            'backup_file', 'status']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str)
                                   .fillna('')
                                   .replace('nan', ''))
                if 'size' in df.columns:
                    df['size'] = pd.to_numeric(
                        df['size'], errors='coerce').fillna(0)

            elif filename == "company_settings.csv":
                if 'tan_no' not in df.columns:
                    df['tan_no'] = ''
                for col in [
                    'id', 'company_name', 'address', 'phone', 'email',
                    'website', 'gst_no', 'tan_no', 'pan_no',
                    'logo_path', 'bank_details']:
                    if col in df.columns:
                        df[col] = (df[col].astype(str)
                                   .fillna('')
                                   .replace('nan', ''))

            return df
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            import traceback
            traceback.print_exc()
            return self._create_empty_df(filename)

    def _create_empty_df(self, filename):
        columns = {
            "users.csv": [
                'id', 'username', 'password_hash', 'full_name',
                'email', 'role', 'permissions', 'created_at',
                'last_login'],
            "travelers.csv": list(TRAVELER_COLUMNS),
            "batches.csv": [
                'id', 'batch_name', 'tour_type_id', 'tour_type_name',
                'year', 'departure_date', 'return_date',
                'total_seats', 'available_seats', 'price',
                'status', 'description'],
            "payments.csv": [
                'id', 'traveler_id', 'batch_id', 'amount',
                'payment_date', 'payment_method', 'status',
                'transaction_id', 'invoice_id', 'notes'],
            "invoices.csv": [
                'id', 'invoice_no', 'traveler_id', 'batch_id',
                'amount', 'discount_percentage', 'discount_amount',
                'taxable_value', 'gst_percentage', 'gst_amount',
                'tcs_percentage', 'tcs_amount', 'total_amount',
                'rounded_total', 'issue_date', 'due_date',
                'status', 'notes'],
            "receipts.csv": [
                'id', 'receipt_no', 'payment_id', 'invoice_id',
                'amount', 'receipt_date', 'notes'],
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

    # =============================================================================
    # 2.4.3 — _save_df  (v4 — atomic + locked)
    # =============================================================================
    def _save_df(self, df, filename):
        path = self.data_dir / filename
        tmp = None
        try:
            with self._file_lock():
                fd, tmp = tempfile.mkstemp(
                    prefix=f".{filename}.",
                    suffix=".tmp",
                    dir=str(self.data_dir),
                    text=True,
                )
                with os.fdopen(fd, "w", encoding="utf-8",
                               newline="") as f:
                    df.to_csv(f, index=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            # Update snapshot so has_csv_changed() ignores our own write
            try:
                self._csv_snapshots[filename] = path.stat().st_mtime
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[DB] [ERROR] Failed to save {filename}: {e}")
            print(f"[DB]     Path: {path}")
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise

    # =============================================================================
    # 2.4.4 — _ensure_permissions_column
    # =============================================================================
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
                print(f"[DB] Backfilled permissions for "
                      f"{len(self.users)} users")
        except Exception as e:
            print(f"[DB] _ensure_permissions_column failed: {e}")

    # =============================================================================
    # 2.4.5 — _initialize_defaults  (v4 — no hardcoded password)
    # =============================================================================
    def _initialize_defaults(self):
        if self.users.empty:
            # Require HAJ_ADMIN_PASSWORD env var; never embed a real password.
            initial_password = os.environ.get("HAJ_ADMIN_PASSWORD", "").strip()
            using_random = False
            if not initial_password:
                import secrets
                initial_password = secrets.token_urlsafe(16)
                using_random = True

            admin_id = "ADMIN/USR/001"
            admin_user = pd.DataFrame([{
                'id': admin_id,
                'username': 'admin',
                'password_hash': self._hash_password(initial_password),
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
            print("[WARN]  DEFAULT ADMIN USER CREATED")
            print("    Username: admin")
            if using_random:
                print(f"    One-time password: {initial_password}")
                print("    -> Save this now. "
                      "It will not be shown again.")
                print("    -> Set HAJ_ADMIN_PASSWORD env var for a "
                      "deterministic first-boot password.")
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
                    'upi': 'alhudha@islamic'
                })
            }])
            self.company_settings = pd.concat(
                [self.company_settings, company], ignore_index=True)
            self._save_df(
                self.company_settings, "company_settings.csv")

    # =============================================================================
    # 2.4.6 — PASSWORD HELPERS (v4)
    # =============================================================================
    def _hash_password(self, password: str) -> str:
        if _WERKZEUG_OK:
            return generate_password_hash(password)
        return hashlib.sha256(password.encode()).hexdigest()

    def _check_password(self, stored_hash: str, password: str) -> bool:
        if not stored_hash:
            return False
        if _WERKZEUG_OK and stored_hash.startswith(("pbkdf2:", "scrypt:",
                                                    "argon2:")):
            try:
                return check_password_hash(stored_hash, password)
            except Exception:
                return False
        # Legacy fallback
        legacy = hashlib.sha256(password.encode()).hexdigest()
        return legacy == stored_hash

    def _is_legacy_hash(self, stored_hash: str) -> bool:
        return bool(stored_hash) and not stored_hash.startswith(
            ("pbkdf2:", "scrypt:", "argon2:")
        )

    # =============================================================================
    # 2.5 — AUTHENTICATION
    # =============================================================================
    def authenticate_user(self, username, password):
        user = self.users[self.users['username'] == username]
        if user.empty:
            return None
        row = user.iloc[0]
        if not self._check_password(row.get('password_hash', ''), password):
            return None

        # Transparent migration: upgrade legacy SHA-256 hashes
        if self._is_legacy_hash(row.get('password_hash', '')):
            try:
                new_hash = self._hash_password(password)
                self.users.loc[self.users['id'] == row['id'],
                               'password_hash'] = new_hash
                self._save_df(self.users, "users.csv")
                print(f"[DB] Upgraded legacy password hash for "
                      f"{row['id']}")
            except Exception as e:
                print(f"[DB] password-hash upgrade failed: {e}")

        self.users.loc[
            self.users['id'] == row['id'],
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
        if not u.empty:
            return u.iloc[0].to_dict()
        return None

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
        perms = str(data.get('permissions', '') or '').strip()
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
    # 2.6 — TRAVELERS  (v4 — transactional + validated)
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
        traveler = self.travelers[
            self.travelers['id'] == traveler_id]
        if not traveler.empty:
            return traveler.iloc[0].to_dict()
        return None

    # -----------------------------------------------------------------------------
    # 2.6.1 — Validation helpers (v4)
    # -----------------------------------------------------------------------------
    def _validate_traveler_data(self, data, *, is_update=False):
        if not is_update:
            missing = [f for f in _REQUIRED_TRAVELER_FIELDS
                       if not str(data.get(f, "") or "").strip()]
            if missing:
                raise ValueError(
                    "Missing required field(s): "
                    + ", ".join(missing))

        # Batch existence
        batch_id = str(data.get("batch_id", "") or "").strip()
        if batch_id:
            if self.get_batch_by_id(batch_id) is None:
                raise ValueError(
                    f"Selected batch does not exist: {batch_id}")

        # PIN format
        pin = str(data.get("pin", "") or "").strip()
        if pin and (not pin.isdigit() or len(pin) != 4):
            raise ValueError("PIN must be exactly 4 digits")

        # Mobile digits
        mobile = str(data.get("mobile", "") or "").strip()
        if mobile:
            import re
            digits = re.sub(r"\D", "", mobile)
            if not (10 <= len(digits) <= 15):
                raise ValueError(
                    "Mobile must contain 10–15 digits")

    def _check_duplicate_passport(self, passport_no, exclude_id=None):
        passport_no = str(passport_no or "").strip()
        if not passport_no:
            return
        mask = (
            self.travelers['passport_no']
            .astype(str).str.strip().str.upper()
            == passport_no.upper()
        )
        if exclude_id is not None:
            mask &= self.travelers['id'].astype(str) != str(exclude_id)
        if bool(mask.any()):
            raise ValueError(
                f"A traveler with passport number "
                f"{passport_no} already exists")

    # -----------------------------------------------------------------------------
    # 2.6.2 — add_traveler  (v4 — transactional)
    # -----------------------------------------------------------------------------
    def add_traveler(self, traveler_data):
        # ---- 1. Validation ----
        self._validate_traveler_data(traveler_data, is_update=False)
        self._check_duplicate_passport(
            traveler_data.get("passport_no"))

        batch_id = str(
            traveler_data.get('batch_id', '') or '').strip()

        # ---- 2. Resolve prefix/year ----
        year = datetime.now().year
        prefix = 'HAJ'
        batch = self.get_batch_by_id(batch_id) if batch_id else None
        if batch:
            batch_year = batch.get('year')
            if batch_year:
                year = batch_year
            prefix = self._get_prefix_from_name(
                batch.get('tour_type_name', 'HAJ'))

        # ---- 3. Pre-compute seat change ----
        seat_change = -1 if batch_id else 0
        new_batch_seats = None
        if batch and seat_change < 0:
            try:
                current = int(batch.get('available_seats', 0) or 0)
            except (ValueError, TypeError):
                current = 0
            if current < 1:
                raise ValueError(
                    "No seats available in this batch")
            new_batch_seats = current + seat_change

        # ---- 4. Build clean row ----
        traveler_data = dict(traveler_data)
        traveler_data['id'] = self._generate_id(
            prefix, 'TRV', str(year))
        traveler_data['registration_date'] = (
            datetime.now().isoformat())
        traveler_data.setdefault('status', 'Active')

        clean = {}
        for key in TRAVELER_COLUMNS:
            value = traveler_data.get(key, '')
            if value is None:
                clean[key] = ''
            elif isinstance(value, float) and pd.isna(value):
                clean[key] = ''
            else:
                clean[key] = str(value)

        # ---- 5. Snapshot for rollback ----
        prev_travelers = self.travelers.copy()
        prev_batches = self.batches.copy()

        # ---- 6. Apply in memory, save atomically (travelers first) ----
        try:
            new_traveler = pd.DataFrame([clean])
            self.travelers = pd.concat(
                [self.travelers, new_traveler], ignore_index=True)
            self._save_df(self.travelers, "travelers.csv")

            if batch_id and new_batch_seats is not None:
                self.batches.loc[
                    self.batches['id'] == batch_id,
                    'available_seats'] = new_batch_seats
                self._save_df(self.batches, "batches.csv")

            return clean['id']
        except Exception:
            # Restore in-memory state on any save failure
            self.travelers = prev_travelers
            self.batches = prev_batches
            raise

    # -----------------------------------------------------------------------------
    # 2.6.3 — update_traveler  (v4 — transactional)
    # -----------------------------------------------------------------------------
    def update_traveler(self, traveler_id, traveler_data):
        try:
            mask = (self.travelers['id'].astype(str)
                    == str(traveler_id))
            if not mask.any():
                print(f"[DB] update_traveler: {traveler_id} not found")
                return False

            old_row = self.travelers.loc[mask].iloc[0]
            old_batch = str(old_row.get('batch_id', '') or '').strip()

            # v4 — validate before mutating anything
            self._validate_traveler_data(
                traveler_data, is_update=True)
            if 'passport_no' in traveler_data:
                self._check_duplicate_passport(
                    traveler_data['passport_no'],
                    exclude_id=traveler_id)

            new_batch = str(
                traveler_data.get('batch_id', old_batch) or '').strip()

            # v4 — pre-compute seat deltas and validate capacity
            seat_updates = []  # list of (batch_id, new_seats)
            if old_batch != new_batch:
                if old_batch:
                    b = self.get_batch_by_id(old_batch)
                    if b is not None:
                        try:
                            cur = int(b.get('available_seats', 0) or 0)
                        except (ValueError, TypeError):
                            cur = 0
                        seat_updates.append((old_batch, cur + 1))
                if new_batch:
                    b = self.get_batch_by_id(new_batch)
                    if b is None:
                        raise ValueError(
                            f"Selected batch does not exist: {new_batch}")
                    try:
                        cur = int(b.get('available_seats', 0) or 0)
                    except (ValueError, TypeError):
                        cur = 0
                    if cur < 1:
                        raise ValueError(
                            "No seats available in this batch")
                    seat_updates.append((new_batch, cur - 1))

            # v4 — snapshot for rollback
            prev_travelers = self.travelers.copy()
            prev_batches = self.batches.copy()

            # Apply column updates
            valid_cols = set(self.travelers.columns)
            updated = 0
            for key, value in traveler_data.items():
                if key not in valid_cols:
                    continue
                try:
                    col_dtype = self.travelers[key].dtype
                    if pd.api.types.is_numeric_dtype(col_dtype):
                        if (value is None
                                or value == ""
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
                        elif (isinstance(value, float)
                              and pd.isna(value)):
                            value = ""
                        else:
                            value = str(value)
                    self.travelers.loc[mask, key] = value
                    updated += 1
                except (ValueError, TypeError) as e:
                    print(f"[DB] update_traveler: skip {key} -> {e}")
                    continue

            # Persist atomically
            try:
                self._save_df(self.travelers, "travelers.csv")
                for batch_id, new_seats in seat_updates:
                    self.batches.loc[
                        self.batches['id'] == batch_id,
                        'available_seats'] = new_seats
                if seat_updates:
                    self._save_df(self.batches, "batches.csv")
            except Exception:
                self.travelers = prev_travelers
                self.batches = prev_batches
                raise

            print(f"[DB] update_traveler: {traveler_id} "
                  f"({updated} fields)")
            return True
        except ValueError:
            raise
        except Exception as e:
            print(f"[DB] update_traveler failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    # -----------------------------------------------------------------------------
    # 2.6.4 — delete_traveler  (v4 — safe when ID missing)
    # -----------------------------------------------------------------------------
    def delete_traveler(self, traveler_id):
        mask = (self.travelers['id'].astype(str)
                == str(traveler_id))
        if not mask.any():
            raise ValueError(f"Traveler not found: {traveler_id}")

        traveler = self.travelers.loc[mask].iloc[0]
        batch_id = str(traveler.get('batch_id', '') or '').strip()

        prev_travelers = self.travelers.copy()
        prev_batches = self.batches.copy()

        new_batch_seats = None
        if batch_id:
            b = self.get_batch_by_id(batch_id)
            if b is not None:
                try:
                    cur = int(b.get('available_seats', 0) or 0)
                except (ValueError, TypeError):
                    cur = 0
                new_batch_seats = cur + 1

        try:
            self.travelers = self.travelers.loc[~mask].copy()
            self._save_df(self.travelers, "travelers.csv")

            if new_batch_seats is not None:
                self.batches.loc[
                    self.batches['id'] == batch_id,
                    'available_seats'] = new_batch_seats
                self._save_df(self.batches, "batches.csv")
            return True
        except Exception:
            self.travelers = prev_travelers
            self.batches = prev_batches
            raise

    # =================================================================================
    # 2.7 — BATCHES  (v4 — status normalization + safe seats)
    # =================================================================================
    def get_batches(self, status=None):
        if status:
            target = str(status).strip().lower()
            mask = (self.batches['status'].astype(str)
                    .str.strip().str.lower() == target)
            return self.batches[mask].to_dict('records')
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

    # -----------------------------------------------------------------------------
    # 2.7.1 — _update_batch_seats  (v4 — bounds + explicit failures)
    # -----------------------------------------------------------------------------
    def _update_batch_seats(self, batch_id, change):
        """
        Adjust available_seats.

        Raises ValueError if the batch is missing or the change would
        drive seats below zero — this is the correct behaviour for
        transactional callers who pre-validate capacity.
        """
        mask = self.batches['id'] == batch_id
        if not mask.any():
            raise ValueError(f"Batch not found: {batch_id}")

        current = self.batches.loc[mask, 'available_seats'].iloc[0]
        try:
            current = int(float(current))
        except (ValueError, TypeError):
            current = 0

        new_seats = current + int(change)
        if new_seats < 0:
            raise ValueError(
                f"Batch {batch_id} has only {current} seats available")

        self.batches.loc[mask, 'available_seats'] = new_seats
        self._save_df(self.batches, "batches.csv")

    # =================================================================================
    # 2.8 — PAYMENTS  (unchanged structurally; ID gen now safe)
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
                prefix = self._get_prefix_from_name(
                    batch.get('tour_type_name', 'HAJ'))
        payment_data['id'] = self._generate_id(
            prefix, 'PAY', str(year))
        payment_data['payment_date'] = (
            datetime.now().isoformat())
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
                print(f"[WARN] Payment {payment_id} not found")
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
                'notes': self._convert_to_string,
            }
            for field, converter in fields.items():
                if field in payment_data:
                    try:
                        updates[field] = converter(
                            payment_data[field])
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
                        print(f"[WARN] Could not update invoice "
                              f"{inv_id}: {e}")
            try:
                self.log_activity(
                    self._current_user_id,
                    "update_payment",
                    f"Updated payment {payment_id} - "
                    f"Amount: {updates.get('amount', 0):,.2f}")
            except Exception as log_ex:
                print(f"[DB] update_payment activity log "
                      f"failed: {log_ex}")
            return True
        except Exception as e:
            print(f"[ERROR] Error updating payment "
                  f"{payment_id}: {e}")
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
        if value is None:
            return ''
        return str(value).strip()

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
        receipts = self.receipts[
            self.receipts['payment_id'] == payment_id]
        if not receipts.empty:
            raise Exception(
                "Cannot delete payment with associated receipts")
        self.payments = self.payments[
            self.payments['id'] != payment_id]
        self._save_df(self.payments, "payments.csv")

    # =================================================================================
    # 2.10 — INVOICES  (unchanged structurally)
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
            discount_percentage = (
                (discount_amount / amount) * 100.0
                if amount > 0 else 0.0)
        else:
            discount_percentage = float(discount_percentage)
            discount_amount = (
                amount * (discount_percentage / 100.0))
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
            'due_date': (datetime.now()
                         + timedelta(days=30)).isoformat(),
            'status': 'pending',
            'notes': '',
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
            return math.floor(amount)
        return amount

    # =================================================================================
    # 2.11 — RECEIPTS
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
                prefix = self._get_prefix_from_name(
                    batch.get('tour_type_name', 'HAJ'))
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
            'notes': payment_data.get('notes', ''),
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
    # 2.12 — REPORTS  (v4 — status normalization)
    # =================================================================================
    def get_dashboard_summary(self):
        statuses = (self.batches['status'].astype(str)
                    .str.strip().str.lower())
        active_batches = int(statuses.isin(_ACTIVE_BATCH_STATUSES).sum())

        pending_inv = self.invoices['status'].astype(str).str.lower()
        return {
            'total_travelers': len(self.travelers),
            'active_batches': active_batches,
            'total_payments': (
                self.payments['amount'].sum()
                if not self.payments.empty else 0),
            'pending_payments': int(
                (pending_inv == 'pending').sum()),
            'available_seats': (
                self.batches['available_seats'].sum()
                if not self.batches.empty else 0),
            'total_receipts': len(self.receipts),
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
            'total_collected': (
                payments['amount'].sum()
                if not payments.empty else 0),
            'payment_count': (
                len(payments) if not payments.empty else 0),
            'by_method': (
                payments.groupby('payment_method')['amount']
                .sum().to_dict()
                if not payments.empty else {}),
            'average_payment': (
                payments['amount'].mean()
                if not payments.empty else 0),
        }

    # =================================================================================
    # 2.12.1 — BACKUP / RESTORE  (v4 — safe + consistent)
    # =================================================================================
    def create_backup(self):
        backup_id = self._generate_id('BAK', 'BUP', None)
        backup_date = datetime.now()
        backup_filename = (
            f"backup_{backup_date.strftime('%Y%m%d_%H%M%S')}.zip")
        backup_dir = self._backup_dir  # already created in _ensure_dirs
        backup_path = backup_dir / backup_filename

        with zipfile.ZipFile(backup_path, 'w',
                             zipfile.ZIP_DEFLATED) as zipf:
            for csv_file in self.data_dir.glob("*.csv"):
                zipf.write(csv_file, csv_file.name)

        backup_record = pd.DataFrame([{
            'id': backup_id,
            'backup_date': backup_date.isoformat(),
            'backup_file': str(backup_path),
            'size': os.path.getsize(backup_path),
            'status': 'success',
        }])
        self.backup_history = pd.concat(
            [self.backup_history, backup_record], ignore_index=True)
        self._save_df(self.backup_history, "backup_history.csv")
        print(f"[DB] Backup created: {backup_path}")
        return str(backup_path)

    @staticmethod
    def _safe_extract(zip_file, target_dir: Path):
        """Reject members whose extracted path escapes target_dir."""
        target = Path(target_dir).resolve()
        for member in zip_file.infolist():
            dest = (target / member.filename).resolve()
            if not str(dest).startswith(str(target) + os.sep):
                raise ValueError(
                    f"Unsafe path in backup archive: "
                    f"{member.filename}")
        zip_file.extractall(target)

    def restore_backup(self, backup_file):
        """Validate, stage, then swap data directory contents."""
        with zipfile.ZipFile(backup_file, 'r') as zipf:
            # 1. Validate archive members before touching live data
            self._safe_extract.__func__(zipf, self.data_dir)  # dry check
            # 2. Extract into a temp staging dir
            staging = Path(tempfile.mkdtemp(
                prefix=".restore_", dir=str(self.data_dir.parent)))
            try:
                zipf.extractall(staging)

                # 3. Validate required CSVs exist and contain headers
                for required in ("travelers.csv", "users.csv",
                                 "batches.csv"):
                    src = staging / required
                    if not src.exists():
                        raise ValueError(
                            f"Backup missing required file: "
                            f"{required}")
                    # Non-empty header check
                    with open(src, "r", encoding="utf-8") as f:
                        header = f.readline().strip()
                    if not header:
                        raise ValueError(
                            f"Backup file is empty: {required}")

                # 4. Snapshot current state, then replace
                safety_dir = (self._backup_dir
                              / f"pre_restore_"
                                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                safety_dir.mkdir(parents=True, exist_ok=True)
                for csv_file in self.data_dir.glob("*.csv"):
                    shutil_copy = safety_dir / csv_file.name
                    try:
                        os.replace(str(csv_file), str(shutil_copy))
                    except OSError:
                        # Fall back to copy on cross-device
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

        # 5. Reload in-memory state
        self.reload_all()

    # =================================================================================
    # 2.12.2 — ACTIVITY LOG
    # =================================================================================
    def log_activity(self, user_id, action, details=""):
        try:
            if not user_id:
                user_id = self._current_user_id or 'system'
            log_id = self._generate_id('LOG', 'ACT', None)
            log_entry = pd.DataFrame([{
                'id': log_id,
                'user_id': user_id,
                'action': action,
                'timestamp': datetime.now().isoformat(),
                'details': details,
            }])
            self.activity_log = pd.concat(
                [self.activity_log, log_entry], ignore_index=True)
            self._save_df(self.activity_log, "activity_log.csv")
        except Exception as e:
            print(f"[DB] log_activity failed: {e}")

    def get_activity_log(self, user_id=None, limit=100):
        logs = self.activity_log
        if user_id:
            logs = logs[logs['user_id'] == user_id]
        return (logs.sort_values('timestamp', ascending=False)
                .head(limit).to_dict('records'))

    # =================================================================================
    # 2.13 — CURRENT USER MANAGEMENT
    # =================================================================================
    def set_current_user(self, user_id):
        self._current_user_id = user_id

    def get_current_user_id(self):
        return self._current_user_id

    # =================================================================================
    # 2.14 — DATA MIGRATION
    # =================================================================================
    def migrate_batch_tour_types(self):
        pass

    # =================================================================================
    # 2.15 — RELOAD METHODS
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
        print(f"[DB] [OK] Reloaded: "
              f"{len(self.users)} users, "
              f"{len(self.travelers)} travelers, "
              f"{len(self.batches)} batches, "
              f"{len(self.payments)} payments, "
              f"{len(self.invoices)} invoices, "
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
    # 2.16 — FILE CHANGE DETECTION
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
        current_mtime = self._csv_mtime(filename)
        last_snapshot = self._csv_snapshots.get(filename, 0)
        return current_mtime > last_snapshot

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
# SECTION 2 END (FLET VERSION) — v4
# =================================================================================