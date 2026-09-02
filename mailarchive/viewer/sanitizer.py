from html.parser import HTMLParser
from html import escape
from urllib.parse import urlparse

SAFE_TAGS = {
    'html', 'body', 'p', 'br', 'div', 'span', 'b', 'strong', 'i', 'em', 'u',
    'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'table', 'thead', 'tbody',
    'tr', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'a', 'img',
}
VOID = {'br', 'hr', 'img'}
SAFE_ATTRS = {'a': {'href', 'title'}, 'img': {'src', 'alt', 'title'}, '*': {'class'}}
DANGEROUS = {'script', 'style', 'iframe', 'object', 'embed', 'form', 'svg', 'math', 'video', 'audio', 'source', 'meta', 'link', 'base'}


def _safe_local_reference(value: str) -> str | None:
    """Return a browser-safe local reference or None.

    Browser URL parsers canonicalize backslashes as path separators for special
    schemes. A value such as ``\\evil.invalid/path`` can therefore become an
    external HTTP URL even though urllib.parse reports no scheme/netloc. V1 only
    emits local viewer references, so reject backslashes, C0 controls, explicit
    schemes/netlocs, and network-path references before serialization.
    """
    value = str(value or '').strip()
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        return None
    if '\\' in value or value.startswith('//'):
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return None
    return value


class Sanitizer(HTMLParser):
    def __init__(self, cid_map=None):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0
        self.cid_map = {str(k).lower(): v for k, v in (cid_map or {}).items()}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DANGEROUS:
            self.skip += 1
            return
        if self.skip or tag not in SAFE_TAGS:
            return
        clean = []
        for key, value in attrs:
            key = key.lower()
            value = value or ''
            if key.startswith('on'):
                continue
            if key not in (SAFE_ATTRS.get(tag, set()) | SAFE_ATTRS['*']):
                continue
            if key in {'href', 'src'}:
                parsed = urlparse(value)
                scheme = parsed.scheme.lower()
                if scheme == 'cid' and tag == 'img':
                    mapped = self.cid_map.get(parsed.path.lower())
                    if not mapped:
                        continue
                    value = mapped
                else:
                    value = _safe_local_reference(value)
                    if value is None:
                        continue
                    if tag == 'img' and not value.startswith('/resource/'):
                        continue
            clean.append(f' {key}="{escape(value, quote=True)}"')
        self.out.append('<' + tag + ''.join(clean) + '>')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in DANGEROUS:
            if self.skip:
                self.skip -= 1
            return
        if not self.skip and tag in SAFE_TAGS and tag not in VOID:
            self.out.append(f'</{tag}>')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data))


def sanitize_html(text, *, cid_map=None):
    parser = Sanitizer(cid_map=cid_map)
    parser.feed(text or '')
    parser.close()
    return ''.join(parser.out)
