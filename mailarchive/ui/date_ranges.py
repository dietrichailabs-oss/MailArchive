from __future__ import annotations

from datetime import date, timedelta
import calendar


PRESETS = ('Older than 30 days', 'Older than 90 days', 'Older than 6 months', 'Older than 1 year', 'Custom')


def _subtract_months(day: date, months: int) -> date:
    total = day.year * 12 + (day.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def resolve_date_range(preset: str, *, today: date | None = None, custom_start: str = '', custom_end: str = ''):
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
    start = custom_start.strip() or None
    end = custom_end.strip() or None
    for label, value in [('start', start), ('end', end)]:
        if value:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f'{label} date must be YYYY-MM-DD') from exc
    if start and end and start > end:
        raise ValueError('start date cannot be after end date')
    return start, end
