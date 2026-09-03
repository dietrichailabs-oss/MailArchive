from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.database.connection import connect
from mailarchive.database.migrations import LATEST_SCHEMA_VERSION
from mailarchive.providers.fake_mailbox import FakeMailboxProvider


def test_v1_required_structural_tables_exist(tmp_path):
    db = connect(tmp_path)
    version = db.execute('PRAGMA user_version').fetchone()[0]
    names = {r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    db.close()
    assert version == LATEST_SCHEMA_VERSION == 5
    columns = {r['name'] for r in connect(tmp_path).execute('PRAGMA table_info(cleanup_jobs)')}
    assert 'unknown_count' in columns
    for name in {'archive_metadata','accounts','folders','messages','recipients','attachments','archive_jobs','archive_job_items','hashes','verification','cleanup_state','cleanup_jobs','errors','checkpoints'}:
        assert name in names


def test_verified_message_populates_recipient_and_hash_accounting(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox'])
    aid, status = result[0]
    assert status == 'VERIFIED'
    db = connect(tmp_path)
    recipients = db.execute('SELECT address FROM recipients WHERE archive_id=?', (aid,)).fetchall()
    hashes = db.execute('SELECT object_kind,relative_path,sha256 FROM hashes WHERE archive_id=?', (aid,)).fetchall()
    db.close()
    assert [r['address'] for r in recipients] == ['to@example.test']
    assert any(r['object_kind'] == 'MIME' and r['sha256'] for r in hashes)
