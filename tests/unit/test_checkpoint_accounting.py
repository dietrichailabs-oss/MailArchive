from mailarchive.archive.checkpointing import CheckpointStore
from mailarchive.database.connection import connect


def _job_counts(db, job_id='job-1'):
    row = db.execute(
        'SELECT processed_count,verified_count,failed_count,discovered_count FROM archive_jobs WHERE job_id=?',
        (job_id,),
    ).fetchone()
    return tuple(row)


def _truth(db, job_id='job-1'):
    row = db.execute(
        '''SELECT COUNT(*) processed,
                  SUM(CASE WHEN status IN ('VERIFIED','SKIPPED_VERIFIED') THEN 1 ELSE 0 END) verified,
                  SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) failed
           FROM archive_job_items WHERE job_id=?''',
        (job_id,),
    ).fetchone()
    return (row['processed'] or 0, row['verified'] or 0, row['failed'] or 0)


def test_incremental_checkpoint_counters_match_item_truth_across_transitions(tmp_path):
    store = CheckpointStore(tmp_path)
    store.begin_or_resume('job-1', ['inbox'], None, None)
    db = connect(tmp_path)
    try:
        transitions = [
            ('a', 'FAILED'),
            ('a', 'VERIFIED'),
            ('a', 'SKIPPED_VERIFIED'),
            ('a', 'INTERRUPTED'),
            ('a', 'VERIFIED'),
            ('b', 'FAILED'),
            ('b', 'FAILED'),
            ('b', 'VERIFIED'),
            ('c', 'CANCELLED'),
        ]
        for archive_id, status in transitions:
            store.record_item('job-1', archive_id, f'provider-{archive_id}', status, db=db)
            assert _job_counts(db)[:3] == _truth(db)

        assert _job_counts(db)[:3] == (3, 2, 0)
        assert store.item_status('job-1', 'a', db=db) == 'VERIFIED'
        # Shared-connection methods must not close the engine's persistent DB handle.
        assert db.execute('SELECT 1').fetchone()[0] == 1
    finally:
        db.close()


def test_checkpoint_discovered_and_resume_counters_remain_durable(tmp_path):
    store = CheckpointStore(tmp_path)
    store.begin_or_resume('job-1', ['inbox'], '2026-01-01', '2026-01-31')
    db = connect(tmp_path)
    store.set_discovered('job-1', 17, db=db)
    store.record_item('job-1', 'a', 'provider-a', 'INTERRUPTED', db=db)
    store.finish('job-1', 'INTERRUPTED', stop_reason='NetworkUnavailable', db=db)
    db.close()

    store.begin_or_resume('job-1', ['inbox'], '2026-01-01', '2026-01-31')
    store.record_item('job-1', 'a', 'provider-a', 'VERIFIED')
    store.record_item('job-1', 'b', 'provider-b', 'SKIPPED_VERIFIED')
    store.finish('job-1', 'COMPLETED')

    db = connect(tmp_path)
    try:
        row = db.execute('SELECT * FROM archive_jobs WHERE job_id=?', ('job-1',)).fetchone()
        assert row['status'] == 'COMPLETED'
        assert row['discovered_count'] == 17
        assert row['processed_count'] == 2
        assert row['verified_count'] == 2
        assert row['failed_count'] == 0
        assert _truth(db) == (2, 2, 0)
    finally:
        db.close()


def test_engine_flushes_exact_discovered_count_on_interruption(tmp_path):
    from mailarchive.archive.job_engine import ArchiveJobEngine
    from mailarchive.providers.fake_mailbox import FakeFaults, FakeMailboxProvider

    provider = FakeMailboxProvider(
        messages=FakeMailboxProvider.synthetic_messages(10),
        faults=FakeFaults(network_fail={'msg-4'}),
        page_size=3,
    )
    ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], job_id='job-1')
    db = connect(tmp_path)
    try:
        row = db.execute('SELECT status,discovered_count FROM archive_jobs WHERE job_id=?', ('job-1',)).fetchone()
        assert row['status'] == 'INTERRUPTED'
        # Sorted discovery reaches msg-4 after msg-0..msg-3, far below the batch interval.
        assert row['discovered_count'] > 0
        item_count = db.execute('SELECT COUNT(*) FROM archive_job_items WHERE job_id=?', ('job-1',)).fetchone()[0]
        assert row['discovered_count'] == item_count
    finally:
        db.close()
