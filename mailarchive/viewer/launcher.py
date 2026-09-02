from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import http.client
import sys
import threading
import webbrowser

from mailarchive.viewer.server import ArchiveViewer


def archive_root_from_runtime() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def launch_archive(root: str | Path, *, open_browser: bool = True):
    root = Path(root).resolve()
    viewer = ArchiveViewer(root)
    host, port = viewer.start()
    if host not in {'127.0.0.1', '::1', 'localhost'}:
        viewer.server.server_close()
        raise RuntimeError('viewer refused non-loopback bind')
    url = f'http://127.0.0.1:{port}/'
    thread = threading.Thread(target=viewer.server.serve_forever, name='MailArchiveViewer', daemon=True)
    thread.start()
    if open_browser:
        webbrowser.open(url, new=1, autoraise=True)
    return viewer, thread, url


def self_test_archive(root: str | Path) -> None:
    root = Path(root).resolve()
    db_path = root / 'archive.db'
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    viewer, thread, _ = launch_archive(root, open_browser=False)
    host, port = viewer.server.server_address
    if host != '127.0.0.1':
        raise RuntimeError(f'non-loopback bind: {host}')
    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request('GET', '/')
        response = connection.getresponse()
        body = response.read()
        connection.close()
        if response.status != 200 or b'MailArchive' not in body:
            raise RuntimeError(f'viewer HTTP self-test failed: status={response.status}')
    finally:
        viewer.server.shutdown()
        viewer.server.server_close()
        thread.join(timeout=5)
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    if after != before:
        raise RuntimeError('viewer self-test modified archive.db')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Open a MailArchive archive offline')
    parser.add_argument('archive', nargs='?', default=None)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args(argv)
    root = Path(args.archive).resolve() if args.archive else archive_root_from_runtime()
    if args.self_test:
        self_test_archive(root)
        print('MAILARCHIVE_VIEWER_SELF_TEST_PASS')
        return 0
    viewer = ArchiveViewer(root)
    host, port = viewer.start()
    if host != '127.0.0.1':
        raise RuntimeError('viewer must bind to IPv4 loopback')
    if not args.no_browser:
        webbrowser.open(f'http://127.0.0.1:{port}/', new=1, autoraise=True)
    try:
        viewer.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        viewer.server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
