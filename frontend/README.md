# AniKoKo — Frontend

Single-page client. Zero build step. Three files: `index.html`, `styles.css`, `app.js`.

## Run

```bash
python3 -m http.server 5500
```

Then open `http://localhost:5500`.

## Configuration

The API base URL is set by a `<meta>` tag in `index.html`:

```html
<meta name="anikoko-api" content="http://localhost:8000" />
```

Change it to point at a remote API. If the page is served from port 8000 itself, the client auto-detects it.

## Features

- Latest feed with "load more"
- Search (alias + fuzzy handled server-side)
- Series detail: poster, synopsis, episode list
- Watch modal: source switcher, iframe for embeds, native `<video>`+HLS.js for direct streams
- Watch history — Continue Watching row from `localStorage`
- Deep links — `#q=…`, `#anime=…&provider=…`
- Responsive — mobile-first modal goes full-screen under 720px