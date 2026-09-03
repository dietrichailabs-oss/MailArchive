from mailarchive.archive.manager import ArchiveRegistry
from mailarchive.archive.planning import ArchivePlanner
from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.providers.fake_mailbox import FakeMailboxProvider


def test_preview_counts_selected_folders_without_mailbox_modification(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(10), page_size=3)
    preview = ArchivePlanner(provider).preview(['inbox'], None, None, tmp_path / 'archive')
    assert preview.message_count == 5
    assert preview.estimated_bytes is not None
    assert provider.moves == []
    assert preview.cleanup_behavior.startswith('Archive Only')


def test_archive_registry_remove_does_not_delete_archive(tmp_path):
    archive = tmp_path / 'archive'
    archive.mkdir()
    registry = ArchiveRegistry(tmp_path / 'app' / 'archives.json')
    registry.register(archive)
    assert registry.list_archives()[0]['exists'] is True
    registry.remove_from_list(archive)
    assert archive.exists()
    assert registry.list_archives() == []


def test_preview_rejects_destination_that_is_an_existing_file(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    destination = tmp_path / 'not-a-folder'
    destination.write_text('occupied', encoding='utf-8')
    preview = ArchivePlanner(provider).preview(['inbox'], None, None, destination)
    assert preview.destination_writable is False
    assert 'not a directory' in preview.destination_error
    assert provider.moves == []


def test_controller_refuses_invalid_destination_before_mime_download(tmp_path):
    from mailarchive.application.controller import ArchiveSelection, MailArchiveController
    from mailarchive.archive.planning import ArchiveDestinationError

    class CountingProvider(FakeMailboxProvider):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.mime_downloads = 0

        def get_message_mime(self, provider_id):
            self.mime_downloads += 1
            return super().get_message_mime(provider_id)

    provider = CountingProvider(messages=FakeMailboxProvider.synthetic_messages(2))
    destination = tmp_path / 'occupied'
    destination.write_text('not a directory', encoding='utf-8')
    controller = MailArchiveController(provider)
    selection = ArchiveSelection(('inbox',), None, None, destination)
    try:
        controller.run_archive(selection)
    except ArchiveDestinationError:
        pass
    else:
        raise AssertionError('invalid destination was accepted')
    assert provider.mime_downloads == 0
    assert provider.moves == []


def test_archive_folder_name_is_stable_for_date_shapes():
    from mailarchive.archive.planning import archive_folder_name

    assert archive_folder_name('2025-01-01', '2025-12-31') == '2025-01-01_to_2025-12-31'
    assert archive_folder_name(None, '2025-09-01') == 'through_2025-09-01'
    assert archive_folder_name('2025-09-01', None) == 'from_2025-09-01'
    assert archive_folder_name(None, None) == 'all_mail'


def test_resolve_archive_root_reuses_same_verified_account_and_date_range_archive(tmp_path):
    from mailarchive.archive.planning import resolve_archive_root

    parent = tmp_path / 'Mail Archives'
    root = parent / '2025-01-01_to_2025-12-31'
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(2))
    ArchiveJobEngine(provider, root).run(['inbox'], '2025-01-01', '2025-12-31')

    before = {
        name: (root / name).read_bytes()
        for name in ('archive.db', 'manifest.json', 'archive_info.json')
    }
    repeated = resolve_archive_root(
        parent, '2025-01-01', '2025-12-31', account_metadata=provider.get_account_metadata()
    )
    assert repeated == root
    after = {name: (root / name).read_bytes() for name in before}
    assert after == before  # destination resolution is strictly read-only


def test_resolve_archive_root_does_not_mix_different_mailbox_account(tmp_path):
    from mailarchive.archive.planning import resolve_archive_root

    parent = tmp_path / 'Mail Archives'
    root = parent / '2025-01-01_to_2025-12-31'
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    ArchiveJobEngine(provider, root).run(['inbox'], '2025-01-01', '2025-12-31')

    resolved = resolve_archive_root(
        parent, '2025-01-01', '2025-12-31',
        account_metadata={'account_id': 'different@example.test', 'principal_hint': 'different@example.test'},
    )
    assert resolved == parent / '2025-01-01_to_2025-12-31_2'


def test_resolve_archive_root_does_not_reuse_corrupt_or_unknown_archive_markers(tmp_path):
    from mailarchive.archive.planning import resolve_archive_root

    parent = tmp_path / 'Mail Archives'
    root = parent / '2025-01-01_to_2025-12-31'
    root.mkdir(parents=True)
    (root / 'archive.db').write_bytes(b'not sqlite')
    (root / 'manifest.json').write_text('{broken', encoding='utf-8')

    resolved = resolve_archive_root(
        parent, '2025-01-01', '2025-12-31',
        account_metadata={'account_id': 'synthetic@example.test'},
    )
    assert resolved == parent / '2025-01-01_to_2025-12-31_2'


def test_resolve_archive_root_does_not_reuse_archive_with_different_date_metadata(tmp_path):
    from mailarchive.archive.planning import resolve_archive_root

    parent = tmp_path / 'Mail Archives'
    root = parent / '2025-01-01_to_2025-12-31'
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    # Deliberately create a valid archive whose on-disk directory name lies about its range.
    ArchiveJobEngine(provider, root).run(['inbox'], '2024-01-01', '2024-12-31')

    resolved = resolve_archive_root(
        parent, '2025-01-01', '2025-12-31', account_metadata=provider.get_account_metadata()
    )
    assert resolved == parent / '2025-01-01_to_2025-12-31_2'


def test_resolve_archive_root_never_overwrites_unrelated_nonempty_folder(tmp_path):
    from mailarchive.archive.planning import resolve_archive_root

    parent = tmp_path / 'Mail Archives'
    collision = parent / '2025-01-01_to_2025-12-31'
    collision.mkdir(parents=True)
    (collision / 'unrelated.txt').write_text('do not touch', encoding='utf-8')

    resolved = resolve_archive_root(parent, '2025-01-01', '2025-12-31')
    assert resolved == parent / '2025-01-01_to_2025-12-31_2'
    assert (collision / 'unrelated.txt').read_text(encoding='utf-8') == 'do not touch'


def test_registry_distinguishes_archive_registration_from_actual_open(tmp_path):
    archive = tmp_path / 'archive'
    archive.mkdir()
    registry = ArchiveRegistry(tmp_path / 'registry.json')
    registry.register(archive, opened=False)
    row = registry.list_archives()[0]
    assert 'last_opened' not in row

    registry.register(archive, opened=True)
    row = registry.list_archives()[0]
    assert row['last_opened']
