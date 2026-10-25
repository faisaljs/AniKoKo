"""Validation helpers for URLs fetched on behalf of API clients."""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit


class UnsafeURL(ValueError):
    pass


def _check_public_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise UnsafeURL("invalid URL") from exc

    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise UnsafeURL("only absolute HTTP(S) URLs are allowed")
    if parsed.username or parsed.password:
        raise UnsafeURL("URL credentials are not allowed")
    if port is not None and port not in (80, 443):
        raise UnsafeURL("only ports 80 and 443 are allowed")

    host = parsed.hostname.rstrip(".").lower()
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            records = socket.getaddrinfo(
                host,
                port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except (OSError, UnicodeError) as exc:
            raise UnsafeURL("hostname could not be resolved") from exc
        addresses = [ipaddress.ip_address(record[4][0]) for record in records]

    if not addresses or any(not address.is_global for address in addresses):
        raise UnsafeURL("private or reserved network destinations are not allowed")
    return url


async def validate_public_url(url: str) -> str:
    """Accept public HTTP(S) URLs and reject local or non-public destinations."""
    return await asyncio.to_thread(_check_public_url, url)


async def safe_request(client, method: str, url: str, **kwargs):
    """Send a request while validating each redirect destination."""
    current_url = url
    current_method = method
    current_kwargs = kwargs
    for redirect_count in range(6):
        await validate_public_url(current_url)
        request = client.build_request(current_method, current_url, **current_kwargs)
        response = await client.send(request)
        location = response.headers.get("location")
        if response.status_code not in (301, 302, 303, 307, 308) or not location:
            return response
        if redirect_count == 5:
            await response.aclose()
            raise UnsafeURL("too many redirects")
        next_url = urljoin(str(response.url), location)
        await response.aclose()
        if response.status_code == 303 or (
            response.status_code in (301, 302)
            and current_method.upper() == "POST"
        ):
            current_method = "GET"
            current_kwargs = {k: v for k, v in kwargs.items() if k != "content"}
        current_url = next_url
    raise UnsafeURL("too many redirects")
