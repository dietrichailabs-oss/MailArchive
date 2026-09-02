import hashlib
import http.client

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.viewer.server import ArchiveViewer


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_opening_and_searching_viewer_do_not_modify_archive_database(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(3))
    ArchiveJobEngine(provider, tmp_path).run(['inbox', 'sentitems'])
    db_path = tmp_path / 'archive.db'
    before = digest(db_path)
    viewer = ArchiveViewer(tmp_path)
    host, port = viewer.start()
    assert host == '127.0.0.1'
    thread = __import__('threading').Thread(target=viewer.server.serve_forever, daemon=True)
    thread.start()
    try:
        for url in ['/', '/search?q=Subject', '/message?id=' + next(iter(__import__('json').loads((tmp_path/'manifest.json').read_text())['messages']))]:
            conn = http.client.HTTPConnection(host, port, timeout=3)
            conn.request('GET', url)
            response = conn.getresponse()
            response.read()
            assert response.status == 200
            conn.close()
    finally:
        viewer.server.shutdown()
        viewer.server.server_close()
        thread.join(timeout=3)
    after = digest(db_path)
    assert after == before
