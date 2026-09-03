from __future__ import annotations

from datetime import date, datetime, timedelta
import calendar


PRESETS = ('Older than 30 days', 'Older than 90 days', 'Older than 6 months', 'Older than 1 year', 'Custom')
USER_DATE_FORMAT = '%m/%d/%Y'


def _subtract_months(day: date, months: int) -> date:
    total = day.year * 12 + (day.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def format_user_date(value: str | date | None, *, empty: str = '') -> str:
    """Format an internal ISO date/date object as MM/DD/YYYY for the Windows UI."""
    if value is None or value == '':
        return empty
    if isinstance(value, date):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return empty
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.strptime(text, USER_DATE_FORMAT).date()
            except ValueError as exc:
                raise ValueError('date must be MM/DD/YYYY') from exc
    return parsed.strftime(USER_DATE_FORMAT)


def parse_user_date(value: str, *, label: str = 'date') -> str | None:
    """Parse a user-facing MM/DD/YYYY date to ISO YYYY-MM-DD.

    ISO input remains accepted for compatibility with existing automation and old
    saved test fixtures, but the user-facing Windows UI only presents MM/DD/YYYY.
    """
    text = str(value or '').strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, USER_DATE_FORMAT).date()
    except ValueError:
        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f'{label} date must be MM/DD/YYYY') from exc
    return parsed.isoformat()


def resolve_date_range(preset: str, *, today: date | None = None, custom_start: str = '', custom_end: str = ''):
    """Resolve UI dates to inclusive ISO boundaries used by Graph/archive logic."""
    today = today or date.today()
    if preset == 'Older than 30 days':
        return None, (today - timedelta(days=30)).isoformat()
    if preset == 'Older than 90 days':
        return None, (today - timedelta(days=90)).isoformat()
    if preset == 'Older than 6 months':
        return None, _subtract_months(today, 6).isoformat()
    if preset == 'Older than 1 year':
        return None, _subtract_months(today, 12).isoformat()
    if preset != 'Custom':
        raise ValueError('unknown date preset')

    start = parse_user_date(custom_start, label='start')
    end = parse_user_date(custom_end, label='end')
    if start and end and date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError('start date cannot be after end date')
    return start, end
