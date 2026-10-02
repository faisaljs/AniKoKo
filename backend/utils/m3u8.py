import re
from urllib.parse import urljoin, urlparse


def extract_m3u8_urls(html: str) -> list[str]:
    pattern = re.compile(r"""["'`](https?://[^"'`\s\\]+?\.m3u8[^"'`\s\\]*)["'`]""")
    found = pattern.findall(html)
    seen, out = set(), []
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def extract_mp4_urls(html: str) -> list[str]:
    pattern = re.compile(r"""["'`](https?://[^"'`\s\\]+?\.mp4[^"'`\s\\]*)["'`]""")
    found = pattern.findall(html)
    seen, out = set(), []
    for u in found:
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
    found = pattern.findall(html)
    seen, out = set(), []
    for u in found:
        if u not in seen and u.startswith("http"):
            seen.add(u)
            out.append(u)
    return out


def absolutize(base: str, url: str) -> str:
    return urljoin(base, url)


def same_host(base: str, url: str) -> bool:
    return urlparse(base).netloc == urlparse(url).netloc