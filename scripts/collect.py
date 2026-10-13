import os
import sys
import json
import time
from datetime import datetime, timezone
import concurrent.futures

# Crucial import path fix for GitHub Actions
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.http_client import HttpClient
from utils.anilist import AniListClient
from utils.storage_gist import GistStorage
from utils.validator import validate_anime_json_schema
from scrapers.desidubanime import DesiDubAnimeScraper
from resolvers.vidmoly import VidmolyResolver
from resolvers.filesforever import FilesForeverResolver
from resolvers.abyssplayer import AbyssPlayerResolver
from resolvers.p2pplay import P2PPlayResolver

def safe_filename(title: str, anilist_id: int) -> str:
    cleaned = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    return f"{cleaned}_{anilist_id}.json"

def process_single_anime(anime_config: dict, existing_data_str: str, settings: dict) -> tuple:
    """
    Executes the full scraping process for a single anime.
    """
    http_client = HttpClient(timeout=15)
    anilist = AniListClient(http_client)
    
    resolvers = [
        VidmolyResolver(http_client),
        FilesForeverResolver(http_client),
        AbyssPlayerResolver(http_client),
        P2PPlayResolver(http_client)
    ]
    scrapers = [DesiDubAnimeScraper(http_client, resolvers)]
    
    anilist_id = anime_config["anilist_id"]
    print(f"[*] Fetching metadata for AniList ID: {anilist_id}...")
    
    meta = anilist.get_anime_by_id(anilist_id)
    if not meta:
        print(f"[WARN] Could not retrieve AniList metadata for ID {anilist_id}. Skipping.")
        http_client.close()
        raise Exception("Metadata retrieval failed")

    canonical_title = meta["title"]["english"] or meta["title"]["romaji"]
    file_name = safe_filename(canonical_title, anilist_id)
    
    # Load existing data if available
    existing_anime_data = None
    if existing_data_str:
        try:
            existing_anime_data = json.loads(existing_data_str)
        except Exception:
            pass

    collected_episodes = []
    
    for scraper in scrapers:
        print(f"[*] Searching for '{canonical_title}' on {scraper.source_name}...")
        matched_url = scraper.search_anime(canonical_title)
        
        # Fallback to Romaji title if English fails
        if not matched_url and meta["title"]["romaji"]:
            matched_url = scraper.search_anime(meta["title"]["romaji"])

        if not matched_url:
            print(f"[SOURCE] No match found on {scraper.source_name} for {canonical_title}")
            continue

        print(f"[SOURCE] Match found! Extracting episodes from: {matched_url}")
        episodes = scraper.get_episodes(matched_url)
        
        max_ep = settings.get("scraping", {}).get("max_episodes_per_anime", 10)
        
        for ep in episodes[:max_ep]:
            ep_num = ep["episode_number"]
            embeds = scraper.extract_embeds(ep["episode_url"])
            
            stream_list = []
            download_list = []
            
            for embed in embeds:
                res_data = scraper.resolve_stream(embed)
                if res_data:
                    for st in res_data.get("stream_urls", []):
                        # Link verification
                        is_valid = True
                        if settings.get("verification", {}).get("verify_links", True):
                            is_valid = http_client.check_url(st["url"])
                        
                        if is_valid:
                            st["collected_at"] = datetime.now(timezone.utc).isoformat()
                            st["last_checked_at"] = datetime.now(timezone.utc).isoformat()
                            st["status"] = "reachable"
                            stream_list.append(st)

                    for dl in res_data.get("download_urls", []):
                        dl["collected_at"] = datetime.now(timezone.utc).isoformat()
                        dl["status"] = "reachable"
                        download_list.append(dl)

            if stream_list or download_list:
                collected_episodes.append({
                    "episode_number": ep_num,
                    "episode_title": ep["title"],
                    "sources": [{
                        "source_id": scraper.source_id,
                        "source_name": scraper.source_name,
                        "stream_urls": stream_list,
                        "download_urls": download_list,
                        "subtitles": []
                    }]
                })
            
            # Be polite to the source servers
            time.sleep(settings.get("scraping", {}).get("request_delay_seconds", 1.5))

    new_payload = {
        "schema_version": 1,
        "anilist_id": anilist_id,
        "title": meta["title"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "episodes": collected_episodes
    }

    # Minimal merging logic (replaces old payload if schema is valid)
    if validate_anime_json_schema(new_payload):
        http_client.close()
        return file_name, json.dumps(new_payload, indent=2, ensure_ascii=False)
    else:
        http_client.close()
        raise Exception("Generated JSON failed schema validation")

def main():
    start_time = time.time()
    
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")

    if not gist_token or not gist_id:
        print("[CRITICAL] Missing GIST_TOKEN or GIST_ID. Exiting.")
        sys.exit(1)

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    # Load Settings
    with open(os.path.join(base_dir, "config", "settings.json"), "r") as f:
        settings = json.load(f)

    # Load Watchlist
    with open(os.path.join(base_dir, "config", "anime.json"), "r") as f:
        anime_config = json.load(f)

    anime_queue = [a for a in anime_config.get("anime", []) if a.get("enabled", True)]
    
    print(f"[INFO] Loaded {len(anime_queue)} active anime from config/anime.json")

    gist = GistStorage(gist_token, gist_id)
    try:
        existing_files = gist.fetch_all_files()
    except Exception as e:
        print(f"[CRITICAL] Could not fetch base data: {e}")
        sys.exit(1)

    files_to_update = {}
    success_count = 0

    print("[INFO] Starting Scraping Engine...")
    
    # Process scraping concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_anime = {
            executor.submit(
                process_single_anime, 
                anime, 
                existing_files.get(safe_filename(anime.get("title", ""), anime["anilist_id"]), ""),
                settings
            ): anime 
            for anime in anime_queue
        }
        
        for future in concurrent.futures.as_completed(future_to_anime):
            anime = future_to_anime[future]
            try:
                filename, json_content = future.result()
                files_to_update[filename] = json_content
                success_count += 1
            except Exception as exc:
                print(f"[ERROR] Failed processing {anime.get('title', 'Unknown')}: {exc}")

    # Generate Index
    files_to_update["index.json"] = json.dumps({
        "last_run": datetime.now(timezone.utc).isoformat(),
        "total_anime_processed": success_count,
        "execution_time_seconds": round(time.time() - start_time, 2)
    }, indent=2)

    # Publish
    try:
        gist.publish_files(files_to_update)
    except Exception as e:
        print(f"[CRITICAL] Gist publish failed: {e}")
        sys.exit(1)

    print(f"[INFO] Script finished cleanly in {round(time.time() - start_time, 2)} seconds.")

if __name__ == "__main__":
    main()
