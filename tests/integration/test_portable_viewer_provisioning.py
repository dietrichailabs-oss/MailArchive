import json

from mailarchive.application.controller import ArchiveSelection, MailArchiveController
from mailarchive.archive.hashing import sha256_file
from mailarchive.providers.fake_mailbox import FakeMailboxProvider


def test_finished_archive_gets_standalone_viewer_from_packaged_runtime(tmp_path):
    viewer = tmp_path / 'packaged-viewer.exe'
    viewer.write_bytes(b'MZ' + b'fake-engineering-viewer-binary')
    archive = tmp_path / 'archive'
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    controller = MailArchiveController(provider, portable_viewer_source=viewer)
    result = controller.run_archive(ArchiveSelection(('inbox',), None, None, archive))
    target = archive / 'Open Archive.exe'
    assert result.portable_viewer_ready is True
    assert target.read_bytes() == viewer.read_bytes()
    info = json.loads((archive / 'archive_info.json').read_text(encoding='utf-8'))
    assert info['portable_viewer']['relative_path'] == 'Open Archive.exe'
    assert info['portable_viewer']['sha256'] == sha256_file(target)
