from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.cleanup.mailbox_actions import CleanupService
from mailarchive.database.connection import connect
from mailarchive.providers.fake_mailbox import FakeMailboxProvider, FakeFaults


def test_auth_expiration_interrupts_job_at_safe_boundary_and_is_resumable(tmp_path):
    provider = FakeMailboxProvider(
        messages=FakeMailboxProvider.synthetic_messages(4),
        faults=FakeFaults(auth_expire={'msg-0'}),
    )
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], job_id='auth-expire')
    assert result[0][1] == 'INTERRUPTED'
    assert provider.moves == []
    db = connect(tmp_path)
    job = db.execute("SELECT status,stop_reason FROM archive_jobs WHERE job_id='auth-expire'").fetchone()
    db.close()
    assert job['status'] == 'INTERRUPTED'
    assert job['stop_reason'] == 'AuthenticationRequired'

    provider.faults.auth_expire.clear()
    resumed = ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], job_id='auth-expire')
    assert all(status in {'VERIFIED', 'SKIPPED_VERIFIED'} for _, status in resumed)


def test_network_loss_interrupts_instead_of_falsely_marking_message_permanently_failed(tmp_path):
    provider = FakeMailboxProvider(
        messages=FakeMailboxProvider.synthetic_messages(4),
        faults=FakeFaults(network_fail={'msg-0'}),
    )
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'], job_id='net-loss')
    assert result[0][1] == 'INTERRUPTED'
    db = connect(tmp_path)
    row = db.execute("SELECT status,stop_reason FROM archive_jobs WHERE job_id='net-loss'").fetchone()
    failed = db.execute("SELECT COUNT(*) c FROM messages WHERE verification_status='FAILED'").fetchone()['c']
    db.close()
    assert row['status'] == 'INTERRUPTED'
    assert row['stop_reason'] == 'NetworkUnavailable'
    assert failed == 0
    assert provider.moves == []


def test_read_only_destination_failure_blocks_all_cleanup(tmp_path):
    import errno
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(3))
    engine = ArchiveJobEngine(provider, tmp_path)
    original = engine.mime_store.write_atomic
    calls = {'n': 0}
    def read_only_after_first(archive_id, data):
        calls['n'] += 1
        if calls['n'] == 2:
            raise OSError(errno.EROFS, 'synthetic read-only destination')
        return original(archive_id, data)
    engine.mime_store.write_atomic = read_only_after_first
    result = engine.run(['inbox', 'sentitems'], job_id='readonly')
    assert result[0][1] == 'VERIFIED'
    assert result[1][1] == 'FAILED'
    out = CleanupService(provider, tmp_path).move_verified([result[0][0]])
    assert out[0][1] == 'SKIPPED_NOT_VERIFIED'
    assert provider.moves == []


def test_controller_never_reports_provider_interruption_as_completed(tmp_path):
    from mailarchive.application.controller import ArchiveSelection, MailArchiveController

    provider = FakeMailboxProvider(
        messages=FakeMailboxProvider.synthetic_messages(4),
        faults=FakeFaults(network_fail={'msg-0'}),
    )
    controller = MailArchiveController(provider)
    selection = ArchiveSelection(('inbox', 'sentitems'), None, None, tmp_path / 'archive')
    result = controller.run_archive(selection, job_id='controller-interrupt')

    assert result.status == 'INTERRUPTED'
    assert result.interrupted is True
    assert result.completed is False
    assert result.failed == 0
    assert result.cancelled is False
    assert result.stop_reason == 'NetworkUnavailable'
    assert provider.moves == []
