from pathlib import Path
import os, tempfile

class MimeStore:
    def __init__(self, root):
        self.root=Path(root)
        (self.root/'messages').mkdir(parents=True, exist_ok=True)
    def write_atomic(self, archive_id, data: bytes):
        final=self.root/'messages'/f'{archive_id}.eml'
        fd,tmp=tempfile.mkstemp(prefix=archive_id+'.', suffix='.part', dir=final.parent)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,final)
        except Exception:
            try: os.unlink(tmp)
            except FileNotFoundError: pass
            raise
        return final
