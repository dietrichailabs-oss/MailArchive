import pytest
from mailarchive.providers.fake_mailbox import FakeMailboxProvider, FakeFaults
from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.cleanup.mailbox_actions import CleanupService
from mailarchive.database.connection import connect

@pytest.mark.parametrize('fault_name', ['download_fail','partial_download','corrupt_mime','network_fail','auth_expire','disappear'])
def test_unverified_never_moves(tmp_path, fault_name):
    faults=FakeFaults(); getattr(faults,fault_name).add('msg-0')
    p=FakeMailboxProvider(faults=faults)
    r=ArchiveJobEngine(p,tmp_path).run(['inbox'])
    aid=[a for a,s in r if a][0]
    CleanupService(p,tmp_path).move_verified([aid])
    assert 'msg-0' not in p.moves


def test_verified_can_move_only_after_verification(tmp_path):
    p=FakeMailboxProvider()
    r=ArchiveJobEngine(p,tmp_path).run(['inbox'])
    verified=[a for a,s in r if s=='VERIFIED']
    out=CleanupService(p,tmp_path).move_verified(verified[:1])
    assert out[0][1]=='MOVED'
    assert len(p.moves)==1


def test_arbitrary_archive_id_cannot_move(tmp_path):
    p=FakeMailboxProvider()
    out=CleanupService(p,tmp_path).move_verified(['attacker-controlled'])
    assert out==[('attacker-controlled','SKIPPED_NOT_VERIFIED')]
    assert p.moves==[]


def test_failed_db_state_is_ineligible(tmp_path):
    p=FakeMailboxProvider()
    db=connect(tmp_path)
    with db:
        db.execute("INSERT INTO messages(archive_id,provider_id,verification_status) VALUES('x','msg-0','FAILED')")
        db.execute("INSERT INTO cleanup_state(archive_id,provider_id_at_archive,status) VALUES('x','msg-0','NOT_ATTEMPTED')")
    db.close()
    out=CleanupService(p,tmp_path).move_verified(['x'])
    assert out[0][1]=='SKIPPED_NOT_VERIFIED'
    assert p.moves==[]
