from google.cloud import backupdr_v1
import sys

def debug_datasource(project_id, location):
    client = backupdr_v1.BackupDRClient()
    parent = f"projects/{project_id}/locations/{location}"
    
    print(f"Listing vaults in {parent}...")
    vaults = client.list_backup_vaults(parent=parent)
    
    for vault in vaults:
        print(f"Checking vault: {vault.name}")
        ds_request = backupdr_v1.ListDataSourcesRequest(parent=vault.name)
        data_sources = client.list_data_sources(request=ds_request)
        
        for ds in data_sources:
            print("\n--- FOUND DATASOURCE ---")
            print(f"Name: {ds.name}")
            print(f"Type (raw): {type(ds)}")
            # Print all interesting fields
            if hasattr(ds, 'data_source_gcp_resource'):
                 print(f"GCP Resource: {ds.data_source_gcp_resource}")
                 if hasattr(ds.data_source_gcp_resource, 'type'):
                     print(f"GCP Resource Type: {ds.data_source_gcp_resource.type}")
            
            if hasattr(ds, 'config'):
                print(f"Config: {ds.config}")
            
            # Stop after one for brevity
            return

if __name__ == "__main__":
    debug_datasource("argo-svc-dev-3", "asia-southeast1")
