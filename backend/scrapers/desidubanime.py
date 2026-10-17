import base64
import binascii
import logging
import re
from typing import List, Optional
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from backend.scrapers.base import (
    BaseScraper, AnimeCard, Episode, StreamSource,
)
from backend.config import PROVIDERS
from backend.resolvers import resolve_embed
from backend.utils.m3u8 import extract_m3u8_urls, extract_mp4_urls, extract_embed_sources


logger = logging.getLogger("anikoko.scraper.desidubanime")


ALIASES = {
    "aot": "attack on titan",
    "jjk": "jujutsu kaisen",
    "mha": "my hero academia",
    "bnh": "my hero academia",
    "op": "one piece",
    "opm": "one punch man",
    "fmab": "fullmetal alchemist brotherhood",
    "fma": "fullmetal alchemist",
    "hxh": "hunter x hunter",
    "dn": "death note",
    "tpn": "the promised neverland",
    "spy": "spy x family",
    "sxf": "spy x family",
    "kny": "demon slayer",
    "ds": "demon slayer",
    "demon": "demon slayer",
    "slime": "tensei shitara slime datta ken",
    "tensura": "tensei shitara slime datta ken",
    "csm": "chainsaw man",
    "tr": "tokyo revengers",
    "jjba": "jojo",
    "jojo": "jojo",
    "naruto": "naruto",
    "onepunch": "one punch man",
    "onepiece": "one piece",
    "hunter": "hunter x hunter",
    "konosuba": "kono subarashii",
    "konosub": "kono subarashii",
    "titan": "attack on titan",
    "kaiju": "kaiju no. 8",
    "gundam": "mobile suit gundam",
    "gintama": "gintama",
    "bleach": "bleach",
}


def _b64_try_decode(s: str) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    pad = (-len(s)) % 4
    if pad:
        s = s + ("=" * pad)
    try:
        raw = base64.b64decode(s, validate=False)
        return raw.decode("utf-8", errors="strict")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


def decode_embed_id(value: str) -> Optional[dict]:
    """data-embed-id is b64(server_name):b64(embed_url)."""
    if not value or ":" not in value:
        return None
    name_b64, _, url_b64 = value.partition(":")
    name = _b64_try_decode(name_b64)
    url = _b64_try_decode(url_b64)
    if not url or not url.startswith(("http://", "https://")):
        return None
    return {"server": name or "server", "url": url}


REJECT_HOSTS = (
    "desidubanime.me",
    "wp-json",
    "wp-content",
    "wp-includes",
    "fonts.googleapis.com",
    "googletagmanager.com",
    "googlesitekit",
    "google-analytics",
    "gstatic",
)

_ASSET_EXT_RE = re.compile(
    r"\.(css|js|png|jpe?g|svg|woff2?|gif|webp|ico|ttf|map)(\?|$)",
    re.I,
)


def _is_noise(u: str) -> bool:
    if not u:
        return True
    lu = u.lower()
    if any(h in lu for h in REJECT_HOSTS):
        return True
    if _ASSET_EXT_RE.search(lu):
        return True
    if "/oembed" in lu or "/embed?url=" in lu:
        return True
    return False


