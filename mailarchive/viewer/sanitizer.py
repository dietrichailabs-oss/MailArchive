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

# Dangerous containers suppress their complete subtree. Dangerous void/non-container
# elements are dropped without changing skip depth; HTML email commonly emits tags
# such as <meta> and <link> without matching end tags.
DANGEROUS_CONTAINERS = {
    'script', 'style', 'iframe', 'object', 'form', 'svg', 'math', 'video', 'audio',
}
DANGEROUS_VOID = {'embed', 'source', 'meta', 'link', 'base'}

# Unicode Default_Ignorable_Code_Point ranges used for display/body-selection semantics.
# These characters are intentionally ignored only when deciding whether sanitized HTML
# contains a visible body. They are not deleted from otherwise meaningful sanitized HTML.
# The ranges follow the Unicode DerivedCoreProperties Default_Ignorable_Code_Point set,
# including the forward-compatible reserved ranges defined for that property.
DEFAULT_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)


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


def _is_default_ignorable(ch: str) -> bool:
    cp = ord(ch)
    return any(start <= cp <= end for start, end in DEFAULT_IGNORABLE_RANGES)


def _has_visible_text(data: str) -> bool:
    """Return True only if text contains a display-significant character.

    Unicode default-ignorable code points include format controls, variation
    selectors, COMBINING GRAPHEME JOINER, Hangul fillers, tag characters, and
    reserved default-ignorable ranges. Standalone default-ignorable text must not
    suppress a valid text/plain MIME fallback. If a real base/display character
    exists beside those code points, the real character makes the HTML meaningful.
    """
    return any(
        not ch.isspace() and not _is_default_ignorable(ch)
        for ch in (data or '')
    )


class Sanitizer(HTMLParser):
    def __init__(self, cid_map=None):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0
        self.cid_map = {str(k).lower(): v for k, v in (cid_map or {}).items()}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in DANGEROUS_VOID:
            return
        if tag in DANGEROUS_CONTAINERS:
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
        if tag in DANGEROUS_VOID:
            return
        if tag in DANGEROUS_CONTAINERS:
            if self.skip:
                self.skip -= 1
            return
        if not self.skip and tag in SAFE_TAGS and tag not in VOID:
            self.out.append(f'</{tag}>')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data))


class VisibleContentDetector(HTMLParser):
    """Detect whether already-sanitized viewer HTML has meaningful visible content.

    Structural wrappers alone are not a usable message body. Display-significant
    text is visible, and a sanitized ``img`` is visible because the sanitizer only
    preserves controlled local ``/resource/`` images. Whitespace, default-ignorable
    text, empty wrappers, unlabeled links, and layout-only tags do not suppress a
    valid ``text/plain`` MIME fallback.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.visible = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'img':
            src = dict(attrs).get('src', '')
            if str(src).startswith('/resource/'):
                self.visible = True

    def handle_data(self, data):
        if _has_visible_text(data):
            self.visible = True


def has_meaningful_visible_html(text: str) -> bool:
    """Return True only when sanitized HTML would visibly convey message content."""
    detector = VisibleContentDetector()
    detector.feed(text or '')
    detector.close()
    return detector.visible


def sanitize_html(text, *, cid_map=None):
    parser = Sanitizer(cid_map=cid_map)
    parser.feed(text or '')
    parser.close()
    rendered = ''.join(parser.out)
    return rendered if has_meaningful_visible_html(rendered) else ''
