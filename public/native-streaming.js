// TRACKROOM v6.10.0: Android MediaSession sync. No notification text/audio is collected.
(() => {
  'use strict';
  const enabled = /TRACKROOMAndroid\/0\.1/.test(navigator.userAgent);
  const SERVICES = [
    ['melon','멜론'], ['genie','지니뮤직'], ['flo','FLO'],
    ['bugs','벅스'], ['youtube','YouTube Music'], ['spotify','Spotify']
  ];
  const STORAGE = 'trackroom.stream.provider';
  let snapshot = null;
  if (enabled) document.documentElement.classList.add('trackroom-android');

  function preferred() {
    let stored = '';
    try { stored = localStorage.getItem(STORAGE) || ''; } catch {}
    const profile = window.TRACKROOM_USER_PLATFORM || '';
    return SERVICES.some(x => x[0] === stored) ? stored :
      SERVICES.some(x => x[0] === profile) ? profile : 'melon';
  }
  const safeHTML = value => String(value ?? '').replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const formatTime = ms => {
    if (!Number.isFinite(ms) || ms < 0) return '--:--';
    const secs = Math.floor(ms / 1000);
    return `${Math.floor(secs/60)}:${String(secs%60).padStart(2,'0')}`;
  };
  const buttonText = p => p === 'spotify' ? 'Spotify에서 재생' : '음악 앱에서 재생';

  function controls(track) {
    if (!enabled || !track) return '';
    const options = SERVICES.map(([id,name]) =>
      `<option value="${id}" ${preferred()===id?'selected':''}>${safeHTML(name)}</option>`).join('');
    return `<section class="trackroom-stream-box" data-trackroom-stream="1"
      data-track-title="${safeHTML(String(track.title || '').slice(0,160))}"
      data-track-artist="${safeHTML(String(track.artist || '').slice(0,160))}">
      <label class="trackroom-stream-label">내 스트리밍 앱으로 듣기</label>
      <div class="trackroom-stream-row">
        <select class="trackroom-stream-select" aria-label="연결할 스트리밍 앱">${options}</select>
        <button class="trackroom-stream-play" type="button" data-trackroom-stream-play="1">${buttonText(preferred())}</button>
      </div>
      <section class="trackroom-media-panel" aria-label="외부 음악 앱 재생 상태">
        <div class="trackroom-media-head"><b>앱 재생 상태 동기화</b><span class="trackroom-media-chip" data-media-badge>확인 중</span></div>
        <div class="trackroom-media-now">
          <b class="trackroom-media-track" data-media-title>연결 상태 확인 중</b>
          <small class="trackroom-media-artist" data-media-artist></small>
          <small class="trackroom-media-desc" data-media-description>TRACKROOM은 음악 앱의 오디오를 복사하거나 저장하지 않아.</small>
        </div>
        <button type="button" class="trackroom-media-permission" data-media-permission hidden>안드로이드 알림 접근 권한 연결</button>
        <button type="button" class="trackroom-media-refresh" data-media-refresh>상태 새로고침</button>
        <div class="trackroom-media-player" data-media-player hidden>
          <input class="trackroom-media-seek" data-media-seek type="range" min="0" max="100" step="1000" value="0" aria-label="외부 음악 앱 재생 위치" />
          <div class="trackroom-media-time"><span data-media-time>--:--</span><span data-media-duration>--:--</span></div>
          <div class="trackroom-media-buttons">
            <button type="button" data-media-command="previous" aria-label="이전 곡">⏮</button>
            <button type="button" data-media-command="play" aria-label="재생">▶</button>
            <button type="button" data-media-command="pause" aria-label="일시정지" hidden>Ⅱ</button>
            <button type="button" data-media-command="next" aria-label="다음 곡">⏭</button>
          </div>
          <button type="button" class="trackroom-media-search" data-media-command="playFromSearch" hidden>이 추천곡 재생 요청</button>
          <small class="trackroom-media-support" data-media-support></small>
        </div>
      </section>
      <small class="trackroom-stream-hint">멜론 등: 지원되는 MediaSession 제어 · Spotify: 별도 계정 인증 API도 사용 가능. 곡 자동 재생은 앱 지원 여부에 따라 달라져.</small>
    </section>`;
  }

  function send(action, values = {}) {
    if (!enabled) return false;
    const params = new URLSearchParams({action, ...values});
    window.location.assign(`trackroom-native://media?${params.toString()}`);
    return true;
  }
  function play(track, provider) {
    if (!enabled || !track?.title || !track?.artist) return false;
    if (!SERVICES.some(s => s[0] === provider)) return false;
    const params = new URLSearchParams({provider,
      title:String(track.title).slice(0,160), artist:String(track.artist).slice(0,160),
      musicUrl:String(track.musicUrl || '').slice(0,900)});
    window.TrackroomPauseLocalPreview?.();
    window.location.assign(`trackroom-native://play?${params.toString()}`);
    return true;
  }

  function updatePanels() {
    if (!enabled) return;
    const selected = preferred();
    document.querySelectorAll('[data-trackroom-stream]').forEach(panel => {
      const status = panel.querySelector('[data-media-badge]');
      const title = panel.querySelector('[data-media-title]');
      const artist = panel.querySelector('[data-media-artist]');
      const desc = panel.querySelector('[data-media-description]');
      const permission = panel.querySelector('[data-media-permission]');
      const refresh = panel.querySelector('[data-media-refresh]');
      const player = panel.querySelector('[data-media-player]');
      if (!status || !title || !permission || !player) return;
      const matches = snapshot?.provider === selected;
      const canRead = matches && snapshot.permission === true;
      const connected = canRead && snapshot.connected === true;
      status.textContent = !snapshot || !matches ? '확인 중' : !canRead ? '권한 필요' : connected ? '연결됨' : '재생 대기';
      status.dataset.status = connected ? 'connected' : !canRead ? 'permission' : 'waiting';
      permission.hidden = canRead || !matches && !!snapshot;
      refresh.hidden = !canRead && matches;
      player.hidden = !connected;
      if (!canRead) {
        title.textContent = 'Android 음악 재생 정보 연결';
        artist.textContent = '';
        desc.textContent = '사용자가 알림 접근 권한을 허용해야 음악 앱의 MediaSession을 읽을 수 있어.';
      } else if (!connected) {
        title.textContent = `${snapshot.providerName || '음악 앱'}에서 재생 중인 곡이 없어`;
        artist.textContent = '';
        desc.textContent = '음악 앱을 열고 먼저 아무 곡이나 재생한 뒤 상태를 새로고침해 줘.';
      } else {
        title.textContent = snapshot.title || '곡 제목을 제공하지 않음';
        artist.textContent = [snapshot.artist,snapshot.album].filter(Boolean).join(' · ');
        desc.textContent = snapshot.state === 'playing' ? '음악 앱에서 재생 중' : snapshot.state === 'paused' ? '음악 앱에서 일시정지됨' : '재생 상태 확인 중';
        const seek = panel.querySelector('[data-media-seek]');
        const duration = Math.max(0, Number(snapshot.durationMs) || 0);
        const position = Math.max(0, Number(snapshot.positionMs) || 0);
        if (seek && seek.dataset.dragging !== 'yes') {
          seek.max = String(Math.max(1, duration));
          seek.value = String(Math.min(duration || 1, position));
          seek.disabled = !snapshot.canSeek || !duration;
        }
        panel.querySelector('[data-media-time]').textContent = formatTime(snapshot.positionMs);
        panel.querySelector('[data-media-duration]').textContent = formatTime(duration);
        const playing = snapshot.state === 'playing';
        const playBtn = panel.querySelector('[data-media-command="play"]');
        const pauseBtn = panel.querySelector('[data-media-command="pause"]');
        playBtn.hidden = playing;
        pauseBtn.hidden = !playing;
        playBtn.disabled = !snapshot.canPlay;
        pauseBtn.disabled = !snapshot.canPause;
        panel.querySelector('[data-media-command="next"]').disabled = !snapshot.canNext;
        panel.querySelector('[data-media-command="previous"]').disabled = !snapshot.canPrevious;
        const searchBtn = panel.querySelector('[data-media-command="playFromSearch"]');
        searchBtn.hidden = !snapshot.canPlayFromSearch;
        panel.querySelector('[data-media-support]').textContent = snapshot.canPlayFromSearch
          ? '곡 검색 재생 명령 지원 표시됨 · 실제 정확한 곡 재생 여부는 확인 필요'
          : '이 앱은 곡 지정 검색 재생을 지원한다고 표시하지 않았어.';
      }
    });
  }

  function bind(root) {
    if (!enabled || !root) return;
    root.querySelectorAll('[data-trackroom-stream]').forEach(panel => {
      const select = panel.querySelector('.trackroom-stream-select');
      if (!select || select.dataset.bound) return;
      select.dataset.bound = '1';
      select.value = preferred();
      select.addEventListener('change', () => {
        if (!SERVICES.some(s => s[0] === select.value)) return;
        try { localStorage.setItem(STORAGE, select.value); } catch {}
        snapshot = null;
        document.querySelectorAll('.trackroom-stream-select').forEach(s => {
          s.value = select.value;
          const btn = s.closest('[data-trackroom-stream]')?.querySelector('.trackroom-stream-play');
          if (btn) btn.textContent = buttonText(select.value);
        });
        updatePanels();
        send('select', {provider:select.value});
      });
    });
    updatePanels();
    if (!snapshot) send('sync', {provider:preferred()});
  }

  // User-initiated commands only. Nothing is automatically dispatched to music apps.
  document.addEventListener('click', event => {
    const btn = event.target.closest('[data-trackroom-stream-play], [data-media-command], [data-media-permission], [data-media-refresh]');
    if (!btn || !enabled) return;
    const panel = btn.closest('[data-trackroom-stream]');
    if (!panel) return;
    event.preventDefault();
    const provider = panel.querySelector('.trackroom-stream-select')?.value || preferred();
    if (btn.matches('[data-media-permission]')) return send('permission', {provider});
    if (btn.matches('[data-media-refresh]')) return send('sync', {provider});
    if (btn.matches('[data-media-command]')) {
      if (btn.disabled) return;
      const action = btn.dataset.mediaCommand;
      if (action === 'playFromSearch') return send(action, {provider,
        title:panel.dataset.trackTitle || '', artist:panel.dataset.trackArtist || ''});
      return send(action, {provider});
    }
    if (!btn.matches('[data-trackroom-stream-play]')) return;
    let track = null;
    if (panel.closest('#bubbleDetail')) {
      track = window.TrackroomRoomStreamSongById?.(window.TrackroomRoomStreamSelectedId?.());
    } else if (panel.closest('#roomPlaybackOverlay')) {
      track = window.TrackroomRoomStreamActiveSong?.();
    }
    if (!track) track = {title:panel.dataset.trackTitle, artist:panel.dataset.trackArtist};
    window.dispatchEvent(new CustomEvent('trackroom:external-stream', {detail:{provider,track}}));
    play(track, provider);
  });

  document.addEventListener('input', event => {
    if (event.target.matches?.('[data-media-seek]')) event.target.dataset.dragging = 'yes';
  });
  document.addEventListener('change', event => {
    const seek = event.target;
    if (!seek.matches?.('[data-media-seek]')) return;
    const panel = seek.closest('[data-trackroom-stream]');
    seek.dataset.dragging = 'no';
    if (panel && snapshot?.canSeek) send('seek', {
      provider:panel.querySelector('.trackroom-stream-select')?.value || preferred(),
      toMs:String(Math.max(0,Math.round(Number(seek.value)||0)))
    });
  });
  window.addEventListener('trackroom:media-session', event => {
    const state = event.detail;
    if (!state || typeof state !== 'object' || typeof state.provider !== 'string') return;
    snapshot = state;
    updatePanels();
  });
  window.addEventListener('trackroom:native-result', event => {
    const data = event.detail || {};
    if (typeof data.message === 'string') window.TrackroomNativeStatus?.(data.message, !data.ok);
  });
  document.addEventListener('DOMContentLoaded', () => { if (enabled) send('sync', {provider:preferred()}); });
  window.TrackroomStreaming = {enabled,controls,bind,play,preferred,send,formatTime,state:()=>snapshot};
})();
