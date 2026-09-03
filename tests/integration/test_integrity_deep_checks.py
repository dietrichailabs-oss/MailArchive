from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.database.connection import connect
from mailarchive.integrity.verify_archive import ArchiveIntegrityVerifier
from mailarchive.providers.fake_mailbox import FakeMailboxProvider


def test_integrity_detects_search_manifest_and_hash_ledger_drift(tmp_path):
    result = ArchiveJobEngine(FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1)), tmp_path).run(['inbox'])
    aid = result[0][0]
    db = connect(tmp_path)
    with db:
        db.execute('DELETE FROM message_fts WHERE archive_id=?', (aid,))
        db.execute("DELETE FROM hashes WHERE archive_id=? AND object_kind='MIME'", (aid,))
    db.close()
    check = ArchiveIntegrityVerifier(tmp_path).verify()
    kinds = {issue['type'] for issue in check['issues']}
    assert check['status'] == 'DAMAGED'
    assert 'SEARCH_INDEX_RECORD_MISSING' in kinds
    assert 'MIME_HASH_ACCOUNTING_MISMATCH' in kinds


def test_integrity_detects_untracked_attachment_file_without_deleting_it(tmp_path):
    ArchiveJobEngine(FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1)), tmp_path).run(['inbox'])
    extra = tmp_path / 'attachments' / 'orphan' / 'leftover.bin'
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b'orphan')
    check = ArchiveIntegrityVerifier(tmp_path).verify()
    assert any(issue['type'] == 'UNTRACKED_ATTACHMENT_FILE' for issue in check['issues'])
    assert extra.exists()
