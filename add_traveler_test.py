# =================================================================================
# add_traveler_test.py — Add a test traveler directly to the CSV
# =================================================================================
# Usage (in Railway Shell):
#     cd /app
#     python add_traveler_test.py
#
# Optional: pass custom values as arguments:
#     python add_traveler_test.py "John" "Doe" "TEST99999"
# =================================================================================

import os
import sys
import json
from datetime import datetime

import pandas as pd

from core.helpers import get_app_base_path


# =================================================================================
# Config — edit these or pass as CLI args
# =================================================================================
FIRST_NAME = "PERSIST"
LAST_NAME  = "TEST"
PASSPORT   = "TEST12345"
MOBILE     = "9999999999"
EMAIL      = "test@example.com"
BATCH_ID   = ""       # leave blank to auto-pick first available batch
STATUS     = "Active"

# Override from CLI if provided
if len(sys.argv) >= 4:
    FIRST_NAME = sys.argv[1]
    LAST_NAME  = sys.argv[2]
    PASSPORT   = sys.argv[3]


# =================================================================================
# 1. Locate files
# =================================================================================
BASE = get_app_base_path()
DATA_DIR = os.path.join(BASE, "data")
TRAVELERS_CSV = os.path.join(DATA_DIR, "travelers.csv")
COUNTERS_JSON = os.path.join(DATA_DIR, "id_counters.json")

print(f"[add_traveler] Base: {BASE}")
print(f"[add_traveler] CSV : {TRAVELERS_CSV}")

if not os.path.exists(TRAVELERS_CSV):
    print(f"[add_traveler] ❌ travelers.csv not found at {TRAVELERS_CSV}")
    sys.exit(1)


# =================================================================================
# 2. Load CSV
# =================================================================================
df = pd.read_csv(TRAVELERS_CSV, dtype=str, keep_default_na=False)
print(f"[add_traveler] Loaded {len(df)} existing traveler(s)")

if "id" not in df.columns:
    print(f"[add_traveler] ❌ 'id' column missing in CSV")
    sys.exit(1)

# Columns present
print(f"[add_traveler] Columns: {list(df.columns)}")


# =================================================================================
# 3. Generate next ID
# =================================================================================
YEAR = datetime.now().year + 1     # tour year (e.g. 2027 if now 2026)
PREFIX = "HAJ"

# Auto-detect prefix from existing IDs (e.g. "HAJ/TRV/2027/002" → "HAJ")
existing_ids = df["id"].dropna().astype(str).tolist()
if existing_ids:
    sample = existing_ids[-1].split("/")
    if len(sample) >= 1 and sample[0]:
        PREFIX = sample[0]

# Find max sequence number for this prefix+year
max_seq = 0
pattern_start = f"{PREFIX}/TRV/{YEAR}/"
for eid in existing_ids:
    if eid.startswith(pattern_start):
        try:
            seq = int(eid.split("/")[-1])
            max_seq = max(max_seq, seq)
        except ValueError:
            pass

next_seq = max_seq + 1
new_id = f"{PREFIX}/TRV/{YEAR}/{next_seq:03d}"
print(f"[add_traveler] Next ID: {new_id}")


# =================================================================================
# 4. Pick a batch (if not specified)
# =================================================================================
if not BATCH_ID:
    batches_csv = os.path.join(DATA_DIR, "batches.csv")
    if os.path.exists(batches_csv):
        bdf = pd.read_csv(batches_csv, dtype=str, keep_default_na=False)
        if not bdf.empty and "id" in bdf.columns:
            BATCH_ID = str(bdf.iloc[0]["id"])
            print(f"[add_traveler] Auto-picked batch: {BATCH_ID}")


# =================================================================================
# 5. Build the new row
# =================================================================================
now = datetime.now().isoformat()

# Start with an empty row (all columns blank), then fill in what we know
new_row = {col: "" for col in df.columns}
new_row.update({
    "id": new_id,
    "first_name": FIRST_NAME,
    "last_name": LAST_NAME,
    "passport_name": f"{FIRST_NAME} {LAST_NAME}".upper(),
    "batch_id": BATCH_ID,
    "passport_no": PASSPORT,
    "mobile": MOBILE,
    "email": EMAIL,
    "status": STATUS,
    "registration_date": now,
    "gender": "",
    "dob": "",
    "vaccine_status": "Not Vaccinated",
})

print(f"[add_traveler] New row:")
for k, v in new_row.items():
    if v:
        print(f"    {k:<22} = {v}")


# =================================================================================
# 6. Append and save
# =================================================================================
new_df = pd.DataFrame([new_row], columns=df.columns)
df_out = pd.concat([df, new_df], ignore_index=True)

# Write to temp first (safer), then rename
temp_path = TRAVELERS_CSV + ".tmp"
df_out.to_csv(temp_path, index=False)
os.replace(temp_path, TRAVELERS_CSV)

print(f"\n[add_traveler] ✅ Appended. CSV now has {len(df_out)} rows")
print(f"[add_traveler] Saved to {TRAVELERS_CSV}")

size = os.path.getsize(TRAVELERS_CSV)
print(f"[add_traveler] File size: {size} bytes")


# =================================================================================
# 7. Verify
# =================================================================================
print("\n[add_traveler] Verification — last row of CSV:")
print("─" * 70)
with open(TRAVELERS_CSV, "r", encoding="utf-8") as f:
    lines = f.readlines()
    print(f"  {lines[0].strip()}")
    print(f"  {lines[-1].strip()}")
print("─" * 70)

print("\n[add_traveler] Done. Reload the app to see the new traveler.")