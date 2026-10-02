import json
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from backend.resolvers.base import BaseResolver


M3U8_RE = re.compile(r"""['"]?(https?://[^'"\s]+\.m3u8[^'"\s]*)['"]?""")


class P2PPlayResolver(BaseResolver):
    name = "p2pplay"
    hosts = ("p2pplay.pro",)

    async def resolve(self, embed_url: str) -> Optional[str]:
        parsed = urlparse(embed_url)
        frag = (parsed.fragment or "").strip()
        origin = f"{parsed.scheme}://{parsed.netloc}"

        if not frag:
            return None

        # Prime the origin so any required cookies are set
        try:
            await self.fetch(origin + "/", referer=embed_url)
        except Exception:
            pass

        # The p2pplay SPA encrypts the response from /api/v1/info — the actual
        # playback URL comes from /api/v1/player?t=<token> where the token is
        # derived from the encrypted info blob in-browser. Without running their
        # JS we can't mint a valid token, so we just probe the plaintext cases.
        candidates = [
            f"/api/v1/player?t={frag}",
            f"/api/v1/video?id={frag}",
            f"/api/v1/download?id={frag}",
        ]

        for path in candidates:
            u = urljoin(origin + "/", path.lstrip("/"))
            try:
                body = await self.fetch(u, referer=embed_url)
            except Exception:
                continue

            m = M3U8_RE.search(body)
            if m:
                return m.group(1)

            try:
                data = json.loads(body)
            except Exception:
                data = None

            if isinstance(data, dict):
                for k in ("url", "file", "hls", "source", "stream", "link", "video", "src"):
                    v = data.get(k)
                    if isinstance(v, str) and v.startswith("http") and ".m3u8" in v:
                        return v
                    if isinstance(v, str) and v.startswith("http"):
                        try:
                            sub = await self.fetch(v, referer=embed_url)
                            m2 = M3U8_RE.search(sub)
                            if m2:
                                return m2.group(1)
                        except Exception:
                            pass

        return None