from email import policy
from email.parser import BytesParser
from datetime import datetime, timezone
from mailarchive.archive.hashing import sha256_file


class VerificationError(RuntimeError):
    pass


class Verifier:
    def verify_file(self, path, expected_hash):
        if not path.exists():
            raise VerificationError('eml missing')
        if path.stat().st_size <= 0:
            raise VerificationError('eml empty')
        actual = sha256_file(path)
        if actual != expected_hash:
            raise VerificationError('hash mismatch')
        raw = path.read_bytes()
        if b'\x00' in raw:
            raise VerificationError('mime contains NUL bytes')
        if b'\r\n\r\n' not in raw and b'\n\n' not in raw:
            raise VerificationError('mime appears incomplete: no header/body separator')
        try:
            msg = BytesParser(policy=policy.default).parsebytes(raw)
        except Exception as exc:
            raise VerificationError(f'mime parse failed: {exc}') from exc
        if not msg.keys():
            raise VerificationError('mime has no headers')
        if msg.defects:
            names = ','.join(type(defect).__name__ for defect in msg.defects[:8])
            raise VerificationError(f'mime parser reported structural defects: {names}')
        # Multipart truncation can hide in nested child defects, so inspect every part.
        for part in msg.walk():
            if part.defects:
                names = ','.join(type(defect).__name__ for defect in part.defects[:8])
                raise VerificationError(f'mime part reported structural defects: {names}')
        return {
            'sha256': actual,
            'size': len(raw),
            'parsed': True,
            'verified_at': datetime.now(timezone.utc).isoformat(),
        }
