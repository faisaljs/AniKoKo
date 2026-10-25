import logging
from typing import Optional

from urllib.parse import urlsplit

import httpx

from backend.config import USER_AGENT, REQUEST_TIMEOUT, SCRAPE_PROXY
from backend.utils.url import safe_request


logger = logging.getLogger("anikoko.resolver")


class BaseResolver:
    name: str = ""
    hosts: tuple = ()

    @classmethod
    def matches(cls, url: str) -> bool:
        if not url:
            return False
        try:
            host = urlsplit(url).hostname
        except ValueError:
            return False
        if not host:
            return False
        host = host.lower().rstrip(".")
        return any(host == h or host.endswith("." + h) for h in cls.hosts)

    async def fetch(self, url: str, referer: Optional[str] = None) -> str:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            headers["Referer"] = referer
        kwargs = dict(headers=headers, timeout=REQUEST_TIMEOUT, follow_redirects=False)
        if SCRAPE_PROXY:
            kwargs["proxy"] = SCRAPE_PROXY
        async with httpx.AsyncClient(**kwargs) as client:
            r = await safe_request(client, "GET", url)
            r.raise_for_status()
            return r.text

    async def post_form(
        self,
        url: str,
        body: str,
        referer: Optional[str] = None,
        extra_headers: Optional[dict] = None,
    ) -> str:
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
        }
        if referer:
            headers["Referer"] = referer
        if extra_headers:
            headers.update(extra_headers)
        kwargs = dict(headers=headers, timeout=REQUEST_TIMEOUT, follow_redirects=False)
        if SCRAPE_PROXY:
            kwargs["proxy"] = SCRAPE_PROXY
        async with httpx.AsyncClient(**kwargs) as client:
            r = await safe_request(client, "POST", url, content=body)
            r.raise_for_status()
            return r.text

    async def resolve(self, embed_url: str) -> Optional[str]:
        raise NotImplementedError
