# Contributing to AniKoKo

Thanks for wanting to contribute. This is a small project with a narrow scope — a
Hindi-dub anime aggregator — so a few ground rules keep it maintainable.

## What this project is

- **Backend** (`backend/`) — FastAPI service. Scrapes anime metadata and stream
  sources from source sites, normalizes them into one API, proxies media.
- **Frontend** (`frontend/`) — Zero-build single-page client. Plain HTML, CSS,
  and vanilla JavaScript. Talks to the backend over JSON.

No frameworks on the frontend. No ORM, no database. Everything is in-memory or
ephemeral. Keep it that way unless there's a strong reason.

## Getting set up

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python3 main.py
```

### Frontend

```bash
cd frontend
python3 -m http.server 5500
```

Open `http://localhost:5500`.

## Reporting bugs

Open an issue with:

- what you did
- what you expected
- what actually happened
- browser / OS / Python version
- relevant console output (browser DevTools or server terminal)

If a scraper broke because a source site changed its HTML, include the exact
series or episode URL and — if you can — a `curl` output of the page.

## Suggesting features

Open an issue first. Small, focused suggestions are easier to accept than broad
rewrites. If your idea touches more than one subsystem, describe the shape
before writing code.

## Adding a provider

Providers are the main extension point. To add one:

1. **Probe the source site.** Figure out:
   - How to search (`?s=` or a REST endpoint)
   - How to list latest / popular
   - How a series page links to its episodes
   - Where the stream sources live (m3u8? iframe? base64 blob?)

2. **Create `backend/scrapers/<slug>.py`.** Subclass `BaseScraper`:

   ```python
   from scrapers.base import BaseScraper, AnimeCard, Episode, StreamSource
   from config import PROVIDERS

   class MyProviderScraper(BaseScraper):
       slug = "myprovider"
       base = PROVIDERS[slug]["base"]

       async def search(self, query: str) -> list[AnimeCard]: ...
       async def latest(self, page: int = 1) -> list[AnimeCard]: ...
       async def anime_detail(self, url: str) -> dict: ...
       async def episode_sources(self, url: str) -> list[StreamSource]: ...
   ```

3. **Register it** in `backend/scrapers/registry.py` and `backend/config.py`:

   ```python
   # registry.py
   _SCRAPERS = {
       "desidubanime": DesiDubAnimeScraper(),
       "myprovider":   MyProviderScraper(),
   }

   # config.py
   PROVIDERS = {
       "desidubanime": {"name": "DesiDubAnime", "base": "...", "lang": "Hindi"},
       "myprovider":   {"name": "MyProvider",   "base": "...", "lang": "Hindi"},
   }
   ```

4. **Test it** against real URLs before opening a PR. Confirm:
   - `GET /api/latest?provider=myprovider`
   - `GET /api/search?q=some%20title&provider=myprovider`
   - `GET /api/anime?url=<series>&provider=myprovider` → has episodes
   - `GET /api/sources?url=<episode>&provider=myprovider` → has at least one source

## Adding an embed resolver

If a source site uses a third-party player you want to turn into a direct m3u8:

1. Fetch an example embed page and inspect what it returns (raw HTML, JSON,
   base64 blob, packed JS).
2. Create `backend/resolvers/<host>.py` subclassing `BaseResolver`.
3. Register it in `backend/resolvers/__init__.py`.
4. Test with `GET /api/resolve?url=<embed_url>` — it should return
   `{"ok": true, "resolved": "https://.../something.m3u8"}`.

If the resolver needs to execute JavaScript (obfuscated crypto, token derivation),
**don't guess**. Document what you found and leave it as a plain embed — a working
iframe is better than a broken native player.

## Code style

### Python

- 4-space indent
- Type hints on public functions
- Prefer `async`/`await` throughout — this is an I/O-bound service
- No blocking calls in request paths
- Keep imports flat; no lazy imports unless avoiding a cycle

### JavaScript

- 2-space indent
- `const` and `let`, never `var`
- Prefer template literals over concatenation
- Every user-facing string goes through the escape helper before HTML insertion
- No frameworks, no build step — plain DOM APIs

### CSS

- 2-space indent
- CSS custom properties for anything reused
- Mobile-first — the base styles should work at 360px; widen upward
- No `!important` except for the global `[hidden]` rule

## Commit style

Conventional-ish, short, imperative:

```
scraper: handle new episode URL shape on desidubanime
frontend: add keyboard shortcut for search focus
resolver: fix vidmoly m3u8 extraction when folder changes
api: return 404 instead of 500 for unknown provider
```

Prefixes in use: `scraper:`, `resolver:`, `api:`, `frontend:`, `style:`,
`docs:`, `fix:`, `chore:`.

One change per commit. Don't mix a scraper fix with a CSS tweak.

## Pull requests

- Keep PRs focused — one feature or one fix
- Reference the issue it closes: `Closes #12`
- Include a short "what changed" and "how to test" section
- If you touched a scraper, say which URLs you tested against
- Screenshots help for frontend changes

Before submitting:

- `python3 -c "import main"` in `backend/` should not error
- Hard-refresh the frontend and click through the flow you changed
- No new warnings in the browser console

## What we don't want

- **Don't add telemetry.** No analytics, no trackers, no external beacons.
- **Don't add a build step.** The frontend is deliberately three files.
- **Don't gate features behind accounts.** This is a personal tool.
- **Don't rewrite working scrapers "for cleanliness."** Site HTML is fragile;
  the working scraper is the spec.
- **Don't commit `.env`, `venv/`, `__pycache__/`, or anything under `.gitignore`.**
  If a file feels like it shouldn't be tracked, it probably shouldn't.

## Legal note

This project scrapes publicly available pages. Only contribute scrapers for
sources you're comfortable handling personally. Don't add DRM circumvention,
paid-content bypasses, or anything that impersonates a logged-in user.

## Questions

Open an issue. If it's small, ask in the issue itself — no need for a separate
discussion thread.