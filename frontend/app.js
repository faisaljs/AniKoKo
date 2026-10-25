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
  const SETTINGS_KEY = 'anikoko:settings:v1';
  const SEARCH_DEBOUNCE_MS = 380;
  const SEARCH_MIN_CHARS = 2;

  const DEFAULT_SETTINGS = { maxQuality: 0, autoplayNext: false };

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
    animeSeq: 0,
    watchSeq: 0,
    searchController: null,
    episodes: [],
    currentEpisodeIndex: -1,
    settings: { ...DEFAULT_SETTINGS },
    activeGenre: null,      // { id: number, name: string } | null
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

  function removeFromHistory(episodeUrl) {
    if (!episodeUrl) return;
    const arr = readHistory().filter(e => e.episodeUrl !== episodeUrl);
    writeHistory(arr);
    renderContinue();
  }

  function clearHistory() {
    writeHistory([]);
    renderContinue();
  }

  // ---------------- resume ----------------

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

  function markCompleted(url) {
    if (!url) return;
    const m = readResumeMap();
    m[url] = { t: 0, completed: true, at: Date.now() };
    writeResumeMap(m);
  }

  function getResume(url) {
    const m = readResumeMap();
    const e = m[url];
    return (e && Number(e.t)) || 0;
  }

  function getEpisodeState(url) {
    const m = readResumeMap();
    const e = m[url];
    if (!e) return 'unwatched';
    if (e.completed) return 'completed';
    if ((e.t || 0) > 3) return 'in-progress';
    return 'unwatched';
  }

  // ---------------- settings ----------------

  function readSettings() {
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      if (!raw) return { ...DEFAULT_SETTINGS };
      const s = JSON.parse(raw);
      return {
        maxQuality: Number(s.maxQuality) || 0,
        autoplayNext: !!s.autoplayNext,
      };
    } catch { return { ...DEFAULT_SETTINGS }; }
  }

  function writeSettings(s) {
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); } catch {}
  }

  // ---------------- api ----------------

  const api = {
    latest: (page = 1, genre = null) => {
      let u = `${API_BASE}/api/latest?page=${page}`;
      if (genre) u += `&genre=${genre}`;
      return fetchJson(u);
    },
    search: (q, signal) =>
      fetchJson(`${API_BASE}/api/search?q=${encodeURIComponent(q)}`, { signal }),
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

  async function fetchJson(url, opts = {}) {
    let r;
    try { r = await fetch(url, opts); }
    catch (e) {
      if (e.name === 'AbortError') throw e;
      throw new Error(`Network error: ${e.message}`);
    }
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
    if (name !== 'anime') state.animeSeq += 1;
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
      const data = await api.latest(state.latestPage, state.activeGenre?.id || null);
      const items = data.items || [];
      const html = items.map(cardHTML).join('');
      if (append) grid.insertAdjacentHTML('beforeend', html);
      else grid.innerHTML = html || '<p class="empty">No items.</p>';
      wireCards(grid);
      // "No more" only fires when a page returns zero items — partial pages
      // are not the end of the list (WP pagination can return 6, 12, etc.)
      if (items.length === 0) {
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
            <button type="button" class="remove-btn"
                    data-ep-url="${esc(e.episodeUrl)}"
                    aria-label="Remove from continue watching"
                    title="Remove">✕</button>
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

    // × buttons — stopPropagation so the card's open handler doesn't fire
    $$('.remove-btn', grid).forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        removeFromHistory(btn.dataset.epUrl);
      });
      btn.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          e.stopPropagation();
          removeFromHistory(btn.dataset.epUrl);
        }
      });
    });
  }

  // ---------------- genres ----------------

  async function loadGenres() {
    const bar = $('#genreBar');
    if (!bar) return;
    try {
      const data = await fetchJson(`${API_BASE}/api/genres`);
      const items = (data.items || []).slice(0, 40);
      if (!items.length) { bar.hidden = true; return; }

      const allChip = document.createElement('button');
      allChip.type = 'button';
      allChip.className = 'genre-chip active';
      allChip.dataset.genre = '';
      allChip.textContent = 'All';
      bar.innerHTML = '';
      bar.appendChild(allChip);

      for (const g of items) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'genre-chip';
        btn.dataset.genre = String(g.id);
        btn.dataset.name = g.name;
        btn.title = `${g.name} · ${g.count}`;
        btn.textContent = g.name;
        bar.appendChild(btn);
      }

      bar.hidden = false;
      $$('.genre-chip', bar).forEach(chip => {
        chip.addEventListener('click', () => selectGenre(chip.dataset.genre || '', chip.dataset.name || 'All'));
      });
    } catch (e) {
      console.warn('[AniKoKo] genres failed:', e);
      bar.hidden = true;
    }
  }

  function selectGenre(idStr, name) {
    const id = idStr ? parseInt(idStr, 10) : null;
    state.activeGenre = id ? { id, name } : null;

    $$('.genre-chip').forEach(b => {
      b.classList.toggle('active', (b.dataset.genre || '') === (idStr || ''));
    });

    const active = $('.genre-chip.active');
    if (active && active.scrollIntoView) {
      active.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    }

    const h = $('#latestHeading');
    if (h) h.textContent = state.activeGenre ? state.activeGenre.name : 'Latest';

    state.latestPage = 1;
    state.latestEnd = false;
    loadLatest(false);
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

    if (state.searchController) {
      try { state.searchController.abort(); } catch {}
    }
    state.searchController = new AbortController();
    const sig = state.searchController.signal;

    const seq = ++state.searchSeq;
    try {
      const data = await api.search(q, sig);
      if (seq !== state.searchSeq) return;
      const items = data.items || [];
      if (!items.length) {
        $('#searchGrid').innerHTML = '';
        $('#searchEmpty').hidden = false;
        return;
      }
      $('#searchGrid').innerHTML = items.map(cardHTML).join('');
      wireCards($('#searchGrid'));
    } catch (e) {
      if (e.name === 'AbortError') return;
      if (seq !== state.searchSeq) return;
      $('#searchGrid').innerHTML = `<p class="empty">Search failed: ${esc(e.message)}</p>`;
    } finally {
      if (seq === state.searchSeq) state.searchController = null;
    }
  }

  const debouncedLiveSearch = debounce((q) => {
    if (q.length >= SEARCH_MIN_CHARS) doSearch(q);
  }, SEARCH_DEBOUNCE_MS);

  // ---------------- anime detail ----------------

  function updateResumeBtn(provider, animeTitle) {
    const btn = $('#resumeBtn');
    const eps = state.episodes;
    if (!eps || !eps.length) { btn.hidden = true; return; }

    let inProgress = null;
    let firstUnwatched = null;
    for (const ep of eps) {
      const st = getEpisodeState(ep.url);
      if (st === 'in-progress' && !inProgress) inProgress = ep;
      if (st === 'unwatched' && !firstUnwatched) firstUnwatched = ep;
    }

    const target = inProgress || firstUnwatched;
    if (!target) {
      btn.hidden = true;
      btn.onclick = null;
      return;
    }

    const label = target.title || (target.number ? `Episode ${target.number}` : 'Episode');
    btn.textContent = inProgress ? `Resume ${label}` : `Play ${label}`;
    btn.hidden = false;
    btn.onclick = () => openWatch(target.url, provider, animeTitle || '', label);
  }

  function renderEpisodes() {
    const list = $('#epList');
    const eps = state.episodes || [];
    const query = ($('#episodeFilter')?.value || '').trim().toLowerCase();
    const order = $('#episodeOrder')?.value || 'asc';
    const visible = eps.filter(ep => {
      const label = ep.title || (ep.number ? `Episode ${ep.number}` : 'Episode');
      return !query || label.toLowerCase().includes(query) || String(ep.number || '').includes(query);
    });
    if (order === 'desc') visible.reverse();

    const count = $('#epCount');
    count.textContent = visible.length === eps.length
      ? `${eps.length} ${eps.length === 1 ? 'episode' : 'episodes'}`
      : `${visible.length} of ${eps.length} episodes`;
    $('#episodeEmpty').hidden = visible.length > 0 || eps.length === 0;
    list.innerHTML = visible.map(ep => {
      const label = ep.title || (ep.number ? `Episode ${ep.number}` : 'Episode');
      return `<button type="button" data-url="${esc(ep.url)}" data-title="${esc(label)}" title="${esc(label)}">
        <span>${esc(label)}</span><span class="episode-play" aria-hidden="true">▶</span>
      </button>`;
    }).join('');

    $$('#epList button').forEach(button => {
      button.addEventListener('click', () =>
        openWatch(button.dataset.url, state.lastAnime?.provider || '', $('#dTitle').textContent, button.dataset.title || '')
      );
      const status = getEpisodeState(button.dataset.url);
      if (status !== 'unwatched') button.classList.add(status);
    });
  }

  async function openAnime(url, provider) {
    state.lastAnime = { url, provider, poster: null };
    state.episodes = [];
    state.currentEpisodeIndex = -1;
    showView('anime');
    const requestSeq = ++state.animeSeq;

    const dTitle  = $('#dTitle');
    const dPoster = $('#dPoster');
    const dSyn    = $('#dSyn');
    const dProv   = $('#dProvider');
    const epList  = $('#epList');
    const epCount = $('#epCount');
    const resumeBtn = $('#resumeBtn');
    const playFirstBtn = $('#playFirstBtn');
    const episodeToolbar = $('#episodeToolbar');

    dTitle.textContent = 'Loading…';
    dPoster.removeAttribute('src');
    dSyn.textContent = '';
    dProv.textContent = provider || '';
    epCount.textContent = '';
    resumeBtn.hidden = true;
    resumeBtn.onclick = null;
    playFirstBtn.hidden = true;
    playFirstBtn.onclick = null;
    episodeToolbar.hidden = true;
    $('#episodeFilter').value = '';
    $('#episodeOrder').value = 'asc';
    $('#episodeEmpty').hidden = true;
    epList.innerHTML = '<p class="empty">Loading episodes…</p>';

    try {
      const data = await api.anime(url, provider);
      if (requestSeq !== state.animeSeq) return;
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
      state.episodes = eps;
      if (!eps.length) {
        epCount.textContent = '';
        epList.innerHTML = '<p class="empty">No episodes detected.</p>';
        return;
      }
      episodeToolbar.hidden = false;
      playFirstBtn.hidden = false;
      playFirstBtn.onclick = () => {
        const first = eps[0];
        const label = first.title || (first.number ? `Episode ${first.number}` : 'Episode');
        openWatch(first.url, provider, data.title || '', label);
      };
      renderEpisodes();
      updateResumeBtn(provider, data.title);
    } catch (e) {
      if (requestSeq !== state.animeSeq) return;
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
  let playbackWatchdog = null;
  let sourcePlaySeq = 0;

  async function openWatch(episodeUrl, provider, animeTitle, epTitle, animeUrlOverride, posterOverride) {
    const requestSeq = ++state.watchSeq;
    sourcePlaySeq += 1;
    clearTimeout(playbackWatchdog);
    playbackWatchdog = null;
    teardownHls();
    currentEpisodeUrl = episodeUrl;
    currentProvider = provider;
    currentTitle = `${animeTitle || ''} — ${epTitle || ''}`.trim();
    currentAnimeTitle = animeTitle;
    currentAnimeUrl = animeUrlOverride || (state.lastAnime ? state.lastAnime.url : null);
    currentPoster = posterOverride || (state.lastAnime ? state.lastAnime.poster : null) || null;

    state.currentEpisodeIndex = state.episodes.findIndex(e => e.url === episodeUrl);
    updateEpNav();

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
      if (requestSeq !== state.watchSeq || currentEpisodeUrl !== episodeUrl) return;
      const sources = data.sources || [];
      if (!sources.length) {
        showFallback('No sources found for this episode.');
        return;
      }
      renderSources(sources, episodeUrl);
    } catch (e) {
      if (requestSeq !== state.watchSeq || currentEpisodeUrl !== episodeUrl) return;
      showFallback(e.message || 'Failed to load sources.');
    }
  }

  function updateEpNav() {
    const nav = $('#epNav');
    const total = state.episodes.length;
    if (state.currentEpisodeIndex < 0 || total < 2) {
      nav.hidden = true;
      return;
    }
    nav.hidden = false;
    const pos = state.currentEpisodeIndex + 1;
    $('#epPosition').textContent = `${pos} / ${total}`;
    $('#prevEpBtn').disabled = state.currentEpisodeIndex <= 0;
    $('#nextEpBtn').disabled = state.currentEpisodeIndex >= total - 1;
  }

  function saveCurrentResume() {
    const v = document.getElementById('__player');
    if (v && currentEpisodeUrl) saveResume(currentEpisodeUrl, v.currentTime);
  }

  function goNext() {
    if (state.currentEpisodeIndex < 0) return;
    const next = state.episodes[state.currentEpisodeIndex + 1];
    if (!next) return;
    saveCurrentResume();
    const label = next.title || (next.number ? `Episode ${next.number}` : 'Episode');
    openWatch(next.url, currentProvider, currentAnimeTitle, label, currentAnimeUrl, currentPoster);
  }

  function goPrev() {
    if (state.currentEpisodeIndex <= 0) return;
    const prev = state.episodes[state.currentEpisodeIndex - 1];
    if (!prev) return;
    saveCurrentResume();
    const label = prev.title || (prev.number ? `Episode ${prev.number}` : 'Episode');
    openWatch(prev.url, currentProvider, currentAnimeTitle, label, currentAnimeUrl, currentPoster);
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
    state.watchSeq += 1;
    sourcePlaySeq += 1;
    clearTimeout(playbackWatchdog);
    playbackWatchdog = null;
    teardownHls();
    saveCurrentResume();
    $('#playerHost').innerHTML = '';
    $('#watchModal').hidden = true;
    document.body.style.overflow = '';
    currentEpisodeUrl = null;

    // refresh episode state badges + resume button in the detail view behind
    if (state.episodes.length) {
      $$('#epList button').forEach(b => {
        b.classList.remove('in-progress', 'completed');
        const st = getEpisodeState(b.dataset.url);
        if (st !== 'unwatched') b.classList.add(st);
      });
      if (state.lastAnime) {
        updateResumeBtn(state.lastAnime.provider, $('#dTitle').textContent);
      }
    }
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
    if (s.toLowerCase() === 'auto') return 1080;
    return 0;
  }

  function sourceRank(s) {
    const k = KIND_RANK[s.kind] ?? 9;
    const qs = qualityScore(s.quality);
    const cap = state.settings.maxQuality;
    const overCap = (cap > 0 && qs > cap && qs > 0) ? 1 : 0;
    return k * 100000 + overCap * 50000 - qs;
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
    video.addEventListener('ended', () => {
      markCompleted(episodeUrl);
      if (state.settings.autoplayNext) goNext();
    });
  }

  function renderSources(sources, episodeUrl) {
    const host = $('#playerHost');
    const fallback = $('#playerFallback');
    const list = $('#sourceList');
    const dlRow = $('#downloadRow');

    sources.sort((a, b) => sourceRank(a) - sourceRank(b));

    const play = async (source, btn) => {
      const playSeq = ++sourcePlaySeq;
      clearTimeout(playbackWatchdog);
      playbackWatchdog = null;
      $$('#sourceList button').forEach(b => b.classList.remove('active'));
      if (btn) btn.classList.add('active');
      fallback.hidden = true;
      teardownHls();

      if (source.kind === 'embed') {
        host.innerHTML = `<iframe src="${esc(source.url)}"
          allow="autoplay; fullscreen; encrypted-media; picture-in-picture"
          allowfullscreen referrerpolicy="origin"></iframe>`;
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
        if (playSeq !== sourcePlaySeq) return;
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
          if (playSeq !== sourcePlaySeq) return;
          console.error('[AniKoKo] HLS error:', data);
          if (data.fatal) {
            fallback.hidden = false;
            fallback.innerHTML = `<p>HLS playback failed: ${esc(data.details || data.type)}<br><small>${esc(data.reason || '')}</small></p>`;
          }
        });
        currentHls = hls;

        playbackWatchdog = setTimeout(() => {
          if (playSeq !== sourcePlaySeq) return;
          if (v.readyState < 2 || v.paused) {
            fallback.hidden = false;
            fallback.innerHTML = '<p>Stream taking too long — try another server.</p>';
          }
        }, 10000);
        const clearWatchdog = () => {
          if (playSeq === sourcePlaySeq) {
            clearTimeout(playbackWatchdog);
            playbackWatchdog = null;
          }
        };
        v.addEventListener('playing', clearWatchdog, { once: true });
        v.addEventListener('loadeddata', clearWatchdog, { once: true });
      } catch (e) {
        if (playSeq !== sourcePlaySeq) return;
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
      btn.dataset.idx = String(i);
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

  // ---------------- settings modal ----------------

  function openSettings() {
    $('#maxQuality').value = String(state.settings.maxQuality);
    $('#autoplayNext').checked = !!state.settings.autoplayNext;
    $('#settingsModal').hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function closeSettings() {
    $('#settingsModal').hidden = true;
    if ($('#watchModal').hidden) document.body.style.overflow = '';
  }

  function wireSettings() {
    $('#settingsBtn').addEventListener('click', openSettings);
    $('#settingsClose').addEventListener('click', closeSettings);
    $('#settingsBg').addEventListener('click', closeSettings);

    $('#maxQuality').addEventListener('change', (e) => {
      state.settings.maxQuality = parseInt(e.target.value, 10) || 0;
      writeSettings(state.settings);
    });

    $('#autoplayNext').addEventListener('change', (e) => {
      state.settings.autoplayNext = !!e.target.checked;
      writeSettings(state.settings);
    });
  }

  // ---------------- keyboard ----------------

  function wireKeyboard(searchInput) {
    document.addEventListener('keydown', e => {
      const t = document.activeElement && document.activeElement.tagName;
      const typing = t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT';

      if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        searchInput.focus();
        return;
      }

      if (e.key === 'Escape') {
        if (!$('#settingsModal').hidden) { closeSettings(); return; }
        if (!$('#watchModal').hidden) { closeWatch(); return; }
        return;
      }

      if (typing) return;
      if ($('#watchModal').hidden) return;

      if (e.key === 'n' || e.key === 'N') { e.preventDefault(); goNext(); return; }
      if (e.key === 'p' || e.key === 'P') { e.preventDefault(); goPrev(); return; }

      if (/^[1-9]$/.test(e.key)) {
        const buttons = $$('#sourceList button');
        const i = parseInt(e.key, 10) - 1;
        if (buttons[i]) { e.preventDefault(); buttons[i].click(); }
      }
    });
  }

  // ---------------- bootstrap ----------------

  document.addEventListener('DOMContentLoaded', () => {
    state.settings = readSettings();

    $$('[data-nav="home"]').forEach(el =>
      el.addEventListener('click', e => { e.preventDefault(); showView('home'); })
    );

    const searchInput = $('#searchInput');
    $('#searchForm').addEventListener('submit', e => {
      e.preventDefault();
      const q = searchInput.value.trim();
      if (q) doSearch(q);
    });
    searchInput.addEventListener('input', () => {
      debouncedLiveSearch(searchInput.value.trim());
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

    $('#prevEpBtn').addEventListener('click', goPrev);
    $('#nextEpBtn').addEventListener('click', goNext);

    wireSettings();
    wireKeyboard(searchInput);

    $('#episodeFilter').addEventListener('input', renderEpisodes);
    $('#episodeOrder').addEventListener('change', renderEpisodes);

    window.addEventListener('beforeunload', () => {
      const v = document.getElementById('__player');
      if (v && currentEpisodeUrl && !v.paused) {
        saveResume(currentEpisodeUrl, v.currentTime);
      }
    });

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
    loadGenres();
    loadLatest();
  });
})();
