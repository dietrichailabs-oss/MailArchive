from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Callable
import time

from mailarchive.providers.contracts import (
    AuthenticationRequired,
    InvalidResponse,
    NetworkUnavailable,
    PermissionDenied,
    ProviderUnavailable,
    RateLimited,
)


GRAPH_ROOT = 'https://graph.microsoft.com/v1.0'


@dataclass(frozen=True)
class GraphResponse:
    status_code: int
    headers: dict[str, str]
    json_data: Any = None
    content: bytes = b''

    def json(self):
        return self.json_data


class GraphClient:
    """Small Graph v1.0 transport with stable internal errors and no token logging."""

    def __init__(
        self,
        token_provider: Callable[[], str],
        transport=None,
        *,
        timeout: tuple[float, float] = (10.0, 60.0),
        sleep=time.sleep,
    ):
        self.token_provider = token_provider
        self.timeout = timeout
        self.sleep = sleep
        if transport is None:
            import requests
            transport = requests.Session()
        self.transport = transport

    def request(self, method: str, path_or_url: str, *, expect_bytes=False, **kwargs):
        token = self.token_provider()
        if not token:
            raise AuthenticationRequired('no access token available')
        url = path_or_url if path_or_url.startswith('https://') else GRAPH_ROOT + path_or_url
        headers = dict(kwargs.pop('headers', {}) or {})
        headers['Authorization'] = f'Bearer {token}'
        headers.setdefault('Accept', 'application/octet-stream' if expect_bytes else 'application/json')
        try:
            response = self.transport.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        except Exception as exc:
            # Keep implementation independent of requests exception classes for injected transports.
            raise NetworkUnavailable(str(exc)) from exc
        status = int(response.status_code)
        if status == 401:
            raise AuthenticationRequired('Microsoft sign-in is required again')
        if status == 403:
            raise PermissionDenied('Microsoft Graph permission denied')
        if status == 429:
            raise RateLimited(self._retry_after_seconds(response.headers.get('Retry-After')))
        if status >= 500:
            raise ProviderUnavailable(f'Microsoft Graph service error HTTP {status}')
        if status >= 400:
            # Callers translate resource-specific 404s where useful.
            if status == 404:
                return response
            raise InvalidResponse(f'Microsoft Graph returned HTTP {status}')
        if expect_bytes:
            content = bytes(response.content)
            declared = response.headers.get('Content-Length')
            encoding = response.headers.get('Content-Encoding')
            if declared and not encoding:
                try:
                    if int(declared) != len(content):
                        raise InvalidResponse('Microsoft Graph MIME response length did not match Content-Length')
                except ValueError as exc:
                    raise InvalidResponse('Microsoft Graph returned invalid Content-Length') from exc
            return content
        return self._json(response)

    @staticmethod
    def _json(response):
        try:
            return response.json()
        except Exception as exc:
            raise InvalidResponse('Microsoft Graph returned invalid JSON') from exc

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float:
        if not value:
            return 1.0
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                dt = parsedate_to_datetime(value)
                import datetime as _dt
                now = _dt.datetime.now(dt.tzinfo or _dt.timezone.utc)
                return max(0.0, (dt - now).total_seconds())
            except Exception:
                return 1.0
