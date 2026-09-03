import json

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.cleanup.mailbox_actions import CleanupService
from mailarchive.database.connection import connect
from mailarchive.domain.models import MessageRef, ProviderMessage
from mailarchive.providers.fake_mailbox import FakeMailboxProvider


def _one_verified(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox'])
    return provider, next(a for a, status in result if status == 'VERIFIED')


def test_missing_eml_after_verification_blocks_cleanup(tmp_path):
    provider, aid = _one_verified(tmp_path)
    db = connect(tmp_path)
    row = db.execute('SELECT eml_path FROM messages WHERE archive_id=?', (aid,)).fetchone()
    db.close()
    (tmp_path / row['eml_path']).unlink()
    result = CleanupService(provider, tmp_path).move_verified([aid])
    assert result == [(aid, 'SKIPPED_NOT_VERIFIED')]
    assert provider.moves == []


def test_corrupt_eml_after_verification_blocks_cleanup(tmp_path):
    provider, aid = _one_verified(tmp_path)
    db = connect(tmp_path)
    row = db.execute('SELECT eml_path FROM messages WHERE archive_id=?', (aid,)).fetchone()
    db.close()
    (tmp_path / row['eml_path']).write_bytes(b'changed\r\n\r\nbody')
    result = CleanupService(provider, tmp_path).move_verified([aid])
    assert result == [(aid, 'SKIPPED_NOT_VERIFIED')]
    assert provider.moves == []


def test_manifest_hash_tamper_blocks_cleanup(tmp_path):
    provider, aid = _one_verified(tmp_path)
    path = tmp_path / 'manifest.json'
    doc = json.loads(path.read_text(encoding='utf-8'))
    doc['messages'][aid]['sha256'] = '0' * 64
    path.write_text(json.dumps(doc), encoding='utf-8')
    result = CleanupService(provider, tmp_path).move_verified([aid])
    assert result == [(aid, 'SKIPPED_NOT_VERIFIED')]
    assert provider.moves == []


def test_duplicate_internet_message_id_never_collapses_or_cleans(tmp_path):
    messages = [
        ProviderMessage(MessageRef('p1', 'inbox', '<duplicate@example>'), 'one', 'a@x', ['b@x'], '2026-01-01T00:00:00Z'),
        ProviderMessage(MessageRef('p2', 'inbox', '<duplicate@example>'), 'two', 'c@x', ['d@x'], '2026-01-02T00:00:00Z'),
    ]
    provider = FakeMailboxProvider(messages=messages)
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox'])
    verified = [aid for aid, status in result if status == 'VERIFIED']
    assert len(verified) == 2
    db = connect(tmp_path)
    rows = db.execute('SELECT archive_id,identity_ambiguous FROM messages ORDER BY archive_id').fetchall()
    db.close()
    assert len(rows) == 2
    assert all(row['identity_ambiguous'] == 1 for row in rows)
    CleanupService(provider, tmp_path).move_verified(verified)
    assert provider.moves == []


def test_provider_identity_changed_before_cleanup_is_skipped(tmp_path):
    provider, aid = _one_verified(tmp_path)
    old = provider.messages['msg-0']
    provider.messages['msg-0'] = ProviderMessage(
        MessageRef('msg-0', old.ref.folder_id, '<different@example>'),
        old.subject, old.sender, old.recipients, old.received_ts, old.sent_ts,
    )
    result = CleanupService(provider, tmp_path).move_verified([aid])
    assert result == [(aid, 'SKIPPED_IDENTITY_MISMATCH')]
    assert provider.moves == []


def test_missing_extracted_attachment_blocks_cleanup(tmp_path):
    from email.message import EmailMessage
    from mailarchive.archive.hashing import sha256_file

    class AttachmentProvider(FakeMailboxProvider):
        def get_message_mime(self, provider_id):
            msg = EmailMessage()
            msg['From'] = 'a@x'
            msg['To'] = 'b@x'
            msg['Subject'] = 'with attachment'
            msg['Message-ID'] = '<attachment@example>'
            msg.set_content('body')
            msg.add_attachment(b'important', maintype='application', subtype='octet-stream', filename='proof.bin')
            return msg.as_bytes()

    message = ProviderMessage(MessageRef('att-1', 'inbox', '<attachment@example>'), 'with attachment', 'a@x', ['b@x'], '2026-01-01T00:00:00Z')
    provider = AttachmentProvider(messages=[message])
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox'])
    aid = next(a for a, status in result if status == 'VERIFIED')
    db = connect(tmp_path)
    attachment = db.execute('SELECT relative_path FROM attachments WHERE archive_id=?', (aid,)).fetchone()
    db.close()
    (tmp_path / attachment['relative_path']).unlink()
    outcome = CleanupService(provider, tmp_path).move_verified([aid])
    assert outcome == [(aid, 'SKIPPED_NOT_VERIFIED')]
    assert provider.moves == []


def test_missing_internet_message_id_reused_provider_id_is_skipped(tmp_path):
    messages = [
        ProviderMessage(MessageRef('stable-1', 'inbox', None), 'original', 'a@x', ['b@x'], '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
    ]
    provider = FakeMailboxProvider(messages=messages)
    result = ArchiveJobEngine(provider, tmp_path).run(['inbox'])
    aid = next(a for a, status in result if status == 'VERIFIED')
    provider.messages['stable-1'] = ProviderMessage(
        MessageRef('stable-1', 'inbox', None), 'replacement', 'attacker@x', ['victim@x'],
        '2026-01-02T00:00:00Z', '2026-01-02T00:00:00Z',
    )
    outcome = CleanupService(provider, tmp_path).move_verified([aid])
    assert outcome == [(aid, 'SKIPPED_IDENTITY_MISMATCH')]
    assert provider.moves == []


def test_folder_move_does_not_invalidate_same_verified_message(tmp_path):
    provider, aid = _one_verified(tmp_path)
    old = provider.messages['msg-0']
    provider.messages['msg-0'] = ProviderMessage(
        MessageRef('msg-0', 'another-folder', old.ref.internet_message_id),
        old.subject, old.sender, old.recipients, old.received_ts, old.sent_ts, old.size_hint,
    )
    outcome = CleanupService(provider, tmp_path).move_verified([aid])
    assert outcome == [(aid, 'MOVED')]
    assert provider.moves == ['msg-0']
