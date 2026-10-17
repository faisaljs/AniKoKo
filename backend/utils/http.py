import asyncio
import logging
from typing import Optional

import httpx

from backend.config import (
    USER_AGENT, REQUEST_TIMEOUT, SCRAPE_PROXY,
    PROXY_RETRIES, PROXY_RETRY_BACKOFF,
)


logger = logging.getLogger("anikoko.http")


DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/json,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Connection": "keep-alive",
}


def build_client(
    referer: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout: Optional[float] = None,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    if referer:
        merged["Referer"] = referer

    kwargs = dict(
        headers=merged,
        timeout=timeout if timeout is not None else REQUEST_TIMEOUT,
        follow_redirects=follow_redirects,
    )
    if SCRAPE_PROXY:
        kwargs["proxy"] = SCRAPE_PROXY
    return httpx.AsyncClient(**kwargs)


async def _retry(coro_factory, tries: int = None, label: str = "request"):
    """Run coro_factory() up to `tries` times with exponential backoff.
    Re-raises the final exception."""
    if tries is None:
        tries = PROXY_RETRIES + 1
    last_exc = None
    for i in range(tries):
        try:
            return await coro_factory()
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            if i == tries - 1:
                break
            delay = PROXY_RETRY_BACKOFF * (2 ** i)
            logger.debug("%s retry %d/%d in %.1fs: %s", label, i + 1, tries, delay, e)
            await asyncio.sleep(delay)
    if last_exc is not None:
        raise last_exc


async def get_text(
    url: str,
    referer: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout: Optional[float] = None,
    retries: Optional[int] = None,
) -> str:
    async def _do():
        async with build_client(referer, headers, timeout) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text
    return await _retry(_do, tries=(retries + 1) if retries is not None else None, label="get_text")


async def get_json(
    url: str,
    referer: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout: Optional[float] = None,
    retries: Optional[int] = None,
) -> dict:
    async def _do():
        async with build_client(referer, headers, timeout) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    return await _retry(_do, tries=(retries + 1) if retries is not None else None, label="get_json")


async def get_bytes(
    url: str,
    referer: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout: Optional[float] = None,
    retries: Optional[int] = None,
) -> bytes:
    async def _do():
        async with build_client(referer, headers, timeout) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.content
    return await _retry(_do, tries=(retries + 1) if retries is not None else None, label="get_bytes")


async def stream_upstream(
    url: str,
    referer: Optional[str] = None,
    extra_headers: Optional[dict] = None,
    method: str = "GET",
) -> tuple[httpx.AsyncClient, httpx.Response]:
    """Open a streaming upstream request. Caller is responsible for closing
    both the client and the response. Retries on transport errors only —
    HTTP errors (4xx/5xx) are returned to the caller as-is."""
    headers = {}
    if extra_headers:
        headers.update(extra_headers)
    if referer:
        headers["Referer"] = referer

    client = build_client(referer=referer, headers=headers, timeout=None)
    try:
        async def _do():
            return await client.send(
                client.build_request(method, url, headers=headers),
                stream=True,
            )
        upstream = await _retry(_do, label="stream_upstream")
        return client, upstream
    except Exception:
        await client.aclose()
        raise