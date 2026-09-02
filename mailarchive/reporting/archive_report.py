from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import tempfile

from mailarchive.database.connection import connect


def write_archive_report(root, job_id: str):
    root = Path(root)
    reports = root / 'reports'
    reports.mkdir(parents=True, exist_ok=True)
    db = connect(root)
    job = db.execute('SELECT * FROM archive_jobs WHERE job_id=?', (job_id,)).fetchone()
    if not job:
        db.close()
        raise KeyError(job_id)
    items = [
        dict(row) for row in db.execute(
            'SELECT archive_id,provider_id,status,detail FROM archive_job_items WHERE job_id=? ORDER BY archive_id',
            (job_id,),
        )
    ]
    errors = [
        {'archive_id': row['archive_id'], 'code': row['code'], 'detail': row['detail'], 'created_at': row['created_at']}
        for row in db.execute(
            'SELECT archive_id,code,detail,created_at FROM errors WHERE job_id=? ORDER BY id',
            (job_id,),
        )
    ]
    size = db.execute(
        "SELECT COALESCE(SUM(mime_size),0) size FROM messages WHERE verification_status='VERIFIED'"
    ).fetchone()['size']
    db.close()
    report = {
        'job_id': job_id,
        'status': job['status'],
        'stop_reason': job['stop_reason'] if 'stop_reason' in job.keys() else '',
        'start': job['created_at'],
        'stop': job['updated_at'],
        'selected_folders': json.loads(job['selected_folders']),
        'date_range': {'start': job['start_date'], 'end': job['end_date'], 'inclusive': True},
        'messages_discovered': job['discovered_count'],
        'messages_processed': job['processed_count'],
        'messages_verified': job['verified_count'],
        'failures': job['failed_count'],
        'archive_size_bytes': int(size or 0),
        'mailbox_modified': False,
        'cleanup_behavior': 'Archive Only — Keep Original Messages',
        'items': items,
        'errors': errors,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
    path = reports / 'archive_report.json'
    fd, tmp = tempfile.mkstemp(prefix='archive_report.', suffix='.tmp', dir=reports)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
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
