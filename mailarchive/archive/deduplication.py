from __future__ import annotations

from sqlite3 import Connection

from mailarchive.database.connection import connect


class IdentityGuard:
    """Marks cleanup-unsafe identity collisions without discarding archived content."""

    def __init__(self, root):
        self.root = root

    def register_and_check(
        self,
        archive_id: str,
        provider_id: str,
        internet_message_id: str | None,
        *,
        db: Connection | None = None,
    ) -> bool:
        conn = db or connect(self.root)
        owned = db is None
        try:
            colliding_ids: set[str] = set()
            for row in conn.execute(
                'SELECT archive_id FROM messages WHERE provider_id=? AND archive_id<>?',
                (provider_id, archive_id),
            ):
                colliding_ids.add(row['archive_id'])
            if internet_message_id:
                for row in conn.execute(
                    'SELECT archive_id FROM messages WHERE internet_message_id=? AND archive_id<>?',
                    (internet_message_id, archive_id),
                ):
                    colliding_ids.add(row['archive_id'])
            ambiguous = bool(colliding_ids)
            if ambiguous:
                def mark_ambiguous() -> None:
                    conn.execute('UPDATE messages SET identity_ambiguous=1 WHERE archive_id=?', (archive_id,))
                    conn.executemany(
                        'UPDATE messages SET identity_ambiguous=1 WHERE archive_id=?',
                        ((x,) for x in colliding_ids),
                    )

                if conn.in_transaction:
                    mark_ambiguous()
                else:
                    with conn:
                        mark_ambiguous()
            return ambiguous
        finally:
            if owned:
                conn.close()
