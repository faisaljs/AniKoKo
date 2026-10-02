import base64
import binascii
import json
import re
from typing import Optional
from urllib.parse import urlencode

import httpx

from backend.config import USER_AGENT, REQUEST_TIMEOUT, SCRAPE_PROXY
from backend.resolvers.base import BaseResolver


M3U8_RE = re.compile(r"""['"](https?://[^'"]+\.m3u8[^'"]*)['"]""")


def _b64_decode_safe(s: str) -> Optional[str]:
    try:
        pad = (-len(s)) % 4
        if pad:
            s = s + ("=" * pad)
        return base64.b64decode(s).decode("utf-8", errors="ignore")
    except (binascii.Error, ValueError):
        return None


class FilesForeverResolver(BaseResolver):
    name = "filesforever"
    hosts = ("filesforever.link", "iqsmartgames.com")

    async def resolve(self, embed_url: str) -> Optional[str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.desidubanime.me/",
        }
        kwargs = dict(headers=headers, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        if SCRAPE_PROXY:
            kwargs["proxy"] = SCRAPE_PROXY

        # 1. walk the redirect chain to the final /svid/<token> page
        async with httpx.AsyncClient(**kwargs) as client:
            r = await client.get(embed_url)
            if r.status_code >= 400:
                return None
            html = r.text
            final_url = str(r.url)

        # 2. slug from the hidden input
        sid = None
        m = re.search(r'id=["\']gdmrfid["\'][^>]*value=["\']([^"\']+)["\']', html)
        if m:
            sid = m.group(1)
        if not sid:
            sid = final_url.rstrip("/").split("/")[-1]
        if not sid:
            return None

        # 3. POST to embedhelper2.php
        helper = "https://pro.iqsmartgames.com/embedhelper2.php"
        post_headers = {
            "User-Agent": USER_AGENT,
            "Referer": final_url,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
        }
        body = urlencode({
            "sid": sid,
            "UserFavSite": "",
            "currentDomain": json.dumps(["pro.iqsmartgames.com", "www.desidubanime.me"]),
        })

        async with httpx.AsyncClient(**kwargs) as client:
            hr = await client.post(helper, headers=post_headers, content=body)
            if hr.status_code >= 400:
                return None
            txt = hr.text

        # 4. response is JSON (or JSON-wrapped HTML)
        try:
            data = hr.json()
        except Exception:
            m2 = re.search(r"\{.*\}", txt, re.S)
            if not m2:
                return None
            try:
                data = json.loads(m2.group(0))
            except Exception:
                return None

        # 5. any direct m3u8 already?
        m3 = M3U8_RE.search(json.dumps(data))
        if m3:
            return m3.group(1)

        # 6. pick the first source → build the downstream embed URL
        sources = data.get("sources") or {}
        mresult = {}
        mr_b64 = data.get("mresult") or data.get("mr") or ""
        if mr_b64:
            dec = _b64_decode_safe(mr_b64)
            if dec:
                try:
                    mresult = json.loads(dec)
                except Exception:
                    mresult = {}

        for key in sources.keys():
            srv = sources[key] or {}
            base = srv.get("siteUrl") or srv.get("url") or ""
            path = srv.get("path") or ""
            fid = mresult.get(key) or ""
            if not base:
                continue
            full = (base + fid + (path or "")) if fid else base
            if full.startswith("//"):
                full = "https:" + full
            if full.startswith("http"):
                return full

        return None