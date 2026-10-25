import base64
import binascii
import json
import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx

from backend.config import USER_AGENT, REQUEST_TIMEOUT, SCRAPE_PROXY
from backend.resolvers.base import BaseResolver
from backend.utils.url import safe_request


logger = logging.getLogger("anikoko.resolver.filesforever")


M3U8_RE = re.compile(r"""['"](https?://[^'"]+\.m3u8[^'"]*)['"]""")
GDMRFID_RE = re.compile(r'id=["\']gdmrfid["\'][^>]*value=["\']([^"\']+)["\']', re.I)


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

    HELPER = "https://pro.iqsmartgames.com/embedhelper2.php"

    async def _fetch_with_final_url(
        self, url: str, referer: Optional[str] = None
    ) -> Tuple[Optional[str], str]:
        """Follow the redirect chain, return (html, final_url)."""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        kwargs = dict(headers=headers, timeout=REQUEST_TIMEOUT, follow_redirects=False)
        if SCRAPE_PROXY:
            kwargs["proxy"] = SCRAPE_PROXY
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                r = await safe_request(client, "GET", url)
                if r.status_code >= 400:
                    logger.debug("filesforever: %d from %s", r.status_code, url)
                    return None, str(r.url)
                return r.text, str(r.url)
        except Exception as e:
            logger.debug("filesforever: fetch failed (%s): %s", url, e)
            return None, url

    def _extract_sid(self, html: str, final_url: str) -> Optional[str]:
        m = GDMRFID_RE.search(html)
        if m:
            return m.group(1)
        tail = final_url.rstrip("/").split("/")[-1].split("?")[0]
        return tail or None

    async def resolve(self, embed_url: str) -> Optional[str]:
        # Step 1: walk redirects to /svid/<token>
        html, final_url = await self._fetch_with_final_url(
            embed_url, referer="https://www.desidubanime.me/"
        )
        if not html:
            return None

        # Step 2: token from hidden input, or URL tail
        sid = self._extract_sid(html, final_url)
        if not sid:
            logger.debug("filesforever: no sid found in %s", final_url)
            return None

        # Step 3: POST the helper
        body = urlencode({
            "sid": sid,
            "UserFavSite": "",
            "currentDomain": json.dumps([
                "pro.iqsmartgames.com",
                "www.desidubanime.me",
            ]),
        })
        try:
            txt = await self.post_form(
                self.HELPER,
                body,
                referer=final_url,
                extra_headers={"X-Requested-With": "XMLHttpRequest"},
            )
        except Exception as e:
            logger.debug("filesforever: helper POST failed: %s", e)
            return None

        # Step 4: parse JSON (or JSON-wrapped HTML)
        data = None
        try:
            data = json.loads(txt)
        except Exception:
            m = re.search(r"\{.*\}", txt, re.S)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    data = None
        if not isinstance(data, dict):
            logger.debug("filesforever: unparseable helper response")
            return None

        # Step 5: direct m3u8 in the response?
        m3 = M3U8_RE.search(json.dumps(data))
        if m3:
            return m3.group(1)

        # Step 6: decode mresult → map of source_key → file_id
        mresult: dict = {}
        mr_b64 = data.get("mresult") or data.get("mr") or ""
        if mr_b64:
            dec = _b64_decode_safe(mr_b64)
            if dec:
                try:
                    parsed = json.loads(dec)
                    if isinstance(parsed, dict):
                        mresult = parsed
                except Exception:
                    pass

        # Step 7: build a downstream embed URL from the first usable source
        sources = data.get("sources") or {}
        if not isinstance(sources, dict):
            return None

        for key, srv in sources.items():
            if not isinstance(srv, dict):
                continue
            base = srv.get("siteUrl") or srv.get("url") or ""
            path = srv.get("path") or ""
            fid = mresult.get(key) or ""
            if not base:
                continue
            full = (base + fid + path) if fid else (base + path if path else base)
            if full.startswith("//"):
                full = "https:" + full
            if not full.startswith("http"):
                continue
            return full

        logger.debug("filesforever: no usable source in helper response")
        return None
