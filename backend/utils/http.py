import httpx
from typing import Optional

from backend.config import USER_AGENT, REQUEST_TIMEOUT, SCRAPE_PROXY


def build_client(referer: Optional[str] = None) -> httpx.AsyncClient:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    kwargs = dict(headers=headers, timeout=REQUEST_TIMEOUT, follow_redirects=True)
    if SCRAPE_PROXY:
        kwargs["proxy"] = SCRAPE_PROXY
    return httpx.AsyncClient(**kwargs)


async def get_text(url: str, referer: Optional[str] = None) -> str:
    async with build_client(referer) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


async def get_json(url: str, referer: Optional[str] = None) -> dict:
    async with build_client(referer) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


async def get_bytes(url: str, referer: Optional[str] = None) -> bytes:
    async with build_client(referer) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content