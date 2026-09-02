from __future__ import annotations

from urllib.parse import quote
import time

from mailarchive.domain.models import MessageRef, ProviderMessage
from mailarchive.providers.contracts import (
    MailboxProvider,
    MessageNotFound,
    FolderNotFound,
    InvalidResponse,
    NetworkUnavailable,
    ProviderUnavailable,
    RateLimited,
)


# Microsoft Graph message resource fields used by MailArchive. Do not add fields
# here unless they are supported by the v1.0 message resource and selectable on
# /me/mailFolders/{id}/messages. In particular, Graph message does not expose a
# selectable `size` property; asking for it causes HTTP 400 on real mailboxes.
MESSAGE_SELECT = 'id,internetMessageId,subject,from,toRecipients,receivedDateTime,sentDateTime,parentFolderId'
IMMUTABLE_ID_HEADERS = {'Prefer': 'IdType="ImmutableId"'}
FOLDER_SELECT = 'id,displayName,parentFolderId,childFolderCount,totalItemCount,isHidden'


def _escape_odata_datetime(value: str) -> str:
    # Accept YYYY-MM-DD or a complete ISO timestamp and normalize date-only values.
    if len(value) == 10:
        return value + 'T00:00:00Z'
    return value


def _inclusive_end(value: str) -> str:
    if len(value) == 10:
        return value + 'T23:59:59.9999999Z'
    return value


