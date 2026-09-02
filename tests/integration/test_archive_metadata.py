import json

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.database.connection import connect


def test_archive_info_and_manifest_metadata_are_portable_relative(tmp_path):
    ArchiveJobEngine(FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(4)), tmp_path).run(['inbox', 'sentitems'], '2026-01-01', '2026-01-28')
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    info = json.loads((tmp_path / 'archive_info.json').read_text(encoding='utf-8'))
    assert manifest['verified_count'] == 4
    assert info['message_count'] == 4
    assert info['selected_date_range']['inclusive'] is True
    assert all(not row['eml_relative_path'].startswith(('C:', '/', '\\')) for row in manifest['messages'].values())


def test_repeated_same_range_jobs_preserve_creation_time_and_union_selected_folders(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(6))
    engine = ArchiveJobEngine(provider, tmp_path)
    engine.run(['inbox'], '2026-01-01', '2026-01-28')
    first = json.loads((tmp_path / 'archive_info.json').read_text(encoding='utf-8'))

    ArchiveJobEngine(provider, tmp_path).run(['sentitems'], '2026-01-01', '2026-01-28')
    second = json.loads((tmp_path / 'archive_info.json').read_text(encoding='utf-8'))

    assert second['archive_creation_timestamp'] == first['archive_creation_timestamp']
    assert set(second['selected_folders']) == {'inbox', 'sentitems'}
    assert {row['id'] for row in second['selected_folder_details']} == {'inbox', 'sentitems'}
    assert second['verified_count'] == 6
    assert second['message_count'] == 6


def test_core_engine_refuses_cross_account_or_cross_range_archive_mixing_before_download(tmp_path):
    from mailarchive.archive.job_engine import ArchiveIdentityMismatch

    class CountingProvider(FakeMailboxProvider):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.mime_downloads = 0

        def get_message_mime(self, provider_id):
            self.mime_downloads += 1
            return super().get_message_mime(provider_id)

    first = CountingProvider(
        messages=FakeMailboxProvider.synthetic_messages(2),
        account_metadata={'account_id': 'account-a', 'principal_hint': 'a@example.test'},
    )
    ArchiveJobEngine(first, tmp_path).run(['inbox'], '2026-01-01', '2026-01-31')

    other_account = CountingProvider(
        messages=FakeMailboxProvider.synthetic_messages(2),
        account_metadata={'account_id': 'account-b', 'principal_hint': 'b@example.test'},
    )
    try:
        ArchiveJobEngine(other_account, tmp_path).run(['inbox'], '2026-01-01', '2026-01-31')
    except ArchiveIdentityMismatch:
        pass
    else:
        raise AssertionError('cross-account archive mixing was accepted')
    assert other_account.mime_downloads == 0
    assert other_account.moves == []

    other_range = CountingProvider(
        messages=FakeMailboxProvider.synthetic_messages(2),
        account_metadata={'account_id': 'account-a', 'principal_hint': 'a@example.test'},
    )
    try:
        ArchiveJobEngine(other_range, tmp_path).run(['inbox'], '2025-01-01', '2025-12-31')
    except ArchiveIdentityMismatch:
        pass
    else:
        raise AssertionError('cross-range archive mixing was accepted')
    assert other_range.mime_downloads == 0
    assert other_range.moves == []


def test_repeated_run_preserves_legacy_archive_creation_timestamp_when_db_key_is_missing(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(2))
    ArchiveJobEngine(provider, tmp_path).run(['inbox'], '2026-01-01', '2026-01-28')
    first = json.loads((tmp_path / 'archive_info.json').read_text(encoding='utf-8'))
    db = connect(tmp_path)
    with db:
        db.execute("DELETE FROM archive_metadata WHERE key='archive_created_at'")
    db.close()

    ArchiveJobEngine(provider, tmp_path).run(['sentitems'], '2026-01-01', '2026-01-28')
    second = json.loads((tmp_path / 'archive_info.json').read_text(encoding='utf-8'))
    assert second['archive_creation_timestamp'] == first['archive_creation_timestamp']
