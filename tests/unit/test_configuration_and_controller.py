import json

from mailarchive.application.controller import ArchiveSelection, MailArchiveController
from mailarchive.archive.manager import ArchiveRegistry
from mailarchive.configuration.settings import AppSettings, SettingsStore
from mailarchive.domain.models import MessageRef, ProviderMessage
from mailarchive.providers.fake_mailbox import FakeMailboxProvider


def test_settings_roundtrip_contains_no_auth_material(tmp_path):
    path = tmp_path / 'settings.json'
    store = SettingsStore(path)
    store.save(AppSettings(last_archive_destination='D:/Mail', preferred_folder_ids=['inbox']))
    raw = path.read_text(encoding='utf-8')
    assert 'token' not in raw.casefold()
    loaded = store.load()
    assert loaded.last_archive_destination == 'D:/Mail'
    assert loaded.preferred_folder_ids == ['inbox']


def test_controller_preview_and_archive_default_to_no_mailbox_mutation(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(4))
    registry = ArchiveRegistry(tmp_path / 'registry.json')
    controller = MailArchiveController(provider, registry=registry)
    archive_root = tmp_path / 'archive'
    selection = ArchiveSelection(('inbox',), '2026-01-01', '2026-01-28', archive_root)
    preview = controller.preview(selection)
    assert preview.cleanup_behavior.startswith('Archive Only')
    assert provider.moves == []
    result = controller.run_archive(selection)
    assert result.discovered == 2
    assert result.processed == 2
    assert result.verified == 2
    assert result.failed == 0
    assert result.archive_size_bytes > 0
    assert provider.moves == []
    assert registry.list_archives()[0]['exists'] is True


def test_cleanup_plan_reports_exact_eligible_count_and_never_permanent_delete(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(2))
    controller = MailArchiveController(provider)
    selection = ArchiveSelection(('inbox',), None, None, tmp_path / 'archive')
    controller.run_archive(selection)
    plan = controller.cleanup_plan(selection.destination)
    assert plan.verified_eligible_count == 1
    assert plan.permanent_delete is False
    assert plan.folders == ('Inbox',)
    assert 'Deleted Items' in plan.action
    assert 'continue counting' in plan.quota_notice


