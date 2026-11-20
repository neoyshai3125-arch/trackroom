const dashboard = (() => {
  const state = {
    userId: null, home: null, charts: null, homeRequest: 0, searchRequest: 0,
    playRequest: 0, track: null, queue: [], restoredPosition: 0, dragTime: null,
  };
  const pages = {home: 'dashHome', explore: 'dashExplore', rooms: 'dashFindRooms'};
  const emptyHome = {rooms: [], recentSongs: [], popularSongs: []};
  let chartRequest = null;
  let chartExpires = 0;
  let searchHistory = [];
  let media;
  let player;
  let context;
  let analyser;
  let spectrumBuffer;
  let frame;
  let resumePosition = 0;
  let lastSaved = 0;
  let playingStatus = '';
  let previewCatalogId = '';
  let nativeAudio;
  let pointerId = null;
  let previewLoading = false;
  let homeFilters;
  const previewListeners = new Set();
  const previewCountries = ['KR', 'US', 'JP', 'GB', 'FR', 'DE'];

  function element(tag, className, value) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value !== undefined) el.textContent = value;
    return el;
  }
  function message(value) { return element('p', 'dash-muted', value); }
  function urlWithHost(value, matches) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && !url.username && !url.password && matches(url.hostname)
        ? url : null;
    } catch { return null; }
  }
  function shopUrl(value) {
    return urlWithHost(value, host => ['music.apple.com','itunes.apple.com','www.last.fm','open.spotify.com'].includes(host));
  }
  function coverUrl(value) {
    return urlWithHost(value, host => host.endsWith('.mzstatic.com') || host === 'i.scdn.co' ||
      host === 'mosaic.scdn.co' || /^e-cdns-images-dzcdn\.net$/.test(host))?.href || '';
  }
  function previewUrl(value) {
    return urlWithHost(value, host => ['audio-ssl.itunes.apple.com','audio.itunes.apple.com','audio-ssl.music.apple.com'].includes(host))?.href || '';
  }
  function trackId(track) {
    if (track?.sourcePlatform === 'apple' && /^[0-9]{1,20}$/.test(track.sourceId)) return String(track.sourceId);
    const url = shopUrl(track?.artworkStoreUrl || track?.musicUrl);
    if (!url || !['music.apple.com','itunes.apple.com'].includes(url.hostname)) return '';
    return (url.searchParams.get('i') || url.pathname.match(/\/song\/[^/]+\/([0-9]+)$/)?.[1] || '').match(/^[0-9]{1,20}$/)?.[0] || '';
  }
  function roomSource(track) {
    return track && /^[A-HJ-NP-Z2-9]{8}$/.test(track.previewRoomCode || '')
      && /^[0-9]{1,18}$/.test(track.id) ? track.previewRoomCode : '';
  }
  function playbackKey(track) {
    const room = roomSource(track);
    return room ? `room:${room}:${track.id}` : trackId(track);
  }
  function uniqueTracks(tracks) {
    const unique = new Map();
    for (const row of tracks) {
      const id = playbackKey(row);
      if (id && !unique.has(id)) unique.set(id, row);
    }
    return [...unique.values()];
  }
  function cover(value, circle) {
    const art = element('span', 'dash-row-art' + (circle ? ' is-artist' : ''));
    const src = coverUrl(value);
    if (src) {
      const img = element('img');
      img.src = src;
      img.alt = '';
      img.loading = 'lazy';
      img.referrerPolicy = 'no-referrer';
      img.addEventListener('error', () => img.remove(), {once: true});
      art.append(img);
    }
    return art;
  }
  function linkFor(value, title) {
    const url = shopUrl(value);
    if (!url) return null;
    const link = element('a', 'dash-row-arrow', title || '↗');
    link.href = url.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', title || '음원 서비스에서 보기');
    return link;
  }
  function row(title, subtitle, artwork, activate, external = '', artist = false) {
    const line = element('div', 'dash-row');
    const text = element('span', 'dash-row-text');
    text.append(element('strong', '', title), element('small', '', subtitle));
    const link = external && linkFor(external, '↗');
    if (activate) {
      const button = element('button', 'dash-row-open');
      button.type = 'button';
      button.append(cover(artwork, artist), text, element('span', 'dash-row-chevron', '›'));
      button.addEventListener('click', activate);
      line.append(button);
      if (link) line.append(link);
    } else if (link) {
      link.className = 'dash-row-open';
      link.setAttribute('aria-label', title + ' · 음원 서비스에서 보기');
      link.replaceChildren(cover(artwork, artist), text, element('span', 'dash-row-chevron', '↗'));
      line.append(link);
    } else {
      const item = element('div', 'dash-row-open');
      item.append(cover(artwork, artist), text);
      line.append(item);
    }
    return line;
  }
  function songRow(track, queue, label) {
    const subtitle = [label, track.artist].filter(Boolean).join(' · ');
    return row(track.title, subtitle, track.artworkUrl,
      trackId(track) ? () => selectTrack(track, queue) : null, track.musicUrl || track.artworkStoreUrl);
  }
  function fillRooms(id, rooms) {
    $(id).replaceChildren(...(rooms.length
      ? rooms.map(room => row(room.name, `${room.memberCount}명 · ${room.songCount}곡`, room.artworkUrl,
        () => goToRoom(room.code)))
      : [message('아직 참여한 방이 없어요. 초대 코드로 참여하거나 방을 만들어 봐.')]));
  }
  function renderHome(data) {
    const {rooms, recentSongs, popularSongs} = data;
    fillRooms('dashRooms', rooms);
    fillRooms('dashRoomDirectory', rooms);
    const rec = $('dashRecommendations');
    const feed = $('dashRoomTracks');
    const shelf = uniqueTracks([...popularSongs, ...recentSongs]);
    rec.replaceChildren();
    feed.replaceChildren();
    if (shelf.length) {
      const next = shelf.find(song => trackId(song) !== trackId(state.track)) || shelf[0];
      rec.append(songRow(next, shelf, '곡'));
      const album = shelf.find(song => song.album);
      if (album) rec.append(row(album.album, '앨범 · ' + album.artist, album.artworkUrl,
        () => runSearch(album.album, 'album'), album.musicUrl));
      rec.append(row('내 방에서 골라 듣기', `플레이리스트 · ${shelf.length}곡`, next.artworkUrl,
        () => showSearchResults(shelf, '내 방에서 골라 듣기')));
    } else {
      rec.append(message('방에 공유된 음악이 생기면 추천에 표시돼요.'));
    }
    for (const [label, tracks] of [['새로 추가된 곡', recentSongs], ['방에서 인기 있는 곡', popularSongs]]) {
      feed.append(element('h3', '', label));
      if (!tracks.length) feed.append(message(label === '새로 추가된 곡' ? '아직 방에 추가된 곡이 없어요.' : '아직 좋아요를 받은 곡이 없어요.'));
      for (const track of tracks.slice(0, 2)) feed.append(songRow(track, uniqueTracks(tracks), track.room.name));
    }
  }
  function renderCharts(data) {
    const charts = $('dashCharts');
    charts.replaceChildren();
    const tracks = uniqueTracks(data.tracks);
    for (const [label, items] of [['인기곡', data.tracks], ['인기 앨범', data.albums]]) {
      if (items.length) {
        charts.append(element('h3', '', label));
        items.slice(0, 3).forEach((item, index) => {
          const rank = String(index + 1).padStart(2, '0');
          charts.append(item.itemType === 'album'
            ? row(item.title, rank + ' · ' + item.artist, item.artworkUrl, null, item.musicUrl)
            : songRow(item, tracks, rank));
        });
      }
    }
    if (!charts.childElementCount) charts.append(message('Apple 차트를 불러오지 못했어요.'));
    const links = element('div', 'dash-chart-links');
    for (const [path, title] of [['songs', '인기곡 차트'], ['albums', '인기 앨범 차트']]) {
      links.append(linkFor(`https://music.apple.com/kr/new/top-charts/${path}`, title + ' ↗'));
    }
    charts.append(links);
  }
  function ensureCharts() {
    if (chartRequest || Date.now() < chartExpires || !state.userId) return;
    const owner = state.userId;
    const request = api('/api/home/charts');
    chartRequest = request;
    request.then(data => {
      if (state.userId !== owner) return;
      state.charts = data;
      chartExpires = Date.now() + (data.tracks.length || data.albums.length ? 900000 : 60000);
      renderCharts(data);
    }).catch(() => {
      if (state.userId === owner) {
        chartExpires = Date.now() + 60000;
        if (!state.charts) renderCharts({tracks: [], albums: []});
      }
    }).finally(() => {
      if (chartRequest === request) chartRequest = null;
    });
  }
  async function refresh() {
    if (!state.userId) return;
    const version = ++state.homeRequest;
    try {
      const data = await api('/api/home');
      if (version !== state.homeRequest) return;
      state.home = data;
      renderHome(data);
    } catch (error) {
      if (version !== state.homeRequest || state.home) return;
      $('dashRooms').replaceChildren(message(error.message));
      $('dashRoomDirectory').replaceChildren(message(error.message));
      $('dashRecommendations').replaceChildren(message('추천 음악을 불러오지 못했어요.'));
      $('dashRoomTracks').replaceChildren(message('방 소식을 불러오지 못했어요.'));
    }
  }
  function chooseTab(tab) {
    if (!(tab in pages)) return;
    Object.entries(pages).forEach(([key, id]) => $(id).classList.toggle('hidden', tab !== key));
    document.querySelectorAll('[data-dash-tab]').forEach(button => {
      if (button.dataset.dashTab === tab) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    window.scrollTo(0, 0);
    if (frame != null) cancelAnimationFrame(frame);
    drawSpectrum();
    if (tab === 'rooms') refresh();
  }
  function slide(index, animate = true) {
    const area = $('dashCarousel');
    const target = area.children[index];
    if (!target) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    area.scrollTo({left: target.offsetLeft, behavior: animate && !reduced ? 'smooth' : 'instant'});
    if (index === 2) ensureCharts();
  }
  function updateDots() {
    const area = $('dashCarousel');
    const index = [...area.children].reduce((closest, card, i) =>
      Math.abs(card.offsetLeft - area.scrollLeft) < Math.abs(area.children[closest].offsetLeft - area.scrollLeft) ? i : closest, 0);
    document.querySelectorAll('[data-slide]').forEach((dot, i) => {
      if (i === index) dot.setAttribute('aria-current', 'true');
      else dot.removeAttribute('aria-current');
    });
    if (index === 2) ensureCharts();
  }
  async function runSearch(query, kind, filters = {}) {
    chooseTab('explore');
    $('dashSearchQuery').value = query;
    $('dashSearchKind').value = kind;
    const version = ++state.searchRequest;
    searchHistory = [];
    $('dashSearchBack').classList.add('hidden');
    $('dashSearchResults').replaceChildren(message('검색 중이에요…'));
    try {
      const data = await api('/api/catalog/search?' + new URLSearchParams({platform: 'apple', q: query, kind, ...filters}));
      if (version === state.searchRequest) renderSearch(data.results);
    } catch (error) {
      if (version === state.searchRequest) $('dashSearchResults').replaceChildren(message(error.message));
    }
  }
  function renderSearch(items, heading = '') {
    const result = $('dashSearchResults');
    result.replaceChildren();
    if (heading) result.append(element('h2', '', heading));
    if (!items.length) result.append(message('검색 결과가 없어요.'));
    const queue = uniqueTracks(items.filter(item => item.itemType !== 'artist' && item.itemType !== 'album'));
    result.append(...items.map(track => ['album', 'artist'].includes(track.itemType)
      ? row(track.title, track.itemType === 'artist' ? '아티스트' : track.artist,
        track.artworkUrl, track.selectionToken ? () => openCollection(track, items, heading) : null,
        track.musicUrl, track.itemType === 'artist')
      : songRow(track, queue)));
  }
  async function openCollection(item, items, heading) {
    const version = ++state.searchRequest;
    searchHistory.push({items, heading});
    $('dashSearchBack').classList.remove('hidden');
    $('dashSearchResults').replaceChildren(message('수록곡을 불러오는 중이에요…'));
    try {
      const kind = item.itemType === 'artist' ? 'artist-tracks' : 'album-tracks';
      const response = await api('/api/catalog/' + kind, {method: 'POST', body: JSON.stringify({selectionToken: item.selectionToken})});
      if (state.searchRequest === version) renderSearch([...(response.artistInfo?.albums || []), ...response.results], item.title);
    } catch (error) {
      if (state.searchRequest === version) $('dashSearchResults').replaceChildren(message(error.message));
    }
  }
  function showSearchResults(items, heading) {
    ++state.searchRequest;
    searchHistory = [];
    $('dashSearchBack').classList.add('hidden');
    chooseTab('explore');
    renderSearch(items, heading);
  }
  function restoreTrack() {
    try {
      const record = JSON.parse(localStorage.getItem('trackroom-preview:' + state.userId));
      if (!record || !playbackKey(record.track)) return;
      state.track = record.track;
      state.queue = [record.track];
      resumePosition = Number.isFinite(record.position) ? Math.max(0, record.position) : 0;
    } catch { /* Local storage may be unavailable. */ }
  }
  function saveTrack() {
    if (!state.userId || !state.track || !player?.currentSrc || player.currentSrc !== previewUrl(state.track.previewUrl)) return;
    try {
      localStorage.setItem('trackroom-preview:' + state.userId, JSON.stringify({
        track: state.track, position: player.ended ? 0 : player.currentTime,
      }));
    } catch { /* Playback still works without local storage. */ }
  }
  function setUser(user) {
    const id = user?.id || null;
    if (state.userId === id) return;
    saveTrack();
    ++state.homeRequest;
    ++state.searchRequest;
    ++state.playRequest;
    media?.pause();
    nativeAudio?.pause();
    for (const audio of [media, nativeAudio]) {
      if (audio) { audio.removeAttribute('src'); audio.load(); }
    }
    state.userId = id;
    state.track = null;
    state.queue = [];
    state.home = null;
    state.charts = null;
    chartExpires = 0;
    chartRequest = null;
    searchHistory = [];
    resumePosition = 0;
    state.dragTime = null;
    previewCatalogId = '';
    playingStatus = '';
    previewLoading = false;
    player = media;
    homeFilters?.reset();
    $('dashSearchQuery').value = '';
    $('dashSearchResults').replaceChildren();
    $('dashSearchBack').classList.add('hidden');
    $('dashCharts').replaceChildren(message('차트를 불러오는 중이에요.'));
    renderHome(emptyHome);
    if (id) { restoreTrack(); refresh(); }
    showPlayer();
  }
  function setStatus(text) {
    playingStatus = text;
    $('dashPlayStatus').textContent = text;
    notifyPreview();
  }

  function getPreview() {
    const total = duration();
    const position = total ? player.currentTime : resumePosition;
    const track = state.track;
    const link = shopUrl(track?.musicUrl || track?.artworkStoreUrl);
    return {
      track,
      duration: total,
      position,
      playing: !!(player && !player.paused && previewCatalogId === playbackKey(track)),
      loading: previewLoading,
      status: playingStatus,
      cover: coverUrl(track?.artworkUrl),
      store: link && ['music.apple.com','itunes.apple.com'].includes(link.hostname) ? link.href : '',
    };
  }
  function notifyPreview() {
    const value = getPreview();
    previewListeners.forEach(listener => listener(value));
  }
  function watchPreview(listener) {
    previewListeners.add(listener);
    listener(getPreview());
  }
  function pausePreview() {
    ++state.playRequest;
    previewLoading = false;
    player?.pause();
    if (playingStatus === '미리듣기를 준비하는 중이에요.') setStatus('Apple 미리듣기');
    showPlayer();
  }
  function togglePreview() {
    if (previewLoading || !player?.paused) pausePreview();
    else void play();
  }
  function seekPreview(seconds) {
    if (!duration() || !Number.isFinite(seconds)) return;
    player.currentTime = Math.max(0, Math.min(duration() - 0.05, seconds));
    updateProgress();
    saveTrack();
  }
  function displayCover(art, raw) {
    if (art.dataset.original === raw) return;
    art.dataset.original = raw;
    art.classList.toggle('hidden', !raw);
    if (raw) art.src = highResArtworkUrl(raw, 1200);
    else art.removeAttribute('src');
  }
  function showPlayer() {
    const track = state.track;
    $('dashPlayerEmpty').classList.toggle('hidden', Boolean(track));
    $('dashPlayerContent').classList.toggle('hidden', !track);
    $('dashMiniPlayer').classList.toggle('hidden', !track);
    $('dashboard').classList.toggle('has-preview', Boolean(track));
    displayCover($('dashCoverArt'), coverUrl(track?.artworkUrl));
    if (track) {
      const src = coverUrl(track.artworkUrl);
      $('dashPlayingTitle').textContent = $('dashMiniTitle').textContent = track.title;
      $('dashPlayingArtist').textContent = track.artist;
      $('dashMiniArtist').textContent = track.artist;
      $('dashMiniArt').replaceChildren(cover(src));
      const link = shopUrl(track.musicUrl || track.artworkStoreUrl);
      const store = $('dashStoreLink');
      store.classList.toggle('hidden', !link);
      if (link) {
        store.href = link.href;
        store.textContent = link.hostname === 'itunes.apple.com' ? 'iTunes Store에서 보기 ↗' :
          link.hostname === 'music.apple.com' ? 'Apple Music에서 듣기 ↗' : '음원 서비스에서 듣기 ↗';
      } else {
        store.removeAttribute('href');
      }
      setStatus(playingStatus || 'Apple 미리듣기');
    }
    const playing = player && !player.paused;
    $('dashPlay').setAttribute('aria-label', playing ? '일시정지' : '미리듣기 재생');
    $('dashPlayIcon').setAttribute('d', playing ? 'M7 4h4v16H7zm7 0h4v16h-4z' : 'M7 4l14 8L7 20z');
    const index = state.queue.findIndex(item => playbackKey(item) === playbackKey(track));
    $('dashPrev').disabled = index <= 0;
    $('dashNext').disabled = index < 0 || index >= state.queue.length - 1;
    updateProgress();
  }
  function initAnalysis() {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return;
    try {
      if (!context) {
        context = new Audio();
        analyser = context.createAnalyser();
        analyser.fftSize = 2048;
        analyser.smoothingTimeConstant = .76;
        analyser.minDecibels = -88;
        analyser.maxDecibels = -20;
        const source = context.createMediaElementSource(media);
        source.connect(analyser);
        analyser.connect(context.destination);
        spectrumBuffer = new Uint8Array(analyser.frequencyBinCount);
      }
      if (context.state === 'suspended') context.resume().catch(() => {});
    } catch { analyser = null; }
  }
  function hydrate(track, catalog) {
    return {
      ...track, previewUrl: previewUrl(catalog.previewUrl), durationMs: catalog.durationMs || track.durationMs,
      artworkUrl: track.artworkUrl || catalog.artworkUrl, musicUrl: catalog.musicUrl,
    };
  }
  async function selectTrack(track, queue = [track]) {
    if (!playbackKey(track)) return;
    if (playbackKey(track) !== playbackKey(state.track)) {
      saveTrack();
      player?.pause();
      state.track = track;
      resumePosition = 0;
      playingStatus = 'Apple 미리듣기';
    }
    state.queue = uniqueTracks(queue);
    if (!state.queue.some(item => playbackKey(item) === playbackKey(state.track))) state.queue.unshift(state.track);
    showPlayer();
    await play();
  }
  async function play() {
    const track = state.track;
    if (!track || !playbackKey(track)) return;
    initAnalysis();
    const version = ++state.playRequest;
    const id = playbackKey(track);
    previewLoading = true;
    if (!previewUrl(track.previewUrl)) setStatus('미리듣기를 준비하는 중이에요.');
    try {
      if (!previewUrl(track.previewUrl)) {
        const country = previewCountries.includes(track.storeCountry) ? track.storeCountry : 'KR';
        const room = roomSource(track);
        const endpoint = room ? `/api/rooms/${room}/songs/${track.id}/preview` :
          '/api/catalog/preview?' + new URLSearchParams({trackId: trackId(track), country});
        const response = await api(endpoint);
        if (version !== state.playRequest || id !== playbackKey(state.track)) return;
        state.track = hydrate(track, response.track);
      }
      const url = previewUrl(state.track.previewUrl);
      if (!url) throw Error('미리듣기를 제공하지 않는 곡이에요.');
      if (previewCatalogId !== id || !player || player.src !== url) {
        player?.pause();
        player = media;
        previewCatalogId = id;
        if (player.src !== url) player.src = url;
        else if (Number.isFinite(player.duration)) player.currentTime = 0;
      }
      setStatus(player === nativeAudio ? 'Apple 미리듣기 · 이 음원의 시각화는 제공되지 않아요.' : 'Apple 미리듣기');
      showPlayer();
      await player.play();
      if (version === state.playRequest) saveTrack();
    } catch (error) {
      if (version !== state.playRequest) return;
      if (error.name === 'NotSupportedError' && previewUrl(state.track?.previewUrl) && player === media) {
        await playWithoutAnalysis(version);
      } else {
        setStatus(error.name === 'NotAllowedError' ? '재생 버튼을 한 번 더 눌러 줘.' :
          error.name === 'AbortError' ? 'Apple 미리듣기' : error.message);
        showPlayer();
      }
    } finally {
      if (version === state.playRequest) {
        previewLoading = false;
        notifyPreview();
      }
    }
  }
  async function playWithoutAnalysis(version) {
    const url = previewUrl(state.track?.previewUrl);
    if (!url || version !== state.playRequest || player !== media) return;
    media.pause();
    player = nativeAudio;
    nativeAudio.src = url;
    try {
      await nativeAudio.play();
      if (version === state.playRequest) {
        setStatus('Apple 미리듣기 · 이 음원의 시각화는 제공되지 않아요.');
        saveTrack();
        showPlayer();
      }
    } catch (error) {
      if (version === state.playRequest) {
        setStatus(error.name === 'NotAllowedError' ? '재생 버튼을 한 번 더 눌러 줘.' : '이 음원의 미리듣기를 재생하지 못했어요.');
        showPlayer();
      }
    }
  }
  function step(offset) {
    const at = state.queue.findIndex(track => playbackKey(track) === playbackKey(state.track));
    const next = state.queue[at + offset];
    if (next) selectTrack(next, state.queue);
  }
  function duration() {
    return player && previewCatalogId === playbackKey(state.track) && Number.isFinite(player.duration) ? player.duration : 0;
  }
  function updateProgress() {
    const total = duration();
    const displayed = total ? state.dragTime ?? player.currentTime : resumePosition;
    const proportion = total ? Math.min(1, displayed / total) : 0;
    const angle = proportion * Math.PI * 2 - Math.PI / 2;
    $('dashSeekProgress').setAttribute('stroke-dasharray', `${proportion * 100} 100`);
    $('dashSeekHandle').setAttribute('cx', 100 + Math.cos(angle) * 89);
    $('dashSeekHandle').setAttribute('cy', 100 + Math.sin(angle) * 89);
    $('dashTime').textContent = `${timeLabel(displayed)} / ${total ? timeLabel(total) : '–:––'}`;
    const dial = $('dashSeek');
    dial.setAttribute('aria-disabled', String(!total));
    dial.setAttribute('aria-valuemax', String(Math.floor(total)));
    dial.setAttribute('aria-valuenow', String(Math.floor(total ? displayed : 0)));
    dial.setAttribute('aria-valuetext', $('dashTime').textContent);
    notifyPreview();
  }
  function dialPoint(event) {
    const rect = $('dashSeek').getBoundingClientRect();
    const dx = event.clientX - rect.left - rect.width / 2;
    const dy = event.clientY - rect.top - rect.height / 2;
    if (!dx && !dy) return;
    const angle = (Math.atan2(dy, dx) + Math.PI / 2 + Math.PI * 2) % (Math.PI * 2);
    state.dragTime = angle / (Math.PI * 2) * duration();
    updateProgress();
  }
  function endDrag(event) {
    if (pointerId !== event.pointerId) return;
    pointerId = null;
    if (event.type === 'pointerup' && duration() && state.dragTime != null) {
      player.currentTime = Math.min(state.dragTime, Math.max(0, duration() - 0.05));
      saveTrack();
    }
    state.dragTime = null;
    updateProgress();
  }
  function drawSpectrum() {
    const isPlaying = Boolean(analyser && player === media && !media.paused &&
      !$('dashHome').classList.contains('hidden') && !$('dashboard').classList.contains('hidden') &&
      !$('landing').classList.contains('hidden'));
    if (isPlaying) analyser.getByteFrequencyData(spectrumBuffer);
    const points = [];
    for (let i = 0; i <= 32; i++) {
      const frequency = 45 * Math.pow(260, i / 32);
      const index = isPlaying ? Math.min(spectrumBuffer.length - 1, Math.round(frequency / context.sampleRate * analyser.fftSize)) : 0;
      points.push([i * 10, 45 - (isPlaying ? spectrumBuffer[index] * 39 / 255 : 0)]);
    }
    const curve = points.slice(1).reduce((d, [x, y], i) => {
      const [previous, oldY] = points[i];
      const mid = (previous + x) / 2;
      return `${d} C ${mid} ${oldY}, ${mid} ${y}, ${x} ${y}`;
    }, 'M 0 ' + points[0][1]);
    $('dashSpectrumLine').setAttribute('d', curve);
    $('dashSpectrumFill').setAttribute('d', curve + ' V 48 H 0 Z');
    if (isPlaying) frame = requestAnimationFrame(drawSpectrum);
    else frame = null;
  }
  function mediaState(event) {
    if (event.currentTarget !== player) return;
    if (event.type === 'loadedmetadata' && resumePosition > 0) {
      player.currentTime = Math.min(resumePosition, Math.max(0, duration() - 0.1));
      resumePosition = 0;
    }
    if (event.type === 'play' || event.type === 'pause' || event.type === 'ended') {
      if (frame != null) cancelAnimationFrame(frame);
      drawSpectrum();
      showPlayer();
      saveTrack();
    } else {
      updateProgress();
      if (Date.now() - lastSaved > 2500 && !player.paused) {
        lastSaved = Date.now();
        saveTrack();
      }
    }
  }
  function init() {
    player = media = $('dashAudio');
    nativeAudio = new Audio();
    nativeAudio.preload = 'none';
    for (const audio of [media, nativeAudio]) {
      for (const type of ['timeupdate','loadedmetadata','durationchange','play','pause','ended']) audio.addEventListener(type, mediaState);
    }
    window.addEventListener('pagehide', saveTrack);
    $('dashStartExplore').addEventListener('click', () => chooseTab('explore'));
    $('dashMiniDetails').addEventListener('click', () => { chooseTab('home'); slide(0); });
    $('dashPlay').addEventListener('click', togglePreview);
    $('dashCoverArt').addEventListener('error', event => {
      const art = event.currentTarget;
      if (art.dataset.original && art.src !== art.dataset.original) art.src = art.dataset.original;
      else art.classList.add('hidden');
    });
    $('dashPrev').addEventListener('click', () => step(-1));
    $('dashNext').addEventListener('click', () => step(1));
    $('dashCarousel').addEventListener('scroll', updateDots, {passive: true});
    document.querySelectorAll('[data-slide]').forEach(button => {
      button.addEventListener('click', () => slide(Number(button.dataset.slide)));
    });
    document.querySelectorAll('[data-dash-tab]').forEach(button => {
      button.addEventListener('click', () => chooseTab(button.dataset.dashTab));
    });
    homeFilters = window.TrackroomCatalogFilters.mount($('dashCatalogFilters'), {
      platform: () => 'apple',
      onChange: () => {
        ++state.searchRequest;
        searchHistory = [];
        $('dashSearchBack').classList.add('hidden');
        $('dashSearchResults').replaceChildren(message('선택한 조건으로 검색해 줘.'));
      }
    });
    $('dashSearchForm').addEventListener('submit', event => {
      event.preventDefault();
      const query = $('dashSearchQuery').value.trim();
      if (query.length >= 2) runSearch(query, $('dashSearchKind').value, homeFilters.params());
    });
    $('dashSearchBack').addEventListener('click', () => {
      ++state.searchRequest;
      const last = searchHistory.pop();
      if (last) renderSearch(last.items, last.heading);
      $('dashSearchBack').classList.toggle('hidden', !searchHistory.length);
    });
    const dial = $('dashSeek');
    dial.addEventListener('pointerdown', event => {
      if (!duration() || event.button !== 0 || pointerId !== null) return;
      event.preventDefault();
      pointerId = event.pointerId;
      dial.setPointerCapture(pointerId);
      dialPoint(event);
    });
    dial.addEventListener('pointermove', event => { if (pointerId === event.pointerId) dialPoint(event); });
    dial.addEventListener('pointerup', endDrag);
    dial.addEventListener('pointercancel', endDrag);
    dial.addEventListener('keydown', event => {
      const offsets = {ArrowLeft: -5, ArrowDown: -5, ArrowRight: 5, ArrowUp: 5};
      if (!duration() || !(event.key in offsets || ['Home','End'].includes(event.key))) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? duration() : player.currentTime + offsets[event.key];
      player.currentTime = Math.max(0, Math.min(duration() - 0.05, next));
      updateProgress();
      saveTrack();
    });
    drawSpectrum();
    renderHome(emptyHome);
  }
  return {
    init, setUser, refresh, chooseTab, selectTrack, getPreview, watchPreview, togglePreview, pausePreview, seekPreview,
    canPreview: track => Boolean(trackId(track))
  };
})();
