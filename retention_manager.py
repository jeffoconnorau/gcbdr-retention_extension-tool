import logging
from datetime import datetime, timedelta, timezone
from dateutil import parser
from google.cloud import backupdr_v1
from google.api_core import client_options
from tabulate import tabulate
import json
import re
import os
import subprocess
import time
from google.api_core.exceptions import GoogleAPICallError
from google.oauth2.credentials import Credentials
from report_generator import ReportGenerator

BACKUP_NAME_REGEX = re.compile(
    r"^projects/[^/]+/locations/[^/]+/backupVaults/(?P<vault>[^/]+)/dataSources/(?P<datasource>[^/]+)/backups/(?P<backup>[^/]+)$"
)

class RetentionManager:
    def __init__(self, project_id, location, verbose=False, gcloud_verbose=False, dry_run=True):
        self.project_id = project_id
        self.location = location
        self.verbose = verbose
        self.gcloud_verbose = gcloud_verbose
        self.dry_run = dry_run
        self.logger = logging.getLogger(__name__)
        
        # Determine executor
        self.executor = "Unknown"
        env = os.environ.copy()
        env["CLOUDSDK_PYTHON"] = "python3"
        try:
            self.executor = subprocess.run(
                ["gcloud", "config", "get-value", "core/account"],
                capture_output=True,
                text=True,
                check=True,
                env=env
            ).stdout.strip()
        except Exception:
            pass

        # Initialize BackupDR Client using active token or fallback to ADC
        credentials = None
        try:
            token = subprocess.run(
                ["gcloud", "auth", "print-access-token"],
                capture_output=True,
                text=True,
                check=True,
                env=env
            ).stdout.strip()
            credentials = Credentials(token)
            self.logger.info(f"Authenticated using active gcloud account: {self.executor}")
        except Exception as e:
            self.logger.warning(f"Could not load active gcloud credentials token ({e}). Falling back to Application Default Credentials.")

        self.client = backupdr_v1.BackupDRClient(credentials=credentials)

    def list_backups(self, vault_filter=None, workload_type_filter=None, age_days_filter=0, name_filter=None, label_filter=None, filter_locked=None, filter_unlocked=None):
        """
        Enumerates backups across vaults in the specified project and location.
        Note: The API structure is Project -> Location -> BackupVault -> DataSource -> Backup.
        Listing all backups directly might require listing vaults first.
        """
        backups = []
        
        # 1. List Vaults
        parent = f"projects/{self.project_id}/locations/{self.location}"
        
        # Workload Type Map (Friendly Name -> API Substring)
        WORKLOAD_TYPE_MAP = {
            "COMPUTE_ENGINE_INSTANCE": "compute.googleapis.com/Instance",
            "COMPUTE_ENGINE_DISK": "compute.googleapis.com/Disk",
            "CLOUD_SQL_INSTANCE": "sqladmin.googleapis.com/Instance",
            "ALLOY_DB_CLUSTER": "alloydb.googleapis.com/Cluster",
            "FILESTORE_INSTANCE": "file.googleapis.com/Instance"
        }

        try:
            request = backupdr_v1.ListBackupVaultsRequest(parent=parent)
            vaults = self.client.list_backup_vaults(request=request)
            
            for vault in vaults:
                if vault_filter and vault_filter not in vault.name:
                    continue
                
                # 2. List DataSources in Vault
                ds_request = backupdr_v1.ListDataSourcesRequest(parent=vault.name)
                data_sources = self.client.list_data_sources(request=ds_request)
                
                for ds in data_sources:
                    ds_type = "Unknown"
                    if hasattr(ds, 'data_source_gcp_resource') and hasattr(ds.data_source_gcp_resource, 'type'):
                        ds_type = ds.data_source_gcp_resource.type

                    # Filter by Workload Type
                    if workload_type_filter:
                        # Normalize to map value if possible, else use raw input
                        target_type = WORKLOAD_TYPE_MAP.get(workload_type_filter, workload_type_filter)
                        
                        # Check GCP Resource Type
                        if target_type not in ds_type:
                            continue

                    # 3. List Backups in DataSource
                    backup_request = backupdr_v1.ListBackupsRequest(parent=ds.name)
                    ds_backups = self.client.list_backups(request=backup_request)
                    for backup in ds_backups:
                        # Client side filtering for now for flexibility
                        if self._matches_criteria(backup, age_days_filter, name_filter, label_filter, filter_locked, filter_unlocked):
                            backups.append(self._proto_to_dict(backup, ds_type))
                            
        except Exception as e:
            self.logger.error(f"Error listing backups: {e}")
            
        return backups

    def _matches_criteria(self, backup, age_days_filter, name_filter, label_filter, filter_locked=None, filter_unlocked=None):
        if age_days_filter > 0:
            create_time = backup.create_time
            if not create_time:
                return False
            age = datetime.now(create_time.tzinfo) - create_time
            if age.days < age_days_filter:
                return False
        
        if name_filter:
            if name_filter not in backup.name:
                return False

        if label_filter:
            # backup.labels is a MutableMapping (dict-like)
            # label_filter is assumed to be a dict or list of "key=value" strings
            # If API doesn't return labels, we can't filter, so return False if labels required
            if not backup.labels:
                 return False
            
            for key, value in label_filter.items():
                if backup.labels.get(key) != value:
                    return False
                    
        # Immutability/Lock status filtering
        if filter_locked or filter_unlocked:
            is_locked = False
            if hasattr(backup, 'enforced_retention_end_time') and backup.enforced_retention_end_time:
                try:
                    if backup.enforced_retention_end_time > datetime.now(timezone.utc):
                        is_locked = True
                except Exception:
                    pass
            if filter_locked and not is_locked:
                return False
            if filter_unlocked and is_locked:
                return False

        return True

    def _proto_to_dict(self, backup, ds_type="Unknown"):
        match = BACKUP_NAME_REGEX.match(backup.name)
        vault_id = match.group("vault") if match else "Unknown"
        datasource_id = match.group("datasource") if match else "Unknown"
        backup_id = match.group("backup") if match else "Unknown"
        
        # Friendly Workload Types
        FRIENDLY_WORKLOAD_TYPES = {
            "compute.googleapis.com/Instance": "Compute VM",
            "compute.googleapis.com/Disk": "Persistent Disk",
            "sqladmin.googleapis.com/Instance": "Cloud SQL",
            "alloydb.googleapis.com/Cluster": "AlloyDB Cluster",
            "file.googleapis.com/Instance": "Filestore Share",
            "vmwareengine.googleapis.com/VirtualMachine": "VMware Engine VM"
        }
        friendly_type = FRIENDLY_WORKLOAD_TYPES.get(ds_type, ds_type or "Unknown/Custom")
        
        enforced_retention = None
        is_locked = False
        if hasattr(backup, 'enforced_retention_end_time') and backup.enforced_retention_end_time:
            enforced_retention = backup.enforced_retention_end_time.isoformat()
            try:
                dt_enforced = parser.parse(enforced_retention)
                if dt_enforced > datetime.now(timezone.utc):
                    is_locked = True
            except Exception:
                pass

        return {
            'name': backup.name,
            'backup_id': backup_id,
            'vault_id': vault_id,
            'datasource_id': datasource_id,
            'workload_type': friendly_type,
            'expireTime': backup.expire_time.isoformat() if backup.expire_time else None,
            'createTime': backup.create_time.isoformat() if backup.create_time else None,
            'enforced_retention_end_time': enforced_retention,
            'is_locked': is_locked,
            'state': backup.state.name
        }

    def calculate_new_expiration(self, current_expire_str, add_days=None, set_date=None):
        current_expire = parser.parse(current_expire_str)
        
        if set_date:
            target_date = datetime.strptime(set_date, "%Y-%m-%d").date()
            new_expire = current_expire.replace(
                year=target_date.year, 
                month=target_date.month, 
                day=target_date.day,
                hour=23,
                minute=59,
                second=0,
                microsecond=0
            )
        elif add_days:
            new_expire = current_expire + timedelta(days=add_days)
        else:
            return current_expire_str
            
        return new_expire.isoformat()

    def calculate_new_enforced_retention(self, current_enforced_str, new_expire_str, add_days=None, set_date=None, sync_retention=False):
        if sync_retention:
            return new_expire_str
            
        if not current_enforced_str:
            # If no lock set, set a new lock starting from current time
            current_enforced = datetime.now(timezone.utc)
        else:
            current_enforced = parser.parse(current_enforced_str)
            
        if set_date:
            target_date = datetime.strptime(set_date, "%Y-%m-%d").date()
            new_enforced = current_enforced.replace(
                year=target_date.year, 
                month=target_date.month, 
                day=target_date.day,
                hour=23,
                minute=59,
                second=0,
                microsecond=0
            )
        elif add_days:
            new_enforced = current_enforced + timedelta(days=add_days)
        else:
            return current_enforced_str
            
        # Enforce rule: enforced_retention <= new_expire
        new_expire = parser.parse(new_expire_str)
        if new_enforced > new_expire:
            self.logger.warning(
                f"Requested enforced retention lock ({new_enforced.isoformat()}) exceeds new expiration date ({new_expire_str}). "
                f"Capping enforced retention lock to expiration date."
            )
            return new_expire_str
            
        return new_enforced.isoformat()

    def _execute_api_call_with_retry(self, func, *args, **kwargs):
        max_retries = 5
        base_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except GoogleAPICallError as e:
                is_retryable = False
                if e.code in [429, 500, 503, 504]:
                    is_retryable = True
                    
                if not is_retryable or attempt == max_retries - 1:
                    raise e
                    
                delay = base_delay * (2 ** attempt)
                self.logger.warning(f"API call failed with retryable error: {e}. Retrying attempt {attempt+1}/{max_retries} in {delay:.1f}s...")
                time.sleep(delay)

    def load_state(self, state_file_path, action_desc):
        if not state_file_path or not os.path.exists(state_file_path):
            return set()
            
        try:
            with open(state_file_path, "r") as f:
                state = json.load(f)
                
            if (state.get("project_id") == self.project_id and 
                state.get("location") == self.location and 
                state.get("action") == action_desc):
                completed = set(state.get("completed_updates", []))
                self.logger.info(f"Loaded resume state file from {state_file_path}. Found {len(completed)} already completed updates.")
                return completed
            else:
                self.logger.warning(f"State file {state_file_path} doesn't match current project/location/action. Starting fresh.")
        except Exception as e:
            self.logger.error(f"Failed to load state file {state_file_path}: {e}")
            
        return set()
        
    def save_state(self, state_file_path, action_desc, completed_set):
        if not state_file_path:
            return
        try:
            state = {
                "project_id": self.project_id,
                "location": self.location,
                "action": action_desc,
                "completed_updates": list(completed_set)
            }
            with open(state_file_path, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to write state file: {e}")
            
    def delete_state(self, state_file_path):
        if state_file_path and os.path.exists(state_file_path):
            try:
                os.remove(state_file_path)
                self.logger.info(f"Cleaned up state file {state_file_path}")
            except Exception as e:
                self.logger.error(f"Failed to delete state file {state_file_path}: {e}")

    def process_updates(self, updates, generate_report=False, group_by="vault", report_file="retention_report.html", state_file=None, action_desc="", extension_action="N/A", lock_action="None"):
        table_data = []
        report_updates = []
        
        # Load completed backups from state file
        completed_backups = self.load_state(state_file, action_desc)
        
        for update in updates:
            backup_name = update['backup']['name']
            current = update['current_expire']
            new = update['new_expire']
            current_enforced = update.get('current_enforced')
            new_enforced = update.get('new_enforced')
            
            table_row = [
                backup_name.split('/')[-1],
                current,
                new,
                current_enforced or "None",
                new_enforced or "None"
            ]
            
            status = "DRY_RUN"
            if backup_name in completed_backups:
                status = "SUCCESS" if not self.dry_run else "DRY_RUN"
                table_row.append("SKIPPED (Done)")
                table_data.append(table_row)
            else:
                if self.verbose:
                    print(f"\n[VERBOSE] curl Command for {backup_name}:")
                    print(self._generate_curl_command(backup_name, new, new_enforced))

                if self.gcloud_verbose:
                    print(f"\n[GCLOUD] gcloud Command for {backup_name}:")
                    print(self._generate_gcloud_command(backup_name, new, new_enforced))
                    
                if not self.dry_run:
                    success = self._update_backup_expiration(backup_name, new, new_enforced)
                    if success:
                        status = "SUCCESS"
                        completed_backups.add(backup_name)
                        self.save_state(state_file, action_desc, completed_backups)
                        table_row.append("UPDATED")
                    else:
                        status = "FAILED"
                        table_row.append("FAILED")
                else:
                    table_row.append("PREVIEW")
                table_data.append(table_row)
                
            report_updates.append({
                'backup': update['backup'],
                'current_expire': current,
                'new_expire': new,
                'current_enforced': current_enforced,
                'new_enforced': new_enforced,
                'status': status
            })
        
        print("\nSummary of Changes:")
        headers = ["Backup Name", "Current Expiry", "New Expiry", "Current Lock", "New Lock", "Action Taken"]
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        
        if self.dry_run:
             print("\n[DRY RUN] No changes were applied. Run with --execute to apply.")
        else:
             failed_count = sum(1 for ru in report_updates if ru['status'] == 'FAILED')
             if failed_count == 0:
                 self.delete_state(state_file)
             else:
                 self.logger.warning(f"Some updates failed. State file {state_file} preserved for retry.")

        if generate_report:
             generator = ReportGenerator(
                 project_id=self.project_id,
                 location=self.location,
                 dry_run=self.dry_run,
                 executor=self.executor
             )
             generator.generate_html_report(
                 report_updates, 
                 group_by=group_by, 
                 output_path=report_file,
                 extension_action=extension_action,
                 lock_action=lock_action
             )

    def _generate_curl_command(self, backup_name, new_expire_time, new_enforced_time=None):
        payload = { "expireTime": new_expire_time }
        update_mask = "expireTime"
        if new_enforced_time:
            payload["enforcedRetentionEndTime"] = new_enforced_time
            update_mask += ",enforcedRetentionEndTime"
            
        payload_str = json.dumps(payload)
        
        return f"""
curl -X PATCH \\
-H "Authorization: Bearer $(gcloud auth print-access-token)" \\
-H "Content-Type: application/json" \\
-d '{payload_str}' \\
"https://backupdr.googleapis.com/v1/{backup_name}?updateMask={update_mask}"
"""

    def _update_backup_expiration(self, backup_name, new_expire_time, new_enforced_time=None):
        try:
            self.logger.info(f"Updating {backup_name} to expireTime={new_expire_time}, enforcedRetentionEndTime={new_enforced_time}...")
            
            update_mask = "expireTime"
            backup_obj = backupdr_v1.Backup(
                name=backup_name,
                expire_time=parser.parse(new_expire_time)
            )
            
            if new_enforced_time:
                backup_obj.enforced_retention_end_time = parser.parse(new_enforced_time)
                update_mask += ",enforcedRetentionEndTime"
                
            request = backupdr_v1.UpdateBackupRequest(
                backup=backup_obj,
                update_mask=update_mask
            )
            
            # Wrap API calls with retry logic
            operation = self._execute_api_call_with_retry(self.client.update_backup, request=request)
            result = self._execute_api_call_with_retry(operation.result)
            
            self.logger.info(f"Successfully updated {backup_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update {backup_name}: {e}")
            return False

    def _generate_gcloud_command(self, backup_name, new_expire_time, new_enforced_time=None):
        payload = { "expireTime": new_expire_time }
        update_mask = "expireTime"
        if new_enforced_time:
            payload["enforcedRetentionEndTime"] = new_enforced_time
            update_mask += ",enforcedRetentionEndTime"
            
        payload_str = json.dumps(payload)
        
        return f"""
gcloud curl -X PATCH \\
-H "Content-Type: application/json" \\
-d '{payload_str}' \\
"https://backupdr.googleapis.com/v1/{backup_name}?updateMask={update_mask}"
"""

