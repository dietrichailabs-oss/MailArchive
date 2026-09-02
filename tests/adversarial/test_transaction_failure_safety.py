import errno
import json

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.cleanup.mailbox_actions import CleanupService
from mailarchive.database.connection import connect
from mailarchive.providers.fake_mailbox import FakeMailboxProvider


def _first_archive_id(result):
    return next(aid for aid, _ in result)


def test_manifest_commit_failure_leaves_message_ineligible_and_online(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    engine = ArchiveJobEngine(provider, tmp_path)
    def fail_manifest(*args, **kwargs):
        raise OSError(errno.EIO, 'synthetic manifest write failure')
    engine.manifest.upsert_verified = fail_manifest
    result = engine.run(['inbox'])
    aid = _first_archive_id(result)
    assert result == [(aid, 'FAILED')]
    assert CleanupService(provider, tmp_path).move_verified([aid]) == [(aid, 'SKIPPED_NOT_VERIFIED')]
    assert provider.moves == []


def test_database_final_verification_commit_failure_blocks_cleanup(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    # Install a deterministic fault at the exact transition to VERIFIED.
    db = connect(tmp_path)
    with db:
        db.executescript('''
        CREATE TRIGGER block_verified_update
        BEFORE UPDATE OF verification_status ON messages
        WHEN NEW.verification_status='VERIFIED'
        BEGIN
          SELECT RAISE(ABORT, 'synthetic verification commit failure');
        END;
        ''')
    db.close()
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox'])
    aid = _first_archive_id(result)
    db = connect(tmp_path)
    state = db.execute('SELECT verification_status FROM messages WHERE archive_id=?', (aid,)).fetchone()['verification_status']
    db.close()
    assert state == 'FAILED'
    # A manifest record may already exist, but DB state is authoritative and must fail closed.
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert aid in manifest['messages']
    assert CleanupService(provider, tmp_path).move_verified([aid]) == [(aid, 'SKIPPED_NOT_VERIFIED')]
    assert provider.moves == []


def test_hash_mismatch_during_write_never_becomes_cleanup_eligible(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    engine = ArchiveJobEngine(provider, tmp_path)
    original = engine.mime_store.write_atomic
    def corrupt(archive_id, data):
        path = original(archive_id, data)
        path.write_bytes(data + b'CORRUPTED')
        return path
    engine.mime_store.write_atomic = corrupt
    result = engine.run(['inbox'])
    aid = _first_archive_id(result)
    assert result[0][1] == 'FAILED'
    CleanupService(provider, tmp_path).move_verified([aid])
    assert provider.moves == []


def test_disk_full_stops_job_at_safe_boundary_and_never_moves_mail(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(8))
    engine = ArchiveJobEngine(provider, tmp_path)
    calls = {'n': 0}
    original = engine.mime_store.write_atomic
    def disk_full(archive_id, data):
        calls['n'] += 1
        if calls['n'] == 2:
            raise OSError(errno.ENOSPC, 'No space left on device')
        return original(archive_id, data)
    engine.mime_store.write_atomic = disk_full
    result = engine.run(['inbox', 'sentitems'], job_id='disk-full')
    assert len(result) == 2
    assert result[0][1] == 'VERIFIED'
    assert result[1][1] == 'FAILED'
    db = connect(tmp_path)
    status = db.execute("SELECT status FROM archive_jobs WHERE job_id='disk-full'").fetchone()['status']
    verified = db.execute("SELECT archive_id FROM messages WHERE verification_status='VERIFIED'").fetchall()
    db.close()
    assert status == 'PARTIAL'
    assert len(verified) == 1
    out = CleanupService(provider, tmp_path).move_verified([row['archive_id'] for row in verified])
    # Scope requirement: storage failure blocks cleanup for the entire incomplete job,
    # even items verified before the disk became unavailable.
    assert out == [(verified[0]['archive_id'], 'SKIPPED_NOT_VERIFIED')]
    assert provider.moves == []


def test_successful_resume_after_disk_full_clears_archive_cleanup_block(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(4))
    engine = ArchiveJobEngine(provider, tmp_path)
    original = engine.mime_store.write_atomic
    calls = {'n': 0}
    def disk_full_once(archive_id, data):
        calls['n'] += 1
        if calls['n'] == 2:
            raise OSError(errno.ENOSPC, 'No space left on device')
        return original(archive_id, data)
    engine.mime_store.write_atomic = disk_full_once
    first = engine.run(['inbox', 'sentitems'], job_id='disk-resume')
    assert any(status == 'FAILED' for _, status in first)
    assert CleanupService(provider, tmp_path).move_verified([first[0][0]])[0][1] == 'SKIPPED_NOT_VERIFIED'
    assert provider.moves == []

    # Resume same immutable job parameters with healthy storage. The checkpoint clears
    # the storage stop only after the job reaches COMPLETED.
    second = ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], job_id='disk-resume')
    assert all(status in {'VERIFIED', 'SKIPPED_VERIFIED'} for _, status in second)
    db = connect(tmp_path)
    job = db.execute("SELECT status,stop_reason FROM archive_jobs WHERE job_id='disk-resume'").fetchone()
    verified_ids = [r['archive_id'] for r in db.execute("SELECT archive_id FROM messages WHERE verification_status='VERIFIED' ORDER BY archive_id")]
    db.close()
    assert job['status'] == 'COMPLETED'
    assert job['stop_reason'] == ''
    moved = CleanupService(provider, tmp_path).move_verified(verified_ids[:1])
    assert moved[0][1] == 'MOVED'


def test_attachment_extraction_failure_never_becomes_cleanup_eligible(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    engine = ArchiveJobEngine(provider, tmp_path)

    def fail_extract(*args, **kwargs):
        raise OSError(errno.EIO, 'synthetic attachment accounting failure')

    engine.attachments.extract = fail_extract
    result = engine.run(['inbox'], job_id='attachment-failure')
    aid = result[0][0]
    assert result[0][1] == 'FAILED'
    assert CleanupService(provider, tmp_path).move_verified([aid]) == [(aid, 'SKIPPED_NOT_VERIFIED')]
    assert provider.moves == []


def test_process_crash_between_mime_write_and_verification_leaves_mail_online(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    engine = ArchiveJobEngine(provider, tmp_path)
    original = engine.mime_store.write_atomic

    def crash_after_write(archive_id, data):
        original(archive_id, data)
        raise SystemExit('synthetic process crash immediately after local MIME write')

    engine.mime_store.write_atomic = crash_after_write
    try:
        engine.run(['inbox'], job_id='crash-after-write')
    except SystemExit:
        pass
    else:
        raise AssertionError('synthetic crash did not escape archive engine')

    db = connect(tmp_path)
    job = db.execute("SELECT status FROM archive_jobs WHERE job_id='crash-after-write'").fetchone()
    verified = db.execute("SELECT COUNT(*) c FROM messages WHERE verification_status='VERIFIED'").fetchone()['c']
    db.close()
    assert job['status'] == 'INTERRUPTED'
    assert verified == 0
    assert provider.moves == []
