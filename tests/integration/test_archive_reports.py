import json

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.providers.fake_mailbox import FakeMailboxProvider, FakeFaults


def test_archive_report_distinguishes_partial_from_success(tmp_path):
    faults = FakeFaults(download_fail={'msg-0'})
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(3), faults=faults)
    ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], job_id='partial')
    report = json.loads((tmp_path / 'reports' / 'archive_report.json').read_text(encoding='utf-8'))
    assert report['status'] == 'PARTIAL'
    assert report['failures'] == 1
    assert report['messages_verified'] == 2
    assert report['cleanup_behavior'].startswith('Archive Only')
    assert report['mailbox_modified'] is False


def test_cancelled_archive_report_never_claims_complete(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(5))
    engine = ArchiveJobEngine(provider, tmp_path)
    original = provider.get_message_mime
    calls = {'n': 0}
    def cancel(provider_id):
        calls['n'] += 1
        value = original(provider_id)
        if calls['n'] == 1:
            engine.cancel()
        return value
    provider.get_message_mime = cancel
    engine.run(['inbox', 'sentitems'], job_id='cancelled')
    report = json.loads((tmp_path / 'reports' / 'archive_report.json').read_text(encoding='utf-8'))
    assert report['status'] == 'CANCELLED'
    assert report['mailbox_modified'] is False


def test_cancelled_job_manifest_still_records_exact_selection(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(4))
    engine = ArchiveJobEngine(provider, tmp_path)
    original = provider.get_message_mime
    calls = {'n': 0}
    def cancel(provider_id):
        calls['n'] += 1
        raw = original(provider_id)
        if calls['n'] == 1:
            engine.cancel()
        return raw
    provider.get_message_mime = cancel
    engine.run(['inbox', 'sentitems'], '2026-01-01', '2026-01-31', job_id='cancel-meta')
    manifest = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['last_job_status'] == 'CANCELLED'
    assert manifest['selected_folders'] == ['inbox', 'sentitems']
    assert manifest['selected_date_range'] == {'start': '2026-01-01', 'end': '2026-01-31', 'inclusive': True}
