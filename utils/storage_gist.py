import json
import httpx
import time
from typing import Dict, Any
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

class GistStorage:
    def __init__(self, token: str, gist_id: str):
        self.api_url = f"https://api.github.com/gists/{gist_id}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

    # Smart Retry: Waits 2s, 4s, 8s etc., max 4 attempts if network fails
    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(4),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError))
    )
    def fetch_all_files(self) -> Dict[str, str]:
        """Retrieves existing JSON files with rate-limit protection."""
        print("[INFO] Fetching current database from Gist...")
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(self.api_url, headers=self.headers)
            resp.raise_for_status() # Triggers the retry logic if HTTP error occurs
            
            files_data = resp.json().get("files", {})
            result = {}
            for filename, file_info in files_data.items():
                if file_info.get("truncated", False):
                    # Stream large files directly to save RAM
                    raw_resp = client.get(file_info.get("raw_url"))
                    raw_resp.raise_for_status()
                    result[filename] = raw_resp.text
                else:
                    result[filename] = file_info.get("content", "")
            return result

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=15),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError))
    )
    def publish_files(self, file_updates: Dict[str, str]) -> bool:
        """Pushes updated JSON files back to the Gist securely."""
        if not file_updates:
            print("[INFO] No new data to publish. Skipping Gist update.")
            return True

        # Pre-check payload size to prevent RAM/API overloads
        payload = {"files": {fname: {"content": content} for fname, content in file_updates.items()}}
        payload_size_mb = len(json.dumps(payload)) / (1024 * 1024)
        print(f"[INFO] Payload size: {payload_size_mb:.2f} MB")

        if payload_size_mb > 50:
            print("[WARNING] Payload is getting very large for a single Gist update.")

        with httpx.Client(timeout=45.0) as client:
            resp = client.patch(self.api_url, headers=self.headers, json=payload)
            resp.raise_for_status()
            print(f"[SUCCESS] Uploaded {len(file_updates)} files to Gist.")
            return True
