const $ = (id) => document.getElementById(id);
const state = { roomCode: null, room: null, songs: [], sort: 'none', user: null, pendingInvite: null, authMode: 'login' };
let refreshTimer = null;
let toastTimer = null;
let selectedTrack = null;
let catalogResults = [];
let catalogHistory = [];
let catalogView = 'search'; // search, artist-profiles, artist-tracks, album-tracks
let catalogViewInfo = null;
let searchCounter = 0;
let bubbleSelectedId = null;
let bubbleLastRender = '';
let bubbleCanvasCamera = { x: 0, y: 0, zoom: 1 };
let bubbleRandomIndex = 0;
let bubblePointerState = new Map();
let bubbleDrag = null;
let bubblePinch = null;
let suppressBubbleClick = false;
let addPanelOpen = false;
let roomMenuOpen = false;

function toast(message, error = false) {
  const el = $('toast');
  el.textContent = message;
  el.classList.toggle('error', error);
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3600);
}
function escaped(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  let data;
  try { data = await response.json(); } catch { throw new Error('서버 응답을 읽지 못했습니다.'); }
  if (!response.ok) throw new Error(data.error || `오류가 발생했습니다. (${response.status})`);
  return data;
}
const PLATFORM_NAMES = { spotify: 'Spotify', apple: 'Apple Music', melon: '멜론', genie: '지니뮤직', flo: 'FLO', bugs: '벅스', youtube: 'YouTube Music', other: '기타', none: '미설정' };
function showAuth(mode = 'login') {
  state.authMode = mode;
  $('loginTab').classList.toggle('active', mode === 'login');
  $('registerTab').classList.toggle('active', mode === 'register');
  $('registerExtra').classList.toggle('hidden', mode !== 'register');
  $('authHeading').textContent = mode === 'register' ? '좋아하는 음악으로 연결되는 곳.' : '다시 만나서 반가워.';
  $('authSubmit').innerHTML = mode === 'register' ? '회원가입하고 시작하기 <span>→</span>' : '로그인 <span>→</span>';
  $('authPassword').autocomplete = mode === 'register' ? 'new-password' : 'current-password';
  $('authForm').reset();
  $('authOverlay').classList.remove('hidden');
  $('authUsername').focus();
}
function hideAuth() { $('authOverlay').classList.add('hidden'); }
function showProfile() {
  if (!state.user) return showAuth();
  $('profileUsername').textContent = '@' + state.user.username;
  $('profileNickname').value = state.user.nickname;
  $('profilePlatform').value = state.user.platform;
  $('profileOverlay').classList.remove('hidden');
}
function hideProfile() { $('profileOverlay').classList.add('hidden'); }
function renderAccount() {
  $('accountButton').textContent = state.user ? `${state.user.nickname} · 내 프로필` : '로그인 / 가입';
  $('accountSummary').classList.toggle('logged-in', Boolean(state.user));
  if (state.user) {
    $('accountSummary').innerHTML = `<div class="summary-name">✳ ${escaped(state.user.nickname)}</div><div class="summary-platform">내 음악 플랫폼 · ${escaped(PLATFORM_NAMES[state.user.platform] || '미설정')}</div><button class="btn" type="button" id="authEntryButton">프로필 수정하기 ↗</button>`;
    $('authEntryButton').addEventListener('click', showProfile);
  } else {
    $('accountSummary').innerHTML = '<p>추천방을 이용하려면 먼저 로그인해 줘.</p><button class="btn btn-primary" id="authEntryButton" type="button">회원가입 / 로그인 ↗</button>';
    $('authEntryButton').addEventListener('click', () => showAuth('register'));
  }
}
async function completeLogin(user) {
  state.user = user;
  renderAccount();
  preferSearchPlatform();
  hideAuth();
  if (state.pendingInvite) {
    const code = state.pendingInvite;
    try {
      await api(`/api/rooms/${encodeURIComponent(code)}/join`, {method: 'POST', body: '{}'});
      state.pendingInvite = null;
      goToRoom(code);
    } catch (e) { toast(e.message, true); }
  } else toast(`${user.nickname}님, 환영해!`);
}
async function submitAuth(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = { username: $('authUsername').value.trim(), password: $('authPassword').value };
  if (state.authMode === 'register') {
    payload.nickname = $('registerNickname').value.trim();
    payload.platform = $('registerPlatform').value;
    if (!payload.nickname) return toast('닉네임을 입력해 줘.', true);
  }
  setBusy(form, true);
  try {
    const data = await api(`/api/auth/${state.authMode === 'register' ? 'register' : 'login'}`, {method: 'POST', body: JSON.stringify(payload)});
    await completeLogin(data.user);
  } catch(e) { toast(e.message, true); }
  finally { setBusy(form, false); }
}
async function submitProfile(event) {
  event.preventDefault();
  const form = event.currentTarget;
  setBusy(form, true);
  try {
    const data = await api('/api/auth/profile', {method: 'PATCH', body: JSON.stringify({nickname: $('profileNickname').value.trim(), platform: $('profilePlatform').value})});
    state.user = data.user;
    renderAccount();
    preferSearchPlatform();
    hideProfile();
    await refreshRoom();
    toast('프로필을 저장했어!');
  } catch(e) { toast(e.message, true); }
  finally { setBusy(form, false); }
}
async function logout() {
  try {
    await api('/api/auth/logout', {method: 'POST', body: '{}'});
    state.user = null;
    hideProfile();
    showLanding();
    renderAccount();
    toast('로그아웃했어.');
  } catch(e) { toast(e.message, true); }
}
function setBusy(form, busy) {
  [...form.querySelectorAll('button, input, textarea')].forEach(x => x.disabled = busy);
  if (form.id === 'addSongForm') $('submitSong').disabled = busy || !selectedTrack;
}
function showLanding() {
  closeRoomMenu(false);
  document.body.classList.remove('room-active');
  state.roomCode = null;
  state.room = null;
  clearInterval(refreshTimer);
  $('landing').classList.remove('hidden');
  $('landingFooter').classList.remove('hidden');
  $('roomView').classList.add('hidden');
  closeAddPanel();
  closeBubbleDetail();
  bubbleCanvasCamera = { x: 0, y: 0, zoom: 1 };
  bubbleLastRender = '';
  history.replaceState({}, '', '/');

  window.scrollTo({top:0,behavior:'smooth'});
}
function goToRoom(code) {
  if (state.roomCode !== code) {
    bubbleCanvasCamera = { x: 0, y: 0, zoom: 1 };
    bubbleLastRender = '';
    bubbleSelectedId = null;
  }
  closeRoomMenu(false);
  state.roomCode = code;
  document.body.classList.add('room-active');
  $('landing').classList.add('hidden');
  $('landingFooter').classList.add('hidden');
  $('roomView').classList.remove('hidden');
  history.replaceState({}, '', `/?room=${encodeURIComponent(code)}`);
  refreshRoom();
  clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshRoom, 8000);
  window.scrollTo({top:0,behavior:'smooth'});
}
async function refreshRoom() {
  if (!state.roomCode || !state.user) return;
  const roomCode = state.roomCode;
  try {
    const data = await api(`/api/rooms/${roomCode}`);
    if (state.roomCode !== roomCode) return;
    state.room = data.room;
    state.songs = data.songs;
    $('roomTitle').textContent = data.room.name;
    $('roomCodeText').textContent = data.room.code;
    $('memberCount').textContent = data.room.memberCount;
    $('songTotal').textContent = data.songs.length;
    document.title = `${data.room.name} · TRACKROOM`;
    renderSongs();
  } catch (error) {
    if (error.message.includes('로그인')) { clearInterval(refreshTimer); state.user = null; renderAccount(); showLanding(); showAuth(); }
    toast(error.message, true);
  }
}
function parseTime(str) {
  str = str.trim();
  if (!str) return null;
  if (!/^\d{1,3}:[0-5]\d$/.test(str)) throw new Error('구간은 1:20과 같은 형식으로 입력해 주세요.');
  const [m,s] = str.split(':').map(Number);
  const value = m*60+s;
  if (value > 36000) throw new Error('구간이 너무 깁니다.');
  return value;
}
function timeLabel(value) { if (value === null || value === undefined) return ''; return `${Math.floor(value/60)}:${String(value%60).padStart(2,'0')}`; }
function sourceLabel(url) {
  try {
    const h = new URL(url).hostname.toLowerCase();
    if (h === 'open.spotify.com' || h.endsWith('.spotify.com')) return 'Spotify';
    if (h === 'music.apple.com') return 'Apple Music';
    if (h === 'youtube.com' || h.endsWith('.youtube.com') || h === 'youtu.be') return 'YouTube';
    if (h === 'www.melon.com' || h.endsWith('.melon.com')) return '멜론';
    if (h.endsWith('.genie.co.kr')) return '지니';
    if (h === 'music-flo.com' || h.endsWith('.music-flo.com')) return 'FLO';
    return '음악 링크';
  } catch { return '음악 링크'; }
}
function artGradient(title) {
  const colors = [
    'linear-gradient(135deg,#7f8364,#374839)',
    'linear-gradient(135deg,#be9168,#73434b)',
    'linear-gradient(135deg,#748da8,#42395d)',
    'linear-gradient(135deg,#ad7598,#5b494b)',
    'linear-gradient(135deg,#78a19a,#314e51)',
    'linear-gradient(135deg,#afa76c,#575340)'
  ];
  const n = [...title].reduce((a, c) => a+c.charCodeAt(0), 0);
  return colors[n%colors.length];
}
// -----------------------------------------------
// TRACKROOM v5: spatial discovery canvas
// -----------------------------------------------
function bubblePosition(index) {
  if (index === 0) return { x: 0, y: 0, size: 162 };
  // A deterministic sunflower distribution: no rank or likes-based sizing.
  const angle = index * 2.399963229728653;
  const radius = 192 * Math.sqrt(index);
  const size = 134 + (index * 37 % 25);
  return { x: Math.round(Math.cos(angle) * radius), y: Math.round(Math.sin(angle) * radius), size };
}
// The iTunes Search API provides 100x100 artwork links. Apple CDN images
// support larger size variants without an additional music-search request.
// Rewrite only recognized Apple artwork CDN URLs; leave all other URLs intact.
function highResArtworkUrl(url, size = 600) {
  const original = String(url || '');
  try {
    const parsed = new URL(original);
    if (parsed.protocol !== 'https:' || !/(^|\.)mzstatic\.com$/i.test(parsed.hostname)) return original;
    parsed.pathname = parsed.pathname.replace(
      /([/.])\d{2,4}x\d{2,4}(bb(?:-\d+)?|-\d+)?(\.(?:jpe?g|png|webp))$/i,
      (_match, prefix, suffix = '', extension) => `${prefix}${size}x${size}${suffix}${extension}`
    );
    return parsed.toString();
  } catch {
    return original;
  }
}
function bubbleArtwork(song) {
  if (song.artworkUrl && /^https:\/\//i.test(song.artworkUrl)) {
    // Try the high-resolution image first, then fall back to the existing URL.
    const highResUrl = highResArtworkUrl(song.artworkUrl);
    return `<img src="${escaped(highResUrl)}" data-original-src="${escaped(song.artworkUrl)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="if(!this.dataset.retriedOriginal && this.src !== this.dataset.originalSrc){this.dataset.retriedOriginal='1';this.src=this.dataset.originalSrc;}else{this.style.display='none';this.nextElementSibling.style.display='grid';}" /><span class="bubble-image-fallback" style="display:none">♫</span>`;
  }
  return '<span class="bubble-image-fallback">♫</span>';
}
function bubbleProvider(song) {
  return song.sourceCatalog === 'itunes_store' ? 'iTunes Store' : song.sourceCatalog === 'lastfm' ? 'Last.fm' :
    (PLATFORM_NAMES[song.sourcePlatform] || sourceLabel(song.musicUrl));
}
function applyBubbleCamera() {
  const {x, y, zoom} = bubbleCanvasCamera;
  $('bubbleStage').style.transform = `translate3d(${x}px, ${y}px, 0) scale(${zoom})`;
  $('bubbleZoomLabel').textContent = `${Math.round(zoom * 100)}%`;
  $('bubbleCanvas').classList.toggle('zoomed-out', zoom < .8);
  $('bubbleCanvas').classList.toggle('zoomed-in', zoom > 1.3);
}
function renderSongs() {
  // Bubble positions are stable and independent of catalog search sorting.
  const songs = [...state.songs].sort((a,b) => Number(a.id) - Number(b.id));
  const signature = `${state.sort}|` + songs.map(s => [s.id,s.title,s.artist,s.artworkUrl,s.likeCount,s.liked,s.nickname,s.note,s.startSeconds,s.endSeconds].join('|')).join('~');
  if (signature !== bubbleLastRender) {
    bubbleLastRender = signature;
    $('bubbleStage').innerHTML = songs.map((song, index) => {
      const p = bubblePosition(index);
      const radius = p.size / 2;
      return `<button type="button" class="music-bubble${song.id === bubbleSelectedId?' bubble-active':''}" data-song-id="${song.id}"
        style="--bubble-x:${p.x}px;--bubble-y:${p.y}px;--bubble-size:${p.size}px;--bubble-art:${artGradient(song.title)}"
        aria-label="${escaped(song.title)}, ${escaped(song.artist)}, ${escaped(song.nickname)}님의 추천. 상세 보기">
          <span class="bubble-sphere">${bubbleArtwork(song)}</span>
          <span class="bubble-name">${escaped(song.title)}</span>
          <span class="bubble-artist">${escaped(song.artist)}</span>
          <span class="bubble-dot" aria-hidden="true"></span>
        </button>`;
    }).join('');
    if (bubbleSelectedId !== null) {
      const selected = songs.find(song => song.id === bubbleSelectedId);
      if (selected) renderBubbleDetail(selected); else closeBubbleDetail();
    }
  }
  $('bubbleCanvasEmpty').classList.toggle('hidden', songs.length > 0);
  $('bubbleCanvas').classList.toggle('is-empty', songs.length === 0);
  applyBubbleCamera();
}
function renderBubbleDetail(song) {
  const owned = song.userId === state.user?.id;
  const provider = bubbleProvider(song);
  const art = song.artworkUrl && /^https:\/\//i.test(song.artworkUrl)
    ? `<img src="${escaped(highResArtworkUrl(song.artworkUrl))}" data-original-src="${escaped(song.artworkUrl)}" alt="앨범 커버" loading="lazy" referrerpolicy="no-referrer" onerror="if(!this.dataset.retriedOriginal && this.src !== this.dataset.originalSrc){this.dataset.retriedOriginal='1';this.src=this.dataset.originalSrc;}else{this.parentElement.textContent='♫';}"/>`
    : '<span class="detail-record">♫</span>';
  const range = song.startSeconds !== null && song.startSeconds !== undefined
    ? `<div class="bubble-detail-range">♫ 추천 구간: ${timeLabel(song.startSeconds)}${song.endSeconds !== null ? ' – ' + timeLabel(song.endSeconds) : '부터'}</div>` : '';
  $('bubbleDetailBody').innerHTML = `<div class="bubble-detail-art" style="--bubble-art:${artGradient(song.title)}">${art}</div>
    <p class="bubble-detail-eyebrow">${escaped(provider)} · ${escaped(song.nickname)}님의 추천</p>
    <h3>${escaped(song.title)}</h3><p class="bubble-detail-artist">${escaped(song.artist)}</p>
    ${song.note ? `<p class="bubble-detail-note">“${escaped(song.note)}”</p>` : ''}
    ${range}
    <div class="bubble-detail-actions">
      <button type="button" class="like bubble-like${song.liked ? ' liked':''}" data-action="like" data-id="${song.id}" aria-label="좋아요 ${song.likeCount}개">${song.liked ? '♥' : '♡'} ${song.likeCount}</button>
      ${song.musicUrl ? `<a class="bubble-link" href="${escaped(song.musicUrl)}" target="_blank" rel="noopener noreferrer">${escaped(provider)}에서 보기 ↗</a>` : ''}
      ${song.artworkStoreUrl ? `<a class="bubble-link bubble-link-apple" href="${escaped(song.artworkStoreUrl)}" target="_blank" rel="noopener noreferrer">iTunes Store에서 보기 ↗</a>` : ''}
      ${owned ? `<button type="button" class="icon-plain bubble-delete" data-action="delete" data-id="${song.id}">삭제</button>` : ''}
    </div>`;
  $('bubbleDetail').classList.remove('hidden');
}
function openBubbleDetail(songId) {
  const song = state.songs.find(song => song.id === songId);
  if (!song) return;
  bubbleSelectedId = songId;
  $('bubbleStage').querySelectorAll('.music-bubble').forEach(el => el.classList.toggle('bubble-active', Number(el.dataset.songId)===songId));
  renderBubbleDetail(song);
}
function closeBubbleDetail() {
  bubbleSelectedId = null;
  $('bubbleDetail').classList.add('hidden');
  $('bubbleStage').querySelectorAll('.bubble-active').forEach(el => el.classList.remove('bubble-active'));
}
function openRoomMenu() {
  if (!state.roomCode || roomMenuOpen) return;
  closeAddPanel();
  roomMenuOpen = true;
  $('roomMenu').classList.remove('hidden');
  $('roomMenuBackdrop').classList.remove('hidden');
  $('roomMenuToggle').setAttribute('aria-expanded', 'true');
  $('roomMenuToggle').setAttribute('aria-label', '메뉴 닫기');
  $('roomMenuClose').focus();
}
function closeRoomMenu(restoreFocus = true) {
  const wasOpen = roomMenuOpen;
  roomMenuOpen = false;
  $('roomMenu').classList.add('hidden');
  $('roomMenuBackdrop').classList.add('hidden');
  $('roomMenuToggle').setAttribute('aria-expanded', 'false');
  $('roomMenuToggle').setAttribute('aria-label', '메뉴 열기');
  if (restoreFocus && wasOpen && document.body.classList.contains('room-active')) $('roomMenuToggle').focus();
}
function openAddPanel() {
  closeRoomMenu(false);
  addPanelOpen = true;
  $('addPanel').classList.add('panel-open');
  $('addPanelBackdrop').classList.remove('hidden');
  $('openAddPanel').setAttribute('aria-expanded','true');
  $('closeAddPanel').focus();
}
function closeAddPanel() {
  addPanelOpen = false;
  $('addPanel').classList.remove('panel-open');
  $('addPanelBackdrop').classList.add('hidden');
  $('openAddPanel').setAttribute('aria-expanded','false');
}
function setBubbleZoom(newZoom, clientX, clientY) {
  const viewport = $('bubbleCanvas');
  const rect = viewport.getBoundingClientRect();
  const x = (clientX ?? (rect.left+rect.width/2)) - (rect.left + rect.width/2);
  const y = (clientY ?? (rect.top+rect.height/2)) - (rect.top + rect.height/2);
  const previousZoom = bubbleCanvasCamera.zoom;
  const target = Math.min(2.15, Math.max(.52, newZoom));
  const ratio = target / previousZoom;
  bubbleCanvasCamera.x = x - (x - bubbleCanvasCamera.x) * ratio;
  bubbleCanvasCamera.y = y - (y - bubbleCanvasCamera.y) * ratio;
  bubbleCanvasCamera.zoom = target;
  applyBubbleCamera();
}
function panToSongIndex(index) {
  const position = bubblePosition(index);
  const zoom = bubbleCanvasCamera.zoom;
  bubbleCanvasCamera.x = -position.x * zoom;
  bubbleCanvasCamera.y = -position.y * zoom;
  applyBubbleCamera();
}
function initBubbleCanvas() {
  const viewport = $('bubbleCanvas');
  const stage = $('bubbleStage');
  const localPosition = (event) => {
    const r = viewport.getBoundingClientRect();
    return { x: event.clientX - r.left - r.width/2, y: event.clientY - r.top - r.height/2 };
  };
  stage.addEventListener('click', e => {
    if (suppressBubbleClick) { suppressBubbleClick = false; return; }
    const bubble = e.target.closest('[data-song-id]');
    if (bubble) openBubbleDetail(Number(bubble.dataset.songId));
  });
  viewport.addEventListener('pointerdown', e => {
    if (e.target.closest('.canvas-controls, .bubble-detail, .canvas-empty')) return;
    bubblePointerState.set(e.pointerId, { x:e.clientX, y:e.clientY });
    if (bubblePointerState.size === 1) {
      bubbleDrag = { x:e.clientX, y:e.clientY, originX:bubbleCanvasCamera.x, originY:bubbleCanvasCamera.y, moved:false };
    } else if (bubblePointerState.size === 2) {
      const [p1,p2] = [...bubblePointerState.values()];
      const dx=p1.x-p2.x, dy=p1.y-p2.y;
      bubblePinch = { distance:Math.hypot(dx,dy), zoom:bubbleCanvasCamera.zoom, center:{ x:(p1.x+p2.x)/2, y:(p1.y+p2.y)/2 } };
      bubbleDrag=null;
    }
    if (e.pointerType !== 'mouse') viewport.setPointerCapture(e.pointerId);
  });
  viewport.addEventListener('pointermove', e => {
    if (!bubblePointerState.has(e.pointerId)) return;
    bubblePointerState.set(e.pointerId, { x:e.clientX, y:e.clientY });
    if (bubblePointerState.size === 2 && bubblePinch) {
      const [a,b] = [...bubblePointerState.values()];
      const dx=a.x-b.x,dy=a.y-b.y;
      setBubbleZoom(bubblePinch.zoom * Math.hypot(dx,dy)/bubblePinch.distance, (a.x+b.x)/2,(a.y+b.y)/2);
      suppressBubbleClick = true;
      return;
    }
    if (!bubbleDrag) return;
    const dx=e.clientX-bubbleDrag.x,dy=e.clientY-bubbleDrag.y;
    if (Math.abs(dx) + Math.abs(dy) > 6) {
      bubbleDrag.moved=true;
      if (e.pointerType === 'mouse' && !viewport.hasPointerCapture(e.pointerId)) viewport.setPointerCapture(e.pointerId);
    }
    if (bubbleDrag.moved) {
      bubbleCanvasCamera.x=bubbleDrag.originX+dx;
      bubbleCanvasCamera.y=bubbleDrag.originY+dy;
      viewport.classList.add('is-dragging');
      applyBubbleCamera();
    }
  });
  const releasePointer = e => {
    if (bubbleDrag?.moved || bubblePinch) {
      suppressBubbleClick=true;
      // A synthetic click can follow pointerup; clear suppression after the event loop.
      setTimeout(() => { suppressBubbleClick=false; }, 0);
    }
    bubblePointerState.delete(e.pointerId);
    bubbleDrag=null;
    bubblePinch=null;
    viewport.classList.remove('is-dragging');
    if (viewport.hasPointerCapture(e.pointerId)) viewport.releasePointerCapture(e.pointerId);
  };
  viewport.addEventListener('pointerup',releasePointer);
  viewport.addEventListener('pointercancel',releasePointer);
  viewport.addEventListener('wheel',e=>{if (e.target.closest('.bubble-detail')) return; e.preventDefault(); setBubbleZoom(bubbleCanvasCamera.zoom * (e.deltaY > 0 ? .9 : 1.1), e.clientX,e.clientY);},{passive:false});
  viewport.addEventListener('keydown', e=> {
    if (e.target !== viewport) return;
    const move=65;
    if (e.key==='ArrowLeft') bubbleCanvasCamera.x+=move;
    else if (e.key==='ArrowRight') bubbleCanvasCamera.x-=move;
    else if (e.key==='ArrowUp') bubbleCanvasCamera.y+=move;
    else if (e.key==='ArrowDown') bubbleCanvasCamera.y-=move;
    else if (e.key==='+' || e.key==='=') setBubbleZoom(bubbleCanvasCamera.zoom*1.12);
    else if (e.key==='-') setBubbleZoom(bubbleCanvasCamera.zoom/1.12);
    else return;
    e.preventDefault(); applyBubbleCamera();
  });
  $('bubbleRestoreCovers').addEventListener('click', async () => {
    if (!state.roomCode) return;
    const button = $('bubbleRestoreCovers');
    button.disabled = true;
    try {
      const data = await api(`/api/rooms/${state.roomCode}/covers/restore`, {method:'POST',body:JSON.stringify({retry:true})});
      await refreshRoom();
      toast(data.updated ? `${data.checked}곡을 재검색하여 ${data.updated}곡의 커버를 복구했어!` : `${data.checked}곡 재검색 완료. 일치하는 커버가 아직 없어.`);
    } catch(e) { toast(e.message,true); }
    finally { button.disabled = false; }
  });
  $('bubbleZoomIn').addEventListener('click',()=>setBubbleZoom(bubbleCanvasCamera.zoom*1.2));
  $('bubbleZoomOut').addEventListener('click',()=>setBubbleZoom(bubbleCanvasCamera.zoom/1.2));
  $('bubbleReset').addEventListener('click',()=>{bubbleCanvasCamera={x:0,y:0,zoom:1};applyBubbleCamera();closeBubbleDetail();});
  $('bubbleDiscover').addEventListener('click',()=>{
    if (state.songs.length < 2) return toast('새로운 영역을 탐색하려면 노래를 두 곡 이상 등록해 줘.');
    bubbleRandomIndex = (bubbleRandomIndex + 1 + Math.floor(Math.random()*Math.max(1,state.songs.length-1))) % state.songs.length;
    bubbleCanvasCamera.zoom = 1;
    panToSongIndex(bubbleRandomIndex);
    closeBubbleDetail();
  });
  $('bubbleDetailClose').addEventListener('click',closeBubbleDetail);
  $('bubbleDetail').addEventListener('click',onSongAction);
  $('openAddPanel').addEventListener('click',openAddPanel);
  $('bubbleFirstAdd').addEventListener('click',openAddPanel);
  $('closeAddPanel').addEventListener('click',closeAddPanel);
  $('addPanelBackdrop').addEventListener('click',closeAddPanel);
}
async function createRoom(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    if (!state.user) { showAuth('register'); throw new Error('로그인 후 이용해 줘.'); }
    const name = $('roomName').value.trim();
    if (!name) throw new Error('방 이름을 입력해 주세요.');
    setBusy(form,true);
    const data = await api('/api/rooms',{method:'POST',body:JSON.stringify({name})});
    goToRoom(data.code);
    toast('추천방이 만들어졌어! 초대 링크를 공유해 봐.');
  } catch(e) { toast(e.message, true); }
  finally { setBusy(form,false); }
}
async function joinRoom(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    if (!state.user) { state.pendingInvite = $('roomCodeInput').value.replace(/\s/g,'').toUpperCase(); showAuth('register'); throw new Error('로그인 후 이용해 줘.'); }
    const code = $('roomCodeInput').value.replace(/\s/g,'').toUpperCase();
    if (!/^[A-HJ-NP-Z2-9]{8}$/.test(code)) throw new Error('8자리 초대 코드를 확인해 주세요.');
    setBusy(form,true);
    await api(`/api/rooms/${code}/join`,{method:'POST',body:'{}'});
    goToRoom(code);
    toast('추천방에 입장했어!');
  } catch(e) { toast(e.message,true); }
  finally { setBusy(form,false); }
}
function catalogLabel(catalog) {
  return ({ spotify:'Spotify', apple_music:'Apple Music', itunes_store:'iTunes Store', lastfm:'Last.fm' })[catalog] || '음원 카탈로그';
}
function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return '';
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;
}
function catalogHint() {
  const apple = $('catalogPlatform').value === 'apple';
  $('catalogHint').textContent = apple
    ? 'Apple/iTunes에서 곡·가수·앨범을 검색해. 한국 Apple Music 전체 카탈로그와는 다를 수 있어.'
    : 'Last.fm에서 곡·가수·앨범을 검색해. 일부 커버는 표시되지 않을 수 있어.';
  $('catalogSourceLink').href = apple ? 'https://performance-partners.apple.com/search-api' : 'https://www.last.fm';
  $('catalogSourceLink').textContent = apple ? 'iTunes Search API ↗' : 'Powered by Last.fm ↗';
  $('catalogSearchForm').querySelector('[type="submit"]').disabled = false;
}
function preferSearchPlatform() { catalogHint(); }
function clearSelected() {
  selectedTrack = null;
  $('selectedTrack').innerHTML = '';
  $('selectedTrack').classList.add('hidden');
  $('songFormExtra').classList.add('hidden');
  $('submitSong').disabled = true;
}
function renderSelected(track) {
  const art = track.artworkUrl ? `<img src="${escaped(track.artworkUrl)}" alt="앨범 커버" />` : '<span class="no-art">♫</span>';
  $('selectedTrack').innerHTML = `<div class="chosen-cover">${art}</div><div class="chosen-info"><small>✓ 선택된 음원 · ${escaped(catalogLabel(track.sourceCatalog))}</small><strong>${escaped(track.title)}</strong><span>${escaped(track.artist)}</span><a href="${escaped(track.musicUrl)}" target="_blank" rel="noopener noreferrer">원본 음원 확인 ↗</a>${track.artworkStoreUrl ? `<a href="${escaped(track.artworkStoreUrl)}" target="_blank" rel="noopener noreferrer">iTunes Store에서 보기 ↗</a>` : ''}</div><button class="chosen-clear" type="button" id="clearTrack" aria-label="선택 취소">✕</button>`;
  $('selectedTrack').classList.remove('hidden');
  $('songFormExtra').classList.remove('hidden');
  $('submitSong').disabled = false;
  $('clearTrack').addEventListener('click', clearSelected);
  $('selectedTrack').scrollIntoView({behavior:'smooth',block:'nearest'});
}
// Fill missing covers one song at a time so every search result gets a fair
// lookup, without a blocking request or an Apple API burst.
async function resolveSearchCovers(seq) {
  const indices = catalogResults.map((song, i) =>
    song.sourcePlatform === 'lastfm' && !song.artworkUrl ? i : -1
  ).filter(i => i >= 0).slice(0, 8); // Remaining covers resolve on selection or later retry.
  if (!indices.length) return;
  let checked = 0;
  for (const i of indices) {
    if (seq !== searchCounter) return;
    const original = catalogResults[i];
    if (!original?.selectionToken) return;
    try {
      const data = await api('/api/catalog/cover', {
        method: 'POST', body: JSON.stringify({selectionToken: original.selectionToken})
      });
      if (seq !== searchCounter || !catalogResults[i]) return;
      checked++;
      if (data.found && data.artworkUrl) {
        const updated = {...original, artworkUrl: data.artworkUrl,
          artworkStoreUrl: data.artworkStoreUrl || '', album: data.album || original.album,
          selectionToken: data.selectionToken || original.selectionToken};
        catalogResults[i] = updated;
        const node = $('catalogResults').querySelector(`[data-index="${i}"] .catalog-art`);
        if (node) {
          node.innerHTML = `<img src="${escaped(updated.artworkUrl)}" loading="lazy" alt="앨범 커버" onerror="this.parentElement.textContent='♫'" />`;
        }
        if (selectedTrack?.sourceId === original.sourceId && selectedTrack?.sourcePlatform === 'lastfm') {
          selectedTrack = updated;
          const cover = $('selectedTrack').querySelector('.chosen-cover');
          if (cover) cover.innerHTML = `<img src="${escaped(updated.artworkUrl)}" alt="앨범 커버" onerror="this.parentElement.textContent='♫'" />`;
        }
      }
      if (seq === searchCounter) $('searchStatus').textContent =
        `${catalogResults.length}곡 발견 · 커버 확인 중 ${checked}/${indices.length} · 곡을 눌러 선택해 줘.`;
    } catch (error) {
      if (seq === searchCounter) $('searchStatus').textContent =
        `${catalogResults.length}곡 발견 · 일부 커버 확인에 실패했어. 곡은 그대로 등록할 수 있어.`;
      return;
    }
  }
  if (seq === searchCounter) $('searchStatus').textContent =
    `${catalogResults.length}곡 발견 · 커버 확인 완료 · 곡을 눌러 선택해 줘.`;
}

