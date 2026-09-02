from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import re

from mailarchive.database.readonly import connect_readonly


@dataclass(frozen=True)
class SearchQuery:
    text: str = ''
    subject: str = ''
    sender: str = ''
    recipient: str = ''
    start_date: str | None = None
    end_date: str | None = None
    folder: str | None = None
    has_attachment: bool | None = None
    sort: Literal['newest', 'oldest'] = 'newest'
    limit: int = 200


def _fts_literal(value: str) -> str:
    # Treat normal UI input as literal terms instead of exposing FTS query syntax.
    terms = [t for t in re.split(r'\s+', value.strip()) if t]
    return ' AND '.join('"' + term.replace('"', '""') + '"' for term in terms)


def search(root, q='', limit=200, **filters):
    query = q if isinstance(q, SearchQuery) else SearchQuery(text=q, limit=limit, **filters)
    limit = max(1, min(int(query.limit), 1000))
    db = connect_readonly(root)
    sql = ['SELECT DISTINCT m.* FROM messages m']
    params = []
    fts_terms = []
    if query.text.strip():
        fts_terms.append(_fts_literal(query.text))
    if query.subject.strip():
        fts_terms.append('subject:' + _fts_literal(query.subject))
    if query.sender.strip():
        fts_terms.append('sender:' + _fts_literal(query.sender))
    if query.recipient.strip():
        fts_terms.append('recipients:' + _fts_literal(query.recipient))
    if fts_terms:
        sql.append('JOIN message_fts f ON f.archive_id=m.archive_id')
    where = ["m.verification_status='VERIFIED'"]
    if fts_terms:
        where.append('message_fts MATCH ?')
        params.append(' AND '.join(fts_terms))
    if query.start_date:
        where.append('substr(m.received_ts,1,10) >= ?')
        params.append(query.start_date[:10])
    if query.end_date:
        where.append('substr(m.received_ts,1,10) <= ?')
        params.append(query.end_date[:10])
    if query.folder:
        where.append('m.folder_id = ?')
        params.append(query.folder)
    if query.has_attachment is not None:
        where.append('m.attachment_count > 0' if query.has_attachment else 'm.attachment_count = 0')
    sql.append('WHERE ' + ' AND '.join(where))
    sql.append('ORDER BY m.received_ts ' + ('ASC' if query.sort == 'oldest' else 'DESC'))
    sql.append('LIMIT ?')
    params.append(limit)
    rows = db.execute(' '.join(sql), params).fetchall()
    db.close()
    return [dict(row) for row in rows]
