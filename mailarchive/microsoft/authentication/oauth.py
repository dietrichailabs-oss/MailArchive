from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from mailarchive.providers.contracts import AuthenticationRequired, PermissionDenied
from mailarchive.security.token_cache import ProtectedTokenCacheStore


ARCHIVE_SCOPES = ('Mail.Read',)
CLEANUP_SCOPES = ('Mail.ReadWrite',)


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str
    authority: str = 'https://login.microsoftonline.com/common'
    archive_scopes: tuple[str, ...] = ARCHIVE_SCOPES
    cleanup_scopes: tuple[str, ...] = CLEANUP_SCOPES


class MicrosoftAuthenticator:
    """MSAL public-client authentication. Direct password collection is intentionally impossible."""

    def __init__(self, config: OAuthConfig, cache_store: ProtectedTokenCacheStore | None = None, *, msal_module=None):
        self.config = config
        self.cache_store = cache_store
        self._msal = msal_module
        self._app = None
        self._cache = None

    def password_login(self, *args, **kwargs):
        raise RuntimeError('direct password login is forbidden')

    def _ensure_app(self):
        if self._app is not None:
            return
        msal = self._msal
        if msal is None:
            import msal
        self._cache = msal.SerializableTokenCache()
        if self.cache_store:
            serialized = self.cache_store.load()
            if serialized:
                self._cache.deserialize(serialized)
        self._app = msal.PublicClientApplication(
            self.config.client_id,
            authority=self.config.authority,
            token_cache=self._cache,
        )

    def acquire_archive_token(self, *, interactive=True) -> str:
        return self._acquire(self.config.archive_scopes, interactive=interactive)

    def acquire_cleanup_token(self, *, interactive=True) -> str:
        return self._acquire(self.config.cleanup_scopes, interactive=interactive)

    def _acquire(self, scopes: Iterable[str], *, interactive: bool) -> str:
        self._ensure_app()
        scopes = list(scopes)
        result = None
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(scopes, account=accounts[0])
        if not result and interactive:
            result = self._app.acquire_token_interactive(scopes=scopes, prompt='select_account')
        self._persist_if_changed()
        if not result:
            raise AuthenticationRequired('Microsoft sign-in is required')
        if 'access_token' in result:
            return result['access_token']
        error = result.get('error') or 'authentication_failed'
        description = result.get('error_description') or error
        if error in {'invalid_scope', 'unauthorized_client'}:
            raise PermissionDenied(description)
        raise AuthenticationRequired(description)

    def account_metadata(self) -> dict:
        self._ensure_app()
        accounts = self._app.get_accounts()
        if not accounts:
            return {}
        account = accounts[0] or {}
        username = str(account.get('username') or '').strip() if isinstance(account, dict) else ''
        home_id = str(account.get('home_account_id') or '').strip() if isinstance(account, dict) else ''
        return {
            'account_id': home_id or username,
            'principal_hint': username,
            'display_name': username,
        }

    def sign_out(self) -> None:
        self._ensure_app()
        for account in list(self._app.get_accounts()):
            self._app.remove_account(account)
        if self.cache_store:
            self.cache_store.clear()

    def _persist_if_changed(self):
        if self.cache_store and self._cache is not None and getattr(self._cache, 'has_state_changed', False):
            self.cache_store.save(self._cache.serialize())