function artistPortrait(artist, header = false) {
  const initials = escaped(String(artist?.title || '♪').trim().slice(0,2).toUpperCase());
  const src = artist?.artworkUrl ? escaped(artist.artworkUrl) : '';
  const avatarClass = header ? 'catalog-album-cover catalog-artist-header-avatar' : 'catalog-artist-avatar';
  const photo = src ? `<img class="catalog-artist-photo" src="${src}" loading="lazy" referrerpolicy="no-referrer" alt="" onerror="this.remove()" />` : '';
  return `<span class="${avatarClass}" aria-hidden="true"><span class="catalog-artist-initials">${initials}</span>${photo}</span>`;
}

async function resolveArtistPhotos(seq, query) {
  try {
    const data = await api(`/api/catalog/artist-photos?${new URLSearchParams({q:query})}`);
    if (seq !== searchCounter || catalogView !== 'artist-profiles') return;
    const photos = data.photos || {};
    const normalize = value => String(value || '').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
    let updated = false;
    for (const artist of catalogResults) {
      const art = photos[normalize(artist.title)];
      if (art && !artist.artworkUrl) {
        artist.artworkUrl = art;
        updated = true;
      }
    }
    if (updated) renderCatalogResults();
  } catch { /* Portraits are optional; initials always remain usable. */ }
}

