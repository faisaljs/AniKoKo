import os
import sys
import json
import time
import re
import inspect
import asyncio
import importlib.util
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
import httpx
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Path Configuration & Root/Backend Bridging
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(1, BASE_DIR)

# Dynamically import GistStorage from root utils/storage_gist.py
gist_file_path = os.path.join(BASE_DIR, "utils", "storage_gist.py")
if not os.path.exists(gist_file_path):
    raise FileNotFoundError(f"Cannot find storage_gist.py at {gist_file_path}")

spec = importlib.util.spec_from_file_location("storage_gist", gist_file_path)
storage_gist_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage_gist_module)
GistStorage = storage_gist_module.GistStorage

# Import native AniKoKo resolvers and scrapers
from scrapers.desidubanime import DesiDubAnimeScraper
from resolvers.vidmoly import VidmolyResolver
from resolvers.filesforever import FilesForeverResolver
from resolvers.abyssplayer import AbyssPlayerResolver
from resolvers.p2pplay import P2PPlayResolver


# ---------------------------------------------------------------------------
# Stage 1: Dynamic Object & Dataclass Unpackers
# ---------------------------------------------------------------------------
async def maybe_await(result_or_coro):
    """Safely awaits if target is a coroutine; returns immediate value otherwise."""
    if inspect.iscoroutine(result_or_coro):
        return await result_or_coro
    return result_or_coro


def create_instance(cls, *args, **kwargs):
    """Safely instantiates classes regardless of zero-arg or configured constructor."""
    try:
        return cls(*args, **kwargs)
    except TypeError:
        return cls()


def extract_url(target: Any) -> Optional[str]:
    """Unpacks string URL from AnimeCard, Episode, Source, Dict, or String."""
    if not target:
        return None
    if isinstance(target, str):
        return target
    if hasattr(target, "url") and target.url:
        return str(target.url)
    if hasattr(target, "link") and target.link:
        return str(target.link)
    if isinstance(target, dict):
        return target.get("url") or target.get("link") or target.get("src")
    return None


def extract_episode_meta(ep: Any, index: int) -> Tuple[int, str, Optional[str]]:
    """Extracts (episode_number, title, url) from Episode dataclass, dict, or tuple."""
    num = index + 1
    title = f"Episode {num}"
    url = extract_url(ep)

    if hasattr(ep, "number") and ep.number is not None:
        try:
            num = int(ep.number)
        except Exception:
            pass
    elif hasattr(ep, "episode_number") and ep.episode_number is not None:
        try:
            num = int(ep.episode_number)
        except Exception:
            pass

    if hasattr(ep, "title") and ep.title:
        title = str(ep.title)

    if isinstance(ep, dict):
        num = ep.get("number") or ep.get("episode_number") or num
        title = ep.get("title") or title

    return num, title, url


def safe_filename(title: str, anilist_id: int) -> str:
    cleaned = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    return f"{cleaned}_{anilist_id}.json"


def validate_schema(data: Dict[str, Any]) -> bool:
    required_keys = ["schema_version", "anilist_id", "title", "updated_at", "episodes"]
    return all(k in data for k in required_keys) and isinstance(data["episodes"], list)


# ---------------------------------------------------------------------------
# Stage 2: AniList GraphQL Client
# ---------------------------------------------------------------------------
class AniListClient:
    API_URL = "https://graphql.anilist.co"
    QUERY = """
    query ($id: Int) {
      Media (id: $id, type: ANIME) {
        id
        title {
          romaji
          english
          native
        }
        episodes
      }
    }
    """

    def __init__(self, timeout: int = 15):
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "Aniflix/1.0", "Accept": "application/json"}
        )

    async def get_anime_by_id(self, anilist_id: int) -> Optional[Dict[str, Any]]:
        try:
            res = await self.client.post(self.API_URL, json={"query": self.QUERY, "variables": {"id": anilist_id}})
            if res.status_code == 200:
                media = res.json().get("data", {}).get("Media")
                if media:
                    return {
                        "anilist_id": media["id"],
                        "title": {
                            "romaji": media["title"].get("romaji"),
                            "english": media["title"].get("english") or media["title"].get("romaji"),
                            "native": media["title"].get("native")
                        },
                        "total_episodes": media.get("episodes")
                    }
        except Exception as e:
            print(f"[STAGE 2 WARN] AniList lookup failed for ID {anilist_id}: {e}")
        return None

    async def close(self):
        await self.client.aclose()


