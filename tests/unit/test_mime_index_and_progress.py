from email.message import EmailMessage

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.domain.models import MessageRef, ProviderMessage
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.search.service import search


class HtmlOnlyProvider(FakeMailboxProvider):
    def get_message_mime(self, provider_id):
        msg = EmailMessage()
        msg['From'] = 'a@x'
        msg['To'] = 'b@x'
        msg['Subject'] = 'html only'
        msg['Message-ID'] = '<html@x>'
        msg.set_content('<html><body><p>Visible Needle</p><script>HiddenTrackerWord</script></body></html>', subtype='html')
        return msg.as_bytes()


def test_html_only_visible_body_is_searchable_without_script_text(tmp_path):
    message = ProviderMessage(MessageRef('h1', 'inbox', '<html@x>'), 'html only', 'a@x', ['b@x'], '2026-01-01T00:00:00Z')
    provider = HtmlOnlyProvider(messages=[message])
    ArchiveJobEngine(provider, tmp_path).run(['inbox'])
    assert len(search(tmp_path, 'Needle')) == 1
    assert search(tmp_path, 'HiddenTrackerWord') == []


def test_progress_callback_errors_cannot_break_archival(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    events = []

    def progress(event):
        events.append(event['event'])
        if event['event'] == 'downloading':
            raise RuntimeError('presentation failed')

    result = ArchiveJobEngine(provider, tmp_path, progress=progress).run(['inbox'])
    assert result[0][1] == 'VERIFIED'
    assert 'verified' in events


def test_progress_reports_download_write_verify_and_safe_skip(tmp_path):
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(1))
    first_events = []
    ArchiveJobEngine(provider, tmp_path, progress=lambda event: first_events.append(event)).run(['inbox'])
    names = [event['event'] for event in first_events]
    assert 'downloaded' in names
    assert 'written' in names
    assert 'verified' in names
    written = next(event for event in first_events if event['event'] == 'written')
    assert written['bytes_written'] > 0

    second_events = []
    result = ArchiveJobEngine(provider, tmp_path, progress=lambda event: second_events.append(event)).run(['inbox'])
    assert result[0][1] == 'SKIPPED_VERIFIED'
    assert 'skipped' in [event['event'] for event in second_events]
    assert 'downloading' not in [event['event'] for event in second_events]
