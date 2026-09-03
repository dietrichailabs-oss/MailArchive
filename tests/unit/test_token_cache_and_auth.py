from pathlib import Path

from mailarchive.microsoft.authentication.oauth import MicrosoftAuthenticator, OAuthConfig
from mailarchive.security.token_cache import ProtectedTokenCacheStore


class Protector:
    @staticmethod
    def protect(data): return b'ENC:' + data[::-1]
    @staticmethod
    def unprotect(data):
        assert data.startswith(b'ENC:')
        return data[4:][::-1]


def test_token_cache_is_not_plaintext(tmp_path):
    store = ProtectedTokenCacheStore(tmp_path / 'token.cache', protector=Protector)
    store.save('refresh-token-secret')
    raw = (tmp_path / 'token.cache').read_bytes()
    assert b'refresh-token-secret' not in raw
    assert store.load() == 'refresh-token-secret'
    store.clear()
    assert not (tmp_path / 'token.cache').exists()


class Cache:
    def __init__(self): self.has_state_changed = True; self.value = ''
    def deserialize(self, value): self.value = value
    def serialize(self): return 'serialized-cache-without-test-token'


class App:
    def __init__(self, *a, **kw): self.accounts = [{'username': 'user@example.test'}]
    def get_accounts(self): return list(self.accounts)
    def acquire_token_silent(self, scopes, account): return {'access_token': 'silent-access'}
    def acquire_token_interactive(self, scopes, prompt): raise AssertionError('interactive should not run')
    def remove_account(self, account): self.accounts.remove(account)


class MSAL:
    SerializableTokenCache = Cache
    PublicClientApplication = App


class Store:
    def __init__(self): self.saved = None; self.cleared = False
    def load(self): return ''
    def save(self, value): self.saved = value
    def clear(self): self.cleared = True


def test_auth_prefers_silent_and_persists_protected_cache():
    store = Store()
    auth = MicrosoftAuthenticator(OAuthConfig('client-id'), store, msal_module=MSAL)
    assert auth.acquire_archive_token() == 'silent-access'
    assert auth.account_metadata()['principal_hint'] == 'user@example.test'
    assert store.saved == 'serialized-cache-without-test-token'
    auth.sign_out()
    assert store.cleared
