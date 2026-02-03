import logging
from datetime import datetime, timedelta
from dateutil import parser
from google.cloud import backupdr_v1
from google.api_core import client_options
from tabulate import tabulate
import json

class RetentionManager:
    def __init__(self, project_id, location, verbose=False, gcloud_verbose=False, dry_run=True):
        self.project_id = project_id
        self.location = location
        self.verbose = verbose
        self.gcloud_verbose = gcloud_verbose
        self.dry_run = dry_run
        self.logger = logging.getLogger(__name__)
        
        # Initialize BackupDR Client
        # We might need to iterate over vaults if location is wildcard
        self.client = backupdr_v1.BackupDRClient()

    def list_backups(self, vault_filter=None, workload_type_filter=None, age_days_filter=0, name_filter=None, label_filter=None):
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
                    # Filter by Workload Type
                    if workload_type_filter:
                        # Normalize to map value if possible, else use raw input
                        target_type = WORKLOAD_TYPE_MAP.get(workload_type_filter, workload_type_filter)
                        
                        # Check GCP Resource Type
                        if hasattr(ds, 'data_source_gcp_resource') and hasattr(ds.data_source_gcp_resource, 'type'):
                            if target_type not in ds.data_source_gcp_resource.type:
                                continue
                        else:
                             # If type info is missing but filter is requested, verify if we should skip
                             # Some datasources might not be GCP resources (e.g. on-prem).
                             # For now, skip if we can't verify type
                             continue

                    # 3. List Backups in DataSource

                    # Creating a backup list request
                    
                    backup_request = backupdr_v1.ListBackupsRequest(parent=ds.name)
                    # We can use 'filter' parameter here if the API supports it to optimize
                    # e.g., filter="create_time < ..."
                    
                    ds_backups = self.client.list_backups(request=backup_request)
                    for backup in ds_backups:
                        # Client side filtering for now for flexibility
                        if self._matches_criteria(backup, age_days_filter, name_filter, label_filter):
                            backups.append(self._proto_to_dict(backup))
                            
        except Exception as e:
            self.logger.error(f"Error listing backups: {e}")
            
        return backups

    def _matches_criteria(self, backup, age_days_filter, name_filter, label_filter):
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
                    
        return True

    def _proto_to_dict(self, backup):
        # Convert necessary fields to dict for easier handling
        return {
            'name': backup.name,
            'expireTime': backup.expire_time.isoformat() if backup.expire_time else None,
            'createTime': backup.create_time.isoformat() if backup.create_time else None,
            'state': backup.state.name
        }

    def calculate_new_expiration(self, current_expire_str, add_days=None, set_date=None):
        current_expire = parser.parse(current_expire_str)
        
        if set_date:
            # Assume set_date is YYYY-MM-DD, preserve time info from current or set to EOD?
            # Usually better to preserve current time or set to 23:59:59
            # For simplicity, let's keep current time but change date
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

    def process_updates(self, updates):
        table_data = []
        for update in updates:
            backup_name = update['backup']['name']
            current = update['current_expire']
            new = update['new_expire']
            
            table_data.append([
                backup_name.split('/')[-1], # Short name
                current,
                new
            ])
            
            if self.verbose:
                print(f"\n[VERBOSE] curl Command for {backup_name}:")
                print(self._generate_curl_command(backup_name, new))

            if self.gcloud_verbose:
                print(f"\n[GCLOUD] gcloud Command for {backup_name}:")
                print(self._generate_gcloud_command(backup_name, new))
                
            if not self.dry_run:
                self._update_backup_expiration(backup_name, new)
        
        print("\nSummary of Changes:")
        print(tabulate(table_data, headers=["Backup Name", "Current Expiry", "New Expiry"], tablefmt="grid"))
        
        if self.dry_run:
             print("\n[DRY RUN] No changes were applied. Run with --execute to apply.")

    def _generate_curl_command(self, backup_name, new_expire_time):
        return f"""
curl -X PATCH \\
-H "Authorization: Bearer $(gcloud auth print-access-token)" \\
-H "Content-Type: application/json" \\
-d '{{ "expireTime": "{new_expire_time}" }}' \\
"https://backupdr.googleapis.com/v1/{backup_name}?updateMask=expireTime"
"""

    def _update_backup_expiration(self, backup_name, new_expire_time):
        try:
            self.logger.info(f"Updating {backup_name} to {new_expire_time}...")
            
            backup = backupdr_v1.Backup()
            # Parse isoformat back to timestamp for protobuf?
            # actually the client library expects keys.
            
            # The python client typically needs a Timestamp object or similar.
            # but let's see if we can just pass the dictionary or object.
            # UpdateMask is required.
            
            # Direct API call via client
            request = backupdr_v1.UpdateBackupRequest(
                backup=backupdr_v1.Backup(
                    name=backup_name,
                    expire_time=parser.parse(new_expire_time)
                ),
                update_mask="expireTime"
            )
            
            operation = self.client.update_backup(request=request)
            result = operation.result() # Wait for completion
            self.logger.info(f"Successfully updated {backup_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to update {backup_name}: {e}")

    def _generate_gcloud_command(self, backup_name, new_expire_time):
        return f"""
gcloud curl -X PATCH \\
-H "Content-Type: application/json" \\
-d '{{ "expireTime": "{new_expire_time}" }}' \\
"https://backupdr.googleapis.com/v1/{backup_name}?updateMask=expireTime"
"""

