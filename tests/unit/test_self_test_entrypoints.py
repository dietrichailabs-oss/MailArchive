from mailarchive.app import runtime_self_test
from mailarchive.viewer.launcher import self_test_archive
from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.providers.fake_mailbox import FakeMailboxProvider


def test_runtime_self_test_accepts_configured_client_id(monkeypatch):
    monkeypatch.setenv('MAILARCHIVE_CLIENT_ID', '00000000-0000-0000-0000-000000000001')
    runtime_self_test()


def test_viewer_self_test_is_offline_and_readonly(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(2))
    ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'])
    self_test_archive(tmp_path)
