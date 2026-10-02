(() => {
  'use strict';

  const API_BASE = (() => {
    const meta = document.querySelector('meta[name="anikoko-api"]');
    if (meta && meta.content) return meta.content.replace(/\/$/, '');
    if (location.port === '8000') return location.origin;
    return 'http://localhost:8000';
  })();

  console.log('[AniKoKo] API_BASE =', API_BASE);

  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) =>
    String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const HISTORY_KEY = 'anikoko:history:v1';
  const HISTORY_MAX = 30;

  const state = {
    view: 'home',
    latestPage: 1,
    latestEnd: false,
    lastAnime: null,
    lastQuery: null,
  };

  // ---------------- history ----------------

  function readHistory() {
    try {
      const raw = localStorage.getItem(HISTORY_KEY);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch { return []; }
  }

  function writeHistory(arr) {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(arr.slice(0, HISTORY_MAX))); } catch {}
  }

  function recordWatch(entry) {
    const arr = readHistory().filter(e => e.episodeUrl !== entry.episodeUrl);
    arr.unshift({ ...entry, t: Date.now() });
    writeHistory(arr);
    renderContinue();
  }

  function clearHistory() {
    writeHistory([]);
    renderContinue();
  }

  // ---------------- api ----------------

  const api = {
    latest: (page = 1) => fetchJson(`${API_BASE}/api/latest?page=${page}`),
    search: (q) => fetchJson(`${API_BASE}/api/search?q=${encodeURIComponent(q)}`),
    anime:  (url, provider) =>
      fetchJson(`${API_BASE}/api/anime?url=${encodeURIComponent(url)}&provider=${encodeURIComponent(provider)}`),
    sources:(url, provider) =>
      fetchJson(`${API_BASE}/api/sources?url=${encodeURIComponent(url)}&provider=${encodeURIComponent(provider)}`),
    proxyImg: (url, referer) => {
      let u = `${API_BASE}/proxy/img?url=${encodeURIComponent(url)}`;
      if (referer) u += `&referer=${encodeURIComponent(referer)}`;
      return u;
    },
  };

  async function fetchJson(url) {
    let r;
    try { r = await fetch(url); }
    catch (e) { throw new Error(`Network error: ${e.message}`); }
    const text = await r.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch {}
    if (!r.ok) {
      const msg = (data && (data.error || data.hint || data.detail)) || `${r.status} ${r.statusText}`;
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    if (data == null) throw new Error('Empty or non-JSON response');
    return data;
  }

  // ---------------- view ----------------

  function showView(name) {
    state.view = name;
    $$('.view').forEach(v => { v.hidden = true; });
    const el = document.getElementById(`view-${name}`);
    if (el) el.hidden = false;
    window.scrollTo({ top: 0, behavior: 'instant' });
    updateUrl();
  }

  function updateUrl() {
    const parts = [];
    if (state.view === 'search' && state.lastQuery) parts.push(`q=${encodeURIComponent(state.lastQuery)}`);
    if (state.view === 'anime' && state.lastAnime) {
      parts.push(`anime=${encodeURIComponent(state.lastAnime.url)}`);
      parts.push(`provider=${encodeURIComponent(state.lastAnime.provider)}`);
    }
    const hash = parts.length ? `#${parts.join('&')}` : '';
    history.replaceState(null, '', location.pathname + hash);
  }

  // ---------------- cards ----------------

  function cardHTML(item) {
    const poster = item.poster ? api.proxyImg(item.poster, item.url) : '';
    return `
      <div class="card" data-url="${esc(item.url)}" data-provider="${esc(item.provider)}">
        <div class="thumb">${poster ? `<img loading="lazy" src="${esc(poster)}" alt="">` : ''}</div>
        <div class="meta">
          <h3>${esc(item.title || 'Untitled')}</h3>
          <div class="src">${esc(item.provider || '')}</div>
        </div>
      </div>`;
  }

  function wireCards(root) {
    $$('.card', root).forEach(c => {
      c.addEventListener('click', (e) => {
        e.preventDefault();
        openAnime(c.dataset.url, c.dataset.provider);
      });
    });
  }

  // ---------------- home ----------------

  async function loadLatest(append = false) {
    const grid = $('#latestGrid');
    const btn = $('#loadMoreBtn');
    if (!append) {
      state.latestPage = 1;
      state.latestEnd = false;
      grid.innerHTML = skeleton(8);
    }
    btn.disabled = true;
    btn.textContent = 'Loading…';
    try {
      const data = await api.latest(state.latestPage);
      const items = data.items || [];
      const html = items.map(cardHTML).join('');
      if (append) grid.insertAdjacentHTML('beforeend', html);
      else grid.innerHTML = html || '<p class="empty">No items.</p>';
      wireCards(grid);
      if (items.length < 24) {
        state.latestEnd = true;
        btn.textContent = 'No more';
        btn.disabled = true;
      } else {
        btn.textContent = 'Load more';
        btn.disabled = false;
      }
    } catch (e) {
      grid.innerHTML = `<p class="empty">Failed to load: ${esc(e.message)}</p>`;
      btn.textContent = 'Retry';
      btn.disabled = false;
    }
  }

  function renderContinue() {
    const wrap = $('#continueSection');
    if (!wrap) return;
    const grid = $('#continueGrid');
    const arr = readHistory();
    if (!arr.length) {
      wrap.hidden = true;
      grid.innerHTML = '';
      return;
    }
    wrap.hidden = false;
    grid.innerHTML = arr.slice(0, 12).map(e => {
      const poster = e.poster ? api.proxyImg(e.poster, e.animeUrl) : '';
      return `
        <div class="card continue-card"
             data-ep-url="${esc(e.episodeUrl)}"
             data-provider="${esc(e.provider)}"
             data-anime-url="${esc(e.animeUrl)}"
             data-anime-title="${esc(e.animeTitle || '')}"
             data-ep-title="${esc(e.episodeTitle || '')}">
          <div class="thumb">${poster ? `<img loading="lazy" src="${esc(poster)}" alt="">` : ''}</div>
          <div class="meta">
            <h3>${esc(e.animeTitle || 'Untitled')}</h3>
            <div class="src">${esc(e.episodeTitle || '')}</div>
          </div>
        </div>`;
    }).join('');

    $$('.continue-card', grid).forEach(c => {
      c.addEventListener('click', () => {
        openWatch(
          c.dataset.epUrl,
          c.dataset.provider,
          c.dataset.animeTitle,
          c.dataset.epTitle,
        );
      });
    });
  }

  // ---------------- search ----------------

  async function doSearch(q) {
    q = (q || '').trim();
    if (!q) return;
    state.lastQuery = q;
    showView('search');
    $('#searchTitle').textContent = `Results for “${q}”`;
    $('#searchGrid').innerHTML = skeleton(8);
    $('#searchEmpty').hidden = true;
    try {
      const data = await api.search(q);
      const items = data.items || [];
      if (!items.length) {
        $('#searchGrid').innerHTML = '';
        $('#searchEmpty').hidden = false;
        return;
      }
      $('#searchGrid').innerHTML = items.map(cardHTML).join('');
      wireCards($('#searchGrid'));
    } catch (e) {
      $('#searchGrid').innerHTML = `<p class="empty">Search failed: ${esc(e.message)}</p>`;
    }
  }

  // ---------------- anime detail ----------------

  async function openAnime(url, provider) {
    state.lastAnime = { url, provider };
    showView('anime');

    const dTitle  = $('#dTitle');
    const dPoster = $('#dPoster');
    const dSyn    = $('#dSyn');
    const dProv   = $('#dProvider');
    const epList  = $('#epList');
    const epCount = $('#epCount');

    dTitle.textContent = 'Loading…';
    dPoster.removeAttribute('src');
    dSyn.textContent = '';
    dProv.textContent = provider || '';
    epCount.textContent = '';
    epList.innerHTML = '<p class="empty">Loading episodes…</p>';

    try {
      const data = await api.anime(url, provider);
      dTitle.textContent = data.title || 'Unknown';
      dProv.textContent = data.provider || provider;
      if (data.poster) {
        dPoster.onerror = () => { dPoster.removeAttribute('src'); };
        dPoster.src = api.proxyImg(data.poster, url);
      }
      dSyn.textContent = data.synopsis || '(no synopsis)';

      const eps = (data.episodes || []).filter(ep =>
        ep && ep.url && /^https?:\/\//i.test(ep.url)
      );
      epCount.textContent = eps.length ? `${eps.length} episodes` : '';
      if (!eps.length) {
        epList.innerHTML = '<p class="empty">No episodes detected.</p>';
        return;
      }
      epList.innerHTML = eps.map(ep => {
        const label = ep.title || (ep.number ? `Episode ${ep.number}` : 'Episode');
        return `<button data-url="${esc(ep.url)}" data-title="${esc(label)}" title="${esc(label)}">${esc(label)}</button>`;
      }).join('');
      $$('#epList button').forEach(b => {
        b.addEventListener('click', () =>
          openWatch(b.dataset.url, provider, data.title || '', b.dataset.title || '')
        );
      });
    } catch (e) {
      dTitle.textContent = 'Failed to load';
      dSyn.textContent = e.message || String(e);
      epList.innerHTML = '';
    }
  }

  // ---------------- watch modal ----------------

  let currentEpisodeUrl = null;
  let currentProvider = null;
  let currentTitle = null;
  let currentAnimeUrl = null;
  let currentAnimeTitle = null;
  let currentPoster = null;
  let currentHls = null;

  async function openWatch(episodeUrl, provider, animeTitle, epTitle) {
    currentEpisodeUrl = episodeUrl;
    currentProvider = provider;
    currentTitle = `${animeTitle || ''} — ${epTitle || ''}`.trim();
    currentAnimeTitle = animeTitle;
    currentAnimeUrl = state.lastAnime ? state.lastAnime.url : null;
    currentPoster = ($('#dPoster') && $('#dPoster').src) ? $('#dPoster').src : null;

    $('#wTitle').textContent = currentTitle || 'Now playing';
    $('#wProvider').textContent = provider;
    $('#playerHost').innerHTML = '<div class="player-fallback">Loading sources…</div>';
    $('#playerFallback').hidden = true;
    $('#sourceList').innerHTML = '';
    $('#downloadRow').innerHTML = '';
    $('#watchModal').hidden = false;
    document.body.style.overflow = 'hidden';

    if (currentAnimeUrl) {
      recordWatch({
        animeUrl: currentAnimeUrl,
        animeTitle,
        poster: currentPoster,
        provider,
        episodeUrl,
        episodeTitle: epTitle,
      });
    }

    try {
      const data = await api.sources(episodeUrl, provider);
      const sources = data.sources || [];
      if (!sources.length) {
        showFallback('No sources found for this episode.');
        return;
      }
      renderSources(sources, episodeUrl);
    } catch (e) {
      showFallback(e.message || 'Failed to load sources.');
    }
  }

  function showFallback(msg) {
    teardownHls();
    $('#playerHost').innerHTML = '';
    const fb = $('#playerFallback');
    fb.hidden = false;
    fb.innerHTML = `<p>${esc(msg)}</p>`;
  }

  function teardownHls() {
    if (currentHls) {
      try { currentHls.destroy(); } catch {}
      currentHls = null;
    }
  }

  function closeWatch() {
    teardownHls();
    $('#playerHost').innerHTML = '';
    $('#watchModal').hidden = true;
    document.body.style.overflow = '';
    currentEpisodeUrl = null;
  }

  async function ensureHlsLib() {
    if (window.Hls) {
      console.log('[AniKoKo] hls.js already loaded', window.Hls.version);
      return window.Hls;
    }
    console.log('[AniKoKo] loading hls.js from jsdelivr…');
    await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/hls.js@1.5.15/dist/hls.min.js';
      s.onload = () => {
        console.log('[AniKoKo] hls.js loaded', window.Hls && window.Hls.version);
        resolve();
      };
      s.onerror = (e) => {
        console.error('[AniKoKo] hls.js load failed', e);
        reject(new Error('hls.js load failed'));
      };
      document.head.appendChild(s);
    });
    return window.Hls;
  }

  function renderSources(sources, episodeUrl) {
    const host = $('#playerHost');
    const fallback = $('#playerFallback');
    const list = $('#sourceList');
    const dlRow = $('#downloadRow');

    const rank = { mp4: 0, hls: 1, embed: 2 };
    sources.sort((a, b) => (rank[a.kind] ?? 9) - (rank[b.kind] ?? 9));

    const play = async (source, btn) => {
      $$('#sourceList button').forEach(b => b.classList.remove('active'));
      if (btn) btn.classList.add('active');
      fallback.hidden = true;
      teardownHls();

      if (source.kind === 'embed') {
        host.innerHTML = `<iframe src="${esc(source.url)}"
          allow="autoplay; fullscreen; encrypted-media; picture-in-picture"
          allowfullscreen referrerpolicy="no-referrer"></iframe>`;
        return;
      }

      const proxied = `${API_BASE}/proxy/stream?url=${encodeURIComponent(source.url)}` +
        (source.referer ? `&referer=${encodeURIComponent(source.referer)}` : '');

      const subs = guessSubtitles(source);

      if (source.kind === 'mp4') {
        host.innerHTML = `<video id="__player" controls playsinline autoplay
          style="width:100%;height:100%;background:#000;display:block">
          ${subs.map(s => `<track kind="subtitles" srclang="en" label="English" src="${esc(s)}" default>`).join('')}
        </video>`;
        const v = document.getElementById('__player');
        v.src = proxied;
        v.load();
        v.play().catch(() => {});
        return;
      }

      // hls
      host.innerHTML = `<video id="__player" controls playsinline autoplay
        style="width:100%;height:100%;background:#000;display:block">
        ${subs.map(s => `<track kind="subtitles" srclang="en" label="English" src="${esc(s)}" default>`).join('')}
      </video>`;
      const v = document.getElementById('__player');

      if (v.canPlayType('application/vnd.apple.mpegurl')) {
        v.src = proxied;
        v.play().catch(() => {});
        return;
      }

      try {
        const Hls = await ensureHlsLib();
        if (!Hls || !Hls.isSupported()) {
          v.src = proxied;
          v.play().catch(() => {});
          return;
        }
        const hls = new Hls({
          lowLatencyMode: false,
          enableWorker: true,
          maxBufferLength: 30,
        });
        hls.loadSource(proxied);
        hls.attachMedia(v);
        hls.on(Hls.Events.MANIFEST_PARSED, () => v.play().catch(() => {}));
        hls.on(Hls.Events.ERROR, (_e, data) => {
          console.error('[AniKoKo] HLS error:', data);
          if (data.fatal) {
            fallback.hidden = false;
            fallback.innerHTML = `<p>HLS playback failed: ${esc(data.details || data.type)}<br><small>${esc(data.reason || '')}</small></p>`;
          }
        });
        currentHls = hls;

        // watchdog — if nothing plays within 10s, show fallback
        const watchdog = setTimeout(() => {
          if (v.readyState < 2 || v.paused) {
            fallback.hidden = false;
            fallback.innerHTML = '<p>Stream taking too long — try another server.</p>';
          }
        }, 10000);
        v.addEventListener('playing', () => clearTimeout(watchdog), { once: true });
        v.addEventListener('loadeddata', () => clearTimeout(watchdog), { once: true });
      } catch (e) {
        console.error('[AniKoKo] HLS setup failed:', e);
        fallback.hidden = false;
        fallback.innerHTML = `<p>${esc(e.message || 'hls.js load failed')}</p>`;
      }
    };

    sources.forEach((s, i) => {
      const btn = document.createElement('button');
      const label = s.quality && s.quality !== 'auto' ? `${s.quality}` : `${s.kind.toUpperCase()}`;
      btn.textContent = label;
      btn.addEventListener('click', () => play(s, btn));
      list.appendChild(btn);
      if (i === 0) play(s, btn);
    });

    sources.filter(s => s.kind === 'mp4' || s.kind === 'hls').forEach(s => {
      const a = document.createElement('a');
      const fname = (currentTitle || 'video').replace(/[^\w\-]+/g, '_').slice(0, 60);
      a.href = `${API_BASE}/proxy/download?url=${encodeURIComponent(s.url)}` +
        `&filename=${encodeURIComponent(fname + '.mp4')}` +
        (s.referer ? `&referer=${encodeURIComponent(s.referer)}` : '');
      a.textContent = `Download ${s.quality && s.quality !== 'auto' ? s.quality : s.kind.toUpperCase()}`;
      a.setAttribute('download', '');
      dlRow.appendChild(a);
    });
  }

  function guessSubtitles(source) {
    try {
      if (source.kind !== 'hls') return [];
      const u = new URL(source.url);
      const m = u.pathname.match(/\/hls2\/([0-9]+)\/([0-9]+)\/([A-Za-z0-9]+)_/);
      if (!m) return [];
      const folder = m[2];
      const slug = m[3];
      return [`https://srt.vidmoly.me/srt/${folder}/${slug}_English.vtt`];
    } catch { return []; }
  }

  function skeleton(n, h = 0) {
    let out = '';
    for (let i = 0; i < n; i++) {
      out += h
        ? `<div style="height:${h}px;border-radius:12px;background:#161a20;border:1px solid #232a33"></div>`
        : `<div class="card" style="pointer-events:none">
             <div class="thumb"></div>
             <div class="meta"><h3></h3><div class="src"></div></div>
           </div>`;
    }
    return out;
  }

  document.addEventListener('DOMContentLoaded', () => {
    $$('[data-nav="home"]').forEach(el =>
      el.addEventListener('click', e => { e.preventDefault(); showView('home'); })
    );
    $('#searchForm').addEventListener('submit', e => {
      e.preventDefault();
      const q = $('#searchInput').value.trim();
      if (q) doSearch(q);
    });
    $('#animeBack').addEventListener('click', () => {
      if (state.lastQuery) doSearch(state.lastQuery);
      else showView('home');
    });
    $('#loadMoreBtn').addEventListener('click', () => {
      if (state.latestEnd) return;
      state.latestPage += 1;
      loadLatest(true);
    });
    const clearBtn = $('#clearHistory');
    if (clearBtn) clearBtn.addEventListener('click', clearHistory);
    $('#watchClose').addEventListener('click', closeWatch);
    $('#modalBg').addEventListener('click', closeWatch);
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && !$('#watchModal').hidden) closeWatch();
    });

    const h = location.hash.replace(/^#/, '');
    if (h) {
      const params = new URLSearchParams(h);
      const q = params.get('q');
      const anime = params.get('anime');
      const provider = params.get('provider');
      if (anime && provider) { openAnime(anime, provider); return; }
      if (q) { $('#searchInput').value = q; doSearch(q); return; }
    }
    renderContinue();
    loadLatest();
  });
})();