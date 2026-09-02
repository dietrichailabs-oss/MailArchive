from __future__ import annotations

from email import policy
from email.parser import BytesParser
from html import escape
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote
import mimetypes

from mailarchive.database.readonly import connect_readonly
from mailarchive.archive.hashing import sha256_file
from mailarchive.search.service import SearchQuery, search
from mailarchive.viewer.resources import cid_resource_map, resolve_attachment, ResourceNotFound
from mailarchive.viewer.sanitizer import sanitize_html


CSP = "default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"
INLINE_IMAGE_TYPES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp'}


def _bool_filter(value: str | None):
    if value == '1':
        return True
    if value == '0':
        return False
    return None


class ArchiveViewer:
    def __init__(self, archive_root):
        self.root = Path(archive_root).resolve()
        self.server = None

    def make_handler(self):
        root = self.root

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if not self._valid_host_header():
                    self.send_error(421, 'viewer accepts loopback Host headers only')
                    return
                parsed_url = urlparse(self.path)
                if parsed_url.path == '/':
                    rows = search(root, SearchQuery(limit=200))
                    return self._render_list(rows, title='MailArchive')

                if parsed_url.path == '/search':
                    params = parse_qs(parsed_url.query)
                    query = SearchQuery(
                        text=params.get('q', [''])[0],
                        subject=params.get('subject', [''])[0],
                        sender=params.get('sender', [''])[0],
                        recipient=params.get('recipient', [''])[0],
                        start_date=params.get('start', [None])[0] or None,
                        end_date=params.get('end', [None])[0] or None,
                        folder=params.get('folder', [None])[0] or None,
                        has_attachment=_bool_filter(params.get('has_attachment', [None])[0]),
                        sort='oldest' if params.get('sort', ['newest'])[0] == 'oldest' else 'newest',
                        limit=500,
                    )
                    rows = search(root, query)
                    return self._render_list(rows, title='Search results', query=query)

                if parsed_url.path == '/message':
                    aid = parse_qs(parsed_url.query).get('id', [''])[0]
                    return self._render_message(aid)

                if parsed_url.path.startswith('/resource/'):
                    return self._serve_resource(parsed_url.path)

                if parsed_url.path.startswith('/attachment/'):
                    return self._serve_attachment(parsed_url.path)

                if parsed_url.path.startswith('/original/'):
                    return self._serve_original(parsed_url.path)

                if parsed_url.path.startswith('/raw/'):
                    return self._serve_raw_headers(parsed_url.path)

                self.send_error(404)

            def _valid_host_header(self):
                value = (self.headers.get('Host') or '').strip().casefold()
                if not value:
                    return False
                host = value
                if host.startswith('['):
                    end = host.find(']')
                    host = host[1:end] if end >= 0 else host
                elif ':' in host:
                    host = host.rsplit(':', 1)[0]
                return host in {'127.0.0.1', 'localhost', '::1'}

            def do_POST(self):
                self.send_error(405, 'archive viewer is read-only')

            def _folder_options(self, selected=''):
                db = connect_readonly(root)
                rows = db.execute(
                    """SELECT DISTINCT m.folder_id, COALESCE(f.display_name, m.folder_id) AS display_name
                       FROM messages m LEFT JOIN folders f ON f.folder_id=m.folder_id
                       WHERE m.verification_status='VERIFIED' AND m.folder_id IS NOT NULL
                       ORDER BY display_name, m.folder_id"""
                ).fetchall()
                db.close()
                options = ['<option value="">All folders</option>']
                for row in rows:
                    value = row['folder_id'] or ''
                    marker = ' selected' if value == selected else ''
                    label = row['display_name'] or value
                    options.append(f'<option value="{escape(value, quote=True)}"{marker}>{escape(label)}</option>')
                return ''.join(options)

            def _render_list(self, rows, *, title, query=None):
                query = query or SearchQuery()
                items = ''.join(
                    '<li>'
                    f'<a href="/message?id={quote(row["archive_id"], safe="")}">{escape(row.get("subject") or "(no subject)")}</a> '
                    f'— {escape(row.get("sender") or "")} — {escape(row.get("received_ts") or "")}'
                    f'{" — attachment" if int(row.get("attachment_count") or 0) else ""}'
                    '</li>'
                    for row in rows
                )
                attachment_value = '' if query.has_attachment is None else ('1' if query.has_attachment else '0')
                body = (
                    f'<h1>{escape(title)}</h1>'
                    '<form action="/search" method="get">'
                    '<fieldset><legend>Search and filters</legend>'
                    f'<label>Any text <input name="q" value="{escape(query.text, quote=True)}"></label> '
                    f'<label>Subject <input name="subject" value="{escape(query.subject, quote=True)}"></label> '
                    f'<label>Sender <input name="sender" value="{escape(query.sender, quote=True)}"></label> '
                    f'<label>Recipient <input name="recipient" value="{escape(query.recipient, quote=True)}"></label><br>'
                    f'<label>Start <input type="date" name="start" value="{escape(query.start_date or "", quote=True)}"></label> '
                    f'<label>End <input type="date" name="end" value="{escape(query.end_date or "", quote=True)}"></label> '
                    f'<label>Folder <select name="folder">{self._folder_options(query.folder or "")}</select></label> '
                    '<label>Attachments <select name="has_attachment">'
                    f'<option value=""{" selected" if attachment_value == "" else ""}>Any</option>'
                    f'<option value="1"{" selected" if attachment_value == "1" else ""}>Has attachment</option>'
                    f'<option value="0"{" selected" if attachment_value == "0" else ""}>No attachment</option>'
                    '</select></label> '
                    '<label>Sort <select name="sort">'
                    f'<option value="newest"{" selected" if query.sort == "newest" else ""}>Newest first</option>'
                    f'<option value="oldest"{" selected" if query.sort == "oldest" else ""}>Oldest first</option>'
                    '</select></label> '
                    '<button type="submit">Search</button> <a href="/">Clear</a>'
                    '</fieldset></form>'
                    f'<p>{len(rows)} message(s)</p><ul>{items}</ul>'
                )
                self._html(body)

            def _render_message(self, aid):
                db = connect_readonly(root)
                row = db.execute(
                    "SELECT * FROM messages WHERE archive_id=? AND verification_status='VERIFIED'",
                    (aid,),
                ).fetchone()
                attachments = db.execute(
                    '''SELECT id,sanitized_filename,mime_type,size,content_id
                       FROM attachments WHERE archive_id=? AND extraction_status='EXTRACTED' ORDER BY id''',
                    (aid,),
                ).fetchall() if row else []
                db.close()
                if not row:
                    return self.send_error(404)
                path = self._safe_message_path(row['eml_path'], row['sha256'])
                if path is None:
                    return self.send_error(404)
                msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
                body = ''
                cid_map = cid_resource_map(root, aid)
                for part in (msg.walk() if msg.is_multipart() else [msg]):
                    if part.get_content_disposition() == 'attachment':
                        continue
                    if part.get_content_type() == 'text/html':
                        try:
                            body = sanitize_html(part.get_content(), cid_map=cid_map)
                            break
                        except Exception:
                            pass
                    if part.get_content_type() == 'text/plain' and not body:
                        try:
                            body = '<pre>' + sanitize_html(part.get_content()) + '</pre>'
                        except Exception:
                            pass
                attachment_html = ''.join(
                    f'<li><a href="/attachment/{quote(aid, safe="")}/{item["id"]}">{sanitize_html(item["sanitized_filename"] or "attachment")}</a> '
                    f'({int(item["size"] or 0)} bytes)</li>'
                    for item in attachments
                ) or '<li>None</li>'
                header = (
                    f'<p><strong>From:</strong> {sanitize_html(row["sender"] or "")}</p>'
                    f'<p><strong>To:</strong> {sanitize_html(row["recipients"] or "")}</p>'
                    f'<p><strong>Date:</strong> {sanitize_html(row["received_ts"] or "")}</p>'
                    f'<h2>{sanitize_html(row["subject"] or "(no subject)")}</h2>'
                )
                nav = self._message_navigation(aid)
                actions = (
                    f'<p><a href="/original/{quote(aid, safe="")}">Save original .eml</a> &nbsp; '
                    f'<a href="/raw/{quote(aid, safe="")}">View raw headers</a></p>'
                    f'<h3>Attachments</h3><ul>{attachment_html}</ul>'
                )
                self._html('<p><a href="/">← Archive</a></p>' + nav + header + body + actions + nav)

            def _message_navigation(self, aid):
                db = connect_readonly(root)
                row = db.execute(
                    '''WITH ordered AS (
                         SELECT archive_id,
                                LAG(archive_id) OVER (ORDER BY received_ts DESC, archive_id) AS previous_id,
                                LEAD(archive_id) OVER (ORDER BY received_ts DESC, archive_id) AS next_id
                         FROM messages WHERE verification_status='VERIFIED'
                       )
                       SELECT previous_id,next_id FROM ordered WHERE archive_id=?''',
                    (aid,),
                ).fetchone()
                db.close()
                if not row:
                    return ''
                previous = (f'<a rel="prev" href="/message?id={quote(row["previous_id"], safe="")}">← Previous</a>'
                            if row['previous_id'] else '<span>← Previous</span>')
                nxt = (f'<a rel="next" href="/message?id={quote(row["next_id"], safe="")}">Next →</a>'
                       if row['next_id'] else '<span>Next →</span>')
                return f'<nav>{previous} &nbsp; {nxt}</nav>'

            def _safe_message_path(self, relative, expected_hash):
                if not relative or not expected_hash:
                    return None
                path = (root / relative).resolve()
                try:
                    path.relative_to(root)
                except ValueError:
                    return None
                if not path.is_file():
                    return None
                try:
                    if sha256_file(path) != expected_hash:
                        return None
                except OSError:
                    return None
                return path

            def _serve_resource(self, path_text):
                bits = path_text.split('/')
                if len(bits) != 4:
                    return self.send_error(404)
                aid = bits[2]
                try:
                    attachment_id = int(bits[3])
                    path, metadata = resolve_attachment(root, aid, attachment_id)
                except (ValueError, ResourceNotFound):
                    return self.send_error(404)
                content_type = (metadata.get('mime_type') or '').lower()
                if content_type not in INLINE_IMAGE_TYPES:
                    return self.send_error(404)
                raw = path.read_bytes()
                self._binary(raw, content_type, disposition='inline', filename=metadata.get('sanitized_filename'))

            def _serve_attachment(self, path_text):
                bits = path_text.split('/')
                if len(bits) != 4:
                    return self.send_error(404)
                aid = bits[2]
                try:
                    attachment_id = int(bits[3])
                    path, metadata = resolve_attachment(root, aid, attachment_id)
                except (ValueError, ResourceNotFound):
                    return self.send_error(404)
                raw = path.read_bytes()
                self._binary(raw, 'application/octet-stream', disposition='attachment', filename=metadata.get('sanitized_filename'))

            def _serve_raw_headers(self, path_text):
                bits = path_text.split('/')
                if len(bits) != 3 or not bits[2]:
                    return self.send_error(404)
                aid = bits[2]
                db = connect_readonly(root)
                row = db.execute(
                    "SELECT eml_path,sha256 FROM messages WHERE archive_id=? AND verification_status='VERIFIED'",
                    (aid,),
                ).fetchone()
                db.close()
                if not row:
                    return self.send_error(404)
                path = self._safe_message_path(row['eml_path'], row['sha256'])
                if path is None:
                    return self.send_error(404)
                raw = path.read_bytes()
                separator = b'\r\n\r\n' if b'\r\n\r\n' in raw else b'\n\n'
                header_bytes = raw.split(separator, 1)[0]
                # Raw headers are archive data, not executable HTML. Escape everything before rendering.
                header_text = header_bytes.decode('utf-8', errors='replace')
                self._html(
                    '<p><a href="/message?id=' + quote(aid, safe='') + '">← Message</a></p>'
                    '<h1>Raw message headers</h1><pre>' + escape(header_text) + '</pre>'
                )

            def _serve_original(self, path_text):
                bits = path_text.split('/')
                if len(bits) != 3 or not bits[2]:
                    return self.send_error(404)
                aid = bits[2]
                db = connect_readonly(root)
                row = db.execute(
                    "SELECT eml_path,sha256 FROM messages WHERE archive_id=? AND verification_status='VERIFIED'",
                    (aid,),
                ).fetchone()
                db.close()
                if not row:
                    return self.send_error(404)
                path = self._safe_message_path(row['eml_path'], row['sha256'])
                if path is None:
                    return self.send_error(404)
                self._binary(path.read_bytes(), 'message/rfc822', disposition='attachment', filename=f'{aid}.eml')

            def _binary(self, raw, content_type, *, disposition, filename):
                filename = (filename or 'download').replace('"', '_').replace('\r', '_').replace('\n', '_')
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Content-Disposition', f'{disposition}; filename="{filename}"')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'none'; sandbox")
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
                self.send_header('X-Frame-Options', 'DENY')
                self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=(), usb=()')
                self.end_headers()
                self.wfile.write(raw)

            def _html(self, body):
                raw = (
                    '<!doctype html><meta charset=utf-8>'
                    f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
                    '<body>' + body + '</body>'
                ).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Content-Security-Policy', CSP)
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
                self.send_header('X-Frame-Options', 'DENY')
                self.send_header('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=(), usb=()')
                self.end_headers()
                self.wfile.write(raw)

        return Handler

    def start(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.make_handler())
        return self.server.server_address
