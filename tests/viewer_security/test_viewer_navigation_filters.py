import threading
import urllib.parse
import urllib.request

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.viewer.server import ArchiveViewer


def _running_viewer(root):
    viewer = ArchiveViewer(root)
    host, port = viewer.start()
    thread = threading.Thread(target=viewer.server.serve_forever, daemon=True)
    thread.start()
    return viewer, thread, f'http://{host}:{port}'


def test_viewer_exposes_required_search_filter_controls(tmp_path):
    ArchiveJobEngine(FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(8)), tmp_path).run(['inbox', 'sentitems'])
    viewer, thread, base = _running_viewer(tmp_path)
    try:
        response = urllib.request.urlopen(base + '/')
        page = response.read().decode('utf-8')
        for field in ('name="q"', 'name="subject"', 'name="sender"', 'name="recipient"',
                      'name="start"', 'name="end"', 'name="folder"', 'name="has_attachment"', 'name="sort"'):
            assert field in page
        assert "form-action 'self'" in response.headers['Content-Security-Policy']
    finally:
        viewer.server.shutdown(); viewer.server.server_close(); thread.join(timeout=3)


def test_viewer_filter_form_roundtrips_and_message_has_previous_next(tmp_path):
    ArchiveJobEngine(FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(8)), tmp_path).run(['inbox', 'sentitems'])
    viewer, thread, base = _running_viewer(tmp_path)
    try:
        query = urllib.parse.urlencode({
            'q': 'Subject', 'subject': 'Subject', 'sender': 'sender@example.test',
            'recipient': 'to@example.test', 'start': '2026-01-01', 'end': '2026-01-28',
            'folder': 'inbox', 'has_attachment': '', 'sort': 'oldest',
        })
        page = urllib.request.urlopen(base + '/search?' + query).read().decode('utf-8')
        assert 'value="sender@example.test"' in page
        assert '<option value="inbox" selected>' in page
        assert '<option value="inbox" selected>Inbox</option>' in page
        assert '<option value="oldest" selected>' in page

        listing = urllib.request.urlopen(base + '/').read().decode('utf-8')
        import re
        ids = re.findall(r'/message\?id=([0-9a-f]+)', listing)
        assert len(ids) >= 2
        message = urllib.request.urlopen(base + '/message?id=' + ids[1]).read().decode('utf-8')
        assert 'rel="prev"' in message
        assert 'rel="next"' in message
    finally:
        viewer.server.shutdown(); viewer.server.server_close(); thread.join(timeout=3)
