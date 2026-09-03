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


class MetaBodyProvider(FakeMailboxProvider):
    def get_message_mime(self, provider_id):
        msg = EmailMessage()
        msg['From'] = 'sender@example.test'
        msg['To'] = 'recipient@example.test'
        msg['Subject'] = 'HTML body with meta'
        msg['Message-ID'] = '<meta-body@example>'
        msg.set_content('PLAIN FALLBACK BODY')
        msg.add_alternative(
            '<html><head><meta charset="utf-8"><link rel="stylesheet" href="https://tracker.invalid/x.css"></head>'
            '<body><p>VISIBLE HTML BODY</p></body></html>',
            subtype='html',
        )
        return msg.as_bytes()


class EmptyHtmlFallbackProvider(FakeMailboxProvider):
    def get_message_mime(self, provider_id):
        msg = EmailMessage()
        msg['From'] = 'sender@example.test'
        msg['To'] = 'recipient@example.test'
        msg['Subject'] = 'Fallback body'
        msg['Message-ID'] = '<fallback@example>'
        msg.set_content('VISIBLE PLAIN FALLBACK')
        msg.add_alternative('<meta charset="utf-8"><script>ONLY DANGEROUS HTML</script>', subtype='html')
        return msg.as_bytes()


class StructuralOnlyHtmlFallbackProvider(FakeMailboxProvider):
    def get_message_mime(self, provider_id):
        msg = EmailMessage()
        msg['From'] = 'sender@example.test'
        msg['To'] = 'recipient@example.test'
        msg['Subject'] = 'Semantic fallback body'
        msg['Message-ID'] = '<semantic-fallback@example>'
        msg.set_content('VISIBLE PLAIN WHEN HTML HAS NO SAFE CONTENT')
        msg.add_alternative(
            '<html><head><meta charset="utf-8"><script>HEAD EVIL</script></head>'
            '<body><iframe>FRAME EVIL</iframe></body></html>',
            subtype='html',
        )
        return msg.as_bytes()


class HtmlOnlyNoSafeContentProvider(FakeMailboxProvider):
    def get_message_mime(self, provider_id):
        msg = EmailMessage()
        msg['From'] = 'sender@example.test'
        msg['To'] = 'recipient@example.test'
        msg['Subject'] = 'HTML only unsafe body'
        msg['Message-ID'] = '<html-only-unsafe@example>'
        msg.set_content(
            '<html><body><script>DO NOT SHOW SCRIPT</script><iframe>DO NOT SHOW FRAME</iframe></body></html>',
            subtype='html',
        )
        return msg.as_bytes()


class MultipleHtmlAlternativesProvider(FakeMailboxProvider):
    def get_message_mime(self, provider_id):
        msg = EmailMessage()
        msg['From'] = 'sender@example.test'
        msg['To'] = 'recipient@example.test'
        msg['Subject'] = 'Multiple HTML alternatives'
        msg['Message-ID'] = '<multiple-html@example>'
        msg.set_content('PLAIN SHOULD NOT WIN')
        msg.add_alternative(
            '<html><body><script>FIRST HTML UNSAFE</script><iframe>FIRST FRAME UNSAFE</iframe></body></html>',
            subtype='html',
        )
        msg.add_alternative('<html><body><p>SECOND HTML IS SAFE AND VISIBLE</p></body></html>', subtype='html')
        return msg.as_bytes()


def _running_viewer(root):
    viewer = ArchiveViewer(root)
    host, port = viewer.start()
    thread = threading.Thread(target=viewer.server.serve_forever, daemon=True)
    thread.start()
    return viewer, f'http://{host}:{port}'


def _archive_and_open_message(tmp_path, provider_cls, *, provider_id='message-1', message_id='<message@example>'):
    message = ProviderMessage(
        MessageRef(provider_id, 'inbox', message_id),
        'viewer regression',
        'sender@example.test',
        ['recipient@example.test'],
        '2026-01-01T00:00:00Z',
    )
    ArchiveJobEngine(provider_cls(messages=[message]), tmp_path).run(['inbox'])
    viewer, base = _running_viewer(tmp_path)
    listing = urllib.request.urlopen(base + '/').read().decode('utf-8')
    import re
    aid = re.search(r'/message\?id=([0-9a-f]+)', listing).group(1)
    return viewer, base, aid


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
        assert '>plain<' not in html
        csp = response.headers['Content-Security-Policy']
        assert "connect-src 'none'" in csp and "object-src 'none'" in csp
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_html_meta_and_link_tags_do_not_hide_following_message_body(tmp_path):
    viewer, base, aid = _archive_and_open_message(
        tmp_path, MetaBodyProvider, provider_id='meta-body-1', message_id='<meta-body@example>'
    )
    try:
        response = urllib.request.urlopen(base + '/message?id=' + aid)
        html = response.read().decode('utf-8')
        assert 'VISIBLE HTML BODY' in html
        assert 'PLAIN FALLBACK BODY' not in html
        assert 'tracker.invalid' not in html
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_empty_sanitized_html_falls_back_to_plain_text_body(tmp_path):
    viewer, base, aid = _archive_and_open_message(
        tmp_path, EmptyHtmlFallbackProvider, provider_id='fallback-1', message_id='<fallback@example>'
    )
    try:
        html = urllib.request.urlopen(base + '/message?id=' + aid).read().decode('utf-8')
        assert 'VISIBLE PLAIN FALLBACK' in html
        assert 'ONLY DANGEROUS HTML' not in html
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_structural_only_sanitized_html_falls_back_to_plain_text_body(tmp_path):
    viewer, base, aid = _archive_and_open_message(
        tmp_path,
        StructuralOnlyHtmlFallbackProvider,
        provider_id='semantic-fallback-1',
        message_id='<semantic-fallback@example>',
    )
    try:
        html = urllib.request.urlopen(base + '/message?id=' + aid).read().decode('utf-8')
        assert 'VISIBLE PLAIN WHEN HTML HAS NO SAFE CONTENT' in html
        assert 'HEAD EVIL' not in html
        assert 'FRAME EVIL' not in html
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_html_only_no_safe_content_does_not_render_blocked_content(tmp_path):
    viewer, base, aid = _archive_and_open_message(
        tmp_path,
        HtmlOnlyNoSafeContentProvider,
        provider_id='html-only-unsafe-1',
        message_id='<html-only-unsafe@example>',
    )
    try:
        html = urllib.request.urlopen(base + '/message?id=' + aid).read().decode('utf-8')
        assert 'DO NOT SHOW SCRIPT' not in html
        assert 'DO NOT SHOW FRAME' not in html
        assert 'Save original .eml' in html
    finally:
        viewer.server.shutdown(); viewer.server.server_close()


def test_multiple_html_alternatives_skip_empty_then_use_later_safe_html(tmp_path):
    viewer, base, aid = _archive_and_open_message(
        tmp_path,
        MultipleHtmlAlternativesProvider,
        provider_id='multiple-html-1',
        message_id='<multiple-html@example>',
    )
    try:
        html = urllib.request.urlopen(base + '/message?id=' + aid).read().decode('utf-8')
        assert 'SECOND HTML IS SAFE AND VISIBLE' in html
        assert 'PLAIN SHOULD NOT WIN' not in html
        assert 'FIRST HTML UNSAFE' not in html
        assert 'FIRST FRAME UNSAFE' not in html
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
