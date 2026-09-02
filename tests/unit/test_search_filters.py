from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.providers.fake_mailbox import FakeMailboxProvider
from mailarchive.search.service import SearchQuery, search


def test_search_special_characters_do_not_expose_fts_syntax(tmp_path):
    ArchiveJobEngine(FakeMailboxProvider(), tmp_path).run(['inbox', 'sentitems'])
    assert search(tmp_path, 'Subject')
    assert search(tmp_path, '" OR *') == []


def test_search_field_date_folder_and_sort_filters(tmp_path):
    ArchiveJobEngine(FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(30)), tmp_path).run(['inbox', 'sentitems'])
    rows = search(tmp_path, SearchQuery(subject='Subject', sender='sender@example.test', start_date='2026-01-05', end_date='2026-01-10', folder='inbox', sort='oldest'))
    assert rows
    assert all(row['folder_id'] == 'inbox' for row in rows)
    dates = [row['received_ts'] for row in rows]
    assert dates == sorted(dates)
