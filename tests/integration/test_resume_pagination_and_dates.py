import pytest

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.database.connection import connect
from mailarchive.providers.fake_mailbox import FakeMailboxProvider, FakeFaults


def test_fake_provider_paginates_and_archives_hundreds(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(250), page_size=17)
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'])
    assert len(result) == 250
    assert all(status == 'VERIFIED' for _, status in result)
    assert provider.discovery_pages == 15


def test_inclusive_date_boundaries(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(40), page_size=5)
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], '2026-01-05', '2026-01-05')
    assert result
    db = connect(tmp_path)
    rows = db.execute("SELECT received_ts FROM messages WHERE verification_status='VERIFIED'").fetchall()
    db.close()
    assert rows and all(row['received_ts'].startswith('2026-01-05') for row in rows)


def test_rate_limit_retries_then_verifies(tmp_path):
    faults = FakeFaults(rate_limit_once={'msg-0'})
    provider = FakeMailboxProvider(faults=faults)
    result = ArchiveJobEngine(provider, tmp_path, sleep=lambda _: None).run(['inbox'])
    assert any(status == 'VERIFIED' for _, status in result)
    assert 'msg-0' in provider._rate_limit_seen


def test_cancel_and_resume_same_job(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(12), page_size=3)
    first = ArchiveJobEngine(provider, tmp_path)
    original = provider.get_message_mime
    calls = {'n': 0}
    def cancel_after_three(provider_id):
        calls['n'] += 1
        raw = original(provider_id)
        if calls['n'] == 3:
            first.cancel()
        return raw
    provider.get_message_mime = cancel_after_three
    first_result = first.run(['inbox', 'sentitems'], job_id='resume-me')
    assert any(status == 'CANCELLED' for _, status in first_result)

    provider.get_message_mime = original
    second_result = ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], job_id='resume-me')
    assert all(status in {'VERIFIED', 'SKIPPED_VERIFIED'} for _, status in second_result)
    db = connect(tmp_path)
    job = db.execute("SELECT * FROM archive_jobs WHERE job_id='resume-me'").fetchone()
    count = db.execute("SELECT COUNT(*) c FROM messages WHERE verification_status='VERIFIED'").fetchone()['c']
    db.close()
    assert job['status'] == 'COMPLETED'
    assert count == 12


def test_resume_parameter_mismatch_is_rejected(tmp_path):
    provider = FakeMailboxProvider()
    ArchiveJobEngine(provider, tmp_path).run(['inbox'], job_id='same-id')
    with pytest.raises(ValueError):
        ArchiveJobEngine(provider, tmp_path).run(['sentitems'], job_id='same-id')


def test_discovery_network_interruption_is_checkpointed_and_resumable(tmp_path):
    from mailarchive.providers.contracts import NetworkUnavailable

    class InterruptingProvider(FakeMailboxProvider):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.fail_once = True
        def discover_messages(self, folder_ids, start, end):
            for index, message in enumerate(super().discover_messages(folder_ids, start, end)):
                if self.fail_once and index == 3:
                    self.fail_once = False
                    raise NetworkUnavailable('synthetic discovery interruption')
                yield message

    provider = InterruptingProvider(messages=FakeMailboxProvider.synthetic_messages(10), page_size=2)
    with pytest.raises(NetworkUnavailable):
        ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], job_id='net-resume')
    db = connect(tmp_path)
    status = db.execute("SELECT status FROM archive_jobs WHERE job_id='net-resume'").fetchone()['status']
    preserved = db.execute("SELECT COUNT(*) c FROM messages WHERE verification_status='VERIFIED'").fetchone()['c']
    db.close()
    assert status == 'INTERRUPTED'
    assert preserved == 3
    report = __import__('json').loads((tmp_path / 'reports' / 'archive_report.json').read_text(encoding='utf-8'))
    assert report['status'] == 'INTERRUPTED'
    assert report['mailbox_modified'] is False

    result = ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], job_id='net-resume')
    assert all(status in {'VERIFIED', 'SKIPPED_VERIFIED'} for _, status in result)
    db = connect(tmp_path)
    status = db.execute("SELECT status FROM archive_jobs WHERE job_id='net-resume'").fetchone()['status']
    count = db.execute("SELECT COUNT(*) c FROM messages WHERE verification_status='VERIFIED'").fetchone()['c']
    db.close()
    assert status == 'COMPLETED'
    assert count == 10
