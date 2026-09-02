from __future__ import annotations

import json
from datetime import datetime, timezone
from sqlite3 import Connection

from mailarchive.database.connection import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_VERIFIED_ITEM_STATES = {'VERIFIED', 'SKIPPED_VERIFIED'}


class CheckpointStore:
    def __init__(self, root):
        self.root = root

    def _connection(self, db: Connection | None) -> tuple[Connection, bool]:
        if db is not None:
            return db, False
        return connect(self.root), True

    def begin_or_resume(
        self,
        job_id: str,
        folder_ids: list[str],
        start: str | None,
        end: str | None,
        *,
        db: Connection | None = None,
    ) -> dict:
        conn, owned = self._connection(db)
        try:
            row = conn.execute('SELECT * FROM archive_jobs WHERE job_id=?', (job_id,)).fetchone()
            if row is None:
                now = _now()
                with conn:
                    conn.execute(
                        '''INSERT INTO archive_jobs(job_id,status,selected_folders,start_date,end_date,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?)''',
                        (job_id, 'RUNNING', json.dumps(folder_ids), start, end, now, now),
                    )
                row = conn.execute('SELECT * FROM archive_jobs WHERE job_id=?', (job_id,)).fetchone()
            else:
                original = (json.loads(row['selected_folders']), row['start_date'], row['end_date'])
                requested = (folder_ids, start, end)
                if original != requested:
                    raise ValueError('resume parameters do not match original archive job')
                with conn:
                    conn.execute(
                        "UPDATE archive_jobs SET status='RUNNING',stop_reason='',updated_at=? WHERE job_id=?",
                        (_now(), job_id),
                    )
            return dict(row)
        finally:
            if owned:
                conn.close()

    def item_status(self, job_id: str, archive_id: str, *, db: Connection | None = None) -> str | None:
        conn, owned = self._connection(db)
        try:
            row = conn.execute(
                'SELECT status FROM archive_job_items WHERE job_id=? AND archive_id=?',
                (job_id, archive_id),
            ).fetchone()
            return row['status'] if row else None
        finally:
            if owned:
                conn.close()

    def record_item(
        self,
        job_id: str,
        archive_id: str,
        provider_id: str,
        status: str,
        detail: str = '',
        *,
        db: Connection | None = None,
    ) -> None:
        """Record an item and update job counters in O(1).

        If called inside the archive engine's existing per-message transaction, this method
        joins that transaction so VERIFIED state and checkpoint accounting commit atomically.
        Standalone calls retain their own durable transaction.
        """
        conn, owned = self._connection(db)

        def apply_record() -> None:
            previous = conn.execute(
                'SELECT status FROM archive_job_items WHERE job_id=? AND archive_id=?',
                (job_id, archive_id),
            ).fetchone()
            previous_status = previous['status'] if previous else None

            conn.execute(
                '''INSERT INTO archive_job_items(job_id,archive_id,provider_id,status,detail)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(job_id,archive_id) DO UPDATE SET
                     provider_id=excluded.provider_id,
                     status=excluded.status,
                     detail=excluded.detail''',
                (job_id, archive_id, provider_id, status, detail),
            )

            processed_delta = 0 if previous_status is not None else 1
            verified_delta = int(status in _VERIFIED_ITEM_STATES) - int(previous_status in _VERIFIED_ITEM_STATES)
            failed_delta = int(status == 'FAILED') - int(previous_status == 'FAILED')
            conn.execute(
                '''UPDATE archive_jobs
                   SET processed_count=MAX(0, processed_count + ?),
                       verified_count=MAX(0, verified_count + ?),
                       failed_count=MAX(0, failed_count + ?),
                       updated_at=?
                   WHERE job_id=?''',
                (processed_delta, verified_delta, failed_delta, _now(), job_id),
            )

        try:
            if conn.in_transaction:
                apply_record()
            else:
                with conn:
                    apply_record()
        finally:
            if owned:
                conn.close()

    def set_discovered(self, job_id: str, count: int, *, db: Connection | None = None) -> None:
        conn, owned = self._connection(db)
        try:
            with conn:
                conn.execute(
                    'UPDATE archive_jobs SET discovered_count=?,updated_at=? WHERE job_id=?',
                    (count, _now(), job_id),
                )
        finally:
            if owned:
                conn.close()

    def finish(
        self,
        job_id: str,
        status: str,
        *,
        stop_reason: str = '',
        db: Connection | None = None,
    ) -> None:
        if status not in {'COMPLETED', 'PARTIAL', 'CANCELLED', 'FAILED', 'INTERRUPTED'}:
            raise ValueError(status)
        conn, owned = self._connection(db)
        try:
            with conn:
                conn.execute(
                    'UPDATE archive_jobs SET status=?,stop_reason=?,updated_at=? WHERE job_id=?',
                    (status, stop_reason or '', _now(), job_id),
                )
                conn.execute(
                    'INSERT OR REPLACE INTO checkpoints(job_id,payload,updated_at) VALUES(?,?,?)',
                    (job_id, json.dumps({'status': status, 'stop_reason': stop_reason or ''}), _now()),
                )
        finally:
            if owned:
                conn.close()
