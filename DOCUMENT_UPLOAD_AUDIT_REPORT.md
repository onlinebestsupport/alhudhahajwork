Alhudha Haj Travel System — Maintenance and Testing Guide

This is the single maintenance reference for future updates to the Alhudha Haj Travel System.

The safe order is:

1.
Back up production data.

2.
Update the code locally.

3.
Run the local checks below.

4.
Review the changed files.

5.
Commit and push to GitHub.

6.
Check Railway deployment logs.

7.
Run System Tests → Run All Tests in the admin application.

The commands below do not delete traveler, payment, invoice, receipt, batch, or document data.




1. Open the project on Windows

Open Command Prompt and run:

Plain Text


cd /d C:\Users\Masood\Desktop\FLET_HAJ



Confirm that the expected files exist:

Plain Text


dir main.py
dir database.py
dir core\system_test_tab.py
dir data



The production application files should remain in lowercase folders:

Plain Text


core/
data/
data/backups/
documents/
flet_assets/
logos/
seed_data/
static/
tools/






2. Make a safe local backup before editing

Create a Git checkpoint first:

Plain Text


git status
git add .
git commit -m "Checkpoint before maintenance"



If there are important uncommitted changes, do not continue until they are reviewed.

For production business data, use the application itself:

Plain Text


Admin → Backup → Create Backup



Do not manually delete or replace these production files:

Plain Text


data/travelers.csv
data/payments.csv
data/invoices.csv
data/receipts.csv
data/batches.csv
data/users.csv
data/documents/
data/backups/






3. Update a test or application file

Example: updating the System Test Center file:

Plain Text


notepad core\system_test_tab.py



Or copy the corrected file into the project folder, then check the change:

Plain Text


git diff -- core\system_test_tab.py
git diff --check



Always review the diff before committing:

Plain Text


git diff --stat
git diff



Do not commit generated runtime files such as live exports, logs, temporary files, or production backup ZIP files.




4. Compile every Python file

Run this after every Python edit:

Plain Text


python -m compileall -q .



A successful run returns to the prompt without an error message.

For a more explicit check:

Plain Text


python -c "import pathlib, py_compile; files=list(pathlib.Path('.').rglob('*.py')); [py_compile.compile(str(f), doraise=True) for f in files if '__pycache__' not in f.parts]; print(f'Compiled {len(files)} Python files successfully')"



If compilation fails, fix the displayed filename and line number before pushing.




5. Run local project checks

Run the project's available tests if a test folder exists:

Plain Text


python -m unittest discover -v



If the project uses pytest and it is installed:

Plain Text


python -m pytest -q



Run the static checks that do not change business data:

Plain Text


git diff --check
python -m compileall -q .



If the local environment has all dependencies installed, perform an import check:

Plain Text


python -c "import main; print('main import OK')"



If this import check reports a missing package, install the packages from the project requirements file in the virtual environment. Do not change production data to fix a local dependency error.




6. Verify the System Test Center source

Confirm that the current System Test Center includes the maintenance controls:

Plain Text


grep -n "Refresh Status" core\system_test_tab.py
grep -n "Reset CSV History" core\system_test_tab.py
grep -n "Runtime storage and exports" core\system_test_tab.py



On Windows Command Prompt, if grep is unavailable, use:

Plain Text


findstr /n /c:"Refresh Status" core\system_test_tab.py
findstr /n /c:"Reset CSV History" core\system_test_tab.py
findstr /n /c:"Runtime storage and exports" core\system_test_tab.py



The latest System Test Center should show a version line similar to:

Plain Text


[SYSTEM-TEST] loaded version=2026-11-02-r13-reset-refresh-storage-check



Run the web application and use:

Plain Text


Admin → System Tests → Run All Tests



The progress line should move from 0% to 100%. Use Clear Screen to reset only the visible state. Use Refresh Status to load the saved latest run again. Use Reset CSV History only when old diagnostic history should be cleared.




7. Check System Test CSV history on Railway

The diagnostic files are stored at:

Plain Text


/app/data/system_tests/system_test_history.csv
/app/data/system_tests/system_error_events.csv



To check recent failures without modifying anything:

Bash


tail -n 200 /app/data/system_tests/system_test_history.csv | grep ',FAIL,' || true



To check warnings:

Bash


tail -n 200 /app/data/system_tests/system_test_history.csv | grep ',WARN,' || true



A more reliable CSV-aware check is:

Bash


python3 - <<'PY'
import csv
from pathlib import Path
path = Path('/app/data/system_tests/system_test_history.csv')
if not path.exists():
    print('No diagnostic history file found')
