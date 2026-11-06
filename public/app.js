const $ = (id) => document.getElementById(id);
const state = { roomCode: null, room: null, songs: [], sort: 'recent', nickname: localStorage.getItem('tr_nickname') || '', userId: localStorage.getItem('tr_user_id') };
if (!state.userId) {
  state.userId = (crypto.randomUUID?.() || `user-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  localStorage.setItem('tr_user_id', state.userId);
}
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
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  let data;
  try { data = await response.json(); } catch { throw new Error('서버 응답을 읽지 못했습니다.'); }
  if (!response.ok) throw new Error(data.error || `오류가 발생했습니다. (${response.status})`);
  return data;
}
function nick() {
  const value = $('nickname').value.trim();
  if (!value) { $('nickname').focus(); throw new Error('닉네임을 먼저 입력해 주세요.'); }
  localStorage.setItem('tr_nickname', value);
  state.nickname = value;
  return value;
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
  $('nickname').value = state.nickname;
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
  if (!state.roomCode) return;
  const roomCode = state.roomCode;
  try {
    const data = await api(`/api/rooms/${roomCode}?userId=${encodeURIComponent(state.userId)}`);
    if (state.roomCode !== roomCode) return;
    state.room = data.room;
    state.songs = data.songs;
    $('roomTitle').textContent = data.room.name;
    $('roomCodeText').textContent = data.room.code;
    $('memberCount').textContent = data.room.memberCount;
    $('songTotal').textContent = data.songs.length;
    document.title = `${data.room.name} · TRACKROOM`;
    renderSongs();
  } catch (error) { toast(error.message, true); }
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
    const owned = song.userId === state.userId;
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
    const nickname = nick();
    const name = $('roomName').value.trim();
    if (!name) throw new Error('방 이름을 입력해 주세요.');
    setBusy(form,true);
    const data = await api('/api/rooms',{method:'POST',body:JSON.stringify({name,nickname,userId:state.userId})});
    goToRoom(data.code);
    toast('추천방이 만들어졌어! 초대 링크를 공유해 봐.');
  } catch(e) { toast(e.message, true); }
  finally { setBusy(form,false); }
}
async function joinRoom(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const nickname = nick();
    const code = $('roomCodeInput').value.replace(/\s/g,'').toUpperCase();
    if (!/^[A-HJ-NP-Z2-9]{8}$/.test(code)) throw new Error('8자리 초대 코드를 확인해 주세요.');
    setBusy(form,true);
    await api(`/api/rooms/${code}/join`,{method:'POST',body:JSON.stringify({userId:state.userId,nickname})});
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
      userId:state.userId, nickname:state.nickname,
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
      await api(`/api/rooms/${state.roomCode}/songs/${id}/like`, {method:'POST', body:JSON.stringify({userId:state.userId})});
    } else if (action === 'delete') {
      await api(`/api/rooms/${state.roomCode}/songs/${id}`, {method:'DELETE', body:JSON.stringify({userId:state.userId})});
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
  $('nickname').value = state.nickname;
  $('homeBtn').addEventListener('click',showLanding);
  $('createForm').addEventListener('submit',createRoom);
  $('joinForm').addEventListener('submit',joinRoom);
  $('addSongForm').addEventListener('submit',addSong);
  $('songList').addEventListener('click',onSongAction);
  $('shareBtn').addEventListener('click',copyShare);
  $('sortRecent').addEventListener('click',()=>setSort('recent'));
  $('sortLikes').addEventListener('click',()=>setSort('likes'));
  const code = new URL(location.href).searchParams.get('room');
  if (code) {
    $('roomCodeInput').value = code.toUpperCase();
    try { await api(`/api/rooms/${encodeURIComponent(code.toUpperCase())}`); }
    catch(e) { toast(e.message,true); return; }
    if (state.nickname) {
      try {
        await api(`/api/rooms/${encodeURIComponent(code.toUpperCase())}/join`,{method:'POST',body:JSON.stringify({userId:state.userId,nickname:state.nickname})});
        goToRoom(code.toUpperCase());
      } catch(e) { toast(e.message,true); }
    } else { toast('닉네임을 입력하고 추천방에 참여해 줘.'); }
  }
}
init();
