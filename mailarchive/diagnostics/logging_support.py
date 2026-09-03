import logging,re
TOKEN_PATTERNS=[re.compile(r'(?i)authorization:\s*bearer\s+\S+'),re.compile(r'(?i)(access_token|refresh_token)["\'=:\s]+[^\s,}]+')]
class PrivacyFilter(logging.Filter):
    def filter(self,record):
        text=record.getMessage()
        for p in TOKEN_PATTERNS: text=p.sub('[REDACTED]',text)
        record.msg=text; record.args=(); return True
