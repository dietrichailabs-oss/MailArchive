from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os

from mailarchive.microsoft.authentication.oauth import MicrosoftAuthenticator, OAuthConfig
from mailarchive.microsoft.graph_client.client import GraphClient
from mailarchive.microsoft.mailbox_provider.provider import MicrosoftGraphMailboxProvider
from mailarchive.security.token_cache import ProtectedTokenCacheStore


class MicrosoftConfigurationError(RuntimeError):
    pass


def load_client_id(resource_path: str | Path | None = None) -> str:
    value = os.environ.get('MAILARCHIVE_CLIENT_ID', '').strip()
    if value:
        return value
    if resource_path:
        path = Path(resource_path)
        if path.exists():
            try:
                value = str(json.loads(path.read_text(encoding='utf-8')).get('client_id') or '').strip()
            except Exception as exc:
                raise MicrosoftConfigurationError('Microsoft application configuration is invalid') from exc
            if value and value != 'REPLACE_WITH_MICROSOFT_ENTRA_APP_CLIENT_ID':
                return value
    raise MicrosoftConfigurationError(
        'MailArchive Microsoft sign-in is not configured. A Dietrich AI Labs Entra desktop-app client ID is required.'
    )


@dataclass
class MicrosoftProviderSession:
    authenticator: MicrosoftAuthenticator

    @classmethod
    def create(cls, client_id: str, cache_path: str | Path):
        cache = ProtectedTokenCacheStore(cache_path)
        return cls(MicrosoftAuthenticator(OAuthConfig(client_id=client_id), cache))

    def sign_in_archive(self):
        # Interactive only at explicit sign-in. Every later request uses MSAL silent cache acquisition.
        self.authenticator.acquire_archive_token(interactive=True)
        client = GraphClient(lambda: self.authenticator.acquire_archive_token(interactive=False))
        return MicrosoftGraphMailboxProvider(client, can_cleanup=False, account_metadata=self.authenticator.account_metadata())

    def cleanup_provider(self):
        # Mail.ReadWrite is requested only after the user explicitly selects cleanup.
        self.authenticator.acquire_cleanup_token(interactive=True)
        client = GraphClient(lambda: self.authenticator.acquire_cleanup_token(interactive=False))
        return MicrosoftGraphMailboxProvider(client, can_cleanup=True, account_metadata=self.authenticator.account_metadata())

    def sign_out(self):
        self.authenticator.sign_out()