class DesiDubAnimeScraper(BaseScraper):
    slug = "desidubanime"
    base = PROVIDERS[slug]["base"]
    REST = f"{PROVIDERS[slug]['base']}/wp-json/wp/v2"

    # URL classification — provider-specific. Base uses these via classmethods.
    SERIES_URL_RE = re.compile(r"desidubanime\.me/anime/[^/?#]+/?$", re.I)
    EPISODE_URL_RES = [
        re.compile(r"desidubanime\.me/watch/[^/?#]+-episode-\d+/", re.I),
        re.compile(r"desidubanime\.me/watch/[^/?#]+-ep-?\d+/", re.I),
        re.compile(r"desidubanime\.me/watch/[^/?#]+/", re.I),
    ]

    # `?search_columns=` is valid WP core but this theme's REST endpoint
    # returns 400. Skip tier 2 entirely — falls straight to fuzzy.
    SUPPORTS_SEARCH_COLUMNS = False

    EPISODE_HREF_RE = re.compile(r"desidubanime\.me/watch/[^/?#]+", re.I)
    NUM_RE_EPISODE = re.compile(r"(?:episode|ep)[-_]?(\d+)", re.I)
    NUM_RE_SXE = re.compile(r"(\d+)x(\d+)")
    NUM_RE_TAIL = re.compile(r"(\d+)(?!.*\d)")

    def _extract_num(self, s: str) -> Optional[int]:
        m = self.NUM_RE_EPISODE.search(s)
        if m:
            return int(m.group(1))
        m = self.NUM_RE_SXE.search(s)
        if m:
            return int(m.group(2))
        tail = s.split("?")[0].split("#")[0].rstrip("/").split("/")[-1]
        m = self.NUM_RE_TAIL.search(tail)
        return int(m.group(1)) if m else None

    # -------- WP REST helpers --------

    async def _wp_search_anime(self, query: str, per_page: int = 24) -> List[dict]:
        url = (
            f"{self.REST}/anime?search={quote_plus(query)}"
            f"&per_page={per_page}&_embed=wp:featuredmedia"
        )
        try:
            data = await self.fetch_json(url)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.debug("wp search (%r) failed: %s", query, e)
            return []

    async def _wp_search_anime_columns(self, query: str, per_page: int = 24) -> List[dict]:
        url = (
            f"{self.REST}/anime?search={quote_plus(query)}"
            f"&search_columns=post_title,post_name,post_excerpt"
            f"&per_page={per_page}&_embed=wp:featuredmedia"
        )
        try:
            data = await self.fetch_json(url)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.debug("wp search_columns (%r) failed: %s", query, e)
            return []

    async def _wp_latest_anime(self, page: int = 1, per_page: int = 24) -> List[dict]:
        url = (
            f"{self.REST}/anime?per_page={per_page}&page={page}"
            f"&_embed=wp:featuredmedia"
        )
        try:
            data = await self.fetch_json(url)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.debug("wp latest (page %d) failed: %s", page, e)
            return []

    async def _wp_anime_by_slug(self, slug: str) -> Optional[dict]:
        url = f"{self.REST}/anime?slug={quote_plus(slug)}&_embed=wp:featuredmedia"
        try:
            data = await self.fetch_json(url)
            return data[0] if isinstance(data, list) and data else None
        except Exception as e:
            logger.debug("wp slug (%r) failed: %s", slug, e)
            return None

    @staticmethod
    def _poster_from_wp(post: dict) -> Optional[str]:
        try:
            media = post["_embedded"]["wp:featuredmedia"][0]
            return (
                media.get("source_url")
                or media.get("media_details", {})
                .get("sizes", {})
                .get("full", {})
                .get("source_url")
            )
        except Exception:
            return None

    def _card_from_wp(self, post: dict) -> Optional[AnimeCard]:
        title = (post.get("title") or {}).get("rendered") or ""
        title = BeautifulSoup(title, "lxml").get_text(strip=True)
        link = post.get("link") or ""
        if not title or not link:
            return None
        return AnimeCard(
            title=title,
            url=link,
            poster=self._poster_from_wp(post),
            provider=self.slug,
        )

    def _card_from_html(self, art) -> Optional[AnimeCard]:
        a = art if art.name == "a" and art.get("href") else art.find("a", href=True)
        if not a:
            return None
        href = a["href"].strip()
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = urljoin(self.base, href)
        if not self.looks_like_series_url(href):
            return None

        title = ""
        for sel in (
            ".font-bold.text-text", "h2", "h3",
            "[class*='line-clamp']", "img[alt]",
        ):
            el = art.select_one(sel)
            if el:
                title = (
                    el.get("alt", "").strip()
                    if el.name == "img"
                    else el.get_text(" ", strip=True)
                )
                if title:
                    break
        if not title:
            title = a.get("title", "").strip()
        if not title:
            return None

        img = art.find("img")
        poster = None
        if img:
            poster = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("src")
            )
            if poster:
                poster = urljoin(self.base, poster)

        return AnimeCard(title=title, url=href, poster=poster, provider=self.slug)

    async def _fetch_html_with_retry(self, url: str, tries: int = 3) -> Optional[str]:
        import asyncio as _aio
        for i in range(tries):
            try:
                return await self.fetch(url, referer=self.base)
            except Exception as e:
                if i == tries - 1:
                    logger.warning("fetch failed after %d tries (%s): %s", tries, url, e)
                await _aio.sleep(0.8 * (i + 1))
        return None

    def _episodes_from_html_text(self, html: str) -> List[Episode]:
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")
        episodes: List[Episode] = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href in seen:
                continue
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = urljoin(self.base, href)
            if not href.startswith("http"):
                continue
            if not self.EPISODE_HREF_RE.search(href):
                continue
            if re.search(r"/watch/[^/?#]+-anime/?$", href, re.I):
                continue
            num = self._extract_num(href)
            label = f"Episode {num}" if num is not None else (
                a.get_text(" ", strip=True) or "Episode"
            )
            episodes.append(Episode(title=label, url=href, number=num))
            seen.add(href)

        for m in re.finditer(
            r'https?://[^"\'\s<>]*desidubanime\.me/watch/[^"\'\s<>]+', html
        ):
            href = m.group(0)
            if href in seen:
                continue
            num = self._extract_num(href)
            label = f"Episode {num}" if num is not None else "Episode"
            episodes.append(Episode(title=label, url=href, number=num))
            seen.add(href)

        episodes.sort(key=lambda e: (e.number is None, e.number or 0))
        return episodes

    # -------- public API --------

    async def search(self, query: str) -> List[AnimeCard]:
        raw_q = (query or "").strip()
        if not raw_q:
            return []

        ql = raw_q.lower().strip()
        expanded_q = ALIASES.get(ql, raw_q)
        expanded_ql = expanded_q.lower()

        queries_to_try: List[str] = []
        seen_q: set = set()

        def _push(q: str):
            q = (q or "").strip()
            if q and q not in seen_q:
                seen_q.add(q)
                queries_to_try.append(q)

        _push(expanded_q)
        _push(raw_q)
        tokens: List[str] = []
        for src in (expanded_ql, ql):
            for t in re.split(r"\W+", src):
                if len(t) >= 3 and t not in tokens:
                    tokens.append(t)
        tokens.sort(key=len, reverse=True)
        for t in tokens:
            _push(t)

        filter_tokens = [t for t in re.split(r"\W+", expanded_ql) if len(t) >= 3]

        def _passes_filter(c: AnimeCard) -> bool:
            if not filter_tokens:
                return True
            hay = (c.title + " " + c.url).lower()
            return any(tok in hay for tok in filter_tokens)

        # Tier 1: WP search across query variants
        accumulated: List[AnimeCard] = []
        acc_seen: set = set()

        for try_q in queries_to_try:
            posts = await self._wp_search_anime(try_q)
            for p in posts:
                c = self._card_from_wp(p)
                if c and _passes_filter(c) and c.url not in acc_seen:
                    acc_seen.add(c.url)
                    accumulated.append(c)
            if len(accumulated) >= 24:
                break

        # Tier 2: search_columns — only where the provider supports it.
        if not accumulated and self.SUPPORTS_SEARCH_COLUMNS:
            for try_q in queries_to_try:
                posts = await self._wp_search_anime_columns(try_q)
                for p in posts:
                    c = self._card_from_wp(p)
                    if c and _passes_filter(c) and c.url not in acc_seen:
                        acc_seen.add(c.url)
                        accumulated.append(c)
                if len(accumulated) >= 24:
                    break

        if accumulated:
            return accumulated[:24]

        # Tier 3: fuzzy over latest 300
        try:
            candidates: List[AnimeCard] = []
            for page in (1, 2, 3):
                page_posts = await self._wp_latest_anime(page=page, per_page=100)
                if not page_posts:
                    break
                for p in page_posts:
                    c = self._card_from_wp(p)
                    if c:
                        candidates.append(c)
                if len(page_posts) < 100:
                    break

            tokens_set: set = set()
            for src in (expanded_ql, ql):
                for t in re.split(r"\W+", src):
                    if len(t) >= 3:
                        tokens_set.add(t)

            if tokens_set:
                out: List[AnimeCard] = []
                seen = set()
                for c in candidates:
                    hay = (c.title + " " + c.url).lower()
                    if any(tok in hay for tok in tokens_set):
                        if c.url not in seen:
                            seen.add(c.url)
                            out.append(c)
                if out:
                    return out[:24]
        except Exception as e:
            logger.warning("fuzzy search tier failed: %s", e, exc_info=True)

        # Tier 4: HTML search fallback
        for try_q in (expanded_q, raw_q):
            try:
                soup = await self.soup(f"{self.base}/?s={quote_plus(try_q)}")
                seen, out = set(), []
                for art in soup.select(".anime-card, article.anime-card, article, .post"):
                    card = self._card_from_html(art)
                    if card and card.url not in seen:
                        seen.add(card.url)
                        out.append(card)
                if out:
                    return out
            except Exception as e:
                logger.debug("html search (%r) failed: %s", try_q, e)
                continue

        return []

    async def latest(self, page: int = 1) -> List[AnimeCard]:
        posts = await self._wp_latest_anime(page=page)
        cards = [c for c in (self._card_from_wp(p) for p in posts) if c]
        if cards:
            return cards

        url = self.base if page <= 1 else f"{self.base}/page/{page}/"
        soup = await self.soup(url)
        seen, out = set(), []
        for art in soup.select(".anime-card, article.anime-card, article, .post"):
            card = self._card_from_html(art)
            if card and card.url not in seen:
                seen.add(card.url)
                out.append(card)
        return out

    async def anime_detail(self, url: str) -> dict:
        html = await self._fetch_html_with_retry(url)
        episodes = self._episodes_from_html_text(html or "")

        title = "Unknown"
        poster = None
        synopsis = ""

        if html:
            soup = BeautifulSoup(html, "lxml")
            h1 = soup.find("h1")
            if h1:
                t = h1.get_text(" ", strip=True)
                if t:
                    title = t
            og = soup.find("meta", attrs={"property": "og:image"})
            if og and og.get("content"):
                poster = urljoin(self.base, og["content"])
            syn = (
                soup.select_one(".entry-content")
                or soup.select_one(".description")
                or soup.select_one(".summary__content")
                or soup.select_one(".anime-synopsis")
            )
            if syn:
                synopsis = syn.get_text(" ", strip=True)[:1500]

        need_rest = (title == "Unknown") or (not poster) or (not synopsis)
        if need_rest:
            slug_match = re.search(r"/anime/([^/?#]+)/?", url)
            if slug_match:
                anime = await self._wp_anime_by_slug(slug_match.group(1))
                if anime:
                    raw_title = (anime.get("title") or {}).get("rendered") or ""
                    rt = BeautifulSoup(raw_title, "lxml").get_text(strip=True)
                    if rt and title == "Unknown":
                        title = rt
                    if not poster:
                        poster = self._poster_from_wp(anime)
                    if not synopsis:
                        raw_excerpt = (anime.get("excerpt") or {}).get("rendered") or ""
                        raw_content = (anime.get("content") or {}).get("rendered") or ""
                        synopsis = BeautifulSoup(
                            raw_excerpt or raw_content, "lxml"
                        ).get_text(" ", strip=True)[:1500]

        return {
            "title": title,
            "poster": poster,
            "synopsis": synopsis,
            "episodes": episodes,
        }

    async def episode_sources(self, url: str) -> List[StreamSource]:
        html = await self.fetch(url, referer=self.base)
        soup = BeautifulSoup(html, "lxml")
        raw: List[StreamSource] = []

        # 1. data-embed-id — b64-prefixed server + embed URL
        for el in soup.select("[data-embed-id]"):
            decoded = decode_embed_id(el.get("data-embed-id") or "")
            if not decoded:
                continue
            raw.append(StreamSource(
                url=decoded["url"],
                kind="embed",
                quality=decoded["server"],
                referer=url,
            ))

        # 2. direct m3u8 / mp4 in page HTML
        for u in extract_m3u8_urls(html):
            if not _is_noise(u):
                raw.append(StreamSource(url=u, kind="hls", referer=url))
        for u in extract_mp4_urls(html):
            if not _is_noise(u):
                raw.append(StreamSource(url=u, kind="mp4", referer=url))

        # 3. iframes
        for ifr in soup.find_all("iframe", src=True):
            src = ifr["src"].strip()
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = urljoin(self.base, src)
            if src.startswith("http") and not _is_noise(src):
                raw.append(StreamSource(url=src, kind="embed", referer=url))

        # 4. known embed hosts in raw HTML
        for u in extract_embed_sources(html):
            if not _is_noise(u):
                raw.append(StreamSource(url=u, kind="embed", referer=url))

        # 5. run the resolver chain on embeds; Vidmoly is intentionally
        #    dropped before that — the CDN is rate-limited and stalls
        #    playback often enough that a working iframe is better than
        #    a flaky direct stream.
        resolved: List[StreamSource] = []
        for s in raw:
            lu = s.url.lower()
            if "vidmoly" in lu:
                continue
            if s.kind == "embed":
                if "filesforever" in lu:
                    resolved.append(s)
                    continue
                try:
                    m3u8 = await resolve_embed(s.url)
                except Exception as e:
                    logger.debug("resolve failed (%s): %s", s.url, e)
                    m3u8 = None
                if m3u8 and m3u8 != s.url:
                    resolved.append(StreamSource(
                        url=m3u8,
                        kind="hls",
                        quality=s.quality,
                        referer=s.url,
                    ))
                    continue
            resolved.append(s)

        seen, out = set(), []
        for s in resolved:
            if s.url in seen:
                continue
            seen.add(s.url)
            out.append(s)
        return out