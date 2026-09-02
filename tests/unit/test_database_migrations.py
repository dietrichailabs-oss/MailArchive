from mailarchive.database.connection import connect
from mailarchive.database.migrations import LATEST_SCHEMA_VERSION


def test_new_archive_reaches_latest_schema(tmp_path):
    db = connect(tmp_path)
    version = db.execute('PRAGMA user_version').fetchone()[0]
    cols = {row['name'] for row in db.execute('PRAGMA table_info(messages)')}
    db.close()
    assert version == LATEST_SCHEMA_VERSION
    assert 'identity_ambiguous' in cols
