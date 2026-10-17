import re
from typing import Callable, Optional
from urllib.parse import quote, urljoin, urlparse


M3U8_RE = re.compile(r"""["'`](https?://[^"'`\s\\]+?\.m3u8[^"'`\s\\]*)["'`]""")
MP4_RE = re.compile(r"""["'`](https?://[^"'`\s\\]+?\.mp4[^"'`\s\\]*)["'`]""")
URI_ATTR_RE = re.compile(r'URI="([^"]+)"')


def extract_m3u8_urls(html: str) -> list[str]:
    seen, out = set(), []
    for u in M3U8_RE.findall(html):
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def extract_mp4_urls(html: str) -> list[str]:
    seen, out = set(), []
    for u in MP4_RE.findall(html):
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def extract_embed_sources(html: str) -> list[str]:
    """Common file-host embed iframes: streamtape, dood, filemoon, etc."""
    hosts = (
        "streamtape", "dood", "filemoon", "streamwish", "vidhide",
        "vidsrc", "dailymotion", "ok\\.ru", "mp4upload", "mega",
        "mixdrop", "voe", "upstream", "player", "embed", "streamsb",
        "kiranime",
    )
    host_group = "|".join(hosts)
    pattern = re.compile(
        r"""(?:src|data-src|file|href)\s*=\s*["']([^"']*(?:%s)[^"']*)["']""" % host_group,
        re.I,
    )
    seen, out = set(), []
    for u in pattern.findall(html):
        if u not in seen and u.startswith("http"):
            seen.add(u)
            out.append(u)
    return out


def absolutize(base: str, url: str) -> str:
    return urljoin(base, url)


def same_host(base: str, url: str) -> bool:
    return urlparse(base).netloc == urlparse(url).netloc


def make_proxy_url(absolute: str, referer: Optional[str] = None,
                   path: str = "/proxy/stream") -> str:
    """Build a proxied URL for a segment/key/media reference."""
    out = f"{path}?url={quote(absolute, safe='')}"
    if referer:
        out += f"&referer={quote(referer, safe='')}"
    return out


def rewrite_playlist(
    body: str,
    base_url: str,
    referer: Optional[str] = None,
    make_url: Optional[Callable[[str, Optional[str]], str]] = None,
) -> str:
    """Rewrite every URL in an m3u8 — both bare segment lines and URI=
    attributes inside tags (#EXT-X-KEY, #EXT-X-MAP, #EXT-X-MEDIA,
    #EXT-X-I-FRAME-STREAM-INF, #EXT-X-SESSION-KEY)."""
    if make_url is None:
        make_url = lambda absu, ref: make_proxy_url(absu, ref)

    out_lines: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            out_lines.append(line)
            continue

        if s.startswith("#"):
            if 'URI="' in s:
                def _sub(m):
                    absu = absolutize(base_url, m.group(1))
                    return f'URI="{make_url(absu, referer)}"'
                out_lines.append(URI_ATTR_RE.sub(_sub, line))
            else:
                out_lines.append(line)
            continue

        absolute = absolutize(base_url, s)
        out_lines.append(make_url(absolute, referer))

    return "\n".join(out_lines)


def is_playlist_response(url: str, content_type: str) -> bool:
    ct = (content_type or "").lower()
    if url.split("?")[0].endswith(".m3u8"):
        return True
    if "mpegurl" in ct:
        return True
    if "application/vnd.apple.mpegurl" in ct:
        return True
    return False