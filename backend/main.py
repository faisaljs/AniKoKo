import asyncio
from typing import List, Optional
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response

from backend.config import (
    PROVIDERS, CACHE_TTL_LIST, CACHE_TTL_DETAIL, CACHE_TTL_STREAM,
    USER_AGENT, CORS_ORIGINS,
)
from backend.scrapers.registry import all_scrapers, get_scraper, slugs
from backend.scrapers.base import is_episode_url
from backend.resolvers import resolve_embed as _resolve_embed
from backend.utils import cache
from backend.utils.m3u8 import absolutize


app = FastAPI(
    title="AniKoKo API",
    version="1.0.0",
    description=(
        "Hindi-dub anime scraping API. Metadata + streaming sources from "
        "DesiDubAnime. All responses are JSON."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _json_error(status: int, message: str, hint: Optional[str] = None):
    body = {"error": message}
    if hint:
        body["hint"] = hint
    return JSONResponse(body, status_code=status)


# ---------------- meta ----------------

@app.get("/")
async def root():
    return {
        "name": "AniKoKo API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "providers": "/api/providers",
            "latest": "/api/latest?provider=desidubanime&page=1",
            "search": "/api/search?q=naruto&provider=desidubanime",
            "anime": "/api/anime?url=<series_url>&provider=desidubanime",
            "sources": "/api/sources?url=<episode_url>&provider=desidubanime",
            "resolve": "/api/resolve?url=<embed_url>",
            "stream_proxy": "/proxy/stream?url=<m3u8_or_mp4>",
            "download_proxy": "/proxy/download?url=<url>&filename=out.mp4",
            "image_proxy": "/proxy/img?url=<image_url>",
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/providers")
async def api_providers():
    return [{"slug": s, **PROVIDERS[s]} for s in slugs()]


# ---------------- content ----------------

@app.get("/api/latest")
async def api_latest(provider: Optional[str] = None, page: int = 1):
    key = f"latest:{provider}:{page}"
    hit = cache.get(key)
    if hit is not None:
        return hit

    if provider and provider not in slugs():
        raise HTTPException(404, "unknown provider")

    scrapers = [get_scraper(provider)] if provider else all_scrapers()

    async def run(s):
        try:
            items = await s.latest(page=page)
            return [c.__dict__ for c in items]
        except Exception as e:
            return {"error": str(e), "provider": s.slug}

    results = await asyncio.gather(*(run(s) for s in scrapers))

    flat, errors = [], []
    for r in results:
        if isinstance(r, list):
            flat.extend(r)
        elif isinstance(r, dict) and "error" in r:
            errors.append(r)

    payload = {"items": flat}
    if errors:
        payload["errors"] = errors
    cache.set(key, payload, CACHE_TTL_LIST)
    return payload


@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1), provider: Optional[str] = None):
    key = f"search:{provider}:{q.lower()}"
    hit = cache.get(key)
    if hit is not None:
        return hit

    if provider and provider not in slugs():
        raise HTTPException(404, "unknown provider")

    scrapers = [get_scraper(provider)] if provider else all_scrapers()

    async def run(s):
        try:
            items = await s.search(q)
            return [c.__dict__ for c in items]
        except Exception as e:
            return {"error": str(e), "provider": s.slug}

    results = await asyncio.gather(*(run(s) for s in scrapers))

    flat, errors = [], []
    for r in results:
        if isinstance(r, list):
            flat.extend(r)
        elif isinstance(r, dict) and "error" in r:
            errors.append(r)

    payload = {"query": q, "items": flat}
    if errors:
        payload["errors"] = errors
    cache.set(key, payload, CACHE_TTL_LIST)
    return payload


@app.get("/api/anime")
async def api_anime(url: str, provider: str):
    if provider not in slugs():
        raise HTTPException(404, "unknown provider")

    key = f"anime:{provider}:{url}"
    hit = cache.get(key)
    if hit is not None:
        return hit

    try:
        data = await get_scraper(provider).anime_detail(url)
    except Exception as e:
        return _json_error(502, f"scraper failed: {e}")

    payload = {
        "title": data["title"],
        "poster": data["poster"],
        "synopsis": data["synopsis"],
        "provider": provider,
        "url": url,
        "episodes": [e.__dict__ for e in data["episodes"]],
    }
    cache.set(key, payload, CACHE_TTL_DETAIL)
    return payload


@app.get("/api/sources")
@app.get("/api/episode")
async def api_sources(url: str, provider: str):
    if provider not in slugs():
        raise HTTPException(404, "unknown provider")

    if not is_episode_url(url):
        return _json_error(
            422,
            "not an episode url",
            "open this from an episode link, not a series page",
        )

    key = f"sources:{provider}:{url}"
    hit = cache.get(key)
    if hit is not None:
        return hit

    try:
        srcs = await get_scraper(provider).episode_sources(url)
    except Exception as e:
        return _json_error(502, f"scraper failed: {e}")

    payload = {
        "url": url,
        "provider": provider,
        "sources": [
            {
                "url": s.url,
                "kind": s.kind,
                "quality": s.quality,
                "referer": s.referer,
            }
            for s in srcs
        ],
    }
    cache.set(key, payload, CACHE_TTL_STREAM)
    return payload


# ---------------- resolver debug ----------------

@app.get("/api/resolve")
async def api_resolve(url: str):
    """Given an embed URL, try to resolve it to a direct m3u8."""
    m3u8 = await _resolve_embed(url)
    return {
        "input": url,
        "resolved": m3u8,
        "ok": bool(m3u8),
    }


# ---------------- proxy ----------------

CHUNK = 64 * 1024


def _proxy_kwargs():
    return dict(timeout=None, follow_redirects=True)


@app.get("/proxy/stream")
async def proxy_stream(url: str, referer: Optional[str] = None):
    async def rewrite_m3u8(body: str, base_url: str, ref: Optional[str]) -> str:
        out_lines = []
        for line in body.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                out_lines.append(line)
                continue
            absolute = absolutize(base_url, s)
            proxied = f"/proxy/stream?url={quote(absolute, safe='')}"
            if ref:
                proxied += f"&referer={quote(ref, safe='')}"
            out_lines.append(proxied)
        return "\n".join(out_lines)

    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer

    client = httpx.AsyncClient(**_proxy_kwargs())
    try:
        upstream = await client.send(
            client.build_request("GET", url, headers=headers),
            stream=True,
        )
    except Exception as e:
        await client.aclose()
        raise HTTPException(502, f"upstream error: {e}")

    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(upstream.status_code, "upstream error")

    content_type = upstream.headers.get("content-type", "")
    is_playlist = (
        url.endswith(".m3u8")
        or "mpegurl" in content_type.lower()
        or "application/vnd.apple.mpegurl" in content_type.lower()
    )

    if is_playlist:
        raw = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        text = raw.decode("utf-8", errors="ignore")
        rewritten = await rewrite_m3u8(text, url, referer)
        return Response(
            rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def iter_body():
        try:
            async for chunk in upstream.aiter_bytes(CHUNK):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    resp_headers = {
        "Access-Control-Allow-Origin": "*",
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
    }
    if content_type:
        resp_headers["Content-Type"] = content_type
    if "content-length" in upstream.headers:
        resp_headers["Content-Length"] = upstream.headers["content-length"]

    return StreamingResponse(
        iter_body(),
        headers=resp_headers,
        media_type=content_type or "application/octet-stream",
    )


@app.get("/proxy/download")
async def proxy_download(
    url: str, filename: Optional[str] = None, referer: Optional[str] = None
):
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer

    client = httpx.AsyncClient(**_proxy_kwargs())
    try:
        upstream = await client.send(
            client.build_request("GET", url, headers=headers),
            stream=True,
        )
    except Exception as e:
        await client.aclose()
        raise HTTPException(502, f"upstream error: {e}")

    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(upstream.status_code, "upstream error")

    name = filename or url.split("/")[-1].split("?")[0] or "video.mp4"
    if not name.endswith((".mp4", ".mkv", ".ts", ".m3u8")):
        name += ".mp4"

    content_type = upstream.headers.get("content-type", "application/octet-stream")

    async def iter_body():
        try:
            async for chunk in upstream.aiter_bytes(CHUNK):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        iter_body(),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/proxy/img")
async def proxy_img(url: str, referer: Optional[str] = None):
    headers = {"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    client = httpx.AsyncClient(**_proxy_kwargs())
    try:
        upstream = await client.send(
            client.build_request("GET", url, headers=headers),
            stream=True,
        )
    except Exception as e:
        await client.aclose()
        raise HTTPException(502, f"upstream error: {e}")
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(upstream.status_code, "upstream error")

    ct = upstream.headers.get("content-type", "image/jpeg")

    async def iter_body():
        try:
            async for chunk in upstream.aiter_bytes(CHUNK):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(iter_body(), media_type=ct)


if __name__ == "__main__":
    import uvicorn
    from backend.config import HOST, PORT
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)