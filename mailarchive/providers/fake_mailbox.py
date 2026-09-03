from dataclasses import dataclass
from email.message import EmailMessage

from mailarchive.domain.models import MessageRef, ProviderMessage
from mailarchive.providers.contracts import (
    MailboxProvider, NetworkUnavailable, AuthenticationRequired,
    MessageNotFound, ProviderUnavailable, RateLimited,
)


@dataclass
class FakeFaults:
    download_fail: set[str] | None = None
    partial_download: set[str] | None = None
    corrupt_mime: set[str] | None = None
    disappear: set[str] | None = None
    move_fail: set[str] | None = None
    network_fail: set[str] | None = None
    auth_expire: set[str] | None = None
    rate_limit_once: set[str] | None = None

    def __post_init__(self):
        for name in (
            'download_fail', 'partial_download', 'corrupt_mime', 'disappear',
            'move_fail', 'network_fail', 'auth_expire', 'rate_limit_once',
        ):
            if getattr(self, name) is None:
                setattr(self, name, set())


class FakeMailboxProvider(MailboxProvider):
    def __init__(self, messages=None, faults=None, page_size: int = 50, *, mime_overrides=None, account_metadata=None):
        self.messages: dict[str, ProviderMessage] = {}
        self.faults = faults or FakeFaults()
        self.moves: list[str] = []
        self.page_size = max(1, page_size)
        self.discovery_pages = 0
        self._rate_limit_seen: set[str] = set()
        self.mime_overrides = dict(mime_overrides or {})
        self.account_metadata = dict(account_metadata or {
            'account_id': 'fake-account',
            'principal_hint': 'synthetic@example.test',
            'display_name': 'Synthetic Mailbox',
        })
        for m in messages or self.synthetic_messages():
            self.messages[m.ref.provider_id] = m

    @staticmethod
    def synthetic_messages(count=20):
        out = []
        for i in range(count):
            folder = 'inbox' if i % 2 == 0 else 'sentitems'
            out.append(ProviderMessage(
                MessageRef(f'msg-{i}', folder, f'<m{i}@example.test>'),
                f'Subject {i}', 'sender@example.test', ['to@example.test'],
                f'2026-01-{(i % 28)+1:02d}T12:00:00Z', f'2026-01-{(i % 28)+1:02d}T11:59:00Z',
                1024 + i,
            ))
        return out

    @classmethod
    def edge_case_provider(cls):
        messages = [
            ProviderMessage(MessageRef('edge-unicode', 'inbox', '<unicode@example.test>'), 'Résumé — 東京 📩', 'ålice@example.test', ['bøb@example.test'], '2026-02-01T12:00:00Z'),
            ProviderMessage(MessageRef('edge-no-subject', 'inbox', '<nosubject@example.test>'), '', 'sender@example.test', ['to@example.test'], '2026-02-02T12:00:00Z'),
            ProviderMessage(MessageRef('edge-no-sender', 'inbox', '<nosender@example.test>'), 'Missing sender', '', ['to@example.test'], '2026-02-03T12:00:00Z'),
            ProviderMessage(MessageRef('edge-no-imid', 'sentitems', None), 'No Internet Message ID', 'sender@example.test', ['to@example.test'], '2026-02-04T12:00:00Z'),
            ProviderMessage(MessageRef('edge-dup-imid-a', 'inbox', '<duplicate@example.test>'), 'Duplicate A', 'a@example.test', ['to@example.test'], '2026-02-05T12:00:00Z'),
            ProviderMessage(MessageRef('edge-dup-imid-b', 'sentitems', '<duplicate@example.test>'), 'Duplicate B', 'b@example.test', ['to@example.test'], '2026-02-06T12:00:00Z'),
            ProviderMessage(MessageRef('edge-attachment', 'inbox', '<attachment@example.test>'), 'Attachment', 'sender@example.test', ['to@example.test'], '2026-02-07T12:00:00Z'),
            ProviderMessage(MessageRef('edge-inline', 'inbox', '<inline@example.test>'), 'Inline image', 'sender@example.test', ['to@example.test'], '2026-02-08T12:00:00Z'),
            ProviderMessage(MessageRef('edge-hostile-html', 'inbox', '<hostile@example.test>'), 'Hostile HTML', 'evil@example.test', ['victim@example.test'], '2026-02-09T12:00:00Z'),
            ProviderMessage(MessageRef('edge-large', 'inbox', '<large@example.test>'), 'Large attachment', 'sender@example.test', ['to@example.test'], '2026-02-10T12:00:00Z', size_hint=2 * 1024 * 1024),
        ]

        def make_attachment():
            msg = EmailMessage()
            msg['From'] = 'sender@example.test'; msg['To'] = 'to@example.test'; msg['Subject'] = 'Attachment'; msg['Message-ID'] = '<attachment@example.test>'
            msg.set_content('message with attachment')
            msg.add_attachment(b'hello attachment', maintype='application', subtype='octet-stream', filename='../CON..txt')
            return msg.as_bytes()

        def make_inline():
            msg = EmailMessage()
            msg['From'] = 'sender@example.test'; msg['To'] = 'to@example.test'; msg['Subject'] = 'Inline image'; msg['Message-ID'] = '<inline@example.test>'
            msg.set_content('plain fallback')
            msg.add_alternative('<html><body><img src="cid:local-image"><img src="https://tracker.invalid/pixel"></body></html>', subtype='html')
            html = msg.get_payload()[-1]
            html.add_related(b'PNGDATA', maintype='image', subtype='png', cid='<local-image>', filename='inline.png')
            return msg.as_bytes()

        def make_hostile():
            msg = EmailMessage()
            msg['From'] = 'evil@example.test'; msg['To'] = 'victim@example.test'; msg['Subject'] = 'Hostile HTML'; msg['Message-ID'] = '<hostile@example.test>'
            msg.set_content('safe fallback')
            msg.add_alternative('<html><body onload="fetch(\'http://127.0.0.1:9/\')"><script>alert(1)</script><iframe src="https://evil.invalid"></iframe><a href="javascript:alert(2)">click</a><img src="https://tracker.invalid/pixel"></body></html>', subtype='html')
            return msg.as_bytes()

        def make_large():
            msg = EmailMessage()
            msg['From'] = 'sender@example.test'; msg['To'] = 'to@example.test'; msg['Subject'] = 'Large attachment'; msg['Message-ID'] = '<large@example.test>'
            msg.set_content('large')
            msg.add_attachment(b'Z' * (2 * 1024 * 1024), maintype='application', subtype='octet-stream', filename='large.bin')
            return msg.as_bytes()

        overrides = {
            'edge-attachment': make_attachment,
            'edge-inline': make_inline,
            'edge-hostile-html': make_hostile,
            'edge-large': make_large,
        }
        return cls(messages=messages, page_size=3, mime_overrides=overrides)

    def list_folders(self):
        return [
            {'id': 'inbox', 'name': 'Inbox'},
            {'id': 'sentitems', 'name': 'Sent Items'},
            {'id': 'nested', 'name': 'Nested'},
            {'id': 'empty', 'name': 'Empty'},
        ]

    @staticmethod
    def _in_range(ts: str, start: str | None, end: str | None) -> bool:
        if not ts:
            return True
        value = ts[:10]
        return (start is None or value >= start[:10]) and (end is None or value <= end[:10])

    def discover_messages(self, folder_ids, start, end):
        selected = [
            m for m in self.messages.values()
            if m.ref.folder_id in folder_ids and self._in_range(m.received_ts, start, end)
        ]
        selected.sort(key=lambda x: (x.received_ts, x.ref.provider_id))
        for offset in range(0, len(selected), self.page_size):
            self.discovery_pages += 1
            for message in selected[offset:offset + self.page_size]:
                yield message

    def get_message_metadata(self, provider_id):
        if provider_id in self.faults.disappear or provider_id not in self.messages:
            raise MessageNotFound(provider_id)
        return self.messages[provider_id]

    def get_message_mime(self, provider_id):
        if provider_id in self.faults.network_fail:
            raise NetworkUnavailable(provider_id)
        if provider_id in self.faults.auth_expire:
            raise AuthenticationRequired(provider_id)
        if provider_id in self.faults.disappear:
            raise MessageNotFound(provider_id)
        if provider_id in self.faults.rate_limit_once and provider_id not in self._rate_limit_seen:
            self._rate_limit_seen.add(provider_id)
            raise RateLimited(0)
        if provider_id in self.faults.download_fail:
            raise ProviderUnavailable(provider_id)
        m = self.messages[provider_id]
        override = self.mime_overrides.get(provider_id)
        if override is not None:
            return bytes(override() if callable(override) else override)
        if provider_id in self.faults.partial_download:
            return b'From: partial@example.test\r\nSubject: partial\r\n'
        if provider_id in self.faults.corrupt_mime:
            return b'\x00\xff\x00not-mime'
        em = EmailMessage()
        em['From'] = m.sender
        em['To'] = ', '.join(m.recipients)
        em['Subject'] = m.subject
        em['Date'] = m.sent_ts or 'Thu, 01 Jan 2026 11:59:00 +0000'
        if m.ref.internet_message_id:
            em['Message-ID'] = m.ref.internet_message_id
        em.set_content('plain body')
        em.add_alternative(
            '<html><body><p>Hello</p><img src="https://tracker.invalid/pixel"></body></html>',
            subtype='html',
        )
        return em.as_bytes()

    def move_message_to_deleted_items(self, provider_id):
        if provider_id in self.faults.move_fail:
            raise ProviderUnavailable('move failed')
        if provider_id not in self.messages:
            raise MessageNotFound(provider_id)
        self.moves.append(provider_id)
        return provider_id + '-deleted'

    def get_capabilities(self):
        return {'read': True, 'cleanup': True}

    def get_account_metadata(self):
        return dict(self.account_metadata)
