from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.cleanup.eligibility import CleanupEligibilityService
from mailarchive.database.connection import connect
from mailarchive.integrity.verify_archive import ArchiveIntegrityVerifier
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.search.service import SearchQuery, search


def test_deterministic_edge_case_mailbox_archives_unicode_attachments_inline_and_large(tmp_path):
    provider = FakeMailboxProvider.edge_case_provider()
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], '2026-02-01', '2026-02-28')
    assert len(result) == 10
    assert all(status == 'VERIFIED' for _, status in result)
    assert provider.discovery_pages >= 4
    check = ArchiveIntegrityVerifier(tmp_path).verify()
    assert check['status'] == 'HEALTHY', check['issues']
    assert search(tmp_path, SearchQuery(subject='R\u00e9sum\u00e9'))
    assert search(tmp_path, SearchQuery(has_attachment=True))
    db = connect(tmp_path)
    attachment_count = db.execute('SELECT COUNT(*) c FROM attachments').fetchone()['c']
    max_size = db.execute('SELECT MAX(size) size FROM attachments').fetchone()['size']
    ambiguous = db.execute("SELECT COUNT(*) c FROM messages WHERE identity_ambiguous=1").fetchone()['c']
    db.close()
    assert attachment_count >= 3
    assert max_size >= 2 * 1024 * 1024
    # Duplicate Internet Message IDs are preserved but made cleanup-ambiguous.
    assert ambiguous >= 2


def test_archive_provenance_records_account_and_selected_folder_details(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(2))
    ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'])
    import json
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['source_account']['principal_hint'] == 'synthetic@example.test'
    assert {x['name'] for x in manifest['selected_folder_details']} == {'Inbox', 'Sent Items'}
    db = connect(tmp_path)
    assert db.execute('SELECT COUNT(*) c FROM accounts').fetchone()['c'] == 1
    assert db.execute('SELECT COUNT(*) c FROM folders').fetchone()['c'] == 2
    db.close()
