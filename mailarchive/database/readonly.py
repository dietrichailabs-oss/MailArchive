from __future__ import annotations

from pathlib import Path
import sqlite3


def connect_readonly(root):
    path = (Path(root) / 'archive.db').resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = path.as_uri() + '?mode=ro'
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    connection.execute('PRAGMA foreign_keys=ON')
    return connection
