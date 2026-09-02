import re
import threading
import urllib.error
import urllib.request

import pytest

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.database.connection import connect
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.viewer.server import ArchiveViewer


def _viewer(root):
    viewer = ArchiveViewer(root)
    host, port = viewer.start()
    thread = threading.Thread(target=viewer.server.serve_forever, daemon=True)
    thread.start()
    return viewer, thread, host, port


def test_tampered_eml_is_not_rendered_or_downloaded(tmp_path):
    ArchiveJobEngine(FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1)), tmp_path).run(['inbox'])
    db = connect(tmp_path)
    row = db.execute("SELECT archive_id,eml_path FROM messages WHERE verification_status='VERIFIED'").fetchone()
    db.close()
    (tmp_path / row['eml_path']).write_bytes(b'From: attacker@example\r\n\r\nchanged')
    viewer, thread, host, port = _viewer(tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as rendered:
            urllib.request.urlopen(f'http://{host}:{port}/message?id={row["archive_id"]}')
        assert rendered.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as original:
            urllib.request.urlopen(f'http://{host}:{port}/original/{row["archive_id"]}')
        assert original.value.code == 404
    finally:
        viewer.server.shutdown(); viewer.server.server_close(); thread.join(timeout=3)


def test_non_loopback_host_header_is_rejected(tmp_path):
    ArchiveJobEngine(FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1)), tmp_path).run(['inbox'])
    viewer, thread, host, port = _viewer(tmp_path)
    try:
        request = urllib.request.Request(f'http://{host}:{port}/', headers={'Host': 'attacker.example'})
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        assert caught.value.code == 421
    finally:
        viewer.server.shutdown(); viewer.server.server_close(); thread.join(timeout=3)
