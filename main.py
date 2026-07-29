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
    
    lock_filter_group = parser.add_mutually_exclusive_group()
    lock_filter_group.add_argument("--filter-locked", action="store_true", help="Only select backups currently locked (enforced retention end time in future).")
    lock_filter_group.add_argument("--filter-unlocked", action="store_true", help="Only select backups currently unlocked (enforced retention end time has passed or not set).")
    
    # Action Arguments
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument("--add-expiration-days", type=int, help="Add X days to the current expiration.")
    action_group.add_argument("--set-new-expiration-date", help="Set specific expiration date (YYYY-MM-DD).")
    
    # Immutability Lock Override Actions
    lock_action_group = parser.add_mutually_exclusive_group()
    lock_action_group.add_argument("--add-enforced-retention-days", type=int, help="Add X days to current enforced retention.")
    lock_action_group.add_argument("--set-new-enforced-retention-date", help="Set specific enforced retention date (YYYY-MM-DD).")
    lock_action_group.add_argument("--sync-enforced-retention", action="store_true", help="Sync enforced retention end time to match the new expiration date.")
    
    # Execution Arguments
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview changes without executing (Default).")
    parser.add_argument("--execute", action="store_true", help="Execute changes. MUST be specified to run updates.")
    parser.add_argument("--verbose", action="store_true", help="Print detailed curl equivalent commands.")
    parser.add_argument("--gcloud", action="store_true", help="Print detailed gcloud equivalent commands.")
    parser.add_argument("--state-file", default=".gcbdr_retention_state.json", help="Path to state file for resuming incomplete runs.")
    
    # Reporting Arguments
    parser.add_argument("--report", action="store_true", help="Generate an HTML compliance audit report.")
    parser.add_argument("--report-group-by", choices=["vault", "workload"], default="vault", help="Field to group the HTML report by (vault or workload).")
    parser.add_argument("--report-file", default="retention_report.html", help="File name/path to save the HTML report.")
    
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
    
    manager = RetentionManager(project_id=args.project, location=args.location, verbose=args.verbose, gcloud_verbose=args.gcloud, dry_run=not args.execute)
    
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
        label_filter=label_filter,
        filter_locked=args.filter_locked,
        filter_unlocked=args.filter_unlocked
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
            
        # Current enforced retention end time
        current_enforced = backup.get('enforced_retention_end_time')
        
        # Calculate new expiration
        new_expire_time = manager.calculate_new_expiration(
            current_expire_time,
            add_days=args.add_expiration_days,
            set_date=args.set_new_expiration_date
        )
        
        # Calculate new enforced lock retention
        new_enforced = None
        if args.sync_enforced_retention or args.add_enforced_retention_days or args.set_new_enforced_retention_date:
            new_enforced = manager.calculate_new_enforced_retention(
                current_enforced,
                new_expire_time,
                add_days=args.add_enforced_retention_days,
                set_date=args.set_new_enforced_retention_date,
                sync_retention=args.sync_enforced_retention
            )
        
        updates.append({
            'backup': backup,
            'current_expire': current_expire_time,
            'new_expire': new_expire_time,
            'current_enforced': current_enforced,
            'new_enforced': new_enforced
        })
        
    # 3. Execution / Reporting
    action_desc = f"exp_add={args.add_expiration_days};exp_set={args.set_new_expiration_date};lock_sync={args.sync_enforced_retention};lock_add={args.add_enforced_retention_days};lock_set={args.set_new_enforced_retention_date};locked_f={args.filter_locked};unlocked_f={args.filter_unlocked}"
    
    extension_action = "N/A"
    if args.add_expiration_days:
        extension_action = f"+{args.add_expiration_days} Days"
    elif args.set_new_expiration_date:
        extension_action = f"Set to {args.set_new_expiration_date}"
        
    lock_action = "None"
    if args.sync_enforced_retention:
        lock_action = "Sync with Expiry"
    elif args.add_enforced_retention_days:
        lock_action = f"+{args.add_enforced_retention_days} Days"
    elif args.set_new_enforced_retention_date:
        lock_action = f"Set to {args.set_new_enforced_retention_date}"
        
    manager.process_updates(
        updates,
        generate_report=args.report,
        group_by=args.report_group_by,
        report_file=args.report_file,
        state_file=args.state_file,
        action_desc=action_desc,
        extension_action=extension_action,
        lock_action=lock_action
    )

if __name__ == "__main__":
    main()
