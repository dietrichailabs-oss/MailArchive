import pytest

from mailarchive.microsoft.mailbox_provider.provider import MESSAGE_SELECT, MicrosoftGraphMailboxProvider
from mailarchive.providers.contracts import NetworkUnavailable, ProviderUnavailable, RateLimited


class StubClient:
    def __init__(self):
        self.calls = []
    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path.startswith('/me/mailFolders?'):
            return {'value': [{'id': 'inbox', 'displayName': 'Inbox', 'childFolderCount': 0, 'totalItemCount': 2}]}
        if '/messages?' in path:
            if len([c for c in self.calls if '/messages?' in c[1]]) == 1:
                return {
                    'value': [{'id': 'm1', 'internetMessageId': '<1@x>', 'subject': 'one', 'from': {'emailAddress': {'address': 'a@x'}}, 'toRecipients': [], 'receivedDateTime': '2026-01-01T00:00:00Z', 'parentFolderId': 'inbox'}],
                    '@odata.nextLink': 'https://graph.microsoft.com/v1.0/next-page-token'
                }
            return {'value': [{'id': 'm2', 'internetMessageId': '<2@x>', 'subject': 'two', 'from': {'emailAddress': {'address': 'b@x'}}, 'toRecipients': [], 'receivedDateTime': '2026-01-02T00:00:00Z', 'parentFolderId': 'inbox'}]}
        if path == 'https://graph.microsoft.com/v1.0/next-page-token':
            return {'value': [{'id': 'm2', 'internetMessageId': '<2@x>', 'subject': 'two', 'from': {'emailAddress': {'address': 'b@x'}}, 'toRecipients': [], 'receivedDateTime': '2026-01-02T00:00:00Z', 'parentFolderId': 'inbox'}]}
        if path.endswith('/$value'):
            return b'From: a@x\r\n\r\nbody'
        if path.endswith('/move'):
            return {'id': 'm1-new'}
        if path.startswith('/me/messages/'):
            return {'id': 'm1', 'internetMessageId': '<1@x>', 'parentFolderId': 'inbox', 'toRecipients': []}
        raise AssertionError(path)


def test_provider_follows_nextlink_verbatim_and_filters_dates():
    client = StubClient()
    provider = MicrosoftGraphMailboxProvider(client)
    messages = list(provider.discover_messages(['inbox'], '2026-01-01', '2026-01-02'))
    assert [m.ref.provider_id for m in messages] == ['m1', 'm2']
    assert all(m.size_hint is None for m in messages)
    assert any(call[1] == 'https://graph.microsoft.com/v1.0/next-page-token' for call in client.calls)
    first = next(call[1] for call in client.calls if '/messages?' in call[1])
    assert 'receivedDateTime' in first and '%20' in first
    assert '$select=' in first
    assert 'size' not in MESSAGE_SELECT.split(',')
    assert ',size' not in first and 'size,' not in first
    message_calls = [call for call in client.calls if '/messages?' in call[1] or 'next-page-token' in call[1]]
    assert message_calls and all(call[2]['headers']['Prefer'] == 'IdType=\"ImmutableId\"' for call in message_calls)


def test_metadata_query_also_omits_unsupported_graph_size_field():
    client = StubClient()
    provider = MicrosoftGraphMailboxProvider(client)
    message = provider.get_message_metadata('m1')
    assert message.size_hint is None
    metadata_call = next(call for call in client.calls if call[1].startswith('/me/messages/'))
    assert '$select=' in metadata_call[1]
    assert ',size' not in metadata_call[1] and 'size,' not in metadata_call[1]


def test_provider_lists_folders_and_moves_only_with_cleanup_capability():
    client = StubClient()
    provider = MicrosoftGraphMailboxProvider(client, can_cleanup=True)
    assert provider.list_folders()[0]['name'] == 'Inbox'
    assert provider.move_message_to_deleted_items('m1') == 'm1-new'
    move = next(call for call in client.calls if call[1].endswith('/move'))
    assert move[2]['json'] == {'destinationId': 'deleteditems'}
    assert move[2]['headers']['Prefer'] == 'IdType=\"ImmutableId\"'