else:
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    failures = [r for r in rows if r.get('level') == 'FAIL']
    warnings = [r for r in rows if r.get('level') == 'WARN']
    print(f'Runs recorded: {len({r.get("run_id") for r in rows if r.get("run_id")})}')
    print(f'Failures: {len(failures)}')
    print(f'Warnings: {len(warnings)}')
    for row in (failures + warnings)[-10:]:
        print(row.get('level'), row.get('title'), '-', row.get('message'))
PY



Never edit the business CSV files while troubleshooting diagnostic history.




8. Check Railway application logs

In the Railway Console, use bounded output instead of reading an endless process stream:

Bash


tail -n 200 /proc/1/fd/2



Bash


tail -n 200 /proc/1/fd/1



Healthy startup should include messages similar to:

Plain Text


[DB] [OK] Write test passed
[DB] Database loaded successfully
[BOOT] Security headers middleware registered
[BOOT] Traveler portal endpoints registered
[BOOT] Mounted Flet admin at /admin
INFO: Application startup complete.
WebSocket /admin/ws [accepted]



Investigate these messages if they appear:

Plain Text


Traceback
ERROR
Exception
Database loaded failed
Application startup failed
WebSocket ... failed



Messages such as No session — showing login are normal when the browser is not logged in. A repeated complete startup block usually means Railway restarted or replaced the process; check timestamps and deployment history before changing code.




9. Railway CLI commands

Install the CLI once:

Plain Text


npm i -g @railway/cli



Log in and link the project:

Plain Text


railway login
railway link



View live logs:

Plain Text


railway logs



View a bounded recent log window:

Plain Text


railway logs --lines 100



Stop the live log stream with Ctrl+C. These commands read logs; they do not modify business data.




10. Push the verified update to GitHub

Only run these after the local checks pass:

Plain Text


git status
git diff --check
git add .
git commit -m "Update System Test Center maintenance checks"
git push origin main



After pushing, wait for Railway to finish deploying. Then check the Railway logs and open the website.

Confirm the deployed source version in the Railway logs:

Plain Text


[SYSTEM-TEST] loaded version=2026-11-02-r13-reset-refresh-storage-check



If Railway still reports an older version such as r12, the latest core/system_test_tab.py was not included in the Git commit or the deployment has not completed.




11. Safe rollback

View recent commits:

Plain Text


git log --oneline -10



Undo a bad commit with a new revert commit:

Plain Text


git revert <bad-commit-id>
git push origin main



Do not use git reset --hard on the production branch unless the repository and data impact are fully understood. A revert is safer because it preserves the history.




12. Daily and weekly checklist

Frequency
Action
Daily
Check Railway startup and error logs
Daily
Confirm /healthz responds successfully
Daily
Review recent FAIL diagnostic results
Weekly
Review WARN diagnostic results
Weekly
Open Admin → System Tests → Run All Tests
Weekly
Create a production backup from Admin → Backup
Before every push
Run python -m compileall -q .
Before every push
Run git diff --check
Before every push
Review git diff and confirm business CSVs were not modified
After every push
Confirm Railway deployed the new System Test Center version







Important safety rules

•
Do not delete or reset travelers.csv, payments.csv, invoices.csv, receipts.csv, batches.csv, or users.csv to fix a diagnostic warning.

•
Do not permanently delete files from data/ unless they are verified backups, documents, or unwanted runtime artifacts.

•
Use the System Test Center quarantine workflow before deleting project files.

•
Use Reset CSV History only for diagnostic history. It does not repair application errors and does not change business data.

•
A warning is not automatically a failure. Read the test's simple explanation, technical details, responsible file, and recommended action.




13. Current System Test findings from the latest run

The latest pasted run ID was 20261103160309379942. These findings are maintenance items to review; this section does not authorize automatic deletion or data correction.

A. Complete folder file inventory warning

The inventory listed protected application folders and two root-level review candidates:

Plain Text


FLET_HAJ_CHANGELOG.md
LAYOUT_PLAN.txt



The report also showed the expected folders and protected files under .gitignore, core, data, documents, flet_assets, logos, seed_data, static, and tools.

A file shown as unused is only a review suggestion. Open the file and confirm it is not needed before using the System Test Center quarantine workflow. Never delete business CSVs, uploaded documents, backups, or production configuration merely because they are old or not referenced by a static scan.

To review root files locally:

Plain Text


dir /a
 type FLET_HAJ_CHANGELOG.md
 type LAYOUT_PLAN.txt



If either file is useful documentation, keep it. If it is confirmed unnecessary, move it through System Tests → File cleanup candidates → Move Selected to Delete Folder first. Permanent deletion is a separate action.

B. Receipt/payment amount mismatch

The latest run reported:

Plain Text


