(() => {
  'use strict';

  // ---------------- config ----------------

  const API_BASE = (() => {
    const meta = document.querySelector('meta[name="anikoko-api"]');
    if (meta && meta.content) return meta.content.replace(/\/$/, '');
    if (location.port === '8000') return location.origin;
    return 'http://localhost:8000';
  })();

  console.log('[AniKoKo] API_BASE =', API_BASE);

  const HLS_CDN = 'https://cdn.jsdelivr.net/npm/hls.js@1.5.15/dist/hls.min.js';
  const HISTORY_KEY = 'anikoko:history:v1';
  const HISTORY_MAX = 30;
  const RESUME_KEY = 'anikoko:resume:v1';
  const RESUME_MAX = 200;
  const SEARCH_DEBOUNCE_MS = 380;
  const SEARCH_MIN_CHARS = 2;

  // ---------------- helpers ----------------

  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const esc = (s) =>
    String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');

  const debounce = (fn, ms) => {
    let t = null;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  };

  const state = {
    view: 'home',
    latestPage: 1,
    latestEnd: false,
    lastAnime: null,
    lastQuery: null,
    searchSeq: 0,
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

  // ---------------- resume playback ----------------

  function readResumeMap() {
    try {
      const raw = localStorage.getItem(RESUME_KEY);
      if (!raw) return {};
      const m = JSON.parse(raw);
      return m && typeof m === 'object' ? m : {};
    } catch { return {}; }
  }

  function writeResumeMap(m) {
    try { localStorage.setItem(RESUME_KEY, JSON.stringify(m)); } catch {}
  }

  function saveResume(url, time) {
    if (!url || !isFinite(time) || time < 3) return;
    const m = readResumeMap();
    m[url] = { t: Math.floor(time), at: Date.now() };
    const keys = Object.keys(m);
    if (keys.length > RESUME_MAX) {
      keys.sort((a, b) => (m[a].at || 0) - (m[b].at || 0));
      for (let i = 0; i < keys.length - RESUME_MAX; i++) delete m[keys[i]];
    }
    writeResumeMap(m);
  }

  function getResume(url) {
    const m = readResumeMap();
    return (m[url] && Number(m[url].t)) || 0;
  }

  // ---------------- api ----------------

  const api = {
    latest: (page = 1) =>
      fetchJson(`${API_BASE}/api/latest?page=${page}`),
    search: (q) =>
      fetchJson(`${API_BASE}/api/search?q=${encodeURIComponent(q)}`),
    anime: (url, provider) =>
      fetchJson(`${API_BASE}/api/anime?url=${encodeURIComponent(url)}&provider=${encodeURIComponent(provider)}`),
    sources: (url, provider) =>
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
      <div class="card" data-url="${esc(item.url)}" data-provider="${esc(item.provider)}" tabindex="0" role="button">
        <div class="thumb">${poster ? `<img loading="lazy" src="${esc(poster)}" alt="">` : ''}</div>
        <div class="meta">
          <h3>${esc(item.title || 'Untitled')}</h3>
          <div class="src">${esc(item.provider || '')}</div>
        </div>
      </div>`;
  }

  function wireCards(root) {
    $$('.card', root).forEach(c => {
      const open = () => openAnime(c.dataset.url, c.dataset.provider);
      c.addEventListener('click', open);
      c.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
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
      const resume = getResume(e.episodeUrl);
      const mm = Math.floor(resume / 60);
      const ss = String(Math.floor(resume % 60)).padStart(2, '0');
      const resumeTag = resume > 3
        ? `<span class="resume-tag">${mm}:${ss}</span>`
        : '';
      return `
        <div class="card continue-card"
             tabindex="0" role="button"
             data-ep-url="${esc(e.episodeUrl)}"
             data-provider="${esc(e.provider)}"
             data-anime-url="${esc(e.animeUrl || '')}"
             data-anime-title="${esc(e.animeTitle || '')}"
             data-ep-title="${esc(e.episodeTitle || '')}"
             data-poster="${esc(e.poster || '')}">
          <div class="thumb">
            ${poster ? `<img loading="lazy" src="${esc(poster)}" alt="">` : ''}
            ${resumeTag}
          </div>
          <div class="meta">
            <h3>${esc(e.animeTitle || 'Untitled')}</h3>
            <div class="src">${esc(e.episodeTitle || '')}</div>
          </div>
        </div>`;
    }).join('');

    $$('.continue-card', grid).forEach(c => {
      const open = () => openWatch(
        c.dataset.epUrl,
        c.dataset.provider,
        c.dataset.animeTitle,
        c.dataset.epTitle,
        c.dataset.animeUrl,
        c.dataset.poster,
      );
      c.addEventListener('click', open);
      c.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
    });
  }

  // ---------------- search ----------------

  async function doSearch(q) {
    q = (q || '').trim();
    if (!q) return;
    state.lastQuery = q;
    showView('search');
    $('#searchTitle').textContent = `Results for "${q}"`;
    $('#searchGrid').innerHTML = skeleton(8);
    $('#searchEmpty').hidden = true;

    const seq = ++state.searchSeq;
    try {
      const data = await api.search(q);
      if (seq !== state.searchSeq) return;   // stale response — a newer search fired
      const items = data.items || [];
      if (!items.length) {
        $('#searchGrid').innerHTML = '';
        $('#searchEmpty').hidden = false;
        return;
      }
      $('#searchGrid').innerHTML = items.map(cardHTML).join('');
      wireCards($('#searchGrid'));
    } catch (e) {
      if (seq !== state.searchSeq) return;
      $('#searchGrid').innerHTML = `<p class="empty">Search failed: ${esc(e.message)}</p>`;
    }
  }

  const debouncedLiveSearch = debounce((q) => {
    if (q.length >= SEARCH_MIN_CHARS) doSearch(q);
  }, SEARCH_DEBOUNCE_MS);

  // ---------------- anime detail ----------------

  async function openAnime(url, provider) {
    state.lastAnime = { url, provider, poster: null };
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
      state.lastAnime.poster = data.poster || null;

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
        return `<button type="button" data-url="${esc(ep.url)}" data-title="${esc(label)}" title="${esc(label)}">${esc(label)}</button>`;
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
  let lastResumeSave = 0;

  async function openWatch(episodeUrl, provider, animeTitle, epTitle, animeUrlOverride, posterOverride) {
    currentEpisodeUrl = episodeUrl;
    currentProvider = provider;
    currentTitle = `${animeTitle || ''} — ${epTitle || ''}`.trim();
    currentAnimeTitle = animeTitle;
    currentAnimeUrl = animeUrlOverride || (state.lastAnime ? state.lastAnime.url : null);
    currentPoster = posterOverride || (state.lastAnime ? state.lastAnime.poster : null) || null;

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
        poster: currentPoster,      // raw URL, not proxied
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
    // best-effort save of resume position before we wipe the player
    const v = document.getElementById('__player');
    if (v && currentEpisodeUrl) saveResume(currentEpisodeUrl, v.currentTime);
    $('#playerHost').innerHTML = '';
    $('#watchModal').hidden = true;
    document.body.style.overflow = '';
    currentEpisodeUrl = null;
  }

  async function ensureHlsLib() {
    if (window.Hls) return window.Hls;
    await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = HLS_CDN;
      s.onload = resolve;
      s.onerror = () => reject(new Error('hls.js load failed'));
      document.head.appendChild(s);
    });
    return window.Hls;
  }

  // ---------------- source ranking ----------------

  const KIND_RANK = { mp4: 0, hls: 1, embed: 2 };

  function qualityScore(q) {
    const s = String(q || '');
    const m = s.match(/(\d{3,4})/);
    if (m) return parseInt(m[1], 10);
    if (s.toLowerCase() === 'auto') return 1080;   // auto = master playlist, treat as best
    return 0;
  }

  function sourceRank(s) {
    const k = KIND_RANK[s.kind] ?? 9;
    return k * 100000 - qualityScore(s.quality);
  }

  // ---------------- player ----------------

  function wireResumeHooks(video, episodeUrl) {
    video.addEventListener('loadedmetadata', () => {
      const r = getResume(episodeUrl);
      if (r > 3 && (!isFinite(video.duration) || r < video.duration - 5)) {
        try { video.currentTime = r; } catch {}
      }
    });
    video.addEventListener('timeupdate', () => {
      const now = Date.now();
      if (now - lastResumeSave > 5000) {
        saveResume(episodeUrl, video.currentTime);
        lastResumeSave = now;
      }
    });
    video.addEventListener('pause', () => saveResume(episodeUrl, video.currentTime));
    video.addEventListener('ended', () => saveResume(episodeUrl, 0));
  }

  function renderSources(sources, episodeUrl) {
    const host = $('#playerHost');
    const fallback = $('#playerFallback');
    const list = $('#sourceList');
    const dlRow = $('#downloadRow');

    sources.sort((a, b) => sourceRank(a) - sourceRank(b));

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

      if (source.kind === 'mp4') {
        host.innerHTML = `<video id="__player" controls playsinline autoplay
          style="width:100%;height:100%;background:#000;display:block"></video>`;
        const v = document.getElementById('__player');
        wireResumeHooks(v, episodeUrl);
        v.src = proxied;
        v.load();
        v.play().catch(() => {});
        return;
      }

      // hls
      host.innerHTML = `<video id="__player" controls playsinline autoplay
        style="width:100%;height:100%;background:#000;display:block"></video>`;
      const v = document.getElementById('__player');
      wireResumeHooks(v, episodeUrl);

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
      btn.type = 'button';
      const label = s.quality && s.quality !== 'auto' ? `${s.quality}` : `${s.kind.toUpperCase()}`;
      btn.textContent = label;
      btn.title = `${s.kind}${s.quality && s.quality !== 'auto' ? ' · ' + s.quality : ''}`;
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

  function skeleton(n, h = 0) {
    let out = '';
    for (let i = 0; i < n; i++) {
      out += h
        ? `<div style="height:${h}px;border-radius:12px;background:#161a20;border:1px solid #232a33"></div>`
        : `<div class="card skeleton">
             <div class="thumb"></div>
             <div class="meta"><h3></h3><div class="src"></div></div>
           </div>`;
    }
    return out;
  }

  // ---------------- bootstrap ----------------

  document.addEventListener('DOMContentLoaded', () => {
    // nav
    $$('[data-nav="home"]').forEach(el =>
      el.addEventListener('click', e => { e.preventDefault(); showView('home'); })
    );

    // search — submit is immediate, typing debounces
    const searchInput = $('#searchInput');
    $('#searchForm').addEventListener('submit', e => {
      e.preventDefault();
      const q = searchInput.value.trim();
      if (q) doSearch(q);
    });
    searchInput.addEventListener('input', () => {
      debouncedLiveSearch(searchInput.value.trim());
    });

    // back
    $('#animeBack').addEventListener('click', () => {
      if (state.lastQuery) doSearch(state.lastQuery);
      else showView('home');
    });

    // load more
    $('#loadMoreBtn').addEventListener('click', () => {
      if (state.latestEnd) return;
      state.latestPage += 1;
      loadLatest(true);
    });

    // history
    const clearBtn = $('#clearHistory');
    if (clearBtn) clearBtn.addEventListener('click', clearHistory);

    // modal
    $('#watchClose').addEventListener('click', closeWatch);
    $('#modalBg').addEventListener('click', closeWatch);

    // keyboard
    document.addEventListener('keydown', e => {
      const t = document.activeElement && document.activeElement.tagName;
      const typing = t === 'INPUT' || t === 'TEXTAREA';
      if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        searchInput.focus();
      }
      if (e.key === 'Escape' && !$('#watchModal').hidden) closeWatch();
    });

    // save resume on tab close
    window.addEventListener('beforeunload', () => {
      const v = document.getElementById('__player');
      if (v && currentEpisodeUrl && !v.paused) {
        saveResume(currentEpisodeUrl, v.currentTime);
      }
    });

    // deep link
    const h = location.hash.replace(/^#/, '');
    if (h) {
      const params = new URLSearchParams(h);
      const q = params.get('q');
      const anime = params.get('anime');
      const provider = params.get('provider');
      if (anime && provider) { openAnime(anime, provider); return; }
      if (q) { searchInput.value = q; doSearch(q); return; }
    }

    renderContinue();
    loadLatest();
  });
})();