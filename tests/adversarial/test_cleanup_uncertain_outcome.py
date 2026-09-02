from mailarchive.application.controller import ArchiveSelection, MailArchiveController
from mailarchive.cleanup.mailbox_actions import CleanupService
from mailarchive.database.connection import connect
from mailarchive.providers.contracts import NetworkUnavailable
from mailarchive.providers.fake_mailbox import FakeMailboxProvider


class MoveThenLoseResponseProvider(FakeMailboxProvider):
    """Simulate Microsoft accepting the move before the network response is lost."""

    def move_message_to_deleted_items(self, provider_id):
        super().move_message_to_deleted_items(provider_id)
        raise NetworkUnavailable('response lost after remote acceptance')


def _archive_one(tmp_path):
    source = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    controller = MailArchiveController(source)
    selection = ArchiveSelection(('inbox',), None, None, tmp_path / 'archive')
    controller.run_archive(selection)
    plan = controller.cleanup_plan(selection.destination)
    assert len(plan.archive_ids) == 1
    return source, selection.destination, plan.archive_ids[0]


def test_move_accepted_then_response_lost_is_never_automatically_retried(tmp_path):
    source, root, archive_id = _archive_one(tmp_path)
    uncertain = MoveThenLoseResponseProvider(messages=list(source.messages.values()))
    service = CleanupService(uncertain, root)

    first = service.move_verified([archive_id])
    assert first == [(archive_id, 'UNKNOWN_MOVE_OUTCOME')]
    assert len(uncertain.moves) == 1  # remote mutation may have happened

    db = connect(root)
    state = db.execute('SELECT status FROM cleanup_state WHERE archive_id=?', (archive_id,)).fetchone()['status']
    job = db.execute('SELECT * FROM cleanup_jobs WHERE cleanup_job_id=?', (service.last_job_id,)).fetchone()
    db.close()
    assert state == 'UNKNOWN_MOVE_OUTCOME'
    assert job['status'] == 'RECONCILIATION_REQUIRED'
    assert job['unknown_count'] == 1

    # A direct caller cannot bypass the uncertainty guard with the same archive ID.
    second = service.move_verified([archive_id])
    assert second == [(archive_id, 'UNKNOWN_MOVE_OUTCOME')]
    assert len(uncertain.moves) == 1
    assert CleanupService(uncertain, root).eligibility.eligible_archive_ids() == []


def test_confirmed_moved_state_cannot_be_reset_by_resubmitting_archive_id(tmp_path):
    source, root, archive_id = _archive_one(tmp_path)
    service = CleanupService(source, root)
    assert service.move_verified([archive_id]) == [(archive_id, 'MOVED')]
    assert source.moves.count('msg-0') == 1

    assert service.move_verified([archive_id]) == [(archive_id, 'SKIPPED_NOT_VERIFIED')]
    assert source.moves.count('msg-0') == 1
    db = connect(root)
    state = db.execute('SELECT status FROM cleanup_state WHERE archive_id=?', (archive_id,)).fetchone()['status']
    db.close()
    assert state == 'MOVED'


def test_local_confirmation_failure_after_remote_success_leaves_fail_closed_moving_state(tmp_path, monkeypatch):
    source, root, archive_id = _archive_one(tmp_path)
    service = CleanupService(source, root)
    original_record = service._record

    def fail_moved(aid, status, detail):
        if status == 'MOVED':
            raise OSError('disk failed after Graph success')
        return original_record(aid, status, detail)

    monkeypatch.setattr(service, '_record', fail_moved)
    first = service.move_verified([archive_id])
    assert first == [(archive_id, 'UNKNOWN_MOVE_OUTCOME')]
    assert source.moves.count('msg-0') == 1

    db = connect(root)
    state = db.execute('SELECT status FROM cleanup_state WHERE archive_id=?', (archive_id,)).fetchone()['status']
    db.close()
    assert state == 'MOVING'

    # New service instance still treats MOVING as uncertain and never repeats the move.
    again = CleanupService(source, root).move_verified([archive_id])
    assert again == [(archive_id, 'UNKNOWN_MOVE_OUTCOME')]
    assert source.moves.count('msg-0') == 1
