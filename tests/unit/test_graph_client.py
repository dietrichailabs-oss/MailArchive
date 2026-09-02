import pytest

from mailarchive.microsoft.graph_client.client import GraphClient
from mailarchive.providers.contracts import AuthenticationRequired, PermissionDenied, RateLimited, ProviderUnavailable


class Response:
    def __init__(self, status=200, data=None, content=b'', headers=None):
        self.status_code = status
        self._data = data
        self.content = content
        self.headers = headers or {}
    def json(self):
        return self._data


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


@pytest.mark.parametrize('status,exc', [(401, AuthenticationRequired), (403, PermissionDenied), (500, ProviderUnavailable)])
def test_graph_status_translation(status, exc):
    client = GraphClient(lambda: 'secret-token', Transport(Response(status=status)))
    with pytest.raises(exc):
        client.request('GET', '/me/messages')


def test_graph_429_retry_after_translation():
    client = GraphClient(lambda: 'secret-token', Transport(Response(status=429, headers={'Retry-After': '7'})))
    with pytest.raises(RateLimited) as caught:
        client.request('GET', '/me/messages')
    assert caught.value.retry_after == 7


def test_authorization_header_is_internal_and_bytes_supported():
    transport = Transport(Response(content=b'MIME'))
    client = GraphClient(lambda: 'secret-token', transport)
    assert client.request('GET', '/me/messages/x/$value', expect_bytes=True) == b'MIME'
    method, url, kwargs = transport.calls[0]
    assert kwargs['headers']['Authorization'] == 'Bearer secret-token'
    assert url.startswith('https://graph.microsoft.com/v1.0/')


def test_mime_content_length_mismatch_is_rejected():
    from mailarchive.providers.contracts import InvalidResponse
    transport = Transport(Response(content=b'partial', headers={'Content-Length': '999'}))
    client = GraphClient(lambda: 'secret-token', transport)
    with pytest.raises(InvalidResponse):
        client.request('GET', '/me/messages/x/$value', expect_bytes=True)