function renderArtistAlbums(info) {
  const panel = $('catalogArtistAlbums');
  const albums = Array.isArray(info?.albums) ? info.albums : [];
  panel.classList.remove('hidden');
  if (!albums.length) {
    panel.innerHTML = `<div class="catalog-discography-head"><strong>참여 앨범</strong><small>${escaped(info?.albumError || '카탈로그에서 확인된 앨범이 없어.')}</small></div>`;
    return;
  }
  const cards = albums.map((album,i) => {
    const art = album.artworkUrl
      ? `<img src="${escaped(highResArtworkUrl(album.artworkUrl))}" loading="lazy" alt="" data-original-src="${escaped(album.artworkUrl)}" onerror="if(!this.dataset.fallback){this.dataset.fallback='1';this.src=this.dataset.originalSrc}else{this.remove()}" />`
      : `<span class="catalog-discography-placeholder" aria-hidden="true">♫</span>`;
    const tag = album.participationType === 'credited' ? '참여' : '앨범';
    const year = String(album.releaseDate || '').slice(0,4);
    return `<button type="button" class="catalog-discography-card" data-album-index="${i}" aria-label="${escaped(album.title)} 앨범 수록곡 보기"><span class="catalog-discography-art">${art}</span><strong>${escaped(album.title)}</strong><small>${escaped(album.artist)}${year ? ' · '+escaped(year) : ''}</small><em>${tag}</em></button>`;
  }).join('');
  panel.innerHTML = `<div class="catalog-discography-head"><strong>참여 앨범</strong><small>${albums.length}개 확인 · 앨범을 누르면 수록곡을 볼 수 있어.</small></div><div class="catalog-discography-grid">${cards}</div><div class="catalog-discography-head catalog-artist-track-heading"><strong>아티스트 곡</strong><small>곡 제목을 선택하면 추천할 수 있어.</small></div>`;
}

