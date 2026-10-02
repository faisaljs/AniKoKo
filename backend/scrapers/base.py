from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from backend.config import USER_AGENT, REQUEST_TIMEOUT, SCRAPE_PROXY


# ---------------- URL classification helpers ----------------

SERIES_REJECT = re.compile(r"/(watch|episode|download|ep|watch-online)/", re.I)
EPISODE_HINT = re.compile(r"(episode|ep[-_]?\d+|\d+x\d+)", re.I)

SERIES_URL_RE = re.compile(r"desidubanime\.me/anime/[^/?#]+/?$", re.I)

EPISODE_URL_PATTERNS = [
    re.compile(r"desidubanime\.me/watch/[^/?#]+-episode-\d+/", re.I),
    re.compile(r"desidubanime\.me/watch/[^/?#]+/", re.I),
    re.compile(r"/watch/[^/?#]+-episode-\d+", re.I),
]


def looks_like_series_url(url: str) -> bool:
    """A series URL is /anime/<slug>/ with no episode marker."""
    if not url or url.startswith("#") or url.startswith("javascript:"):
        return False
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("//")):
        return False
    if EPISODE_HINT.search(url):
        return False
    if SERIES_REJECT.search(url):
        return False
    # Only accept /anime/<slug>/ URLs from the provider
    if "desidubanime.me" in url and not SERIES_URL_RE.search(url):
        return False
    return True


def is_episode_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    for pat in EPISODE_URL_PATTERNS:
        if pat.search(url):
            return True
    return False


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
    slug: str = ""
    base: str = ""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def client(self) -> httpx.AsyncClient:
        if self._client is None:
            kwargs = dict(
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
                },
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
            )
            if SCRAPE_PROXY:
                kwargs["proxy"] = SCRAPE_PROXY
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self, url: str, referer: Optional[str] = None) -> str:
        c = await self.client()
        headers = {"Referer": referer} if referer else {}
        r = await c.get(url, headers=headers)
        r.raise_for_status()
        return r.text

    async def fetch_json(self, url: str, referer: Optional[str] = None) -> dict:
        c = await self.client()
        headers = {"Referer": referer} if referer else {}
        r = await c.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

    async def soup(self, url: str, referer: Optional[str] = None) -> BeautifulSoup:
        html = await self.fetch(url, referer=referer)
        return BeautifulSoup(html, "lxml")

    # --- to be implemented by subclasses ---
    async def search(self, query: str) -> List[AnimeCard]:
        raise NotImplementedError

    async def latest(self, page: int = 1) -> List[AnimeCard]:
        raise NotImplementedError

    async def anime_detail(self, url: str) -> dict:
        raise NotImplementedError

    async def episode_sources(self, url: str) -> List[StreamSource]:
        raise NotImplementedError