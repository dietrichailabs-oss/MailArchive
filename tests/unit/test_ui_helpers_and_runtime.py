from datetime import date

import pytest

from mailarchive.runtime.microsoft_session import MicrosoftConfigurationError, load_client_id
from mailarchive.ui.date_ranges import resolve_date_range
from mailarchive.ui.formatting import cleanup_confirmation_text
from mailarchive.cleanup.preview import CleanupPlan


def test_date_presets_are_inclusive_cutoffs():
    today = date(2026, 9, 1)
    assert resolve_date_range('Older than 30 days', today=today) == (None, '2026-08-02')
    assert resolve_date_range('Older than 90 days', today=today) == (None, '2026-06-03')
    assert resolve_date_range('Older than 6 months', today=today) == (None, '2026-03-01')
    assert resolve_date_range('Older than 1 year', today=today) == (None, '2025-09-01')
    assert resolve_date_range('Custom', today=today, custom_start='2026-01-01', custom_end='2026-01-31') == ('2026-01-01', '2026-01-31')


def test_bad_custom_date_range_is_rejected():
    with pytest.raises(ValueError):
        resolve_date_range('Custom', custom_start='2026-02-02', custom_end='2026-01-01')
    with pytest.raises(ValueError):
        resolve_date_range('Custom', custom_start='not-a-date')


def test_client_id_placeholder_is_not_accepted(tmp_path, monkeypatch):
    monkeypatch.delenv('MAILARCHIVE_CLIENT_ID', raising=False)
    path = tmp_path / 'microsoft_app.json'
    path.write_text('{"client_id":"REPLACE_WITH_MICROSOFT_ENTRA_APP_CLIENT_ID"}', encoding='utf-8')
    with pytest.raises(MicrosoftConfigurationError):
        load_client_id(path)


def test_cleanup_confirmation_is_explicit_and_non_destructive():
    plan = CleanupPlan(('a', 'b'), 2, '2025-01-01', '2025-12-31', ('Inbox', 'Sent Items'))
    text = cleanup_confirmation_text(plan)
    assert 'Verified messages eligible: 2' in text
    assert 'Deleted Items' in text
    assert 'NOT be permanently deleted' in text
    assert 'continue counting' in text


def test_preview_account_label_is_human_readable_without_persistence():
    from mailarchive.ui.formatting import format_account_identity
    assert format_account_identity({'display_name': 'Test User', 'principal_hint': 'test@example.invalid'}) == 'Test User (test@example.invalid)'
    assert format_account_identity({'principal_hint': 'test@example.invalid'}) == 'test@example.invalid'
    assert format_account_identity({}) == 'Signed-in Microsoft account'


def test_window_geometry_validation_rejects_corrupt_or_absurd_values():
    from mailarchive.configuration.settings import valid_window_geometry
    assert valid_window_geometry('940x680+10-20') == '940x680+10-20'
    assert valid_window_geometry('1200x900-100+40') == '1200x900-100+40'
    assert valid_window_geometry('not geometry') == ''
    assert valid_window_geometry('20000x900+0+0') == ''
    assert valid_window_geometry('100x100+0+0') == ''


def test_archive_manager_label_displays_full_location():
    from mailarchive.ui.formatting import archive_manager_label
    item = {
        'path': r'D:\Mail Archives\2025', 'exists': True, 'verified_count': 42,
        'selected_date_range': {'start': '2025-01-01', 'end': '2025-12-31'},
        'archive_size': 4096, 'archive_creation_timestamp': '2026-01-02T03:04:05Z',
        'last_opened': '2026-02-03T04:05:06Z',
    }
    label = archive_manager_label(item)
    assert '42 messages' in label
    assert 'Location D:\\Mail Archives\\2025' in label
