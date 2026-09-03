from datetime import datetime, timezone
import json
from pathlib import Path
import os
import tempfile

from mailarchive.database.connection import connect
from mailarchive.cleanup.preview import QUOTA_NOTICE


def write_cleanup_report(root, results, metadata=None):
    root = Path(root)
    (root / 'reports').mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    counts = {}
    for _, status in results:
        counts[status] = counts.get(status, 0) + 1

    db = connect(root)
    metadata_rows = {row['key']: row['value'] for row in db.execute('SELECT key,value FROM archive_metadata')}
    try:
        source_account = json.loads(metadata_rows.get('source_account', '{}'))
    except Exception:
        source_account = {}
    items = []
    for archive_id, status in results:
        row = db.execute(
            'SELECT sha256,folder_id,provider_id FROM messages WHERE archive_id=?',
            (archive_id,),
        ).fetchone()
        cleanup = db.execute(
            'SELECT status,last_detail FROM cleanup_state WHERE archive_id=?',
            (archive_id,),
        ).fetchone()
        items.append({
            'archive_id': archive_id,
            'sha256': row['sha256'] if row else None,
            'source_folder': row['folder_id'] if row else None,
            'provider_id_at_archive': row['provider_id'] if row else None,
            'result': status,
            'cleanup_state': cleanup['status'] if cleanup else None,
            'detail': cleanup['last_detail'] if cleanup else None,
        })
    db.close()

    report = {
        'cleanup_stop': now,
        'source_account': source_account,
        'requested_count': len(results),
        'successfully_moved': counts.get('MOVED', 0),
        'failed': counts.get('FAILED', 0),
        'unknown_move_outcome': counts.get('UNKNOWN_MOVE_OUTCOME', 0),
        'missing': counts.get('MISSING', 0),
        'skipped': sum(value for key, value in counts.items() if key.startswith('SKIPPED_')),
        'counts': counts,
        'items': items,
        'mailbox_quota_notice': QUOTA_NOTICE,
        'permanent_deletion_performed': False,
        'reconciliation_notice': (
            'Any UNKNOWN_MOVE_OUTCOME item may already have moved to Deleted Items. MailArchive will not retry it automatically; reconcile it manually before any further cleanup attempt.'
            if counts.get('UNKNOWN_MOVE_OUTCOME', 0) else ''
        ),
    }
    if metadata:
        report.update(metadata)
    path = root / 'reports' / 'cleanup_report.json'
    fd, tmp = tempfile.mkstemp(prefix='cleanup_report.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return path