92 receipt rows
92 linked payments
92 payment rows
2 completed payments
1 receipt amount differs from payment amount



This is a data-reconciliation finding, not a reason to delete all receipts. First identify the exact receipt and payment IDs. Run the System Test Center receipt reconciliation check and record the displayed mismatch details. Then compare the matching rows in the Payments and Receipts tabs.

The safe manual decision is:

1.
Find the receipt ID and payment ID reported by the test.

2.
Compare receipt amount, payment amount, traveler, date, and payment status.

3.
Decide which value is supported by the original payment proof.

4.
Create a backup before correcting a business record.

5.
Correct only the single confirmed record through the application UI.

6.
Run receipt reconciliation again.

Do not edit payments.csv or receipts.csv directly while the application is running. Do not delete a receipt merely because its payment is linked. The payment and receipt are separate records and must be reconciled deliberately.

C. Document upload persistence check failed in deployment

The latest run reported these missing items:

Plain Text


database.py locked method
signature validation
DOCUMENT_UPLOAD_AUDIT_REPORT.md reference



This means the deployed Railway project does not contain the same source/report files as the verified working copy, or Railway is still running an older commit. It does not mean that traveler or payment data should be changed.

Before deployment, confirm these files are present in the GitHub working copy:

Plain Text


dir core\database.py
dir core\security.py
dir main.py
dir DOCUMENT_UPLOAD_AUDIT_REPORT.md
findstr /n /c:"update_traveler_document_path" core\database.py
findstr /n /c:"validate_document_content" core\security.py
findstr /n /c:"update_traveler_document_path" main.py



Then commit the source and reference file together:

Plain Text


git add main.py core\database.py core\security.py DOCUMENT_UPLOAD_AUDIT_REPORT.md
python -m compileall -q .
git diff --check
git commit -m "Keep document upload audit reference with deployed source"
git push origin main



After Railway deploys, run the System Test Center again. If the check still fails, inspect the deployed commit and logs before changing any data.




14. Known System Test Center limitations and future options

These are recorded for future maintenance. They are not automatically enabled by this guide.

Slow source and UI scan

check_source and check_ui_wiring can become slow if they scan a virtual environment, cache, or other large directory. If a run reaches the timeout, record the named check and inspect whether .venv, venv, env, .flet, __pycache__, node_modules, static/downloads, or data is being scanned. The future code improvement is to add a bounded _should_scan() filter and skip runtime/cache directories while retaining project source files.

Do not repeatedly press Run All Tests while a scan is running. Use the progress bar and wait for the current run to finish.

Test buttons can be clicked more than once

The current maintenance concern is that test buttons may remain clickable while a test is running. If the progress bar moves backward or two runs overlap, record the time and run ID. The future UI improvement is to disable all Run buttons and the Run All button at the beginning of a run, then re-enable them in a finally block after completion or failure.

This is a UI behavior issue; it does not justify restarting the database or deleting diagnostic CSV files.

HSTS check

An HSTS check may be added in a future System Test Center revision. Until then, verify the live header manually from a machine with curl:

Bash


curl -sSI https://alhudhahaj.work/ | grep -i strict-transport-security



A good result contains a header similar to:

Plain Text


strict-transport-security: max-age=31536000; includeSubDomains



Do not enable HSTS before confirming every required production subdomain is HTTPS-ready, because browsers may enforce HTTPS for the declared period.

Mobile responsiveness check

Until a dedicated automated mobile test is added, manually open the homepage, traveler portal, document-upload page, and admin login at a narrow mobile viewport. Verify that buttons, text fields, navigation, alerts, and tables remain usable without horizontal overflow. Do not submit an upload or business transaction during this visual check.

Optional future r2 scope

A future application-code revision may combine these three improvements:

1.
_should_scan() exclusions and a bounded scan timeout.

2.
Run-button disabling during active tests.

3.
HSTS and mobile responsiveness diagnostics.

This maintenance file records the requested scope only. It does not claim that those three features are currently implemented.




15. Correct response to a System Test failure

When the System Test Center creates a copy-ready issue report, keep the complete text including the run ID, test name, simple explanation, technical details, responsible file, and recommended action. Paste that complete message into the maintenance record or developer support request.

Use this order:

Plain Text


1. Do not delete business data.
2. Identify whether the result is a source issue, deployment issue, data mismatch, or optional warning.
3. Back up production data if a business record may need correction.
4. Run the smallest read-only diagnostic first.
5. Change only the responsible source file or confirmed record.
6. Compile and test locally.
7. Push the verified change.
8. Run the System Test Center again and compare the new run ID.



The maintenance file is the reference for future testing. Application-code changes should be made only when you explicitly request an implementation revision.

