from email.message import EmailMessage
import re
import threading
import urllib.request

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.domain.models import MessageRef, ProviderMessage
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.viewer.server import ArchiveViewer


ZERO_WIDTH_FORMATS = '\u200b\u200c\u200d\ufeff\u2060'


class _BaseZeroWidthProvider(FakeMailboxProvider):
    html_body = ''
    plain_body = 'VISIBLE PLAIN FALLBACK'
    include_cid_image = False

    def get_message_mime(self, provider_id):
        msg = EmailMessage()
        msg['From'] = 'sender@example.test'
        msg['To'] = 'recipient@example.test'
        msg['Subject'] = 'RC5 zero-width fallback regression'
        msg['Message-ID'] = f'<{provider_id}@example.test>'
        msg.set_content(self.plain_body)
        msg.add_alternative(self.html_body, subtype='html')
        if self.include_cid_image:
            html = msg.get_payload()[-1]
            html.add_related(b'PNGDATA', maintype='image', subtype='png', cid='<safe>', filename='safe.png')
        return msg.as_bytes()


class U200BOnlyProvider(_BaseZeroWidthProvider):
    html_body = '<html><body><p>\u200b</p></body></html>'


class UFEFFOnlyProvider(_BaseZeroWidthProvider):
    html_body = '<html><body><p>\ufeff</p></body></html>'


class MixedZeroWidthProvider(_BaseZeroWidthProvider):
    html_body = f'<html><body><p>{ZERO_WIDTH_FORMATS}</p></body></html>'


class ZeroWidthPlusVisibleTextProvider(_BaseZeroWidthProvider):
    html_body = f'<html><body><p>\u200bVISIBLE HTML BODY{ZERO_WIDTH_FORMATS}</p></body></html>'


class ZeroWidthPlusCidImageProvider(_BaseZeroWidthProvider):
    html_body = f'<html><body><p>{ZERO_WIDTH_FORMATS}</p><img src="cid:safe"></body></html>'
    include_cid_image = True


def _running_viewer(root):
    viewer = ArchiveViewer(root)
    host, port = viewer.start()
    thread = threading.Thread(target=viewer.server.serve_forever, daemon=True)
    thread.start()
    return viewer, f'http://{host}:{port}'


def _archive_and_render(tmp_path, provider_cls, provider_id):
    message = ProviderMessage(
        MessageRef(provider_id, 'inbox', f'<{provider_id}@example.test>'),
        'RC5 zero-width fallback regression',
        'sender@example.test',
        ['recipient@example.test'],
        '2026-01-01T00:00:00Z',
    )
    ArchiveJobEngine(provider_cls(messages=[message]), tmp_path).run(['inbox'])
    viewer, base = _running_viewer(tmp_path)
    listing = urllib.request.urlopen(base + '/').read().decode('utf-8')
    aid = re.search(r'/message\?id=([0-9a-f]+)', listing).group(1)
    return viewer, urllib.request.urlopen(base + '/message?id=' + aid).read().decode('utf-8')


def test_u200b_only_html_uses_plain_text_fallback(tmp_path):
    viewer, page = _archive_and_render(tmp_path, U200BOnlyProvider, 'u200b-only')
    try:
        assert 'VISIBLE PLAIN FALLBACK' in page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_ufeff_only_html_uses_plain_text_fallback(tmp_path):
    viewer, page = _archive_and_render(tmp_path, UFEFFOnlyProvider, 'ufeff-only')
    try:
        assert 'VISIBLE PLAIN FALLBACK' in page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_mixed_zero_width_format_only_html_uses_plain_text_fallback(tmp_path):
    viewer, page = _archive_and_render(tmp_path, MixedZeroWidthProvider, 'mixed-zero-width')
    try:
        assert 'VISIBLE PLAIN FALLBACK' in page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_zero_width_adjacent_to_real_text_keeps_html_preferred(tmp_path):
    viewer, page = _archive_and_render(tmp_path, ZeroWidthPlusVisibleTextProvider, 'zero-width-visible')
    try:
        assert 'VISIBLE HTML BODY' in page
        assert 'VISIBLE PLAIN FALLBACK' not in page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_controlled_cid_image_plus_zero_width_keeps_html_meaningful(tmp_path):
    viewer, page = _archive_and_render(tmp_path, ZeroWidthPlusCidImageProvider, 'zero-width-cid')
    try:
        assert '/resource/' in page
        assert 'VISIBLE PLAIN FALLBACK' not in page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()
