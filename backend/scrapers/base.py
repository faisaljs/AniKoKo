from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from backend.config import USER_AGENT, REQUEST_TIMEOUT, SCRAPE_PROXY
from backend.utils.url import safe_request


logger = logging.getLogger("anikoko.scraper")


# ---------------- dataclasses ----------------

@dataclass
class AnimeCard:
    title: str
    url: str
    poster: Optional[str] = None
    provider: str = ""


@dataclass
class Episode:
    title: str
    url: str
    number: Optional[int] = None


@dataclass
class StreamSource:
    url: str
    quality: str = "auto"
    kind: str = "hls"  # hls | mp4 | embed
    referer: Optional[str] = None
    headers: dict = field(default_factory=dict)


# ---------------- base scraper ----------------

class BaseScraper:
    """Provider contract.

    Subclasses must set `slug`, `base`, and implement the four async methods.
    URL classification methods (`is_episode_url`, `looks_like_series_url`)
    have sensible defaults but should be overridden per provider — the
    defaults are the desidubanime shape and will silently misfire elsewhere.
    """

    slug: str = ""
    base: str = ""

    # Override in subclasses with provider-specific regexes.
    SERIES_URL_RE: Optional[re.Pattern] = None
    EPISODE_URL_RES: List[re.Pattern] = []

    # Set False on providers whose REST API rejects `?search_columns=`.
    SUPPORTS_SEARCH_COLUMNS: bool = True

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    # -------- url classification (override per provider) --------

    @classmethod
    def looks_like_series_url(cls, url: str) -> bool:
        if not url or url.startswith("#") or url.startswith("javascript:"):
            return False
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("//")):
            return False
        if cls.SERIES_URL_RE is None:
            return True
        return bool(cls.SERIES_URL_RE.search(url))

    @classmethod
    def is_episode_url(cls, url: str) -> bool:
        if not url or not url.startswith(("http://", "https://")):
            return False
        for pat in cls.EPISODE_URL_RES:
            if pat.search(url):
                return True
        return False

    # -------- http --------

    async def client(self) -> httpx.AsyncClient:
        if self._client is None:
            kwargs = dict(
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
                },
                timeout=REQUEST_TIMEOUT,
                follow_redirects=False,
            )
            if SCRAPE_PROXY:
                kwargs["proxy"] = SCRAPE_PROXY
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def close(self):
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def fetch(self, url: str, referer: Optional[str] = None) -> str:
        c = await self.client()
        headers = {"Referer": referer} if referer else {}
        r = await safe_request(c, "GET", url, headers=headers)
        r.raise_for_status()
        return r.text

    async def fetch_json(self, url: str, referer: Optional[str] = None) -> dict:
        c = await self.client()
        headers = {"Referer": referer} if referer else {}
        r = await safe_request(c, "GET", url, headers=headers)
        r.raise_for_status()
        return r.json()

    async def soup(self, url: str, referer: Optional[str] = None) -> BeautifulSoup:
        html = await self.fetch(url, referer=referer)
        return BeautifulSoup(html, "lxml")

    # -------- contract --------

    async def search(self, query: str) -> List[AnimeCard]:
        raise NotImplementedError

    async def latest(
        self,
        page: int = 1,
        genre: Optional[int] = None,
    ) -> List[AnimeCard]:
        raise NotImplementedError

    async def anime_detail(self, url: str) -> dict:
        raise NotImplementedError

    async def episode_sources(self, url: str) -> List[StreamSource]:
        raise NotImplementedError

    async def genres(self) -> List[dict]:
        """Return provider genre list as [{id, name, slug, count}, ...].

        Providers without a taxonomy can leave this as the default — returns [].
        Callers must tolerate an empty list.
        """
        return []