def test_cleanup_requires_separately_write_capable_provider(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    controller = MailArchiveController(provider)
    selection = ArchiveSelection(('inbox',), None, None, tmp_path / 'archive')
    controller.run_archive(selection)
    plan = controller.cleanup_plan(selection.destination)

    class ReadOnly(FakeMailboxProvider):
        def get_capabilities(self):
            return {'read': True, 'cleanup': False}

    read_only = ReadOnly(messages=list(provider.messages.values()))
    try:
        controller.execute_cleanup(selection.destination, plan.archive_ids, cleanup_provider=read_only)
    except PermissionError:
        pass
    else:
        raise AssertionError('read-only provider was allowed to perform cleanup')
    assert read_only.moves == []


def test_cleanup_report_contains_hashes_and_no_quota_claim(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    controller = MailArchiveController(provider)
    selection = ArchiveSelection(('inbox',), None, None, tmp_path / 'archive')
    controller.run_archive(selection)
    plan = controller.cleanup_plan(selection.destination)
    results = controller.execute_cleanup(
        selection.destination,
        plan.archive_ids,
        cleanup_provider=provider,
        metadata={'date_range': {'start': None, 'end': None}, 'folders': ['inbox']},
    )
    assert results[0][1] == 'MOVED'
    report = json.loads((selection.destination / 'reports' / 'cleanup_report.json').read_text(encoding='utf-8'))
    assert report['permanent_deletion_performed'] is False
    assert report['items'][0]['sha256']
    assert 'reclaimed' not in report['mailbox_quota_notice'].casefold()


def test_cleanup_job_and_report_account_partial_move_without_duplicate_attempts(tmp_path):
    from mailarchive.database.connection import connect
    from mailarchive.providers.fake_mailbox import FakeFaults

    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(4))
    controller = MailArchiveController(provider)
    selection = ArchiveSelection(('inbox', 'sentitems'), None, None, tmp_path / 'archive')
    controller.run_archive(selection)
    plan = controller.cleanup_plan(selection.destination)
    assert len(plan.archive_ids) == 4

    # Fail one mailbox move and duplicate another archive ID in the caller request.
    first_pid = provider.messages['msg-0'].ref.provider_id
    failing_pid = provider.messages['msg-1'].ref.provider_id
    provider.faults = FakeFaults(move_fail={failing_pid})
    requested = [plan.archive_ids[0], plan.archive_ids[0], *plan.archive_ids[1:]]
    results = controller.execute_cleanup(selection.destination, requested, cleanup_provider=provider)
    assert len(results) == len(plan.archive_ids)
    assert sum(status == 'MOVED' for _, status in results) == 3
    assert sum(status == 'UNKNOWN_MOVE_OUTCOME' for _, status in results) == 1
    assert provider.moves.count(first_pid) <= 1

    db = connect(selection.destination)
    job = db.execute('SELECT * FROM cleanup_jobs ORDER BY started_at DESC LIMIT 1').fetchone()
    db.close()
    assert job['status'] == 'RECONCILIATION_REQUIRED'
    assert job['requested_count'] == 4
    assert job['moved_count'] == 3
    assert job['failed_count'] == 0
    assert job['unknown_count'] == 1

    report = json.loads((selection.destination / 'reports' / 'cleanup_report.json').read_text(encoding='utf-8'))
    assert report['cleanup_job_id'] == job['cleanup_job_id']
    assert report['requested_count'] == 4
    assert report['successfully_moved'] == 3
    assert report['failed'] == 0
    assert report['unknown_move_outcome'] == 1
    assert 'will not retry' in report['reconciliation_notice']
    assert report['permanent_deletion_performed'] is False
    assert report['source_account']['account_id'] == 'fake-account'


def test_controller_resume_reuses_job_and_completes_without_mailbox_mutation(tmp_path):
    from mailarchive.providers.fake_mailbox import FakeFaults

    provider = FakeMailboxProvider(
        messages=FakeMailboxProvider.synthetic_messages(4),
        faults=FakeFaults(network_fail={'msg-2'}),
    )
    controller = MailArchiveController(provider)
    selection = ArchiveSelection(('inbox',), None, None, tmp_path / 'archive')

    first = controller.run_archive(selection)
    assert first.status == 'INTERRUPTED'
    assert first.resumable is True
    assert first.completed is False
    assert provider.moves == []

    provider.faults.network_fail.clear()
    resumed = controller.run_archive(selection, job_id=first.job_id)
    assert resumed.job_id == first.job_id
    assert resumed.status == 'COMPLETED'
    assert resumed.completed is True
    assert resumed.resumable is False
    assert resumed.verified == 2
    assert provider.moves == []


def test_controller_result_reports_repeated_verified_messages_as_skipped(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(2))
    controller = MailArchiveController(provider)
    selection = ArchiveSelection(('inbox',), None, None, tmp_path / 'archive')
    first = controller.run_archive(selection)
    assert first.verified == 1
    assert first.skipped == 0

    second = controller.run_archive(selection)
    assert second.status == 'COMPLETED'
    assert second.verified == 1  # archive-level verified total remains stable
    assert second.skipped == 1
    assert provider.moves == []


def test_archiving_registers_archive_without_falsely_marking_it_opened(tmp_path, monkeypatch):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    registry = ArchiveRegistry(tmp_path / 'registry.json')
    controller = MailArchiveController(provider, registry=registry)
    selection = ArchiveSelection(('inbox',), None, None, tmp_path / 'archive')
    controller.run_archive(selection)
    assert 'last_opened' not in registry.list_archives()[0]

    monkeypatch.setattr('mailarchive.application.controller.launch_archive', lambda *args, **kwargs: 'opened')
    assert controller.open_archive(selection.destination) == 'opened'
    assert registry.list_archives()[0]['last_opened']