class MicrosoftGraphMailboxProvider(MailboxProvider):
    def __init__(self, client, *, can_cleanup: bool = False, account_metadata=None, sleep=time.sleep, max_read_retries: int = 4):
        self.client = client
        self.can_cleanup = can_cleanup
        self.account_metadata = dict(account_metadata or {})
        self.sleep = sleep
        self.max_read_retries = max(0, int(max_read_retries))

    def _read(self, path_or_url: str, **kwargs):
        """Retry only idempotent Graph reads.

        Mailbox-changing POST operations intentionally bypass this helper. A dropped
        response after a move can have an uncertain server-side outcome, so blindly
        retrying that write would violate MailArchive's cleanup safety model.
        """
        attempt = 0
        while True:
            try:
                return self.client.request('GET', path_or_url, **kwargs)
            except RateLimited as exc:
                attempt += 1
                if attempt > self.max_read_retries:
                    raise
                self.sleep(exc.retry_after)
            except (NetworkUnavailable, ProviderUnavailable):
                attempt += 1
                if attempt > self.max_read_retries:
                    raise
                # Bounded exponential backoff for transient connection loss/5xx.
                self.sleep(min(8.0, 2.0 ** (attempt - 1)))

    def _iter_collection(self, initial_path: str):
        next_link = initial_path
        while next_link:
            data = self._read(next_link, headers=IMMUTABLE_ID_HEADERS)
            if not isinstance(data, dict) or not isinstance(data.get('value'), list):
                raise InvalidResponse('Graph collection response is missing value[]')
            yield from data['value']
            next_link = data.get('@odata.nextLink')
            if next_link is not None and not isinstance(next_link, str):
                raise InvalidResponse('Graph @odata.nextLink is not a string')

    def list_folders(self):
        folders = []
        queue = [('/me/mailFolders?$top=100&$select=' + quote(FOLDER_SELECT, safe=',') + '&includeHiddenFolders=false', None)]
        seen = set()
        while queue:
            path, logical_parent = queue.pop(0)
            for raw in self._iter_collection(path):
                folder_id = raw.get('id')
                if not folder_id or folder_id in seen:
                    continue
                seen.add(folder_id)
                item = {
                    'id': folder_id,
                    'name': raw.get('displayName') or '(unnamed)',
                    'parent_id': raw.get('parentFolderId') or logical_parent,
                    'child_count': int(raw.get('childFolderCount') or 0),
                    'message_count': int(raw.get('totalItemCount') or 0),
                    'hidden': bool(raw.get('isHidden')),
                }
                folders.append(item)
                if item['child_count']:
                    encoded = quote(folder_id, safe='')
                    queue.append((
                        f'/me/mailFolders/{encoded}/childFolders?$top=100&$select=' + quote(FOLDER_SELECT, safe=',') + '&includeHiddenFolders=false',
                        folder_id,
                    ))
        return folders

    def discover_messages(self, folder_ids, start, end):
        for folder_id in folder_ids:
            encoded = quote(folder_id, safe='')
            params = [f'$top=100', '$select=' + quote(MESSAGE_SELECT, safe=',')]
            filters = []
            if start:
                filters.append(f'receivedDateTime ge {_escape_odata_datetime(start)}')
            if end:
                filters.append(f'receivedDateTime le {_inclusive_end(end)}')
            if filters:
                params.append('$filter=' + quote(' and '.join(filters), safe=':.-'))
            path = f'/me/mailFolders/{encoded}/messages?' + '&'.join(params)
            for raw in self._iter_collection(path):
                yield self._to_message(raw, fallback_folder=folder_id)

    def get_message_metadata(self, provider_id):
        encoded = quote(provider_id, safe='')
        response = self._read(f'/me/messages/{encoded}?$select=' + quote(MESSAGE_SELECT, safe=','), headers=IMMUTABLE_ID_HEADERS)
        if getattr(response, 'status_code', None) == 404:
            raise MessageNotFound(provider_id)
        if not isinstance(response, dict):
            raise InvalidResponse('message metadata response is not JSON')
        return self._to_message(response)

    def get_message_mime(self, provider_id):
        encoded = quote(provider_id, safe='')
        response = self._read(f'/me/messages/{encoded}/$value', expect_bytes=True, headers=IMMUTABLE_ID_HEADERS)
        if getattr(response, 'status_code', None) == 404:
            raise MessageNotFound(provider_id)
        if not isinstance(response, (bytes, bytearray)):
            raise InvalidResponse('message MIME response is not bytes')
        return bytes(response)

    def move_message_to_deleted_items(self, provider_id):
        if not self.can_cleanup:
            raise PermissionError('cleanup capability has not been enabled with Mail.ReadWrite')
        encoded = quote(provider_id, safe='')
        response = self.client.request(
            'POST', f'/me/messages/{encoded}/move', json={'destinationId': 'deleteditems'}, headers=IMMUTABLE_ID_HEADERS
        )
        if getattr(response, 'status_code', None) == 404:
            raise MessageNotFound(provider_id)
        if not isinstance(response, dict) or not response.get('id'):
            raise InvalidResponse('Graph move response did not contain the moved message id')
        return response['id']

    def get_capabilities(self):
        return {'read': True, 'cleanup': self.can_cleanup}

    def get_account_metadata(self):
        return dict(self.account_metadata)

    @staticmethod
    def _to_message(raw, fallback_folder=''):
        if not isinstance(raw, dict) or not raw.get('id'):
            raise InvalidResponse('Graph message lacks id')
        sender = ''
        try:
            sender = raw.get('from', {}).get('emailAddress', {}).get('address') or ''
        except AttributeError:
            sender = ''
        recipients = []
        for entry in raw.get('toRecipients') or []:
            try:
                address = entry.get('emailAddress', {}).get('address')
            except AttributeError:
                address = None
            if address:
                recipients.append(address)
        return ProviderMessage(
            MessageRef(
                provider_id=raw['id'],
                folder_id=raw.get('parentFolderId') or fallback_folder,
                internet_message_id=raw.get('internetMessageId'),
            ),
            subject=raw.get('subject') or '',
            sender=sender,
            recipients=recipients,
            received_ts=raw.get('receivedDateTime') or '',
            sent_ts=raw.get('sentDateTime') or '',
            # Graph message v1.0 has no selectable size property. MIME byte length is
            # verified after download; discovery metadata therefore leaves this unset.
            size_hint=None,
        )
