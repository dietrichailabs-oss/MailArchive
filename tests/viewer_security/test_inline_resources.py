from email.message import EmailMessage

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.database.connection import connect
from mailarchive.domain.models import MessageRef, ProviderMessage
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.viewer.resources import cid_resource_map, resolve_attachment
from mailarchive.viewer.sanitizer import sanitize_html


class InlineProvider(FakeMailboxProvider):
    def get_message_mime(self, provider_id):
        msg = EmailMessage()
        msg['From'] = 'a@x'
        msg['To'] = 'b@x'
        msg['Subject'] = 'inline'
        msg['Message-ID'] = '<inline@example>'
        msg.set_content('plain')
        msg.add_alternative('<html><body><img src="cid:pic1"><img src="https://tracker.invalid/t"></body></html>', subtype='html')
        html_part = msg.get_payload()[-1]
        html_part.add_related(b'PNGDATA', maintype='image', subtype='png', cid='<pic1>', filename='pic.png')
        return msg.as_bytes()


def test_cid_maps_only_to_controlled_local_resource(tmp_path):
    message = ProviderMessage(MessageRef('inline-1', 'inbox', '<inline@example>'), 'inline', 'a@x', ['b@x'], '2026-01-01T00:00:00Z')
    provider = InlineProvider(messages=[message])
    aid = next(a for a, status in ArchiveJobEngine(provider, tmp_path).run(['inbox']) if status == 'VERIFIED')
    mapping = cid_resource_map(tmp_path, aid)
    assert mapping['pic1'].startswith(f'/resource/{aid}/')
    rendered = sanitize_html('<img src="cid:pic1"><img src="https://tracker.invalid/t">', cid_map=mapping)
    assert mapping['pic1'] in rendered
    assert 'tracker.invalid' not in rendered

    db = connect(tmp_path)
    row = db.execute('SELECT id FROM attachments WHERE archive_id=? AND content_id=?', (aid, 'pic1')).fetchone()
    db.close()
    path, metadata = resolve_attachment(tmp_path, aid, row['id'])
    assert path.read_bytes() == b'PNGDATA'
