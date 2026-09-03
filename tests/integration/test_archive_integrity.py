import json
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.archive.hashing import sha256_file
from mailarchive.database.connection import connect


def test_eml_hash_manifest_db_agree(tmp_path):
    p=FakeMailboxProvider()
    r=ArchiveJobEngine(p,tmp_path).run(['inbox'])
    aid=next(a for a,s in r if s=='VERIFIED')
    db=connect(tmp_path); row=db.execute('SELECT * FROM messages WHERE archive_id=?',(aid,)).fetchone(); db.close()
    manifest=json.loads((tmp_path/'manifest.json').read_text())['messages'][aid]
    assert row['verification_status']=='VERIFIED'
    assert sha256_file(tmp_path/row['eml_path']) == row['sha256'] == manifest['sha256']


def test_repeated_run_skips_verified(tmp_path):
    p=FakeMailboxProvider()
    e=ArchiveJobEngine(p,tmp_path)
    first=e.run(['inbox']); second=ArchiveJobEngine(p,tmp_path).run(['inbox'])
    assert all(s=='VERIFIED' for _,s in first)
    assert all(s=='SKIPPED_VERIFIED' for _,s in second)


def test_cancel_before_run_never_moves(tmp_path):
    p=FakeMailboxProvider(); e=ArchiveJobEngine(p,tmp_path); e.cancel()
    r=e.run(['inbox'])
    assert r[0][1]=='CANCELLED'; assert p.moves==[]


def test_truncated_multipart_with_missing_close_boundary_never_verifies(tmp_path):
    from mailarchive.archive.job_engine import ArchiveJobEngine
    from mailarchive.domain.models import MessageRef, ProviderMessage
    from mailarchive.providers.fake_mailbox import FakeMailboxProvider

    class TruncatedMultipartProvider(FakeMailboxProvider):
        def get_message_mime(self, provider_id):
            return (
                b'From: a@x\r\nSubject: partial\r\nContent-Type: multipart/mixed; boundary=abc\r\n\r\n'
                b'--abc\r\nContent-Type: text/plain\r\n\r\nbody\r\n'
            )

    message = ProviderMessage(MessageRef('truncated', 'inbox', '<truncated@x>'), 'partial', 'a@x', [], '2026-01-01T00:00:00Z')
    provider = TruncatedMultipartProvider(messages=[message])
    assert ArchiveJobEngine(provider, tmp_path).run(['inbox'])[0][1] == 'FAILED'
