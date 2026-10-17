import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response

from backend.config import (
    API_VERSION, PROVIDERS, CACHE_TTL_LIST, CACHE_TTL_DETAIL, CACHE_TTL_STREAM,
    USER_AGENT, CORS_ORIGINS, PROXY_RETRIES, PROXY_RETRY_BACKOFF,
)
from backend.scrapers.registry import all_scrapers, get_scraper, slugs
from backend.resolvers import resolve_embed as _resolve_embed, all_resolvers
from backend.utils import cache
from backend.utils.m3u8 import rewrite_playlist, make_proxy_url, is_playlist_response


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("anikoko")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AniKoKo %s starting — providers: %s", API_VERSION, slugs())
    yield
    for s in all_scrapers():
        try:
            await s.close()
        except Exception:
            pass
    logger.info("AniKoKo shutdown complete")


app = FastAPI(
    title="AniKoKo API",
    version=API_VERSION,
    description=(
        "Hindi-dub anime scraping API. Metadata + streaming sources from "
        "DesiDubAnime. All responses are JSON."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Type"],
)


def _json_error(status: int, message: str, hint: Optional[str] = None):
    body = {"error": message}
    if hint:
        body["hint"] = hint
    return JSONResponse(body, status_code=status)


@app.exception_handler(HTTPException)
async def _http_exc_handler(request: Request, exc: HTTPException):
    return _json_error(exc.status_code, str(exc.detail))


# ---------------- meta ----------------

@app.get("/")
async def root():
    return {
        "name": "AniKoKo API",
        "version": API_VERSION,
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
            "cache_stats": "/admin/cache/stats",
            "cache_clear": "/admin/cache/clear?prefix=",
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok", "version": API_VERSION}


@app.get("/api/providers")
async def api_providers():
    return [{"slug": s, **PROVIDERS[s]} for s in slugs()]


# ---------------- admin ----------------

@app.get("/admin/cache/stats")
async def admin_cache_stats():
    return cache.stats()


@app.post("/admin/cache/clear")
async def admin_cache_clear(prefix: Optional[str] = None):
    if prefix:
        n = cache.delete_prefix(prefix)
        return {"cleared": n, "prefix": prefix}
    cache.clear()
    return {"cleared": "all"}


@app.get("/admin/resolvers")
async def admin_resolvers():
    return [
        {"name": r.name, "hosts": list(r.hosts)}
        for r in all_resolvers()
    ]


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
            logger.warning("scraper %s failed: %s", s.slug, e, exc_info=True)
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
            logger.warning("scraper %s search failed: %s", s.slug, e, exc_info=True)
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
        logger.warning("anime_detail failed for %s: %s", url, e, exc_info=True)
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

    scraper = get_scraper(provider)
    if not scraper.is_episode_url(url):
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
        srcs = await scraper.episode_sources(url)
    except Exception as e:
        logger.warning("episode_sources failed for %s: %s", url, e, exc_info=True)
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
    m3u8 = await _resolve_embed(url)
    return {
        "input": url,
        "resolved": m3u8,
        "ok": bool(m3u8),
    }


# ---------------- proxy ----------------

CHUNK = 64 * 1024


async def _open_upstream(
    url: str,
    referer: Optional[str] = None,
    extra_headers: Optional[dict] = None,
):
    """Open a streaming upstream request with retry on transport errors.
    Returns (client, response). Caller closes both."""
    if not url:
        raise HTTPException(400, "url parameter required")

    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    if extra_headers:
        headers.update(extra_headers)

    last_exc = None
    for i in range(PROXY_RETRIES + 1):
        client = httpx.AsyncClient(
            timeout=None, follow_redirects=True, headers=headers
        )
        try:
            upstream = await client.send(
                client.build_request("GET", url, headers=headers),
                stream=True,
            )
            return client, upstream
        except (httpx.TimeoutException, httpx.TransportError) as e:
            await client.aclose()
            last_exc = e
            if i == PROXY_RETRIES:
                break
            delay = PROXY_RETRY_BACKOFF * (2 ** i)
            logger.debug("proxy retry %d/%d on %s in %.1fs: %s",
                         i + 1, PROXY_RETRIES + 1, url, delay, e)
            await asyncio.sleep(delay)
    raise HTTPException(502, f"upstream error: {last_exc}")


def _stream_headers(upstream: httpx.Response) -> dict:
    out = {
        "Access-Control-Allow-Origin": "*",
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
    }
    for h in ("content-type", "content-length", "content-range", "accept-ranges"):
        if h in upstream.headers:
            out[h.title()] = upstream.headers[h]
    return out


@app.get("/proxy/stream")
async def proxy_stream(url: str, request: Request, referer: Optional[str] = None):
    fwd = {}
    if "range" in request.headers:
        fwd["Range"] = request.headers["range"]

    client, upstream = await _open_upstream(url, referer=referer, extra_headers=fwd)

    if upstream.status_code >= 400 and upstream.status_code != 416:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(upstream.status_code, "upstream error")

    content_type = upstream.headers.get("content-type", "")

    if is_playlist_response(url, content_type):
        raw = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        text = raw.decode("utf-8", errors="ignore")
        rewritten = rewrite_playlist(text, url, referer=referer)
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

    return StreamingResponse(
        iter_body(),
        headers=_stream_headers(upstream),
        media_type=content_type or "application/octet-stream",
        status_code=upstream.status_code,
    )


@app.get("/proxy/download")
async def proxy_download(
    url: str,
    request: Request,
    filename: Optional[str] = None,
    referer: Optional[str] = None,
):
    fwd = {}
    if "range" in request.headers:
        fwd["Range"] = request.headers["range"]

    client, upstream = await _open_upstream(url, referer=referer, extra_headers=fwd)

    if upstream.status_code >= 400 and upstream.status_code != 416:
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

    headers = {
        "Content-Disposition": f'attachment; filename="{name}"',
        "Access-Control-Allow-Origin": "*",
    }
    for h in ("content-length", "content-range", "accept-ranges"):
        if h in upstream.headers:
            headers[h.title()] = upstream.headers[h]

    return StreamingResponse(
        iter_body(),
        media_type=content_type,
        headers=headers,
        status_code=upstream.status_code,
    )


@app.get("/proxy/img")
async def proxy_img(url: str, referer: Optional[str] = None):
    extra = {"Accept": "image/*,*/*;q=0.8"}
    client, upstream = await _open_upstream(url, referer=referer, extra_headers=extra)

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
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=False)