import argparse
import logging
import sys
from datetime import datetime, timedelta
from retention_manager import RetentionManager

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Extend expiration dates for GCBDR backups.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # Selection Arguments
    parser.add_argument("--project", required=True, help="GCP Project ID searching for backups.")
    parser.add_argument("--location", required=True, help="Lossation/Region to search (e.g., asia-southeast1). Use '-' for all.")
    parser.add_argument("--vault", help="Filter by specific Backup Vault name.")
    parser.add_argument("--workload-type", help="Filter by workload type (e.g., COMPUTE_ENGINE_INSTANCE, CLOUD_SQL_INSTANCE).")
    
    # Filter Arguments
    parser.add_argument("--filter-age-days", type=int, default=0, help="Only select backups older than X days.")
    parser.add_argument("--filter-name", help="Filter backups by name substring.")
    parser.add_argument("--filter-labels", nargs='+', help="Filter by label key=value pairs (e.g., env=prod).")
    
    # Action Arguments
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument("--add-expiration-days", type=int, help="Add X days to the current expiration.")
    action_group.add_argument("--set-new-expiration-date", help="Set specific expiration date (YYYY-MM-DD).")
    
    # Execution Arguments
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview changes without executing (Default).")
    parser.add_argument("--execute", action="store_true", help="Execute changes. MUST be specified to run updates.")
    parser.add_argument("--verbose", action="store_true", help="Print detailed curl/gcloud equivalent commands.")
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    logger = logging.getLogger(__name__)
    
    if not args.execute:
        logger.info("DRY-RUN MODE: No changes will be applied.")
    
    manager = RetentionManager(project_id=args.project, location=args.location, verbose=args.verbose, dry_run=not args.execute)
    
    # 1. Discovery
    logger.info(f"Discovering backups in project {args.project} location {args.location}...")
    # Parse labels if provided
    label_filter = {}
    if args.filter_labels:
        for label in args.filter_labels:
            try:
                key, value = label.split("=")
                label_filter[key] = value
            except ValueError:
                logger.error(f"Invalid label format: {label}. Expected key=value.")
                sys.exit(1)

    backups = manager.list_backups(
        vault_filter=args.vault,
        workload_type_filter=args.workload_type,
        age_days_filter=args.filter_age_days,
        name_filter=args.filter_name,
        label_filter=label_filter
    )
    
    if not backups:
        logger.info("No matching backups found.")
        sys.exit(0)
        
    logger.info(f"Found {len(backups)} backups matching criteria.")
    
    # 2. Planning
    updates = []
    for backup in backups:
        current_expire_time = backup.get('expireTime')
        if not current_expire_time:
            logger.warning(f"Skipping backup {backup['name']} - No expireTime found.")
            continue
            
        new_expire_time = manager.calculate_new_expiration(
            current_expire_time,
            add_days=args.add_expiration_days,
            set_date=args.set_new_expiration_date
        )
        
        updates.append({
            'backup': backup,
            'current_expire': current_expire_time,
            'new_expire': new_expire_time
        })
        
    # 3. Execution / Reporting
    manager.process_updates(updates)

if __name__ == "__main__":
    main()
