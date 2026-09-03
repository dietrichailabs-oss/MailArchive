import pytest
from mailarchive.security.credentials import persist_plaintext_token, CredentialProtectionUnavailable

def test_plaintext_token_persistence_is_forbidden():
    with pytest.raises(CredentialProtectionUnavailable): persist_plaintext_token('secret')
