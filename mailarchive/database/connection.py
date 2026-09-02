import sqlite3
from pathlib import Path
from mailarchive.database.migrations import apply_migrations


def connect(root):
    p = Path(root) / 'archive.db'
    c = sqlite3.connect(p)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA synchronous=FULL')
    apply_migrations(c)
    return c
