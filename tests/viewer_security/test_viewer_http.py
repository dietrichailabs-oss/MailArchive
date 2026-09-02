from email.message import EmailMessage
import threading
import urllib.request
import urllib.error

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.domain.models import MessageRef, ProviderMessage
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.viewer.server import ArchiveViewer


class HostileProvider(FakeMailboxProvider):
    def get_message_mime(self, provider_id):
        msg = EmailMessage()
        msg['From'] = 'evil@example.test'
        msg['To'] = 'victim@example.test'
        msg['Subject'] = '<script>subject</script>'
        msg['Message-ID'] = '<hostile@example>'
        msg.set_content('plain')
        msg.add_alternative('<html><body><script>alert(1)</script><img src="https://tracker.invalid/x"><img src="cid:safe"></body></html>', subtype='html')
        html = msg.get_payload()[-1]
        html.add_related(b'PNG', maintype='image', subtype='png', cid='<safe>', filename='safe.png')
        msg.add_attachment(b'<html><script>alert(2)</script></html>', maintype='text', subtype='html', filename='danger.html')
        return msg.as_bytes()


def _running_viewer(root):
    viewer = ArchiveViewer(root)
    host, port = viewer.start()
    thread = threading.Thread(target=viewer.server.serve_forever, daemon=True)
    thread.start()
    return viewer, f'http://{host}:{port}'


def test_message_render_blocks_remote_and_script_and_has_hard_csp(tmp_path):
    message = ProviderMessage(MessageRef('hostile-1', 'inbox', '<hostile@example>'), '<script>subject</script>', 'evil@example.test', ['victim@example.test'], '2026-01-01T00:00:00Z')
    ArchiveJobEngine(HostileProvider(messages=[message]), tmp_path).run(['inbox'])
    viewer, base = _running_viewer(tmp_path)
    try:
        listing = urllib.request.urlopen(base + '/').read().decode()
        assert '<script>subject</script>' not in listing
        import re
        aid = re.search(r'/message\?id=([0-9a-f]+)', listing).group(1)
        response = urllib.request.urlopen(base + '/message?id=' + aid)
        html = response.read().decode()
        assert 'tracker.invalid' not in html
        assert 'alert(1)' not in html
        assert '/resource/' in html
        csp = response.headers['Content-Security-Policy']
        assert "connect-src 'none'" in csp and "object-src 'none'" in csp
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_dangerous_attachment_forced_download_not_inline(tmp_path):
    message = ProviderMessage(MessageRef('hostile-1', 'inbox', '<hostile@example>'), 'x', 'evil@example.test', [], '2026-01-01T00:00:00Z')
    ArchiveJobEngine(HostileProvider(messages=[message]), tmp_path).run(['inbox'])
    viewer, base = _running_viewer(tmp_path)
    try:
        listing = urllib.request.urlopen(base + '/').read().decode()
        import re
        aid = re.search(r'/message\?id=([0-9a-f]+)', listing).group(1)
        page = urllib.request.urlopen(base + '/message?id=' + aid).read().decode()
        attachment_id = re.search(rf'/attachment/{aid}/(\d+)[^>]*>danger\.html', page).group(1)
        response = urllib.request.urlopen(base + f'/attachment/{aid}/{attachment_id}')
        assert response.headers['Content-Disposition'].startswith('attachment;')
        assert response.headers['Content-Type'] == 'application/octet-stream'
        with __import__('pytest').raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(base + f'/resource/{aid}/{attachment_id}')
        assert caught.value.code == 404
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_raw_header_view_is_explicit_hash_checked_and_html_escaped(tmp_path):
    message = ProviderMessage(MessageRef('hostile-raw', 'inbox', '<raw@example>'), '<script>subject</script>', 'evil@example.test', [], '2026-01-01T00:00:00Z')
    ArchiveJobEngine(HostileProvider(messages=[message]), tmp_path).run(['inbox'])
    viewer, base = _running_viewer(tmp_path)
    try:
        listing = urllib.request.urlopen(base + '/').read().decode('utf-8')
        import re
        aid = re.search(r'/message\?id=([0-9a-f]+)', listing).group(1)
        message_page = urllib.request.urlopen(base + '/message?id=' + aid).read().decode('utf-8')
        assert f'/raw/{aid}' in message_page
        response = urllib.request.urlopen(base + f'/raw/{aid}')
        raw_page = response.read().decode('utf-8')
        assert 'Raw message headers' in raw_page
        assert '<script>subject</script>' not in raw_page
        assert '&lt;script&gt;subject&lt;/script&gt;' in raw_page
        assert "connect-src 'none'" in response.headers['Content-Security-Policy']
        # The raw-header view must not render the body HTML as active/body detail content.
        assert 'tracker.invalid' not in raw_page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()
