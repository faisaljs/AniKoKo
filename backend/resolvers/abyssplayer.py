import base64
import binascii
import json
import logging
import re
from typing import Optional

from backend.resolvers.base import BaseResolver


logger = logging.getLogger("anikoko.resolver.abyssplayer")


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
    """AbyssPlayer / abyss.to.

    The embed page serves a `const datas = "<b64>"` blob whose decoded JSON
    has a `media` field — that field is CIPHERTEXT, not a URL. It's decrypted
    at runtime by `window.SoTrym()` from `iamcdn.net/player-v2/lite.bundle.js`,
    then handed to jwplayer.

    Without executing their bundle, the only things we can crack are
    plaintext m3u8s that occasionally appear directly in the page HTML.
    The `datas` path always fails here — that's expected, not a bug.

    Verified 2026-10: decoded `datas` = `{"slug":"...","md5_id":N,
    "user_id":N,"media":"<ciphertext bytes>"}`.

    To escalate: Playwright resolver, separate module, env-flag opt-in,
    load the page, wait for jwplayer, scrape the m3u8. Real project.
    """
    name = "abyssplayer"
    hosts = ("abyssplayer.com", "abyss.to")

    REFERER = "https://www.desidubanime.me/"

    async def _try_datas_blob(self, blob: str, embed_url: str) -> Optional[str]:
        decoded = _b64(blob)
        if not decoded:
            return None

        # Try as JSON first
        try:
            data = json.loads(decoded)
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, str) and ".m3u8" in v:
                        return v
                    if isinstance(v, str) and v.startswith("http"):
                        try:
                            sub = await self.fetch(v, referer=embed_url)
                            m2 = M3U8_RE.search(sub)
                            if m2:
                                return m2.group(1)
                        except Exception as e:
                            logger.debug("abyssplayer: sub-page fetch failed (%s): %s", v, e)
        except Exception:
            pass

        # Not JSON — scan the raw decoded string
        m = M3U8_RE.search(decoded)
        if m:
            return m.group(1)

        return None

    async def resolve(self, embed_url: str) -> Optional[str]:
        html = await self.fetch(embed_url, referer=self.REFERER)

        # 1. direct m3u8 in page HTML
        m = M3U8_RE.search(html)
        if m:
            return m.group(1)

        # 2. `const datas = "<b64>"` blob — no JS execution needed
        m = DATAS_B64_RE.search(html)
        if m:
            out = await self._try_datas_blob(m.group(1), embed_url)
            if out:
                return out

        # 3. inline sources/file keys
        for pat in (SOURCES_JSON_RE, FILE_RE):
            m = pat.search(html)
            if m and ".m3u8" in m.group(1):
                return m.group(1)

        # 4. atob("...") blobs
        for blob in ATOB_RE.findall(html):
            decoded = _b64(blob)
            if not decoded:
                continue
            m = M3U8_RE.search(decoded)
            if m:
                return m.group(1)

        logger.debug("abyssplayer: no m3u8 found in %s", embed_url)
        return None