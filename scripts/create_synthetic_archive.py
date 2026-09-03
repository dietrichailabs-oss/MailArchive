from __future__ import annotations

import argparse
from pathlib import Path

from mailarchive.archive.job_engine import ArchiveJobEngine
from mailarchive.providers.fake_mailbox import FakeMailboxProvider


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    parser.add_argument('--messages', type=int, default=12)
    args = parser.parse_args(argv)
    root = Path(args.destination).resolve()
    provider = FakeMailboxProvider(messages=FakeMailboxProvider.synthetic_messages(args.messages), page_size=5)
    result = ArchiveJobEngine(provider, root).run(['inbox', 'sentitems'], job_id='windows-synthetic-gate')
    if not result or any(status != 'VERIFIED' for _, status in result):
        raise SystemExit('SYNTHETIC_ARCHIVE_FAILED')
    print(root)


if __name__ == '__main__':
    main()
