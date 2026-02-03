# GCBDR Retention Tool

A CLI tool to extend the expiration date of Google Cloud Backup and DR (GCBDR) backups. This tool is designed to assist during ransomware recovery or legal hold scenarios by ensuring backups do not expire prematurely.

## Features

-   **Discovery**: Find backups by Project, Location, Vault, or Workload Type:
    -   `COMPUTE_ENGINE_INSTANCE` (VMs)
    -   `COMPUTE_ENGINE_DISK` (Persistent Disks)
    -   `CLOUD_SQL_INSTANCE` (Cloud SQL)
    -   `ALLOY_DB_CLUSTER` (AlloyDB)
    -   `FILESTORE_INSTANCE` (Filestore)
    -   `VMWARE_ENGINE_VM` (GCVE)
-   **Filtering**: 
    -   Select backups older than X days (`--filter-age-days`).
    -   Filter by name substring (`--filter-name`).
    -   Filter by labels (`--filter-labels key=value`).
-   **Extension**: Add days to existing expiration (`--add-expiration-days`) or set a specific date (`--set-new-expiration-date`).
-   **Safety First**:
    -   **Dry-Run by Default**: No changes applied unless `--execute` is specified.
    -   **Verbose Mode**: Prints the equivalent `curl` commands for audit or manual execution.

## Installation

1.  **Prerequisites**: Python 3.7+, `gcloud` installed and authenticated.
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Authentication**:
    Ensure you are authenticated with a user/service account that has `backupdr.backups.update` (or `backupdr.managementServers.manageExpiration`) permission.
    ```bash
    gcloud auth application-default login
    # For running generated 'gcloud curl' commands manually:
    gcloud auth login
    ```

## CLI Arguments

| Argument | Description |
| :--- | :--- |
| `--project` | **Required**. GCP Project ID to search. |
| `--location` | **Required**. Region (e.g., `asia-southeast1`) or `-` for all. |
| `--vault` | Filter by Vault Name substring. |
| `--workload-type` | Filter by `COMPUTE_ENGINE_INSTANCE`, `CLOUD_SQL_INSTANCE`, `ALLOY_DB_CLUSTER`, etc. |
| `--filter-age-days` | Include only backups created *more* than X days ago. |
| `--filter-name` | Include only backups where name contains substring. |
| `--filter-labels` | Space-separated `key=value` pairs. Matches ALL provided labels. |
| `--add-expiration-days` | Number of days to ADD to current expiration. |
| `--set-new-expiration-date` | New expiration date (YYYY-MM-DD). Sets time to 23:59:00. |
| `--execute` | Perform the actual update. |
| `--verbose` | Print `curl` commands. |
| `--gcloud` | Print `gcloud curl` commands. |

## Usage Examples

### 1. General Discovery (Dry-Run)
List all backups in `asia-southeast1` that are at least 1 day old.
```bash
python main.py \
  --project argo-svc-dev-3 \
  --location asia-southeast1 \
  --filter-age-days 1 \
  --add-expiration-days 30 \
  --verbose
```

### 2. Apply to VMs Only
Extend retention for **Compute Engine** backups only.
```bash
python main.py \
  --project argo-svc-dev-3 \
  --location asia-southeast1 \
  --workload-type COMPUTE_ENGINE_INSTANCE \
  --add-expiration-days 14 \
  --execute
```


### 3. Apply to CloudSQL Only
Extend retention for **Cloud SQL** backups only.
```bash
python main.py \
  --project argo-svc-dev-3 \
  --location asia-southeast1 \
  --workload-type CLOUD_SQL_INSTANCE \
  --add-expiration-days 14 \
  --execute
```

### 4. Apply to Persistent Disks Only
Extend retention for **Compute Engine Disk** backups only.
```bash
python main.py \
  --project argo-svc-dev-3 \
  --location asia-southeast1 \
  --workload-type COMPUTE_ENGINE_DISK \
  --add-expiration-days 14 \
  --execute
```

### 5. Apply to Filestore Only
Extend retention for **Filestore** backups only.
```bash
python main.py \
  --project argo-svc-dev-3 \
  --location asia-southeast1 \
  --workload-type FILESTORE_INSTANCE \
  --add-expiration-days 14 \
  --execute
```

### 6. Filter by Labels (e.g., "env=prod")
Apply only to backups that have specific labels.
```bash
python main.py \
  --project argo-svc-dev-3 \
  --location asia-southeast1 \
  --filter-labels env=prod dr=critical \
  --add-expiration-days 30 \
  --execute
```

### 7. Legal Hold (Specific Date)
Set all backups for a specific vault `my-vault` to expire on **December 31, 2030**.
```bash
python main.py \
  --project argo-svc-dev-3 \
  --location asia-southeast1 \
  --vault my-vault \
  --set-new-expiration-date 2030-12-31 \
  --execute
```

### 8. Verbose Output (Generate Commands)
Generate the `curl` commands to run manually later, without executing them now.
```bash
python main.py \
  --project argo-svc-dev-3 \
  --location asia-southeast1 \
  --add-expiration-days 7 \
  --verbose
```

### 9. Gcloud Output (Generate gcloud curl Commands)
Generate `gcloud curl` commands instead of raw `curl`.
```bash
python main.py \
  --project argo-svc-dev-3 \
  --location asia-southeast1 \
  --add-expiration-days 7 \
  --gcloud
```
