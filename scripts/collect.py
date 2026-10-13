import os
import json
import sys
import time
from datetime import datetime, timezone
import concurrent.futures

# Assuming storage_gist.py is in the utils folder
from utils.storage_gist import GistStorage

# Example configurations
ANIME_WATCHLIST = [
    {"id": 16498, "title": "Attack on Titan"},
    {"id": 21, "title": "One Piece"}
]

def process_single_anime(anime: dict, existing_data: str) -> tuple:
    """
    Isolated function to scrape a single anime.
    Running this in isolation helps the Garbage Collector free up RAM.
    Returns: (filename, json_string)
    """
    anime_id = anime["id"]
    filename = f"{anime['title'].replace(' ', '_')}_{anime_id}.json"
    
    print(f"[*] Processing {anime['title']}...")
    
    # -> INSERT SCRAPING LOGIC HERE <-
    # Simulate a time-consuming scrape
    time.sleep(2) 
    
    # Merge logic would go here. For now, we simulate new data:
    scraped_data = {
        "anilist_id": anime_id,
        "title": anime["title"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "episodes": [{"episode_number": 1, "sources": []}]
    }
    
    # Serialize to string immediately so we don't hold large dictionaries in memory
    return filename, json.dumps(scraped_data, indent=2)

def main():
    start_time = time.time()
    
    # 1. Secure Credentials
    gist_token = os.environ.get("GIST_TOKEN")
    gist_id = os.environ.get("GIST_ID")

    if not gist_token or not gist_id:
        print("[CRITICAL] Missing GIST_TOKEN or GIST_ID. Exiting safely.")
        sys.exit(1)

    # 2. Init Storage & Fetch existing data
    gist = GistStorage(gist_token, gist_id)
    try:
        existing_files = gist.fetch_all_files()
    except Exception as e:
        print(f"[CRITICAL] Could not fetch base data. Aborting to prevent overwrite. Error: {e}")
        sys.exit(1)

    files_to_update = {}
    success_count = 0

    # 3. Smart Bounded Concurrency (Low CPU/RAM footprint)
    # max_workers=3 ensures we don't overwhelm the target website or the GH Runner memory
    print("[INFO] Starting Scraping Engine...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        # Submit all tasks to the thread pool
        future_to_anime = {
            executor.submit(process_single_anime, anime, existing_files.get(f"{anime['title'].replace(' ', '_')}_{anime['id']}.json")): anime 
            for anime in ANIME_WATCHLIST
        }
        
        # Process results as they complete
        for future in concurrent.futures.as_completed(future_to_anime):
            anime = future_to_anime[future]
            try:
                filename, json_content = future.result()
                files_to_update[filename] = json_content
                success_count += 1
            except Exception as exc:
                print(f"[ERROR] Anime {anime['title']} generated an exception: {exc}")

    # 4. Update the Index File
    files_to_update["index.json"] = json.dumps({
        "last_run": datetime.now(timezone.utc).isoformat(),
        "total_anime_processed": success_count,
        "execution_time_seconds": round(time.time() - start_time, 2)
    }, indent=2)

    # 5. Push to Gist
    try:
        gist.publish_files(files_to_update)
    except Exception as e:
        print(f"[CRITICAL] Failed to publish data to Gist: {e}")
        sys.exit(1)

    print(f"[INFO] Script finished cleanly in {round(time.time() - start_time, 2)} seconds.")

if __name__ == "__main__":
    main()
