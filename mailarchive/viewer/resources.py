from __future__ import annotations

from pathlib import Path
from mailarchive.database.readonly import connect_readonly
from mailarchive.archive.hashing import sha256_file


class ResourceNotFound(FileNotFoundError):
    pass


def resolve_attachment(root, archive_id: str, attachment_id: int):
    root = Path(root).resolve()
    db = connect_readonly(root)
    row = db.execute(
        '''SELECT relative_path,mime_type,sanitized_filename,sha256
           FROM attachments WHERE id=? AND archive_id=? AND extraction_status='EXTRACTED' ''',
        (attachment_id, archive_id),
    ).fetchone()
    db.close()
    if not row:
        raise ResourceNotFound('attachment not found')
    path = (root / row['relative_path']).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ResourceNotFound('attachment path escaped archive root') from exc
    if not path.is_file():
        raise ResourceNotFound('attachment file missing')
    try:
        if sha256_file(path) != row['sha256']:
            raise ResourceNotFound('attachment hash mismatch')
    except OSError as exc:
        raise ResourceNotFound('attachment file unavailable') from exc
    return path, dict(row)


def cid_resource_map(root, archive_id: str) -> dict[str, str]:
    db = connect_readonly(root)
    rows = db.execute(
        "SELECT id,content_id FROM attachments WHERE archive_id=? AND content_id IS NOT NULL",
        (archive_id,),
    ).fetchall()
    db.close()
    return {row['content_id'].lower(): f'/resource/{archive_id}/{row["id"]}' for row in rows}
