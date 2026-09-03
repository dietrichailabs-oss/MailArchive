import shutil
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.integrity.verify_archive import ArchiveIntegrityVerifier
from mailarchive.search.service import search


def test_archive_integrity_and_moved_archive(tmp_path):
    src=tmp_path/'source'; dst=tmp_path/'moved'
    ArchiveJobEngine(FakeMailboxProvider(),src).run(['inbox'])
    assert ArchiveIntegrityVerifier(src).verify()['status']=='HEALTHY'
    shutil.copytree(src,dst)
    assert ArchiveIntegrityVerifier(dst).verify()['status']=='HEALTHY'
    assert search(dst,'Subject')
