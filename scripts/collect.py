import os
import sys
import json
import time
import inspect
import asyncio
import importlib.util
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import httpx

# ---------------------------------------------------------------------------
# Path Configuration
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
# Async Helper: Call functions whether they are sync or async
# ---------------------------------------------------------------------------
async def maybe_await(result_or_coro):
    """Awaits the object if it is a coroutine; otherwise returns it directly."""
    if inspect.iscoroutine(result_or_coro):
        return await result_or_coro
    return result_or_coro


def create_instance(cls, *args, **kwargs):
    """Instantiates a class trying positional arguments first, falling back to empty constructor."""
    try:
        return cls(*args, **kwargs)
    except TypeError:
        try:
            return cls()
        except Exception as e:
            raise e


# ---------------------------------------------------------------------------
# AniList Metadata Helper
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
            print(f"[WARN] AniList lookup failed for ID {anilist_id}: {e}")
        return None

    async def close(self):
        await self.client.aclose()


def safe_filename(title: str, anilist_id: int) -> str:
    cleaned = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    return f"{cleaned}_{anilist_id}.json"


def validate_schema(data: Dict[str, Any]) -> bool:
    required_keys = ["schema_version", "anilist_id", "title", "updated_at", "episodes"]
    return all(k in data for k in required_keys) and isinstance(data["episodes"], list)


# ---------------------------------------------------------------------------
# Async Search & Scrape Invocation
# ---------------------------------------------------------------------------
async def run_search_on_scraper(scraper, title: str) -> Optional[Any]:
    for method_name in ["search", "search_anime"]:
        if hasattr(scraper, method_name):
            try:
                method = getattr(scraper, method_name)
                result = await maybe_await(method(title))
                if result:
                    if isinstance(result, list) and len(result) > 0:
                        first = result[0]
                        if isinstance(first, dict):
                            return first.get("id") or first.get("url") or first.get("link") or first
                        return first
                    return result
            except Exception as e:
                print(f"[DEBUG] {scraper.__class__.__name__}.{method_name} failed: {e}")
    return None


async def run_get_episodes(scraper, anime_identifier: Any) -> List[Any]:
    for method_name in ["get_episodes", "episodes"]:
        if hasattr(scraper, method_name):
            try:
                method = getattr(scraper, method_name)
                res = await maybe_await(method(anime_identifier))
                if isinstance(res, list):
                    return res
            except Exception as e:
                print(f"[DEBUG] {scraper.__class__.__name__}.{method_name} failed: {e}")
    return []


async def run_get_sources(scraper, ep_identifier: Any) -> List[str]:
    for method_name in ["get_sources", "get_episode_sources", "extract_embeds", "get_streams"]:
        if hasattr(scraper, method_name):
            try:
                method = getattr(scraper, method_name)
                res = await maybe_await(method(ep_identifier))
                if isinstance(res, list):
                    urls = []
                    for item in res:
                        if isinstance(item, str):
                            urls.append(item)
                        elif isinstance(item, dict):
                            url = item.get("url") or item.get("src") or item.get("link")
                            if url:
                                urls.append(url)
                    return urls
            except Exception:
                pass
    return []


