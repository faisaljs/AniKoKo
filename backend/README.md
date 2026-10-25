# AniKoKo — Backend

FastAPI service. Scrapes DesiDubAnime (kiranime WP theme), normalizes metadata and stream sources, and proxies media.

## Run

Run these commands from the repository root (the directory containing
`requirements.txt`):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp backend/.env.example backend/.env
python3 -m backend.main
```

## Environment

| Var | Default | Notes |
|-----|---------|-------|
| `ANIKOKO_HOST` | `0.0.0.0` | Bind address |
| `ANIKOKO_PORT` | `8000` | Port |
| `ANIKOKO_CORS_ORIGINS` | `*` | Comma-separated allow-list |
| `ANIKOKO_SCRAPE_PROXY` | *(none)* | Optional outbound proxy |

## Files

- `main.py` — FastAPI app, routes, proxies
- `config.py` — settings + provider registry
- `scrapers/` — one module per source; `desidubanime.py` is the reference
- `resolvers/` — per-embed-host m3u8 resolvers
- `utils/` — http, cache, m3u8 helpers

## Adding a provider

```python
# backend/scrapers/myprovider.py
from scrapers.base import BaseScraper, AnimeCard, Episode, StreamSource
from config import PROVIDERS

class MyProviderScraper(BaseScraper):
    slug = "myprovider"
    base = PROVIDERS[slug]["base"]

    async def search(self, query): ...
    async def latest(self, page=1): ...
    async def anime_detail(self, url): ...
    async def episode_sources(self, url): ...
```

Then register:

```python
# backend/scrapers/registry.py
_SCRAPERS = {
    "desidubanime": DesiDubAnimeScraper(),
    "myprovider":   MyProviderScraper(),
}

# backend/config.py
PROVIDERS = {
    "desidubanime": {"name": "DesiDubAnime", "base": "...", "lang": "Hindi"},
    "myprovider":   {"name": "MyProvider",   "base": "...", "lang": "Hindi"},
}
```

Done — the new provider appears in every API endpoint.
