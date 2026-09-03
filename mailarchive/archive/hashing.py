import hashlib

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()

def sha256_file(path, chunk=1024*1024):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(chunk), b''):
            h.update(b)
    return h.hexdigest().upper()
