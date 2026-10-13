import os
import sys
import json
import time
import importlib.util
from datetime import datetime, timezone
import concurrent.futures
from typing import Dict, Any, Optional, List
import httpx

# ---------------------------------------------------------------------------
# Path Configuration (Bridges root and backend without import collisions)
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

# Import scrapers and resolvers from backend
from scrapers.desidubanime import DesiDubAnimeScraper
from resolvers.vidmoly import VidmolyResolver
from resolvers.filesforever import FilesForeverResolver
from resolvers.abyssplayer import AbyssPlayerResolver
from resolvers.p2pplay import P2PPlayResolver


# ---------------------------------------------------------------------------
# Embedded Network & Validation Helpers
# ---------------------------------------------------------------------------
class HttpClient:
    def __init__(self, timeout: int = 15):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        self.client = httpx.Client(timeout=timeout, headers=headers, follow_redirects=True)

    def get(self, url: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        return self.client.get(url, headers=headers, params=params)

    def post(self, url: str, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
        return self.client.post(url, json=json, headers=headers)

    def check_url(self, url: str, headers: Optional[Dict[str, str]] = None) -> bool:
        """Performs a lightweight verification check on the stream URL."""
        try:
            req_headers = {"Range": "bytes=0-1024"}
            if headers:
                req_headers.update(headers)
            res = self.client.get(url, headers=req_headers, timeout=8.0)
            return res.status_code in [200, 206]
        except Exception:
            try:
                head_res = self.client.head(url, headers=headers, timeout=6.0)
                return head_res.status_code in [200, 301, 302]
            except Exception:
                return False

    def close(self):
        self.client.close()


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

    def __init__(self, client: HttpClient):
        self.http = client

    def get_anime_by_id(self, anilist_id: int) -> Optional[Dict[str, Any]]:
        try:
            res = self.http.post(self.API_URL, json={"query": self.QUERY, "variables": {"id": anilist_id}})
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


def validate_anime_json_schema(data: Dict[str, Any]) -> bool:
    required_keys = ["schema_version", "anilist_id", "title", "updated_at", "episodes"]
    return all(k in data for k in required_keys) and isinstance(data["episodes"], list)


def safe_filename(title: str, anilist_id: int) -> str:
    cleaned = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    return f"{cleaned}_{anilist_id}.json"


# ---------------------------------------------------------------------------
# Scraping Task
# ---------------------------------------------------------------------------
def process_single_anime(anime_config: dict, existing_data_str: str, settings: dict) -> tuple:
    http_client = HttpClient(timeout=settings.get("scraping", {}).get("request_timeout_seconds", 15))
    anilist = AniListClient(http_client)

    resolvers = [
        VidmolyResolver(http_client),
        FilesForeverResolver(http_client),
        AbyssPlayerResolver(http_client),
        P2PPlayResolver(http_client)
    ]
    scrapers = [DesiDubAnimeScraper(http_client, resolvers)]

    anilist_id = anime_config["anilist_id"]
    print(f"[*] Resolving metadata for AniList ID: {anilist_id}")
    meta = anilist.get_anime_by_id(anilist_id)

    if not meta:
        http_client.close()
        raise RuntimeError(f"Could not retrieve AniList metadata for ID {anilist_id}")

    canonical_title = meta["title"]["english"] or meta["title"]["romaji"]
    file_name = safe_filename(canonical_title, anilist_id)

    # Load existing file state if present to preserve old links
    existing_eps = {}
    if existing_data_str:
        try:
            raw_json = json.loads(existing_data_str)
            for ep in raw_json.get("episodes", []):
                existing_eps[ep["episode_number"]] = ep
        except Exception:
            pass

    collected_episodes = []

    for scraper in scrapers:
        print(f"[*] Searching '{canonical_title}' on {scraper.source_name}...")
        matched_url = scraper.search_anime(canonical_title)
        if not matched_url and meta["title"]["romaji"]:
            matched_url = scraper.search_anime(meta["title"]["romaji"])

        if not matched_url:
            print(f"[SOURCE] No match on {scraper.source_name} for '{canonical_title}'")
            continue

        print(f"[SOURCE] Found match: {matched_url}")
        episodes = scraper.get_episodes(matched_url)
        max_ep = settings.get("scraping", {}).get("max_episodes_per_anime", 10)

        for ep in episodes[:max_ep]:
            ep_num = ep["episode_number"]
            embeds = scraper.extract_embeds(ep["episode_url"])

            stream_list = []
            download_list = []

            for embed in embeds:
                resolved = scraper.resolve_stream(embed)
                if not resolved:
                    continue

                for st in resolved.get("stream_urls", []):
                    is_valid = True
                    if settings.get("verification", {}).get("verify_links", True):
                        is_valid = http_client.check_url(st["url"])

                    if is_valid:
                        st["collected_at"] = datetime.now(timezone.utc).isoformat()
                        st["last_checked_at"] = datetime.now(timezone.utc).isoformat()
                        st["status"] = "reachable"
                        stream_list.append(st)

                for dl in resolved.get("download_urls", []):
                    dl["collected_at"] = datetime.now(timezone.utc).isoformat()
                    dl["status"] = "reachable"
                    download_list.append(dl)

            if stream_list or download_list:
                collected_episodes.append({
                    "episode_number": ep_num,
                    "episode_title": ep.get("title", f"Episode {ep_num}"),
                    "sources": [{
                        "source_id": scraper.source_id,
                        "source_name": scraper.source_name,
                        "stream_urls": stream_list,
                        "download_urls": download_list,
                        "subtitles": []
                    }]
                })

            time.sleep(settings.get("scraping", {}).get("request_delay_seconds", 1.0))

    # Merge fresh episodes over cached history
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

    http_client.close()

    if validate_anime_json_schema(payload):
        return file_name, json.dumps(payload, indent=2, ensure_ascii=False)
    raise ValueError(f"Payload validation failed for {canonical_title}")


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------
def main():
    start_time = time.time()

    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")

    if not gist_token or not gist_id:
        print("[CRITICAL] Missing GIST_TOKEN or GIST_ID. Exiting.")
        sys.exit(1)

    # Load configuration
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

    print("[INFO] Starting Scraping Pool (max_workers=3)...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                process_single_anime,
                anime,
                existing_files.get(safe_filename(anime.get("title", ""), anime["anilist_id"]), ""),
                settings
            ): anime
            for anime in anime_queue
        }

        for future in concurrent.futures.as_completed(futures):
            anime_entry = futures[future]
            try:
                filename, json_data = future.result()
                files_to_update[filename] = json_data
                success_count += 1
            except Exception as exc:
                print(f"[ERROR] Task failed for {anime_entry.get('title', 'Unknown ID: ' + str(anime_entry.get('anilist_id')))}: {exc}")

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
    main()
