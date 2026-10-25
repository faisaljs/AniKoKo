import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_VERSION = "1.1.0"

HOST = os.getenv("ANIKOKO_HOST", "0.0.0.0")
PORT = int(os.getenv("ANIKOKO_PORT", "8000"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20.0

# Cache TTLs (seconds)
CACHE_TTL_LIST = 300
CACHE_TTL_DETAIL = 600
CACHE_TTL_STREAM = 900

# Bounded LRU — max entries in the in-memory cache
CACHE_MAX_ENTRIES = int(os.getenv("ANIKOKO_CACHE_MAX", "1024"))

# Proxy retry policy for upstream flapping
PROXY_RETRIES = int(os.getenv("ANIKOKO_PROXY_RETRIES", "2"))
PROXY_RETRY_BACKOFF = 0.6  # base seconds, exponential

PROVIDERS = {
    "desidubanime": {
        "name": "DesiDubAnime",
        "base": "https://www.desidubanime.me",
        "lang": "Hindi",
    },
}

SCRAPE_PROXY = os.getenv("ANIKOKO_SCRAPE_PROXY")  # "http://user:pass@host:port"

# CORS — allow any origin so external frontends can consume the API.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ANIKOKO_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