function hideArtistAlbums() {
  const panel = $('catalogArtistAlbums');
  panel.classList.add('hidden');
  panel.innerHTML = '';
}

// Keep track-selection and album-navigation as separate actions.
// The artwork is a button; the adjacent title/details button still selects
// a track for recommendation. Album-search results open the album either way.
function renderCatalogResults() {
  const isAlbumView = catalogView === 'album-tracks';
  const isArtistProfiles = catalogView === 'artist-profiles';
  const latest = $('catalogResultSort').value === 'recent';
  $('catalogSortRow').classList.toggle('hidden', isArtistProfiles || isAlbumView);
  const entries = catalogResults.map((song,index) => ({song,index}));
  if (isAlbumView) {
    entries.sort((a,b) => {
      const aNum = Number(a.song.trackNumber || 0), bNum = Number(b.song.trackNumber || 0);
      return (aNum && bNum ? aNum-bNum : 0) || a.index-b.index;
    });
  } else {
    entries.sort((a,b) => {
      if (latest && !isArtistProfiles) {
        const dateA = Date.parse(a.song.releaseDate || '') || 0;
        const dateB = Date.parse(b.song.releaseDate || '') || 0;
        if (dateB !== dateA) return dateB - dateA;
      }
      const rankA = Number.isFinite(Number(a.song.searchRank)) ? Number(a.song.searchRank) : a.index;
      const rankB = Number.isFinite(Number(b.song.searchRank)) ? Number(b.song.searchRank) : b.index;
      return rankA - rankB || a.index - b.index;
    });
  }
  $('catalogResults').innerHTML = entries.map(({song,index:i}) => {
    const label = escaped(song.title);
    if (song.itemType === 'artist') {
      const descriptor = song.genre ? escaped(song.genre) : escaped(catalogLabel(song.sourceCatalog));
      return `<div class="catalog-result catalog-artist-result" data-track-index="${i}" role="listitem"><button class="catalog-artist-main" type="button" data-index="${i}" data-catalog-action="artist" aria-label="${label} 아티스트의 앨범과 곡 보기">${artistPortrait(song)}<span class="catalog-result-info"><strong>${label}</strong><span>아티스트 프로필</span><small>${descriptor}</small></span><span class="catalog-choose">프로필 ↗</span></button></div>`;
    }
    const isAlbum = song.itemType === 'album';
    const art = song.artworkUrl
      ? `<img src="${escaped(highResArtworkUrl(song.artworkUrl))}" data-original-src="${escaped(song.artworkUrl)}" loading="lazy" alt="" onerror="if(!this.dataset.retriedOriginal && this.src!==this.dataset.originalSrc){this.dataset.retriedOriginal='1';this.src=this.dataset.originalSrc;}else{this.parentElement.textContent='♫'}" />`
      : '<span class="no-art">♫</span>';
    const details = `<span class="catalog-result-info"><strong>${label}</strong><span>${escaped(song.artist)}</span><small>${isAlbum ? '앨범 · 전체 수록곡' : escaped(catalogLabel(song.sourceCatalog))}${!isAlbum && song.album ? ' · '+escaped(song.album) : ''}${!isAlbum && song.durationMs ? ' · '+formatDuration(song.durationMs) : ''}</small></span>`;
    const artLabel = escaped(isAlbum ? `${song.title} 앨범 수록곡 보기` : `${song.title}의 앨범 수록곡 보기`);
    const cover = isAlbumView
      ? `<span class="catalog-art">${art}</span>`
      : `<button class="catalog-art catalog-art-button" type="button" data-index="${i}" data-catalog-action="album" title="앨범 전체 보기" aria-label="${artLabel}">${art}<span class="album-art-hint" aria-hidden="true">↗</span></button>`;
    const action = isAlbum ? 'album' : 'select';
    const cta = isAlbum ? '수록곡 ↗' : '선택 ↗';
    return `<div class="catalog-result" data-track-index="${i}" role="listitem">${cover}<button type="button" class="catalog-result-main" data-index="${i}" data-catalog-action="${action}" aria-label="${label} ${isAlbum ? '앨범 열기' : '추천곡 선택'}">${details}<span class="catalog-choose">${cta}</span></button></div>`;
  }).join('');
}
function clearAlbumNavigation() {
  catalogHistory = [];
  catalogView = 'search';
  catalogViewInfo = null;
  $('albumBack').classList.add('hidden');
  $('catalogAlbumHeader').classList.add('hidden');
  $('catalogAlbumHeader').innerHTML = '';
  hideArtistAlbums();
  $('catalogSortRow').classList.remove('hidden');
}
function renderAlbumInfo(album) {
  const art = album.artworkUrl
    ? `<img src="${escaped(highResArtworkUrl(album.artworkUrl))}" alt="앨범 커버" referrerpolicy="no-referrer" onerror="if(!this.dataset.retriedOriginal){this.dataset.retriedOriginal='1';this.src='${escaped(album.artworkUrl)}';}else{this.style.display='none'}" />`
    : '<span aria-hidden="true">♫</span>';
  $('catalogAlbumHeader').innerHTML = `<div class="catalog-album-cover">${art}</div><div class="catalog-album-info"><div class="catalog-album-eyebrow">ALBUM · 전체 수록곡</div><strong>${escaped(album.title)}</strong><span>${escaped(album.artist)}</span><small>${Number(album.trackCount)||catalogResults.length}곡 · 곡 제목을 누르면 추천할 수 있어.</small></div>`;
  $('catalogAlbumHeader').classList.remove('hidden');
}
function renderArtistInfo(artist) {
  const genre = artist.genre ? `<span>${escaped(artist.genre)}</span>` : '';
  const external = artist.musicUrl ? `<a href="${escaped(artist.musicUrl)}" target="_blank" rel="noopener noreferrer">아티스트 공식 카탈로그 ↗</a>` : '';
  $('catalogAlbumHeader').innerHTML = `${artistPortrait(artist,true)}<div class="catalog-album-info"><div class="catalog-album-eyebrow">ARTIST · 아티스트 프로필</div><strong>${escaped(artist.title)}</strong>${genre}<small>참여 앨범 ${Number(artist.albumCount)||0}개 · 확인된 곡 ${Number(artist.trackCount)||0}곡</small>${external}</div>`;
  $('catalogAlbumHeader').classList.remove('hidden');
  renderArtistAlbums(artist);
}
function snapshotCatalog() {
  return { results:[...catalogResults], status:$('searchStatus').textContent,
    scroll:$('catalogResults').scrollTop, view:catalogView,
    info:catalogViewInfo ? {...catalogViewInfo} : null };
}
function enterCatalogView(view, results, info, status) {
  catalogHistory.push(snapshotCatalog());
  clearSelected();
  catalogView = view;
  catalogViewInfo = info;
  catalogResults = results;
  $('searchStatus').textContent = status;
  $('albumBack').textContent = view === 'artist-tracks'
    ? '← 아티스트 검색 결과로 돌아가기'
    : '← 이전 결과로 돌아가기';
  $('albumBack').classList.remove('hidden');
  if (view === 'artist-tracks') renderArtistInfo(info);
  else {
    hideArtistAlbums();
    if (view === 'album-tracks') renderAlbumInfo(info);
  }
  renderCatalogResults();
  $('catalogResults').scrollTop = 0;
}
async function openArtistFromResult(artist, trigger) {
  const seq = ++searchCounter;
  const originalStatus = $('searchStatus').textContent;
  $('searchStatus').textContent = `「${artist.title}」 아티스트의 곡을 불러오는 중…`;
  trigger.disabled = true;
  try {
    const result = await api('/api/catalog/artist-tracks', {
      method:'POST', body:JSON.stringify({selectionToken:artist.selectionToken})
    });
    if (seq !== searchCounter) return;
    const info = result.artistInfo || {title:artist.title,genre:artist.genre,musicUrl:artist.musicUrl,
      artworkUrl:artist.artworkUrl, albums:[], albumCount:0, trackCount:result.results?.length||0};
    $('searchStatus').textContent = originalStatus;
    enterCatalogView('artist-tracks',result.results||[],info,
      `「${info.title}」 · 앨범 ${info.albumCount||0}개 · 곡 ${result.results?.length||0}개 · 앨범이나 곡을 선택해 줘.`);
    if (artist.sourcePlatform === 'lastfm') void resolveSearchCovers(seq);
  } catch(error) {
    if (seq !== searchCounter) return;
    $('searchStatus').textContent = error.message;
    toast(error.message,true);
    trigger.disabled = false;
  }
}
async function openAlbumFromResult(song, trigger) {
  const seq = ++searchCounter;
  const existingStatus = $('searchStatus').textContent;
  $('searchStatus').textContent = `「${song.album || song.title}」의 수록곡을 불러오는 중…`;
  trigger.disabled = true;
  try {
    const url = song.itemType === 'album' ? '/api/catalog/album-tracks' : '/api/catalog/track-album';
    const result = await api(url, {
      method:'POST', body:JSON.stringify({selectionToken:song.selectionToken})
    });
    if (seq !== searchCounter) return;
    if (!result.results?.length) throw new Error('이 앨범의 수록곡을 찾지 못했어.');
    // Keep the original search status in the navigation history.
    $('searchStatus').textContent = existingStatus;
    const albumInfo = result.albumInfo || {title:song.album || song.title,artist:song.artist,
      artworkUrl:song.artworkUrl, trackCount:result.results.length};
    enterCatalogView('album-tracks',result.results,albumInfo,
      `「${albumInfo.title}」 · ${result.results.length}곡 · 추천할 곡을 선택해 줘.`);
    if (song.sourcePlatform === 'lastfm') void resolveSearchCovers(seq);
  } catch(error) {
    if (seq !== searchCounter) return;
    $('searchStatus').textContent = error.message;
    toast(error.message,true);
    trigger.disabled = false;
  }
}
function backToAlbumResults() {
  if (!catalogHistory.length) return;
  ++searchCounter;
  clearSelected();
  const previous = catalogHistory.pop();
  catalogResults = previous.results;
  catalogView = previous.view;
  catalogViewInfo = previous.info;
  $('searchStatus').textContent = previous.status;
  if (catalogView === 'artist-tracks') renderArtistInfo(catalogViewInfo);
  else {
    hideArtistAlbums();
    if (catalogView === 'album-tracks') renderAlbumInfo(catalogViewInfo);
    else {
      $('catalogAlbumHeader').classList.add('hidden');
      $('catalogAlbumHeader').innerHTML = '';
    }
  }
  $('albumBack').classList.toggle('hidden', !catalogHistory.length);
  if (catalogHistory.length) $('albumBack').textContent = '← 이전 결과로 돌아가기';
  renderCatalogResults();
  $('catalogResults').scrollTop = previous.scroll;
}
async function searchSongs(event) {
  event.preventDefault();
  const platform = $('catalogPlatform').value;
  const kind = $('catalogSearchMode').value;
  const q = $('songQuery').value.trim();
  const seq = ++searchCounter;
  clearSelected();
  catalogResults = [];
  clearAlbumNavigation();
  $('catalogResults').innerHTML = '';
  if (q.length < 2) return toast('검색어를 2글자 이상 입력해 줘.', true);
  const button = $('catalogSearchForm').querySelector('button[type="submit"]');
  button.disabled = true;
  $('searchStatus').textContent = '음원을 검색하고 있어…';
  try {
    const data = await api(`/api/catalog/search?${new URLSearchParams({platform,q,kind})}`);
    if (seq !== searchCounter) return;
    catalogResults = data.results || [];
    catalogView = kind === 'artist' ? 'artist-profiles' : 'search';
    $('searchStatus').textContent = catalogResults.length
      ? `${catalogResults.length}${kind === 'artist' ? '개 아티스트 프로필 발견 · 프로필을 누르면 해당 아티스트의 곡을 볼 수 있어.' : kind === 'album' ? '개 앨범 발견 · 앨범을 누르면 수록곡을 볼 수 있어.' : '곡 발견 · 인기순(검색 순위 기준)·최신순(발매일 기준)으로 정렬할 수 있어.'}`
      : '검색 결과가 없어. 다른 검색어로 다시 시도해 봐.';
    renderCatalogResults();
    if (kind === 'artist' && catalogResults.length) void resolveArtistPhotos(seq, q);
    if (platform === 'lastfm' && kind === 'track') void resolveSearchCovers(seq);
  } catch (error) {
    if (seq !== searchCounter) return;
    $('searchStatus').textContent = error.message;
    toast(error.message, true);
  } finally {
    if (seq === searchCounter) catalogHint();
  }
}
async function selectSearchResult(event) {
  const trigger = event.target.closest('[data-catalog-action]');
  if (!trigger) return;
  const song = catalogResults[Number(trigger.dataset.index)];
  if (!song?.selectionToken) return;
  if (trigger.dataset.catalogAction === 'artist' || song.itemType === 'artist') {
    await openArtistFromResult(song, trigger);
    return;
  }
  if (trigger.dataset.catalogAction === 'album' || song.itemType === 'album') {
    if (catalogView !== 'album-tracks') await openAlbumFromResult(song, trigger);
    return;
  }
  selectedTrack = song;
  renderSelected(song);
  [...$('catalogResults').querySelectorAll('.catalog-result')].forEach(el =>
    el.classList.toggle('is-selected', Number(el.dataset.trackIndex) === Number(trigger.dataset.index)));
}
async function addSong(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    if (!selectedTrack?.selectionToken) throw new Error('검색 결과에서 음원을 선택해 줘.');
    const startSeconds = parseTime($('startTime').value);
    const endSeconds = parseTime($('endTime').value);
    if (endSeconds !== null && startSeconds === null) throw new Error('시작 구간을 먼저 입력해 주세요.');
    if (endSeconds !== null && endSeconds <= startSeconds) throw new Error('끝 구간은 시작보다 뒤여야 해.');
    setBusy(form,true);
    await api(`/api/rooms/${state.roomCode}/songs`, {method:'POST',body:JSON.stringify({
      selectionToken:selectedTrack.selectionToken,
      note:$('note').value,
      startSeconds, endSeconds
    })});
    form.reset();
    ++searchCounter; // Abort any remaining cover requests from the old search.
    clearSelected();
    catalogResults = [];
    clearAlbumNavigation();
    $('catalogResults').innerHTML = '';
    $('songQuery').value = '';
    $('searchStatus').textContent = '다른 곡을 검색해 추천할 수 있어.';
    await refreshRoom();
    toast('추천곡이 등록됐어!');
    closeAddPanel();
    $('bubbleCanvas').scrollIntoView({behavior:'smooth',block:'center'});
  } catch(e) { toast(e.message,true); }
  finally { setBusy(form,false); }
}
async function onSongAction(event) {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const {action,id} = button.dataset;
  if (action === 'delete' && !confirm('이 추천곡을 삭제할까?')) return;
  button.disabled = true;
  try {
    if (action === 'like') {
      await api(`/api/rooms/${state.roomCode}/songs/${id}/like`, {method:'POST', body:'{}'});
    } else if (action === 'delete') {
      await api(`/api/rooms/${state.roomCode}/songs/${id}`, {method:'DELETE', body:'{}'});
      toast('추천곡을 삭제했어.');
    }
    await refreshRoom();
  } catch(e) { toast(e.message,true); button.disabled = false; }
}
async function copyShare() {
  const url = `${location.origin}/?room=${encodeURIComponent(state.roomCode)}`;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
    } else {
      const input = document.createElement('textarea'); input.value = url;
      document.body.append(input); input.select();
      if (!document.execCommand('copy')) throw new Error('copy failed');
      input.remove();
    }
    toast('초대 링크를 복사했어! 친구에게 보내 줘.');
  } catch { window.prompt('초대 링크를 복사해 줘:',url); }
}
async function init() {
  $('homeBtn').addEventListener('click',showLanding);
  $('accountButton').addEventListener('click', () => state.user ? showProfile() : showAuth());
  $('authForm').addEventListener('submit',submitAuth);
  $('profileForm').addEventListener('submit',submitProfile);
  $('loginTab').addEventListener('click',() => showAuth('login'));
  $('registerTab').addEventListener('click',() => showAuth('register'));
  $('closeAuth').addEventListener('click',hideAuth);
  $('closeProfile').addEventListener('click',hideProfile);
  $('logoutButton').addEventListener('click',logout);
  $('authOverlay').addEventListener('click', e => { if(e.target === e.currentTarget) hideAuth(); });
  $('profileOverlay').addEventListener('click', e => { if(e.target === e.currentTarget) hideProfile(); });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { hideAuth(); hideProfile(); closeBubbleDetail(); closeAddPanel(); closeRoomMenu(); }
    if (e.key === 'Tab' && roomMenuOpen && !$('roomMenu').classList.contains('hidden')) {
      const focusable = [...$('roomMenu').querySelectorAll('button:not(:disabled)')];
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  $('createForm').addEventListener('submit',createRoom);
  $('joinForm').addEventListener('submit',joinRoom);
  $('addSongForm').addEventListener('submit',addSong);
  $('catalogSearchForm').addEventListener('submit', searchSongs);
  $('catalogResultSort').addEventListener('change', () => {
    renderCatalogResults();
    const selectedKey = selectedTrack?.sourceId;
    if (selectedKey) {
      [...$('catalogResults').querySelectorAll('.catalog-result')].forEach(b =>
        b.classList.toggle('is-selected', catalogResults[Number(b.dataset.trackIndex)]?.sourceId === selectedKey));
    }
  });
  $('catalogResults').addEventListener('click', selectSearchResult);
  $('catalogArtistAlbums').addEventListener('click', async event => {
    const trigger = event.target.closest('[data-album-index]');
    if (!trigger || trigger.disabled || catalogView !== 'artist-tracks') return;
    const album = catalogViewInfo?.albums?.[Number(trigger.dataset.albumIndex)];
    if (album?.selectionToken) await openAlbumFromResult(album, trigger);
  });
  $('catalogSearchMode').addEventListener('change', () => { ++searchCounter; clearSelected(); clearAlbumNavigation(); catalogResults=[]; $('catalogResults').innerHTML=''; $('searchStatus').textContent='검색 기준을 변경했어. 다시 검색해 줘.'; });
  $('songQuery').addEventListener('input', () => {
    ++searchCounter;
    clearSelected(); clearAlbumNavigation(); catalogResults = []; $('catalogResults').innerHTML = '';
    $('searchStatus').textContent = '검색 버튼을 눌러 음원을 찾아 줘.';
  });

  initBubbleCanvas();
  $('catalogPlatform').addEventListener('change', () => {++searchCounter;clearSelected();clearAlbumNavigation();catalogResults=[];$('catalogResults').innerHTML='';$('searchStatus').textContent='검색 서비스를 변경했어. 새로 검색해 줘.';catalogHint();});
  $('albumBack').addEventListener('click', backToAlbumResults);
  $('roomMenuToggle').addEventListener('click', () => roomMenuOpen ? closeRoomMenu() : openRoomMenu());
  $('roomMenuClose').addEventListener('click', () => closeRoomMenu());
  $('roomMenuBackdrop').addEventListener('click', () => closeRoomMenu());
  $('shareBtn').addEventListener('click', () => { closeRoomMenu(false); copyShare(); });
  $('roomMenuProfile').addEventListener('click', () => { closeRoomMenu(false); showProfile(); });
  $('roomMenuHome').addEventListener('click', showLanding);
  renderAccount();
  catalogHint();
  try {
    const data = await api('/api/auth/me');
    state.user = data.user;
    renderAccount();
    preferSearchPlatform();
  } catch { /* Not logged in yet */ }
  const invite = new URL(location.href).searchParams.get('room');
  if (invite) {
    const code = invite.replace(/\s/g,'').toUpperCase();
    $('roomCodeInput').value = code;
    if (/^[A-HJ-NP-Z2-9]{8}$/.test(code)) {
      if (state.user) {
        try {
          await api(`/api/rooms/${code}/join`, {method:'POST', body:'{}'});
          goToRoom(code);
        } catch(e) { toast(e.message,true); }
      } else {
        state.pendingInvite = code;
        toast('로그인하면 초대받은 방으로 바로 이동할 수 있어.');
      }
    } else toast('초대 코드가 올바르지 않아.', true);
  }
}
init();
