from __future__ import annotations


def format_bytes(value: int | None) -> str:
    if value is None:
        return 'Unknown'
    size = float(value)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f'{size:.1f} {unit}' if unit != 'B' else f'{int(size)} B'
        size /= 1024


def cleanup_confirmation_text(plan) -> str:
    start = plan.date_start or 'earliest available'
    end = plan.date_end or 'latest available'
    folders = ', '.join(plan.folders) if plan.folders else '(not recorded)'
    return (
        f'Verified messages eligible: {plan.verified_eligible_count}\n'
        f'Date range (inclusive): {start} through {end}\n'
        f'Source folders: {folders}\n\n'
        'Only messages that still pass local integrity and identity checks will be moved.\n'
        'They will be moved to Microsoft 365 Deleted Items. They will NOT be permanently deleted.\n\n'
        f'{plan.quota_notice}\n\nContinue?'
    )


def format_account_identity(metadata) -> str:
    """Human-readable signed-in account label without persisting it to settings."""
    metadata = metadata or {}
    display = str(metadata.get('display_name') or '').strip()
    principal = str(metadata.get('principal_hint') or metadata.get('mail') or metadata.get('user_principal_name') or '').strip()
    if display and principal and display.casefold() != principal.casefold():
        return f'{display} ({principal})'
    return display or principal or 'Signed-in Microsoft account'


def archive_manager_label(item) -> str:
    """Build the archive-manager row label, including the full archive location."""
    from pathlib import Path
    path = str(item.get('path') or '')
    state = '' if item.get('exists') else ' [missing]'
    count = item.get('verified_count', item.get('message_count', '?'))
    date_range = item.get('selected_date_range') or {}
    start = date_range.get('start') or 'earliest'
    end = date_range.get('end') or 'latest'
    size = format_bytes(item.get('archive_size')) if item.get('archive_size') is not None else 'Unknown size'
    created = str(item.get('archive_creation_timestamp') or 'Unknown')
    last_opened = str(item.get('last_opened') or 'Never')
    return (
        f"{Path(path).name} — {count} messages — {start} to {end} — {size} — "
        f"Created {created} — Last opened {last_opened} — Location {path}{state}"
    )
