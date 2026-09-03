from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys

from mailarchive.archive.manager import ArchiveRegistry
from mailarchive.configuration.settings import SettingsStore, application_data_dir
from mailarchive.runtime.microsoft_session import MicrosoftProviderSession, load_client_id
from mailarchive.ui.main_window.rc2 import RC2MailArchiveApp


def resource_dir() -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'resources'
    return Path(__file__).resolve().parent.parent / 'resources'


def runtime_self_test() -> None:
    client_id = load_client_id(resource_dir() / 'microsoft_app.json')
    if not client_id:
        raise RuntimeError('Microsoft client ID missing')
    if os.name == 'nt':
        from mailarchive.platform.windows.dpapi import protect, unprotect
        marker = b'MailArchive-DPAPI-self-test'
        if unprotect(protect(marker)) != marker:
            raise RuntimeError('Windows DPAPI roundtrip failed')
    # Import the full RC2 UI module without opening a window, proving packaging did not omit Tk modules.
    from mailarchive.ui.main_window import rc2 as _ui  # noqa: F401


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args(argv)
    if args.self_test:
        runtime_self_test()
        print('MAILARCHIVE_SELF_TEST_PASS')
        return 0
    data = application_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    client_id = load_client_id(resource_dir() / 'microsoft_app.json')
    session = MicrosoftProviderSession.create(client_id, data / 'auth.cache.dpapi')
    settings = SettingsStore(data / 'settings.json')
    registry = ArchiveRegistry(data / 'archives.json')
    app = RC2MailArchiveApp(session, settings, registry)
    app.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
