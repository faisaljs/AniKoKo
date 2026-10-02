import re
from typing import Optional

from backend.resolvers.base import BaseResolver


M3U8_IN_SOURCES_RE = re.compile(
    r"""sources\s*:\s*\[\s*\{\s*file\s*:\s*['"]([^'"]+\.m3u8[^'"]*)['"]""",
    re.I,
)
M3U8_ANY_RE = re.compile(r"""['"](https?://[^'"]+\.m3u8[^'"]*)['"]""")


class VidmolyResolver(BaseResolver):
    name = "vidmoly"
    hosts = ("vidmoly.org", "vidmoly.to", "vidmoly.me")

    async def resolve(self, embed_url: str) -> Optional[str]:
        html = await self.fetch(embed_url, referer="https://vidmoly.org/")

        m = M3U8_IN_SOURCES_RE.search(html)
        if m:
            return m.group(1)

        m = M3U8_ANY_RE.search(html)
        if m:
            return m.group(1)

        return None