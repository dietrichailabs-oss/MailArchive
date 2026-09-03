class CredentialProtectionUnavailable(RuntimeError): pass

def persist_plaintext_token(*args,**kwargs):
    raise CredentialProtectionUnavailable('plaintext token persistence is forbidden')
