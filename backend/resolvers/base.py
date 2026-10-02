from typing import Optional

import httpx

from backend.config import USER_AGENT, REQUEST_TIMEOUT, SCRAPE_PROXY


class BaseResolver:
    name: str = ""
    hosts: tuple = ()

    @classmethod
    def matches(cls, url: str) -> bool:
        if not url:
            return False
        lu = url.lower()
        return any(h in lu for h in cls.hosts)

    async def fetch(self, url: str, referer: Optional[str] = None) -> str:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            headers["Referer"] = referer
        kwargs = dict(headers=headers, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        if SCRAPE_PROXY:
            kwargs["proxy"] = SCRAPE_PROXY
        async with httpx.AsyncClient(**kwargs) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text

    async def resolve(self, embed_url: str) -> Optional[str]:
        raise NotImplementedError