async def verify_url(url: str, headers: Optional[Dict[str, str]] = None) -> bool:
    """Async link reachability checker."""
    try:
        req_headers = {"Range": "bytes=0-1024", "User-Agent": "Mozilla/5.0"}
        if headers:
            req_headers.update(headers)
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            res = await client.get(url, headers=req_headers)
            return res.status_code in [200, 206]
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Single Anime Scraping Execution (Async)
# ---------------------------------------------------------------------------
async def process_single_anime(anime_config: dict, existing_data_str: str, settings: dict) -> tuple:
    anilist = AniListClient(timeout=15)

    resolvers = [
        create_instance(VidmolyResolver),
        create_instance(FilesForeverResolver),
        create_instance(AbyssPlayerResolver),
        create_instance(P2PPlayResolver)
    ]
    scraper = create_instance(DesiDubAnimeScraper)

    anilist_id = anime_config["anilist_id"]
    print(f"[*] Resolving AniList metadata for ID: {anilist_id}...")
    meta = await anilist.get_anime_by_id(anilist_id)
    await anilist.close()

    if not meta:
        raise RuntimeError(f"Could not retrieve AniList metadata for ID {anilist_id}")

    canonical_title = meta["title"]["english"] or meta["title"]["romaji"]
    file_name = safe_filename(canonical_title, anilist_id)

    # Retain previous episodes if already cached
    existing_eps = {}
    if existing_data_str:
        try:
            raw_json = json.loads(existing_data_str)
            for ep in raw_json.get("episodes", []):
                existing_eps[ep["episode_number"]] = ep
        except Exception:
            pass

    collected_episodes = []

    # Search using Canonical Title, then fall back to Romaji
    print(f"[*] Searching '{canonical_title}' on {scraper.__class__.__name__}...")
    match = await run_search_on_scraper(scraper, canonical_title)
    if not match and meta["title"]["romaji"]:
        match = await run_search_on_scraper(scraper, meta["title"]["romaji"])

    if not match:
        print(f"[SOURCE] No match found for '{canonical_title}'.")
    else:
        print(f"[SOURCE] Match located: {match}")
        episodes = await run_get_episodes(scraper, match)
        max_ep = settings.get("scraping", {}).get("max_episodes_per_anime", 10)

        for idx, ep in enumerate(episodes[:max_ep]):
            ep_num = idx + 1
            ep_target = ep

            if isinstance(ep, dict):
                ep_num = ep.get("number") or ep.get("episode_number") or (idx + 1)
                ep_target = ep.get("id") or ep.get("url") or ep.get("episode_url") or ep

            embed_urls = await run_get_sources(scraper, ep_target)

            stream_list = []
            download_list = []

            for embed in embed_urls:
                for res_obj in resolvers:
                    can_handle = False
                    if hasattr(res_obj, "can_resolve"):
                        can_handle = await maybe_await(res_obj.can_resolve(embed))
                    elif hasattr(res_obj, "is_supported"):
                        can_handle = await maybe_await(res_obj.is_supported(embed))

                    if can_handle and hasattr(res_obj, "resolve"):
                        try:
                            resolved = await maybe_await(res_obj.resolve(embed))
                            if isinstance(resolved, dict):
                                streams = resolved.get("stream_urls") or []
                                for s in streams:
                                    stream_list.append(s)

                                if not streams and "url" in resolved and str(resolved["url"]).startswith("http"):
                                    stream_url = resolved["url"]
                                    is_valid = True
                                    if settings.get("verification", {}).get("verify_links", True):
                                        is_valid = await verify_url(stream_url)

                                    if is_valid:
                                        stream_list.append({
                                            "url": stream_url,
                                            "type": "hls" if ".m3u8" in stream_url else "direct",
                                            "quality": resolved.get("quality", "auto"),
                                            "collected_at": datetime.now(timezone.utc).isoformat(),
                                            "status": "reachable"
                                        })
                        except Exception as ex:
                            print(f"[DEBUG] Resolver {res_obj.__class__.__name__} failed on {embed}: {ex}")

            if stream_list or download_list:
                collected_episodes.append({
                    "episode_number": ep_num,
                    "episode_title": f"Episode {ep_num}",
                    "sources": [{
                        "source_id": "desidubanime",
                        "source_name": "DesiDubAnime",
                        "stream_urls": stream_list,
                        "download_urls": download_list,
                        "subtitles": []
                    }]
                })

            await asyncio.sleep(settings.get("scraping", {}).get("request_delay_seconds", 0.5))

    # Merge fresh episodes into cache
    for ep in collected_episodes:
        existing_eps[ep["episode_number"]] = ep

    final_episodes = sorted(list(existing_eps.values()), key=lambda x: x["episode_number"])

    payload = {
        "schema_version": 1,
        "anilist_id": anilist_id,
        "title": meta["title"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "episodes": final_episodes
    }

    if validate_schema(payload):
        return file_name, json.dumps(payload, indent=2, ensure_ascii=False)
    raise ValueError(f"Schema validation error on {canonical_title}")


# ---------------------------------------------------------------------------
# Main Async Orchestrator
# ---------------------------------------------------------------------------
async def async_main():
    start_time = time.time()

    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")

    if not gist_token or not gist_id:
        print("[CRITICAL] Missing GIST_TOKEN or GIST_ID. Exiting.")
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

    print(f"[INFO] Loaded {len(anime_queue)} active anime from config/anime.json")

    gist = GistStorage(gist_token, gist_id)
    try:
        existing_files = gist.fetch_all_files()
    except Exception as e:
        print(f"[CRITICAL] Failed to fetch current Gist contents: {e}")
        sys.exit(1)

    files_to_update = {}
    success_count = 0

    for anime in anime_queue:
        try:
            fname = safe_filename(anime.get("title", ""), anime["anilist_id"])
            filename, json_data = await process_single_anime(
                anime, existing_files.get(fname, ""), settings
            )
            files_to_update[filename] = json_data
            success_count += 1
        except Exception as exc:
            print(f"[ERROR] Task failed for {anime.get('title', 'Unknown')}: {exc}")

    # Update index.json
    files_to_update["index.json"] = json.dumps({
        "last_run": datetime.now(timezone.utc).isoformat(),
        "total_anime_processed": success_count,
        "execution_time_seconds": round(time.time() - start_time, 2)
    }, indent=2)

    # Publish to Gist
    try:
        gist.publish_files(files_to_update)
    except Exception as e:
        print(f"[CRITICAL] Publishing to Gist failed: {e}")
        sys.exit(1)

    print(f"[INFO] Complete: processed in {round(time.time() - start_time, 2)}s.")


if __name__ == "__main__":
    asyncio.run(async_main())
