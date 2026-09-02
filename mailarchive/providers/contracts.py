from abc import ABC, abstractmethod
from typing import Iterable
from mailarchive.domain.models import ProviderMessage


class ProviderError(RuntimeError): pass
class AuthenticationRequired(ProviderError): pass
class PermissionDenied(ProviderError): pass
class RateLimited(ProviderError):
    def __init__(self, retry_after: float = 1.0):
        super().__init__(f'rate limited; retry after {retry_after}')
        self.retry_after = max(0.0, float(retry_after))
class NetworkUnavailable(ProviderError): pass
class MessageNotFound(ProviderError): pass
class FolderNotFound(ProviderError): pass
class InvalidResponse(ProviderError): pass
class ProviderUnavailable(ProviderError): pass
class OperationCancelled(ProviderError): pass


class MailboxProvider(ABC):
    @abstractmethod
    def list_folders(self) -> list[dict]: ...

    @abstractmethod
    def discover_messages(self, folder_ids: list[str], start: str | None, end: str | None) -> Iterable[ProviderMessage]: ...

    @abstractmethod
    def get_message_metadata(self, provider_id: str) -> ProviderMessage: ...

    @abstractmethod
    def get_message_mime(self, provider_id: str) -> bytes: ...

    @abstractmethod
    def move_message_to_deleted_items(self, provider_id: str) -> str: ...

    @abstractmethod
    def get_capabilities(self) -> dict: ...

    def get_account_metadata(self) -> dict:
        # Optional local identity hint used only for archive provenance. Providers need not
        # request extra permissions merely to populate it.
        return {}