def test_collection_throttle_retries_same_page_without_losing_nextlink():
    class ThrottledClient:
        def __init__(self):
            self.calls = []
            self.throttled = False
        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            if '/messages?' in path:
                if not self.throttled:
                    self.throttled = True
                    raise RateLimited(0)
                return {
                    'value': [{'id': 'm1', 'internetMessageId': '<1@x>', 'subject': 'one', 'from': {'emailAddress': {'address': 'a@x'}}, 'toRecipients': [], 'receivedDateTime': '2026-01-01T00:00:00Z', 'parentFolderId': 'inbox'}],
                    '@odata.nextLink': 'https://graph.microsoft.com/v1.0/next-page-token',
                }
            if path == 'https://graph.microsoft.com/v1.0/next-page-token':
                return {'value': [{'id': 'm2', 'internetMessageId': '<2@x>', 'subject': 'two', 'from': {'emailAddress': {'address': 'b@x'}}, 'toRecipients': [], 'receivedDateTime': '2026-01-02T00:00:00Z', 'parentFolderId': 'inbox'}]}
            raise AssertionError(path)

    client = ThrottledClient()
    provider = MicrosoftGraphMailboxProvider(client, sleep=lambda _: None)
    messages = list(provider.discover_messages(['inbox'], None, None))
    assert [m.ref.provider_id for m in messages] == ['m1', 'm2']
    first_page_calls = [call for call in client.calls if '/messages?' in call[1]]
    assert len(first_page_calls) == 2
    assert all(call[2]['headers']['Prefer'] == 'IdType=\"ImmutableId\"' for call in client.calls)


@pytest.mark.parametrize('failure_type', [NetworkUnavailable, ProviderUnavailable])
def test_transient_graph_read_failures_retry_with_bounded_backoff(failure_type):
    class FlakyReadClient:
        def __init__(self):
            self.calls = 0
        def request(self, method, path, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                raise failure_type('temporary Graph read failure')
            return {'value': [{'id': 'inbox', 'displayName': 'Inbox', 'childFolderCount': 0, 'totalItemCount': 0}]}

    sleeps = []
    client = FlakyReadClient()
    provider = MicrosoftGraphMailboxProvider(client, sleep=sleeps.append, max_read_retries=4)
    folders = provider.list_folders()
    assert folders[0]['name'] == 'Inbox'
    assert client.calls == 3
    assert sleeps == [1.0, 2.0]


def test_transient_graph_read_failure_stops_after_configured_retry_limit():
    class AlwaysFailingReadClient:
        def __init__(self):
            self.calls = 0
        def request(self, method, path, **kwargs):
            self.calls += 1
            raise NetworkUnavailable('connection dropped')

    sleeps = []
    client = AlwaysFailingReadClient()
    provider = MicrosoftGraphMailboxProvider(client, sleep=sleeps.append, max_read_retries=2)
    with pytest.raises(NetworkUnavailable):
        provider.list_folders()
    assert client.calls == 3  # initial request + 2 retries
    assert sleeps == [1.0, 2.0]


def test_cleanup_move_is_never_auto_retried_after_uncertain_transport_failure():
    class FailingMoveClient:
        def __init__(self):
            self.calls = []
        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            raise NetworkUnavailable('response lost after possible server-side move')

    client = FailingMoveClient()
    provider = MicrosoftGraphMailboxProvider(client, can_cleanup=True, sleep=lambda _: None, max_read_retries=4)
    with pytest.raises(NetworkUnavailable):
        provider.move_message_to_deleted_items('m1')
    assert len(client.calls) == 1
    assert client.calls[0][0] == 'POST'
