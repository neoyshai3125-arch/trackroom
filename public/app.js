const $ = (id) => document.getElementById(id);
const state = { roomCode: null, room: null, songs: [], sort: 'recent', user: null, pendingInvite: null, authMode: 'login' };
let refreshTimer = null;
let toastTimer = null;

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
}
function showLanding() {
  state.roomCode = null;
  state.room = null;
  clearInterval(refreshTimer);
  $('landing').classList.remove('hidden');
  $('landingFooter').classList.remove('hidden');
  $('roomView').classList.add('hidden');
  history.replaceState({}, '', '/');

  window.scrollTo({top:0,behavior:'smooth'});
}
function goToRoom(code) {
  state.roomCode = code;
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
function renderSongs() {
  const list = [...state.songs];
  if (state.sort === 'likes') list.sort((a,b)=> b.likeCount-a.likeCount || b.id-a.id);
  if (!list.length) {
    $('songList').innerHTML = `<div class="empty-list"><div class="empty-icon">✳</div><h3>아직 추천된 노래가 없어</h3><p>첫 번째 노래를 등록해서<br>이 방의 플레이리스트를 시작해 봐!</p></div>`;
    return;
  }
  $('songList').innerHTML = list.map(song => {
    const owned = song.userId === state.user?.id;
    const range = song.startSeconds !== null ? `<span class="song-timerange">♫ ${timeLabel(song.startSeconds)}${song.endSeconds !== null ? ' – '+timeLabel(song.endSeconds) : '부터'}</span>` : '';
    const link = song.musicUrl ? `<a href="${escaped(song.musicUrl)}" target="_blank" rel="noopener noreferrer" class="song-link">${escaped(sourceLabel(song.musicUrl))}에서 보기 ↗</a>` : '';
    return `<article class="song-card" data-id="${song.id}">
      <div class="song-card-top">
        <div class="song-art" style="--art:${artGradient(song.title)}" aria-hidden="true"></div>
        <div class="song-info"><h3>${escaped(song.title)}</h3><p>${escaped(song.artist)}</p><div class="song-by"><strong>${escaped(song.nickname)}</strong>의 추천 · ${new Date(song.createdAt).toLocaleDateString('ko-KR',{month:'short',day:'numeric'})}</div></div>
      </div>
      ${song.note ? `<div class="song-note">“${escaped(song.note)}”</div>` : ''}
      <div class="song-bottom"><div class="song-extras">${link}${range}</div><div class="song-actions">
        ${owned ? `<button class="icon-plain" data-action="delete" data-id="${song.id}" aria-label="노래 삭제">삭제</button>` : ''}
        <button class="like ${song.liked?'liked':''}" data-action="like" data-id="${song.id}" aria-label="좋아요 ${song.likeCount}개"><span>${song.liked?'♥':'♡'}</span> ${song.likeCount}</button>
      </div></div>
    </article>`;
  }).join('');
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
async function addSong(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const startSeconds = parseTime($('startTime').value);
    const endSeconds = parseTime($('endTime').value);
    if (endSeconds !== null && startSeconds === null) throw new Error('시작 구간을 먼저 입력해 주세요.');
    if (endSeconds !== null && endSeconds <= startSeconds) throw new Error('끝 구간은 시작보다 뒤여야 해.');
    setBusy(form,true);
    await api(`/api/rooms/${state.roomCode}/songs`, {method:'POST',body:JSON.stringify({
      title:$('songTitle').value.trim(), artist:$('artist').value.trim(),
      note:$('note').value, musicUrl:$('musicUrl').value.trim(),
      startSeconds, endSeconds
    })});
    form.reset();
    await refreshRoom();
    toast('추천곡이 등록됐어!');
    if (window.innerWidth < 721) $('songList').scrollIntoView({behavior:'smooth',block:'start'});
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
function setSort(sort) {
  state.sort = sort;
  $('sortRecent').classList.toggle('active',sort==='recent');
  $('sortLikes').classList.toggle('active',sort==='likes');
  renderSongs();
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
  document.addEventListener('keydown', e => { if(e.key==='Escape') { hideAuth(); hideProfile(); } });
  $('createForm').addEventListener('submit',createRoom);
  $('joinForm').addEventListener('submit',joinRoom);
  $('addSongForm').addEventListener('submit',addSong);
  $('songList').addEventListener('click',onSongAction);
  $('shareBtn').addEventListener('click',copyShare);
  $('sortRecent').addEventListener('click',()=>setSort('recent'));
  $('sortLikes').addEventListener('click',()=>setSort('likes'));
  renderAccount();
  try {
    const data = await api('/api/auth/me');
    state.user = data.user;
    renderAccount();
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
