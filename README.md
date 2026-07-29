# GCBDR Retention Tool

A CLI tool to discover and batch-extend the expiration date and immutability locks of Google Cloud Backup and DR (GCBDR) backups. This tool is designed to assist during ransomware recovery, compliance audits, or legal hold scenarios by ensuring critical backups do not expire and cannot be deleted prematurely.

---

## Key Features

- **Backups Discovery**: Automatically scans and maps backup data sources across your vaults, supporting GCP resource types like VMs, Persistent Disks, Cloud SQL, AlloyDB, Filestore, and VMware Engine VMs.
- **Advanced Filtering**:
  - Filter by age, name substrings, or arbitrary label pairs (e.g., `env=prod`).
  - Filter by **Immutability Lock status** (only process locked `🔒` or unlocked `🔓` backups).
- **Expiration & Immutability Lock Extensions**:
  - Add relative expiration days (`--add-expiration-days`) or set absolute dates (`--set-new-expiration-date`).
  - Modify the enforced retention end time (WORM/immutability lock) to align with expiration (`--sync-enforced-retention`), add relative days (`--add-enforced-retention-days`), or set target dates (`--set-new-enforced-retention-date`).
- **Auditor Compliance Reporting**:
  - Compile highly-styled, dark-themed HTML audit logs grouped by **Vault** or **Workload type**.
  - Includes distribution charts, padlock lock-state badges, metadata summaries, and full API resource identifiers.
- **Fail-Safe & Resilient Execution**:
  - **Dry-run by default** to preview changes without making live API modifications.
  - **State Caching (Auto-Resume)**: In case of network interruption or rate limits, the tool caches progress and skips already-updated backups on successive runs.
  - **Exponential Backoff**: Automatic retries for rate limits (HTTP 429) or transient server errors.

---

## Installation

### 1. Prerequisites
- Python 3.8+
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed and authenticated.

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Authentication Setup
Ensure your local `gcloud` active account has permissions to update GCBDR backups (`backupdr.backups.update` or standard Backup & DR Admin/Operator roles).

The tool automatically retrieves active credentials from your active `gcloud` login session. You do not need to configure complex service accounts or environment variables:
```bash
# Log in to your active developer/admin profile
gcloud auth login
```

---

## CLI Options

| Argument | Category | Description | Default |
| :--- | :--- | :--- | :--- |
| **Selection & Discovery** | | | |
| `--project` | Required | GCP Project ID containing the backups. | |
| `--location` | Required | region (e.g., `asia-southeast1`) or `-` for all regions. | |
| `--vault` | Optional | Filter backups belonging to vaults containing this substring. | |
| `--workload-type` | Optional | Filter by workload type (e.g., `COMPUTE_ENGINE_INSTANCE`, `CLOUD_SQL_INSTANCE`). | |
| **Filters** | | | |
| `--filter-age-days` | Optional | Select backups created *more* than X days ago. | `0` |
| `--filter-name` | Optional | Select backups whose name matches this substring. | |
| `--filter-labels` | Optional | Filter by space-separated `key=value` labels (e.g. `env=prod`). | |
| `--filter-locked` | Optional | **Immutability Filter**: Only process backups with active future locks. | |
| `--filter-unlocked` | Optional | **Immutability Filter**: Only process backups without active locks. | |
| **Expiration Override** | | (Mutually Exclusive) | |
| `--add-expiration-days` | Action | Number of days to add to the current expiration date. | |
| `--set-new-expiration-date` | Action | New expiration date (YYYY-MM-DD) set to EOD `23:59:00`. | |
| **Immutability Override** | | (Mutually Exclusive) | |
| `--sync-enforced-retention` | Immutability | Sync the enforced retention lock date with the new expiration date. | |
| `--add-enforced-retention-days`| Immutability | Add X days to the current enforced retention lock date. | |
| `--set-new-enforced-retention-date`| Immutability| Set a specific target enforced retention lock date (YYYY-MM-DD).| |
| **Reporting & Exec** | | | |
| `--dry-run` | Execution | Preview actions without executing (active by default). | `True` |
| `--execute` | Execution | **Execute changes**. MUST be specified to apply modifications. | `False` |
| `--verbose` | Debugging | Print raw equivalent `curl` API requests for each backup. | `False` |
| `--gcloud` | Debugging | Print wrapper `gcloud curl` equivalent commands. | `False` |
| `--state-file` | Execution | File path to write/read progress checkpoint caches. | `.gcbdr_retention_state.json` |
| `--report` | Reporting | Generates an auditor-friendly HTML compliance report. | `False` |
| `--report-group-by` | Reporting | Group report tables and charts by `vault` or `workload`. | `vault` |
| `--report-file` | Reporting | Output file path/name for the HTML report. | `retention_report.html` |

---

## Detailed Usage Examples

### 1. General Dry-Run & Discovery (Safe Preview)
Search for backups in a vault and preview the proposed expiration dates without applying changes.
```bash
python main.py \
  --project argo-svc-gcbdr \
  --location asia-southeast1 \
  --vault ase1-dbs-bv-1 \
  --add-expiration-days 30
```

### 2. Lock-down Compliance Audit (Immutability Lock + Reporting)
Locate all **unlocked** backups, sync their immutability lock dates to match the new expiration dates (extending by 30 days), and compile a vault-grouped compliance report:
```bash
python main.py \
  --project argo-svc-gcbdr \
  --location asia-southeast1 \
  --filter-unlocked \
  --add-expiration-days 30 \
  --sync-enforced-retention \
  --report \
  --report-group-by vault \
  --report-file vault_compliance_report.html \
  --execute
```

### 3. Exclude Locked Backups & Group by Workload
Extend expiration for only the **unlocked** backups and generate a workload-type grouped HTML report:
```bash
python main.py \
  --project argo-svc-gcbdr \
  --location - \
  --filter-unlocked \
  --add-expiration-days 60 \
  --report \
  --report-group-by workload \
  --report-file workload_report.html \
  --execute
```

### 4. Legal Hold Override (Specific Target Date)
Set a specific target expiration date and sync enforced retention lock (WORM protection) for production workloads:
```bash
python main.py \
  --project argo-svc-gcbdr \
  --location asia-southeast1 \
  --filter-labels env=prod \
  --set-new-expiration-date 2030-12-31 \
  --sync-enforced-retention \
  --report \
  --execute
```

### 5. Resuming Execution after Interruptions
If a large run updating hundreds of backups is interrupted by network outages, the progress is saved to `.gcbdr_retention_state.json`. 

Simply run the exact same command to resume where it left off, avoiding unnecessary API calls and duplicate changes:
```bash
# Re-run after an error or interruption
python main.py \
  --project argo-svc-gcbdr \
  --location asia-southeast1 \
  --add-expiration-days 30 \
  --sync-enforced-retention \
  --execute
```
*(The tool will print: `[INFO] Loaded resume state file... Found X already completed updates. Skipping.`)*

---

## Understanding Audit Reports

The generated HTML report includes the following visual elements:
- **Expiration Policy Panel**: Displays the selected extension period up top.
- **Immutability Lock Panel**: Displays the selected immutability policy up top.
- **Immutability Badges**: Padlock states indicate whether a backup is locked (`🔒 Locked`) or unlocked (`🔓 Unlocked`).
- **Vault Status Alerts**: Color-coded banners displaying the safety summary for each vault:
  - `🔒 X Locked (All Protected)` (Green banner if all backups are immutably locked).
  - `⚠️ X Locked / Y Unlocked` (Yellow banner if there is mixed safety).
  - `🔓 X Unlocked (No Deletion Protection)` (Red banner if backups lack active deletion locks).