# ---------------------------------------------------------------------------
# Stage 3 to 7: Execution & Fallback Engine
# ---------------------------------------------------------------------------
async def fetch_html(url: str, timeout: float = 15.0) -> Optional[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.google.com/"
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                return res.text
    except Exception as e:
        print(f"[HTML FETCH ERROR] {url}: {e}")
    return None


async def verify_stream_url(url: str, headers: Optional[Dict[str, str]] = None) -> bool:
    """Stage 7: Byte-range check for stream reachability."""
    if not url or not str(url).startswith("http"):
        return False
    try:
        req_headers = {"Range": "bytes=0-1024", "User-Agent": "Mozilla/5.0"}
        if headers:
            req_headers.update(headers)
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            res = await client.get(url, headers=req_headers)
            if res.status_code in (200, 206):
                return True
            head_res = await client.head(url, headers=headers)
            return head_res.status_code in (200, 301, 302)
    except Exception:
        return False


def extract_embeds_from_html(html_text: str) -> List[str]:
    """Stage 5: Scrapes embed iframes and video player targets from raw HTML."""
    embeds = set()
    soup = BeautifulSoup(html_text, "lxml")

    # Iframes
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src")
        if src and str(src).startswith("http"):
            embeds.add(src)

    # DooPlay Player Elements
    for tag in soup.select("ul.idTabs li a, div.source-box a, .play-online a"):
        href = tag.get("href")
        if href and str(href).startswith("http"):
            embeds.add(href)

    # Regex search for embed providers
    patterns = [
        r'https?://[^\s\'"]*vidmoly\.[^\s\'"]+',
        r'https?://[^\s\'"]*filesforever\.[^\s\'"]+',
        r'https?://[^\s\'"]*abyssplayer\.[^\s\'"]+',
        r'https?://[^\s\'"]*p2pplay\.[^\s\'"]+'
    ]
    for pat in patterns:
        for match in re.findall(pat, html_text):
            cleaned = match.split('"')[0].split("'")[0]
            embeds.add(cleaned)

    return list(embeds)


async def resolve_embed_to_streams(embed_url: str, resolvers: list) -> List[Dict[str, Any]]:
    """Stage 6: Feeds player links to resolvers with regex fallback."""
    streams = []

    # 1. Native Resolvers
    for res_obj in resolvers:
        can_handle = False
        for chk_method in ["can_resolve", "is_supported"]:
            if hasattr(res_obj, chk_method):
                try:
                    can_handle = await maybe_await(getattr(res_obj, chk_method)(embed_url))
                    if can_handle:
                        break
                except Exception:
                    pass

        if can_handle and hasattr(res_obj, "resolve"):
            try:
                resolved = await maybe_await(res_obj.resolve(embed_url))
                if isinstance(resolved, dict):
                    # Multi-stream array
                    for st in resolved.get("stream_urls", []):
                        if st.get("url") and str(st["url"]).startswith("http"):
                            streams.append(st)
                    # Single stream field
                    if not streams and resolved.get("url") and str(resolved["url"]).startswith("http"):
                        streams.append({
                            "url": resolved["url"],
                            "type": "hls" if ".m3u8" in resolved["url"] else "direct",
                            "quality": resolved.get("quality", "auto"),
                            "collected_at": datetime.now(timezone.utc).isoformat(),
                            "status": "reachable"
                        })
            except Exception as e:
                print(f"[RESOLVER ERROR] {res_obj.__class__.__name__} failed on {embed_url}: {e}")

    # 2. Fallback: Direct Vidmoly JWPlayer M3U8 extraction
    if not streams and "vidmoly" in embed_url.lower():
        html = await fetch_html(embed_url, timeout=10.0)
        if html:
            m3u8_match = re.search(r'file\s*:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
            if m3u8_match:
                direct_m3u8 = m3u8_match.group(1)
                streams.append({
                    "url": direct_m3u8,
                    "type": "hls",
                    "quality": "auto",
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "status": "reachable"
                })

    return streams


# ---------------------------------------------------------------------------
# Core Anime Collector Function
# ---------------------------------------------------------------------------
async def process_single_anime(
    anime_config: dict, existing_data_str: str, settings: dict
) -> Tuple[Optional[str], Optional[str], int]:
    anilist = AniListClient(timeout=15)
    resolvers = [
        create_instance(VidmolyResolver),
        create_instance(FilesForeverResolver),
        create_instance(AbyssPlayerResolver),
        create_instance(P2PPlayResolver)
    ]
    scraper = create_instance(DesiDubAnimeScraper)

    anilist_id = anime_config["anilist_id"]
    print(f"\n=======================================================")
    print(f"[STEP 2: METADATA] Querying AniList for ID {anilist_id}...")
    meta = await anilist.get_anime_by_id(anilist_id)
    await anilist.close()

    if not meta:
        print(f"[STEP 2 FAILED] AniList lookup failed for ID {anilist_id}.")
        return None, None, 0

    canonical_title = meta["title"]["english"] or meta["title"]["romaji"]
    file_name = safe_filename(canonical_title, anilist_id)
    print(f"[STEP 2 COMPLETE] Canonical Title: '{canonical_title}'")

    # Step 3: Search
    print(f"[STEP 3: MATCHING] Searching '{canonical_title}' on {scraper.__class__.__name__}...")
    match_card = None
    for method_name in ["search", "search_anime"]:
        if hasattr(scraper, method_name):
            try:
                res = await maybe_await(getattr(scraper, method_name)(canonical_title))
                if res and isinstance(res, list) and len(res) > 0:
                    match_card = res[0]
                    break
            except Exception as e:
                print(f"[STEP 3 DEBUG] {method_name} failed: {e}")

    # Fallback search with Romaji title
    if not match_card and meta["title"]["romaji"]:
        for method_name in ["search", "search_anime"]:
            if hasattr(scraper, method_name):
                try:
                    res = await maybe_await(getattr(scraper, method_name)(meta["title"]["romaji"]))
                    if res and isinstance(res, list) and len(res) > 0:
                        match_card = res[0]
                        break
                except Exception:
                    pass

    anime_page_url = extract_url(match_card)
    if not anime_page_url:
        print(f"[STEP 3 FAILED] No matching anime URL found for '{canonical_title}'.")
        return None, None, 0

    print(f"[STEP 3 COMPLETE] Matched URL: {anime_page_url}")

    # Step 4: Episode Discovery
    print(f"[STEP 4: EPISODES] Discovering episodes for {anime_page_url}...")
    raw_episodes = []

    # 4A. Native method call (unpacks string URL)
    for ep_method in ["get_episodes", "episodes"]:
        if hasattr(scraper, ep_method):
            try:
                res = await maybe_await(getattr(scraper, ep_method)(anime_page_url))
                if res and isinstance(res, list):
                    raw_episodes = res
                    print(f"[STEP 4 NATIVE] Extracted {len(raw_episodes)} episodes using {ep_method}()")
                    break
            except Exception as e:
                print(f"[STEP 4 DEBUG] {ep_method} failed: {e}")

    # 4B. Fallback: Parse DooPlay HTML structure
    if not raw_episodes:
        print(f"[STEP 4 FALLBACK] Attempting HTML structure parse...")
        anime_html = await fetch_html(anime_page_url)
        if anime_html:
            soup = BeautifulSoup(anime_html, "lxml")
            # Select episodes from DooPlay lists
            for a_tag in soup.select("ul.episodios li .episodiotitle a, ul.episodios li a"):
                ep_href = a_tag.get("href")
                if ep_href and "/episode/" in ep_href:
                    raw_episodes.append({
                        "title": a_tag.get_text(strip=True) or "Episode",
                        "url": ep_href
                    })
            print(f"[STEP 4 FALLBACK] Found {len(raw_episodes)} episodes via HTML selectors.")

    if not raw_episodes:
        print(f"[STEP 4 FAILED] 0 episodes found for '{canonical_title}'.")
        return None, None, 0

    max_episodes = settings.get("scraping", {}).get("max_episodes_per_anime", 12)
    collected_episodes = []

    # Step 5 & 6: Embed Extraction & Stream Resolution
    for idx, ep_obj in enumerate(raw_episodes[:max_episodes]):
        ep_num, ep_title, ep_url = extract_episode_meta(ep_obj, idx)
        if not ep_url:
            continue

        print(f"\n  -> Processing Ep {ep_num}: {ep_title} ({ep_url})")

        # 5A. Embed discovery
        embed_urls = []
        for src_method in ["get_sources", "get_episode_sources", "extract_embeds"]:
            if hasattr(scraper, src_method):
                try:
                    res = await maybe_await(getattr(scraper, src_method)(ep_url))
                    if res and isinstance(res, list):
                        for item in res:
                            u = extract_url(item)
                            if u:
                                embed_urls.append(u)
                        if embed_urls:
                            break
                except Exception:
                    pass

        # 5B. HTML embed fallback
        if not embed_urls:
            ep_html = await fetch_html(ep_url)
            if ep_html:
                embed_urls = extract_embeds_from_html(ep_html)

        print(f"     [STEP 5: EMBEDS] Found {len(embed_urls)} embed players.")

        # 6. Stream Resolution
        ep_stream_list = []
        seen_streams = set()

        for embed in embed_urls:
            resolved_streams = await resolve_embed_to_streams(embed, resolvers)
            for st in resolved_streams:
                st_url = st.get("url")
                if st_url and st_url not in seen_streams:
                    # Step 7: Reachability check
                    is_reachable = True
                    if settings.get("verification", {}).get("verify_links", True):
                        is_reachable = await verify_stream_url(st_url)

                    if is_reachable:
                        seen_streams.add(st_url)
                        st["collected_at"] = datetime.now(timezone.utc).isoformat()
                        st["last_checked_at"] = datetime.now(timezone.utc).isoformat()
                        st["status"] = "reachable"
                        ep_stream_list.append(st)
                        print(f"     [STEP 6 & 7 SUCCESS] Resolved verified {st.get('type')}: {st_url}")

        if ep_stream_list:
            collected_episodes.append({
                "episode_number": ep_num,
                "episode_title": ep_title,
                "sources": [{
                    "source_id": "desidubanime",
                    "source_name": "DesiDubAnime",
                    "stream_urls": ep_stream_list,
                    "download_urls": [],
                    "subtitles": []
                }]
            })

        await asyncio.sleep(settings.get("scraping", {}).get("request_delay_seconds", 0.5))

    total_valid = sum(len(s.get("stream_urls", [])) for ep in collected_episodes for s in ep.get("sources", []))

    if total_valid == 0:
        print(f"\n[STEP 8: REJECTED] '{canonical_title}' produced 0 reachable stream links. Skipping Gist upload.")
        return None, None, 0

    payload = {
        "schema_version": 1,
        "anilist_id": anilist_id,
        "title": meta["title"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "episodes": collected_episodes
    }

    if validate_schema(payload):
        print(f"\n[STEP 8: ACCEPTED] Staging '{canonical_title}' ({total_valid} functional streams).")
        return file_name, json.dumps(payload, indent=2, ensure_ascii=False), total_valid

    return None, None, 0


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------
async def async_main():
    start_time = time.time()
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")

    if not gist_token or not gist_id:
        print("[CRITICAL] Missing GIST_TOKEN or GIST_ID. Terminating.")
        sys.exit(1)

    config_dir = os.path.join(BASE_DIR, "config")
    settings_path = os.path.join(config_dir, "settings.json")
    anime_path = os.path.join(config_dir, "anime.json")

    settings = {}
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)

    anime_queue = []
    if os.path.exists(anime_path):
        with open(anime_path, "r", encoding="utf-8") as f:
            anime_data = json.load(f)
            anime_queue = [a for a in anime_data.get("anime", []) if a.get("enabled", True)]

    print(f"[STARTUP] Loaded {len(anime_queue)} active anime from config/anime.json")

    gist = GistStorage(gist_token, gist_id)
    try:
        existing_files = gist.fetch_all_files()
    except Exception as e:
        print(f"[CRITICAL] Could not read Gist contents: {e}")
        sys.exit(1)

    files_to_update: Dict[str, str] = {}
    catalog_index: List[Dict[str, Any]] = []

    for anime in anime_queue:
        try:
            fname = safe_filename(anime.get("title", ""), anime["anilist_id"])
            filename, json_data, valid_links = await process_single_anime(
                anime, existing_files.get(fname, ""), settings
            )
            if filename and json_data and valid_links > 0:
                files_to_update[filename] = json_data
                catalog_index.append({
                    "anilist_id": anime["anilist_id"],
                    "title": anime.get("title"),
                    "filename": filename,
                    "total_valid_links": valid_links
                })
        except Exception as exc:
            print(f"[ERROR] Task failed for {anime.get('title')}: {exc}")

    if not files_to_update:
        print("\n[INFO] No functional links collected across all anime. Gist remains untouched.")
        return

    # Update index.json
    files_to_update["index.json"] = json.dumps({
        "last_run": datetime.now(timezone.utc).isoformat(),
        "total_active_anime": len(files_to_update),
        "catalog": catalog_index,
        "execution_time_seconds": round(time.time() - start_time, 2)
    }, indent=2)

    try:
        gist.publish_files(files_to_update)
    except Exception as e:
        print(f"[CRITICAL] Publishing to Gist failed: {e}")
        sys.exit(1)

    print(f"\n[DONE] Successfully uploaded {len(files_to_update)} files to Gist in {round(time.time() - start_time, 2)}s.")


if __name__ == "__main__":
    asyncio.run(async_main())
