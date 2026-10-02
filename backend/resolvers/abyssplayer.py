import base64
import binascii
import json
import re
from typing import Optional

from backend.resolvers.base import BaseResolver


M3U8_RE = re.compile(r"""['"](https?://[^'"]+\.m3u8[^'"]*)['"]""")
DATAS_B64_RE = re.compile(r"""const\s+datas\s*=\s*["']([A-Za-z0-9+/=]{40,})["']""")
ATOB_RE = re.compile(r"""atob\(\s*["']([A-Za-z0-9+/=]{20,})["']\s*\)""")
FILE_RE = re.compile(r"""["']file["']\s*:\s*["']([^"']+)["']""", re.I)
SOURCES_JSON_RE = re.compile(
    r"""["']sources["']\s*:\s*\[[^\]]*?["']file["']\s*:\s*["']([^"']+)["']""",
    re.I | re.S,
)


def _b64(s: str) -> Optional[str]:
    try:
        pad = (-len(s)) % 4
        if pad:
            s = s + ("=" * pad)
        return base64.b64decode(s).decode("utf-8", errors="ignore")
    except (binascii.Error, ValueError):
        return None


class AbyssPlayerResolver(BaseResolver):
    name = "abyssplayer"
    hosts = ("abyssplayer.com", "abyss.to")

    async def resolve(self, embed_url: str) -> Optional[str]:
        html = await self.fetch(embed_url, referer="https://www.desidubanime.me/")

        # 1. direct m3u8 in HTML
        m = M3U8_RE.search(html)
        if m:
            return m.group(1)

        # 2. crack the base64 `datas` blob without JS
        m = DATAS_B64_RE.search(html)
        if m:
            decoded = _b64(m.group(1))
            if decoded:
                try:
                    data = json.loads(decoded)
                    for v in data.values():
                        if isinstance(v, str) and ".m3u8" in v:
                            return v
                        if isinstance(v, str) and v.startswith("http"):
                            try:
                                sub = await self.fetch(v, referer=embed_url)
                                m2 = M3U8_RE.search(sub)
                                if m2:
                                    return m2.group(1)
                            except Exception:
                                pass
                except Exception:
                    pass
                m2 = M3U8_RE.search(decoded)
                if m2:
                    return m2.group(1)

        # 3. inline sources/file keys
        for pat in (SOURCES_JSON_RE, FILE_RE):
            m = pat.search(html)
            if m and ".m3u8" in m.group(1):
                return m.group(1)

        # 4. atob blobs
        for blob in ATOB_RE.findall(html):
            decoded = _b64(blob)
            if not decoded:
                continue
            m = M3U8_RE.search(decoded)
            if m:
                return m.group(1)

        return None