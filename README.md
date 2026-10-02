# AniKoKo

Hindi-dub anime aggregator. FastAPI backend that scrapes DesiDubAnime via WP REST + HTML, plus a vanilla-JS frontend.

## Layout

```
backend/   — FastAPI scraping + streaming API
frontend/  — Single-page client (HTML + CSS + vanilla JS)
```

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # edit if you need a proxy
python3 main.py
```

API lives at `http://localhost:8000` — docs at `/docs`.

### 2. Frontend

Serve the static files from any HTTP server:

```bash
cd frontend
python3 -m http.server 5500
```

Open `http://localhost:5500`. The frontend talks to `http://localhost:8000` by default. To point it somewhere else, edit the `<meta name="anikoko-api">` tag in `index.html`.

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/latest?provider=&page=1` | Latest additions |
| `GET /api/search?q=&provider=` | Search (alias + fuzzy) |
| `GET /api/anime?url=&provider=` | Series detail + episode list |
| `GET /api/sources?url=&provider=` | Per-episode stream sources |
| `GET /api/resolve?url=` | Debug an embed URL resolver |
| `GET /proxy/stream?url=&referer=` | HLS/MP4 streaming proxy |
| `GET /proxy/download?url=&filename=` | Download proxy |
| `GET /proxy/img?url=&referer=` | Image proxy |

## Provider

- **desidubanime** — `https://www.desidubanime.me` (kiranime WordPress theme)

Adding a provider means:
1. copy `backend/scrapers/desidubanime.py` to a new module
2. update selectors / API shapes for the new site
3. register it in `backend/scrapers/registry.py` and `backend/config.py`

## Notes

- HLS playback uses hls.js on the client (loaded from CDN) with native fallback on Safari.
- Vidmoly sources are intentionally filtered out — CDN is rate-limited and stalls playback.
- Metadata comes from WP REST `/wp-json/wp/v2/anime`; episodes come from HTML because kiranime doesn't expose the series→episode relation via REST.

## License

MIT — see LICENSE.