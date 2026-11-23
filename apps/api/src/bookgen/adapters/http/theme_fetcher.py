"""Bounded HTTP adapter: resolve every hop and connect only to a verified IP."""
from collections.abc import Callable
from dataclasses import dataclass
import http.client
import ipaddress
import socket
import ssl
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from bookgen.config.theme import ThemeConfig


@dataclass(frozen=True)
class FetchResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class HTTPTransport(Protocol):
    def __call__(self, url: str, address: str, limit: int, timeout: float) -> FetchResponse: ...


def resolve(host: str, port: int) -> list[str]:
    return list(dict.fromkeys(record[4][0] for record in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))


def request_pinned(url: str, address: str, limit: int, timeout: float) -> FetchResponse:
    """TLS verifies the original hostname while the socket uses the checked IP."""
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
    sock = socket.socket(socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect((address, port))
        if parsed.scheme == 'https':
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
        connection.sock = sock
        connection.request('GET', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''), headers={'Accept': 'text/html,image/*', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        if int(headers.get('content-length', '0')) > limit:
            raise ValueError('Website response exceeds the configured limit')
        return FetchResponse(response.status, headers, response.read(limit + 1))
    finally:
        connection.close()
        sock.close()


class ThemeFetcher:
    def __init__(self, settings: ThemeConfig, *, resolver: Callable = resolve, http: HTTPTransport = request_pinned):
        self.settings, self.resolver, self.http = settings.require_complete(), resolver, http

    def fetch(self, url: str) -> FetchResponse:
        for hop in range(self.settings.max_redirects + 1):
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Only public HTTP(S) websites are supported')
            addresses = self.resolver(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
            if not addresses or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast for address in addresses):
                raise ValueError('Website resolves to a blocked address')
            try:
                response = self.http(url, addresses[0], self.settings.max_response_bytes, self.settings.timeout_seconds)
            except http.client.HTTPException as exc:
                raise ValueError('Website could not be fetched') from exc
            if len(response.body) > self.settings.max_response_bytes:
                raise ValueError('Website response exceeds the configured limit')
            if response.status in (301, 302, 303, 307, 308):
                if hop == self.settings.max_redirects or not response.headers.get('location'):
                    raise ValueError('Website redirect limit exceeded')
                url = urljoin(url, response.headers['location'])
                continue
            if response.status != 200:
                raise ValueError('Website could not be fetched')
            return response
        raise ValueError('Website redirect limit exceeded')  # pragma: no cover
