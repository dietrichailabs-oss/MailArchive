from datetime import date
from pathlib import Path

import pytest

from mailarchive.runtime.microsoft_session import MicrosoftConfigurationError, load_client_id
from mailarchive.ui.calendar_picker import month_cells
from mailarchive.ui.date_ranges import format_user_date, parse_user_date, resolve_date_range
from mailarchive.ui.formatting import cleanup_confirmation_text
from mailarchive.ui.main_window.rc2 import build_folder_display_rows
from mailarchive.cleanup.preview import CleanupPlan


def test_date_presets_are_inclusive_cutoffs():
    today = date(2026, 9, 1)
    assert resolve_date_range('Older than 30 days', today=today) == (None, '2026-08-02')
    assert resolve_date_range('Older than 90 days', today=today) == (None, '2026-06-03')
    assert resolve_date_range('Older than 6 months', today=today) == (None, '2026-03-01')
    assert resolve_date_range('Older than 1 year', today=today) == (None, '2025-09-01')
    # Old ISO automation remains accepted even though the Windows UI is now MM/DD/YYYY.
    assert resolve_date_range('Custom', today=today, custom_start='2026-01-01', custom_end='2026-01-31') == ('2026-01-01', '2026-01-31')


def test_us_custom_dates_roundtrip_to_iso_internal_form():
    assert parse_user_date('09/02/2026') == '2026-09-02'
    assert format_user_date('2026-09-02') == '09/02/2026'
    assert resolve_date_range('Custom', custom_start='01/02/2026', custom_end='01/31/2026') == ('2026-01-02', '2026-01-31')
    assert resolve_date_range('Custom', custom_start='02/29/2024', custom_end='02/29/2024') == ('2024-02-29', '2024-02-29')


def test_bad_custom_date_range_is_rejected_in_us_format():
    with pytest.raises(ValueError, match='start date cannot be after end date'):
        resolve_date_range('Custom', custom_start='02/02/2026', custom_end='01/01/2026')
    with pytest.raises(ValueError, match='MM/DD/YYYY'):
        resolve_date_range('Custom', custom_start='13/01/2026')
    with pytest.raises(ValueError, match='MM/DD/YYYY'):
        resolve_date_range('Custom', custom_start='02/29/2025')
    with pytest.raises(ValueError, match='MM/DD/YYYY'):
        resolve_date_range('Custom', custom_start='not-a-date')


def test_calendar_month_grid_is_complete_and_sunday_first():
    weeks = month_cells(2026, 9)
    assert all(len(week) == 7 for week in weeks)
    assert sorted(day for week in weeks for day in week if day) == list(range(1, 31))
    # September 1, 2026 is Tuesday; Sunday/Monday are padding in a Sunday-first grid.
    assert weeks[0][:3] == [0, 0, 1]


def test_folder_display_includes_all_visible_rows_and_indents_children():
    rows = [
        {'id': 'inbox', 'name': 'Inbox', 'parent_id': None, 'hidden': False},
        {'id': 'child', 'name': 'Project', 'parent_id': 'inbox', 'hidden': False},
        {'id': 'nested', 'name': '2026', 'parent_id': 'child', 'hidden': False},
        {'id': 'hidden', 'name': 'Hidden', 'parent_id': None, 'hidden': True},
    ]
    rendered = build_folder_display_rows(rows)
    assert [row['id'] for row, _label in rendered] == ['inbox', 'child', 'nested']
    assert rendered[0][1] == 'Inbox'
    assert rendered[1][1].endswith('↳ Project')
    assert rendered[2][1].endswith('↳ 2026')
    assert len(rendered[2][1]) > len(rendered[1][1])


def test_rc2_navigation_and_folder_controls_are_stateful_in_source():
    root = Path(__file__).resolve().parents[2]
    source = (root / 'mailarchive' / 'ui' / 'main_window' / 'rc2.py').read_text(encoding='utf-8')
    assert 'Select all folders' in source
    assert 'Clear all' in source
    assert '_selected_folder_ids_state' in source
    assert '_folder_selection_initialized' in source
    assert 'command=self._back_to_signed_home_from_folders' in source
    assert 'command=self._back_to_folders_from_date' in source
    assert 'command=self._back_to_date_range' in source
    assert "self.preset.set('Custom')" in source
    assert 'MM/DD/YYYY' in source
    assert 'Calendar…' in source
    # Running archive screens remain controlled by the RC1 safety layer and expose Cancel Safely, not Back.
    base = (root / 'mailarchive' / 'ui' / 'main_window' / 'app.py').read_text(encoding='utf-8')
    assert "text='Cancel Safely'" in base


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
    assert 'Date range (inclusive): 01/01/2025 through 12/31/2025' in text
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


def test_archive_manager_label_displays_full_location_and_us_dates():
    from mailarchive.ui.formatting import archive_manager_label
    item = {
        'path': r'D:\Mail Archives\2025', 'exists': True, 'verified_count': 42,
        'selected_date_range': {'start': '2025-01-01', 'end': '2025-12-31'},
        'archive_size': 4096, 'archive_creation_timestamp': '2026-01-02T03:04:05Z',
        'last_opened': '2026-02-03T04:05:06Z',
    }
    label = archive_manager_label(item)
    assert '42 messages' in label
    assert '01/01/2025 to 12/31/2025' in label
    assert 'Location D:\\Mail Archives\\2025' in label
