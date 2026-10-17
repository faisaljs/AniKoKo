import json
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from backend.resolvers.base import BaseResolver


logger = logging.getLogger("anikoko.resolver.p2pplay")


M3U8_RE = re.compile(r"""['"]?(https?://[^'"\s]+\.m3u8[^'"\s]*)['"]?""")

URL_KEYS = ("url", "file", "hls", "source", "stream", "link", "video", "src")


class P2PPlayResolver(BaseResolver):
    name = "p2pplay"
    hosts = ("p2pplay.pro",)

    # The SPA encrypts /api/v1/info, and /api/v1/player?t=<token> needs a
    # token derived from that encrypted blob *in-browser*. Without executing
    # their JS we can't mint a valid token, so we only probe the plaintext
    # endpoints here. If a source ever opens up, drop the pattern in candidates.
    #
    # To escalate: add a Playwright resolver in a separate module, opt-in via
    # env flag, that loads the embed page and scrapes the final .m3u8 out of
    # the video element. That's a real project, not a weekend patch.

    async def _probe_path(self, origin: str, path: str, embed_url: str) -> Optional[str]:
        u = urljoin(origin + "/", path.lstrip("/"))
        try:
            body = await self.fetch(u, referer=embed_url)
        except Exception as e:
            logger.debug("p2pplay: probe %s failed: %s", path, e)
            return None

        # direct m3u8 in the response body?
        m = M3U8_RE.search(body)
        if m:
            return m.group(1)

        # JSON with a known URL key?
        try:
            data = json.loads(body)
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        for k in URL_KEYS:
            v = data.get(k)
            if not isinstance(v, str) or not v.startswith("http"):
                continue
            if ".m3u8" in v:
                return v
            # Recurse one level — many endpoints return a sub-embed URL
            try:
                sub = await self.fetch(v, referer=embed_url)
                m2 = M3U8_RE.search(sub)
                if m2:
                    return m2.group(1)
            except Exception as e:
                logger.debug("p2pplay: follow %s failed: %s", v, e)

        return None

    async def resolve(self, embed_url: str) -> Optional[str]:
        parsed = urlparse(embed_url)
        frag = (parsed.fragment or "").strip()
        origin = f"{parsed.scheme}://{parsed.netloc}"

        if not frag:
            logger.debug("p2pplay: no fragment token in %s", embed_url)
            return None

        # Prime the origin so any required cookies are set
        try:
            await self.fetch(origin + "/", referer=embed_url)
        except Exception as e:
            logger.debug("p2pplay: prime failed: %s", e)

        candidates = [
            f"/api/v1/player?t={frag}",
            f"/api/v1/video?id={frag}",
            f"/api/v1/download?id={frag}",
        ]

        for path in candidates:
            out = await self._probe_path(origin, path, embed_url)
            if out:
                return out

        logger.debug(
            "p2pplay: no plaintext m3u8 in %s — SPA requires JS token minting",
            embed_url,
        )
        return None