import os
from datetime import datetime, timezone
from collections import defaultdict
from string import Template

class ReportGenerator:
    def __init__(self, project_id, location, dry_run=True, executor="Unknown"):
        self.project_id = project_id
        self.location = location
        self.dry_run = dry_run
        self.executor = executor
        
    def generate_html_report(self, updates, group_by="vault", output_path="retention_report.html", extension_action="N/A", lock_action="None"):
        """
        Compiles and writes the HTML compliance report.
        `updates` is a list of dicts:
        {
            'backup': {
                'name': str,
                'backup_id': str,
                'vault_id': str,
                'datasource_id': str,
                'workload_type': str,
                'expireTime': str,
                'createTime': str,
                'enforced_retention_end_time': str,
                'is_locked': bool,
                'state': str
            },
            'current_expire': str,
            'new_expire': str,
            'current_enforced': str,
            'new_enforced': str,
            'status': str
        }
        """
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Calculate stats
        total_backups = len(updates)
        successful_updates = sum(1 for u in updates if u.get('status') == 'SUCCESS')
        dry_run_updates = sum(1 for u in updates if u.get('status') == 'DRY_RUN')
        failed_updates = sum(1 for u in updates if u.get('status') == 'FAILED')
        
        status_label = "DRY-RUN / PREVIEW" if self.dry_run else "LIVE EXECUTION COMPLETE"
        status_class = "status-preview" if self.dry_run else "status-success"
        if failed_updates > 0 and not self.dry_run:
            status_label = "COMPLETED WITH ERRORS"
            status_class = "status-warning"

        # Organize groups
        groups = defaultdict(list)
        for u in updates:
            b = u['backup']
            group_key = b['vault_id'] if group_by == "vault" else b['workload_type']
            groups[group_key].append(u)
            
        # Group stats for progress bars
        group_counts = {k: len(v) for k, v in groups.items()}
        total_grouped = sum(group_counts.values()) or 1
        
        # Generate chart segments
        chart_html = ""
        colors = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#3af2e1", "#f43f5e"]
        
        chart_legend_html = ""
        for i, (name, count) in enumerate(group_counts.items()):
            pct = (count / total_grouped) * 100
            color = colors[i % len(colors)]
            chart_html += f'<div class="chart-segment" style="width: {pct}%; background-color: {color};" title="{name}: {count} ({pct:.1f}%)"></div>'
            chart_legend_html += f"""
            <div class="legend-item">
                <div class="legend-color" style="background-color: {color};"></div>
                <span>{name} ({count})</span>
            </div>"""

        # Build Group Sections & Tables
        sections_html = ""
        for group_name, group_updates in sorted(groups.items()):
            # Calculate lock status stats within group
            locked_count = sum(1 for u in group_updates if u['backup']['is_locked'])
            unlocked_count = len(group_updates) - locked_count
            
            # Show red-locked warning badge if there are unlocked backups, or green lock if all locked
            lock_summary_html = ""
            if locked_count == len(group_updates):
                lock_summary_html = f'<span class="lock-summary summary-all-locked">🔒 {locked_count} Locked (All Protected)</span>'
            elif locked_count > 0:
                lock_summary_html = f'<span class="lock-summary summary-part-locked">⚠️ {locked_count} Locked / {unlocked_count} Unlocked</span>'
            else:
                lock_summary_html = f'<span class="lock-summary summary-none-locked">🔓 {unlocked_count} Unlocked (No Deletion Protection)</span>'

            table_rows = ""
            for u in group_updates:
                b = u['backup']
                
                # Expiry comparison formatting
                expiry_display = f"""
                <span class="expiry-old">{self._format_date(u['current_expire'])}</span>
                <span class="arrow">→</span>
                <span class="expiry-new">{self._format_date(u['new_expire'])}</span>
                """
                
                # Immutability lock comparison formatting
                curr_lock = u.get('current_enforced')
                new_lock = u.get('new_enforced')
                
                if new_lock or curr_lock:
                    lock_display = f"""
                    <span class="expiry-old">{self._format_date(curr_lock) if curr_lock else "None"}</span>
                    <span class="arrow">→</span>
                    <span class="expiry-new" style="color: var(--accent-warning);">{self._format_date(new_lock) if new_lock else "None"}</span>
                    """
                else:
                    lock_display = '<span style="color: var(--text-secondary); font-size: 0.85rem;">No lock configured</span>'

                # Lock Status Badge
                if b['is_locked']:
                    # Get future end time date
                    lock_badge = f'<span class="status-badge badge-success" style="font-size: 0.7rem; padding: 0.15rem 0.4rem;">🔒 Locked</span>'
                else:
                    lock_badge = '<span class="status-badge badge-failed" style="font-size: 0.7rem; padding: 0.15rem 0.4rem;">🔓 Unlocked</span>'
                
                status_val = u.get('status', 'DRY_RUN')
                badge_class = f"badge-{status_val.lower().replace('_', '-')}"
                
                # Extra metadata column based on grouping
                extra_meta = f"<td>{b['workload_type']}</td>" if group_by == "vault" else f"<td><span class=\"vault-badge\">{b['vault_id']}</span></td>"
                
                table_rows += f"""
                <tr>
                    <td>
                        <strong>{b['backup_id']}</strong> {lock_badge}<br/>
                        <span style="font-size: 0.75rem; color: var(--text-secondary);">{b['name'].split('/')[-1]}</span>
                    </td>
                    {extra_meta}
                    <td>{self._format_date(b['createTime'])}</td>
                    <td>{expiry_display}</td>
                    <td>{lock_display}</td>
                    <td><span class="status-badge {badge_class}">{status_val}</span></td>
                </tr>"""

            extra_header = "Workload Type" if group_by == "vault" else "Backup Vault"
            group_label = "Vault" if group_by == "vault" else "Workload"
            
            sections_html += f"""
            <div class="group-section">
                <div class="group-header">
                    <h3>{group_label}: {group_name}</h3>
                    <div style="display: flex; gap: 0.75rem; align-items: center;">
                        {lock_summary_html}
                        <span class="group-count">{len(group_updates)} backup(s)</span>
                    </div>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Backup ID</th>
                                <th>{extra_header}</th>
                                <th>Creation Date</th>
                                <th>Expiration Override</th>
                                <th>Immutability Lock (Enforced)</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {table_rows}
                        </tbody>
                    </table>
                </div>
            </div>"""

        # HTML Template
        html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Retention Extension Compliance Report</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0b0f19;
            --bg-secondary: #111827;
            --bg-tertiary: #1f2937;
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --accent-blue: #3b82f6;
            --accent-blue-glow: rgba(59, 130, 246, 0.15);
            --accent-success: #10b981;
            --accent-success-glow: rgba(16, 185, 129, 0.15);
            --accent-warning: #f59e0b;
            --accent-warning-glow: rgba(245, 158, 11, 0.15);
            --accent-danger: #ef4444;
            --accent-danger-glow: rgba(239, 68, 68, 0.15);
            --border-color: #374151;
            --glow-card: 0 10px 30px -10px rgba(0, 0, 0, 0.7);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 2rem 1.5rem;
        }

        .container {
            max-width: 1100px;
            margin: 0 auto;
        }

        header {
            margin-bottom: 2.5rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 2rem;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }

        .header-title h1 {
            font-family: 'Outfit', sans-serif;
            font-size: 2.2rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            background: linear-gradient(135deg, #fff 40%, #9ca3af);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }

        .subtitle {
            color: var(--text-secondary);
            font-size: 1rem;
        }

        .execution-badge {
            font-size: 0.8rem;
            font-weight: 700;
            padding: 0.5rem 1rem;
            border-radius: 30px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-top: 0.5rem;
            display: inline-block;
        }

        .status-preview {
            background-color: var(--accent-warning-glow);
            color: var(--accent-warning);
            border: 1px solid var(--accent-warning);
        }

        .status-success {
            background-color: var(--accent-success-glow);
            color: var(--accent-success);
            border: 1px solid var(--accent-success);
        }

        .status-warning {
            background-color: var(--accent-danger-glow);
            color: var(--accent-danger);
            border: 1px solid var(--accent-danger);
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1.25rem;
            margin-bottom: 3rem;
        }

        .stat-card {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.25rem;
            box-shadow: var(--glow-card);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }

        .stat-card:hover {
            transform: translateY(-2px);
            border-color: var(--accent-blue);
        }

        .stat-card.highlight-card {
            border-left: 4px solid var(--accent-blue);
            background: linear-gradient(180deg, var(--bg-secondary) 0%, rgba(59, 130, 246, 0.05) 100%);
        }

        .stat-card.lock-card {
            border-left: 4px solid var(--accent-warning);
            background: linear-gradient(180deg, var(--bg-secondary) 0%, rgba(245, 158, 11, 0.05) 100%);
        }

        .stat-label {
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }

        .stat-value {
            font-family: 'Outfit', sans-serif;
            font-size: 1.8rem;
            font-weight: 600;
            line-height: 1.2;
        }

        .stat-value.value-success {
            color: var(--accent-success);
        }

        .stat-value.value-warning {
            color: var(--accent-warning);
        }

        .stat-value.value-danger {
            color: var(--accent-danger);
        }

        /* Distribution Chart */
        .chart-section {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 1.5rem 2rem;
            margin-bottom: 2.5rem;
            box-shadow: var(--glow-card);
        }

        .chart-section h2 {
            font-family: 'Outfit', sans-serif;
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 1.2rem;
        }

        .chart-container {
            height: 24px;
            background-color: var(--bg-tertiary);
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            margin-bottom: 1.5rem;
            border: 1px solid rgba(55, 65, 81, 0.5);
        }

        .chart-segment {
            height: 100%;
            transition: width 0.3s ease;
            position: relative;
        }

        .chart-segment:hover {
            opacity: 0.85;
            cursor: pointer;
        }

        .chart-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 1.5rem;
            font-size: 0.8rem;
            color: var(--text-secondary);
            justify-content: center;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .legend-color {
            width: 12px;
            height: 12px;
            border-radius: 3px;
        }

        /* Group Sections & Tables */
        .group-section {
            background-color: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 2rem;
            margin-bottom: 2.5rem;
            box-shadow: var(--glow-card);
        }

        .group-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            border-bottom: 1px solid rgba(55, 65, 81, 0.3);
            padding-bottom: 0.75rem;
            flex-wrap: wrap;
            gap: 1rem;
        }

        .group-header h3 {
            font-family: 'Outfit', sans-serif;
            font-size: 1.3rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .group-header h3::before {
            content: '';
            display: inline-block;
            width: 4px;
            height: 1.25rem;
            background-color: var(--accent-blue);
            border-radius: 2px;
        }

        .group-count {
            font-size: 0.85rem;
            color: var(--text-secondary);
            background-color: var(--bg-tertiary);
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
        }

        .lock-summary {
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            display: inline-block;
        }

        .summary-all-locked {
            background-color: var(--accent-success-glow);
            color: var(--accent-success);
            border: 1px solid var(--accent-success);
        }

        .summary-part-locked {
            background-color: var(--accent-warning-glow);
            color: var(--accent-warning);
            border: 1px solid var(--accent-warning);
        }

        .summary-none-locked {
            background-color: var(--accent-danger-glow);
            color: var(--accent-danger);
            border: 1px solid var(--accent-danger);
        }

        .table-container {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.9rem;
        }

        th {
            background-color: var(--bg-tertiary);
            color: var(--text-primary);
            font-weight: 600;
            padding: 1rem;
            border-bottom: 2px solid var(--border-color);
        }

        td {
            padding: 1.2rem 1rem;
            border-bottom: 1px solid var(--border-color);
            color: var(--text-primary);
            vertical-align: middle;
        }

        tr:last-child td {
            border-bottom: none;
        }

        .vault-badge {
            font-family: monospace;
            background-color: var(--bg-tertiary);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.8rem;
            color: #d1d5db;
        }

        /* Expiry Override column styles */
        .expiry-old {
            color: var(--text-secondary);
            text-decoration: line-through;
            font-size: 0.85rem;
        }

        .arrow {
            color: var(--accent-blue);
            margin: 0 0.5rem;
            font-weight: bold;
        }

        .expiry-new {
            color: var(--accent-success);
            font-weight: 600;
        }

        /* Status Badge Styles */
        .status-badge {
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.25rem 0.6rem;
            border-radius: 6px;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            display: inline-block;
        }

        .badge-success {
            background-color: var(--accent-success-glow);
            color: var(--accent-success);
            border: 1px solid var(--accent-success);
        }

        .badge-dry-run {
            background-color: var(--accent-warning-glow);
            color: var(--accent-warning);
            border: 1px solid var(--accent-warning);
        }

        .badge-failed {
            background-color: var(--accent-danger-glow);
            color: var(--accent-danger);
            border: 1px solid var(--accent-danger);
        }

        .badge-skipped {
            background-color: rgba(255, 255, 255, 0.05);
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
        }

        footer {
            text-align: center;
            padding: 2rem 0;
            color: var(--text-secondary);
            font-size: 0.8rem;
            border-top: 1px solid var(--border-color);
            margin-top: 4rem;
        }

        .meta-list {
            list-style: none;
            display: flex;
            justify-content: center;
            gap: 2rem;
            margin-top: 0.5rem;
            flex-wrap: wrap;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-title">
                <h1>GCBDR Retention Extension Compliance Report</h1>
                <div class="subtitle">Google Cloud Backup & DR • Retention Policy Override Audit Log</div>
            </div>
            <div>
                <span class="execution-badge $status_class">$status_label</span>
            </div>
        </header>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Project Scope</div>
                <div class="stat-value" style="font-size: 1.1rem; word-break: break-all; margin-top: 0.5rem; color: var(--text-primary);">$project_id</div>
            </div>
            <div class="stat-card highlight-card">
                <div class="stat-label">Expiration Policy</div>
                <div class="stat-value" style="color: var(--accent-blue);">$extension_action</div>
            </div>
            <div class="stat-card lock-card">
                <div class="stat-label">Immutability Lock</div>
                <div class="stat-value" style="color: var(--accent-warning); font-size: 1.6rem; margin-top: 0.2rem;">$lock_action</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Evaluated</div>
                <div class="stat-value">$total_backups</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Successfully Extended</div>
                <div class="stat-value value-success">$successful_updates</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Failed Updates</div>
                <div class="stat-value value-danger">$failed_updates</div>
            </div>
        </div>

        <section class="chart-section">
            <h2>Backup Distribution by $group_label</h2>
            <div class="chart-container">
                $chart_html
            </div>
            <div class="chart-legend">
                $chart_legend_html
            </div>
        </section>

        $sections_html

        <footer>
            <div>Backup Expiration Overrides Audit Report • Compliance Document</div>
            <ul class="meta-list">
                <li><strong>Audit Date:</strong> $audit_date</li>
                <li><strong>Executor:</strong> $executor</li>
                <li><strong>Location Scope:</strong> $location</li>
                <li><strong>Method:</strong> REST SDK (google-cloud-backupdr)</li>
            </ul>
        </footer>
    </div>
</body>
</html>
"""
        
        tmpl = Template(html_template)
        html_report = tmpl.safe_substitute(
            status_label=status_label,
            status_class=status_class,
            project_id=self.project_id,
            total_backups=total_backups,
            successful_updates=successful_updates,
            dry_run_updates=dry_run_updates,
            failed_updates=failed_updates,
            group_label="Vault" if group_by == "vault" else "Workload Type",
            chart_html=chart_html,
            chart_legend_html=chart_legend_html,
            sections_html=sections_html,
            audit_date=now_str,
            executor=self.executor,
            location=self.location,
            extension_action=extension_action,
            lock_action=lock_action
        )
        
        with open(output_path, "w") as f:
            f.write(html_report)
            
        print(f"\n[INFO] Compliance audit report generated at: {os.path.abspath(output_path)}")
        
    def _format_date(self, date_str):
        if not date_str or date_str == "N/A":
            return "N/A"
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return date_str
