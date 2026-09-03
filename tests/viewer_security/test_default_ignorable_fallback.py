from email.message import EmailMessage
import re
import threading
import urllib.request

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.domain.models import MessageRef, ProviderMessage
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.viewer.sanitizer import sanitize_html
from mailarchive.viewer.server import ArchiveViewer


class _DefaultIgnorableProvider(FakeMailboxProvider):
    html_body = ''
    plain_body = 'VISIBLE PLAIN FALLBACK'
    include_cid_image = False

    def get_message_mime(self, provider_id):
        msg = EmailMessage()
        msg['From'] = 'sender@example.test'
        msg['To'] = 'recipient@example.test'
        msg['Subject'] = 'RC6 default ignorable fallback regression'
        msg['Message-ID'] = f'<{provider_id}@example.test>'
        msg.set_content(self.plain_body)
        msg.add_alternative(self.html_body, subtype='html')
        if self.include_cid_image:
            html = msg.get_payload()[-1]
            html.add_related(b'PNGDATA', maintype='image', subtype='png', cid='<safe>', filename='safe.png')
        return msg.as_bytes()


class VariationSelectorOnlyProvider(_DefaultIgnorableProvider):
    html_body = '<html><body><p>\ufe0f</p></body></html>'


class CombiningGraphemeJoinerOnlyProvider(_DefaultIgnorableProvider):
    html_body = '<html><body><p>\u034f</p></body></html>'


class MixedDefaultIgnorableOnlyProvider(_DefaultIgnorableProvider):
    html_body = '<html><body><p>\u200b\ufeff\u034f\ufe0f\u3164\uffa0\U000e0100</p></body></html>'


class EmojiVariationProvider(_DefaultIgnorableProvider):
    html_body = '<html><body><p>VISIBLE HEART \u2764\ufe0f</p></body></html>'


class ImageAndIgnorableProvider(_DefaultIgnorableProvider):
    html_body = '<html><body><p>\u034f\ufe0f\u200b</p><img src="cid:safe"></body></html>'
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
        'RC6 default ignorable fallback regression',
        'sender@example.test',
        ['recipient@example.test'],
        '2026-01-01T00:00:00Z',
    )
    ArchiveJobEngine(provider_cls(messages=[message]), tmp_path).run(['inbox'])
    viewer, base = _running_viewer(tmp_path)
    listing = urllib.request.urlopen(base + '/').read().decode('utf-8')
    aid = re.search(r'/message\?id=([0-9a-f]+)', listing).group(1)
    page = urllib.request.urlopen(base + '/message?id=' + aid).read().decode('utf-8')
    return viewer, page


def test_variation_selector_16_alone_collapses_to_empty():
    assert sanitize_html('<html><body><p>\ufe0f</p></body></html>') == ''


def test_combining_grapheme_joiner_alone_collapses_to_empty():
    assert sanitize_html('<html><body><p>\u034f</p></body></html>') == ''


def test_representative_default_ignorable_ranges_collapse_to_empty():
    samples = (
        '\u00ad',
        '\u115f',
        '\u17b4',
        '\u180b',
        '\u2065',
        '\u3164',
        '\uffa0',
        '\ufff0',
        '\U0001bca0',
        '\U0001d173',
        '\U000e0100',
    )
    for sample in samples:
        assert sanitize_html(f'<p>{sample}</p>') == '', hex(ord(sample))


def test_variation_selector_attached_to_real_base_is_meaningful():
    out = sanitize_html('<p>\u2764\ufe0f</p>')
    assert '\u2764' in out
    assert '\ufe0f' in out


def test_combining_grapheme_joiner_adjacent_to_real_text_is_meaningful():
    out = sanitize_html('<p>A\u034fB</p>')
    assert 'A' in out and 'B' in out


def test_variation_selector_only_html_falls_back_to_plain(tmp_path):
    viewer, page = _archive_and_render(tmp_path, VariationSelectorOnlyProvider, 'vs16-only')
    try:
        assert 'VISIBLE PLAIN FALLBACK' in page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_combining_grapheme_joiner_only_html_falls_back_to_plain(tmp_path):
    viewer, page = _archive_and_render(tmp_path, CombiningGraphemeJoinerOnlyProvider, 'cgj-only')
    try:
        assert 'VISIBLE PLAIN FALLBACK' in page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_mixed_default_ignorable_only_html_falls_back_to_plain(tmp_path):
    viewer, page = _archive_and_render(tmp_path, MixedDefaultIgnorableOnlyProvider, 'mixed-default-ignorable')
    try:
        assert 'VISIBLE PLAIN FALLBACK' in page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_real_base_plus_variation_selector_keeps_html_preferred(tmp_path):
    viewer, page = _archive_and_render(tmp_path, EmojiVariationProvider, 'emoji-vs16')
    try:
        assert 'VISIBLE HEART' in page
        assert 'VISIBLE PLAIN FALLBACK' not in page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_controlled_image_plus_default_ignorable_marks_remains_meaningful(tmp_path):
    viewer, page = _archive_and_render(tmp_path, ImageAndIgnorableProvider, 'image-default-ignorable')
    try:
        assert '/resource/' in page
        assert 'VISIBLE PLAIN FALLBACK' not in page
    finally:
        viewer.server.shutdown(); viewer.server.server_close()
