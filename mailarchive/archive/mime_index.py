from __future__ import annotations

from email.message import Message
from html.parser import HTMLParser


class _VisibleText(HTMLParser):
    BLOCKED = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.BLOCKED:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.BLOCKED and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth and data.strip():
            self.parts.append(data)


def html_to_visible_text(value: str) -> str:
    parser = _VisibleText()
    try:
        parser.feed(value or '')
        parser.close()
    except Exception:
        return ''
    return ' '.join(parser.parts)


def extract_searchable_body(message: Message) -> str:
    plain: list[str] = []
    html: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_disposition() == 'attachment' or part.is_multipart():
            continue
        content_type = part.get_content_type().lower()
        if content_type not in {'text/plain', 'text/html'}:
            continue
        try:
            value = part.get_content()
        except Exception:
            continue
        if not isinstance(value, str):
            continue
        if content_type == 'text/plain':
            plain.append(value)
        else:
            html.append(html_to_visible_text(value))
    # Index both alternatives because some senders put materially different text in each.
    return '\n'.join(x for x in [*plain, *html] if x)
