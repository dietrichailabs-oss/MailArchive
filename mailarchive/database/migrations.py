from __future__ import annotations

import sqlite3

LATEST_SCHEMA_VERSION = 5

MIGRATIONS: dict[int, str] = {
    1: r'''
    CREATE TABLE IF NOT EXISTS messages(
      archive_id TEXT PRIMARY KEY,
      provider_id TEXT NOT NULL,
      folder_id TEXT,
      internet_message_id TEXT,
      subject TEXT,
      sender TEXT,
      recipients TEXT DEFAULT '',
      received_ts TEXT,
      sent_ts TEXT,
      retrieval_ts TEXT,
      eml_path TEXT,
      sha256 TEXT,
      mime_size INTEGER,
      attachment_count INTEGER NOT NULL DEFAULT 0,
      verification_status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(verification_status IN ('PENDING','VERIFIED','FAILED'))
    );
    CREATE TABLE IF NOT EXISTS attachments(
      id INTEGER PRIMARY KEY,
      archive_id TEXT NOT NULL REFERENCES messages(archive_id),
      filename TEXT,
      sanitized_filename TEXT,
      mime_type TEXT,
      size INTEGER,
      sha256 TEXT,
      relative_path TEXT,
      extraction_status TEXT
    );
    CREATE TABLE IF NOT EXISTS verification(
      archive_id TEXT PRIMARY KEY REFERENCES messages(archive_id),
      verified_at TEXT,
      detail TEXT
    );
    CREATE TABLE IF NOT EXISTS cleanup_state(
      archive_id TEXT PRIMARY KEY REFERENCES messages(archive_id),
      provider_id_at_archive TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'NOT_ATTEMPTED',
      last_detail TEXT
    );
    CREATE TABLE IF NOT EXISTS archive_jobs(
      job_id TEXT PRIMARY KEY,
      status TEXT NOT NULL,
      selected_folders TEXT NOT NULL DEFAULT '[]',
      start_date TEXT,
      end_date TEXT,
      discovered_count INTEGER NOT NULL DEFAULT 0,
      processed_count INTEGER NOT NULL DEFAULT 0,
      verified_count INTEGER NOT NULL DEFAULT 0,
      failed_count INTEGER NOT NULL DEFAULT 0,
      created_at TEXT,
      updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS archive_job_items(
      job_id TEXT,
      archive_id TEXT,
      provider_id TEXT,
      status TEXT,
      detail TEXT,
      PRIMARY KEY(job_id,archive_id)
    );
    CREATE TABLE IF NOT EXISTS errors(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id TEXT,
      archive_id TEXT,
      code TEXT,
      detail TEXT,
      created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS checkpoints(
      job_id TEXT PRIMARY KEY,
      payload TEXT,
      updated_at TEXT
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
      archive_id UNINDEXED, subject, sender, recipients, body, attachment_filenames
    );
    ''',
    2: r'''
    ALTER TABLE messages ADD COLUMN identity_ambiguous INTEGER NOT NULL DEFAULT 0;
    CREATE INDEX IF NOT EXISTS idx_messages_provider_id ON messages(provider_id);
    CREATE INDEX IF NOT EXISTS idx_messages_internet_message_id ON messages(internet_message_id);
    CREATE INDEX IF NOT EXISTS idx_messages_sha256 ON messages(sha256);
    CREATE INDEX IF NOT EXISTS idx_messages_received_ts ON messages(received_ts);
    ''',
    3: r'''
    ALTER TABLE attachments ADD COLUMN content_id TEXT;
    CREATE INDEX IF NOT EXISTS idx_attachments_archive_id ON attachments(archive_id);
    CREATE INDEX IF NOT EXISTS idx_attachments_content_id ON attachments(archive_id,content_id);
    ''',
    4: r'''
    ALTER TABLE archive_jobs ADD COLUMN stop_reason TEXT NOT NULL DEFAULT '';

    CREATE TABLE IF NOT EXISTS archive_metadata(
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS accounts(
      account_id TEXT PRIMARY KEY,
      display_name TEXT,
      principal_hint TEXT,
      created_at TEXT,
      last_used_at TEXT
    );
    CREATE TABLE IF NOT EXISTS folders(
      folder_id TEXT PRIMARY KEY,
      display_name TEXT,
      parent_folder_id TEXT,
      source_account_id TEXT,
      last_seen_at TEXT
    );
    CREATE TABLE IF NOT EXISTS recipients(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      archive_id TEXT NOT NULL REFERENCES messages(archive_id) ON DELETE CASCADE,
      kind TEXT NOT NULL DEFAULT 'TO',
      address TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_recipients_archive_id ON recipients(archive_id);
    CREATE INDEX IF NOT EXISTS idx_recipients_address ON recipients(address);

    CREATE TABLE IF NOT EXISTS hashes(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      archive_id TEXT NOT NULL REFERENCES messages(archive_id) ON DELETE CASCADE,
      object_kind TEXT NOT NULL,
      relative_path TEXT NOT NULL,
      sha256 TEXT NOT NULL,
      size INTEGER,
      UNIQUE(archive_id, object_kind, relative_path)
    );
    CREATE INDEX IF NOT EXISTS idx_hashes_archive_id ON hashes(archive_id);

    CREATE TABLE IF NOT EXISTS cleanup_jobs(
      cleanup_job_id TEXT PRIMARY KEY,
      status TEXT NOT NULL,
      requested_count INTEGER NOT NULL DEFAULT 0,
      moved_count INTEGER NOT NULL DEFAULT 0,
      failed_count INTEGER NOT NULL DEFAULT 0,
      skipped_count INTEGER NOT NULL DEFAULT 0,
      missing_count INTEGER NOT NULL DEFAULT 0,
      started_at TEXT,
      stopped_at TEXT,
      detail TEXT NOT NULL DEFAULT ''
    );
    ''',
    5: r'''
    ALTER TABLE cleanup_jobs ADD COLUMN unknown_count INTEGER NOT NULL DEFAULT 0;
    ''',
}


def apply_migrations(connection: sqlite3.Connection) -> int:
    current = int(connection.execute('PRAGMA user_version').fetchone()[0])
    if current > LATEST_SCHEMA_VERSION:
        raise RuntimeError(f'archive schema {current} is newer than supported {LATEST_SCHEMA_VERSION}')
    for version in range(current + 1, LATEST_SCHEMA_VERSION + 1):
        with connection:
            connection.executescript(MIGRATIONS[version])
            connection.execute(f'PRAGMA user_version={version}')
    return LATEST_SCHEMA_VERSION
