// TRACKROOM v6.9.9: native Android playback hand-off. No audio files are copied.
(() => {
  'use strict';
  const enabled = /TRACKROOMAndroid\/0\.1/.test(navigator.userAgent);
  const SERVICES = [
    ['spotify','Spotify'], ['melon','멜론'], ['genie','지니뮤직'],
    ['flo','FLO'], ['bugs','벅스'], ['youtube','YouTube Music']
  ];
  const STORAGE = 'trackroom.stream.provider';
  const buttonText = p => p === 'spotify' ? 'Spotify 재생' : '앱에서 곡 찾기';
  if (enabled) document.documentElement.classList.add('trackroom-android');
  const preferred = () => {
    let stored = null;
    try { stored = localStorage.getItem(STORAGE); } catch {}
    const profile = window.TRACKROOM_USER_PLATFORM || '';
    return SERVICES.some(x => x[0] === stored) ? stored :
      SERVICES.some(x => x[0] === profile) ? profile : 'spotify';
  };
  function safeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function controls(track, slot = false) {
    if (!enabled || (!track && !slot)) return '';
    const options = SERVICES.map(([id,name]) =>
      `<option value="${id}" ${preferred()===id?'selected':''}>${safeHTML(name)}</option>`).join('');
    return `<section class="trackroom-stream-box" data-trackroom-stream="1">
      <label class="trackroom-stream-label">내 스트리밍 앱으로 듣기</label>
      <div class="trackroom-stream-row">
        <select class="trackroom-stream-select" aria-label="연결할 스트리밍 앱">${options}</select>
        <button class="trackroom-stream-play" type="button" data-trackroom-stream-play="1">${buttonText(preferred())}</button>
      </div>
      <small class="trackroom-stream-hint">Spotify: 계정 인증 후 곡 재생 · 그 외: 곡 페이지 또는 검색 열기</small>
    </section>`;
  }
  function bind(root) {
    if (!enabled || !root) return;
    root.querySelectorAll('[data-trackroom-stream]').forEach(el => {
      const dropdown = el.querySelector('.trackroom-stream-select');
      if (!dropdown || dropdown.dataset.bound) return;
      dropdown.dataset.bound = '1';
      dropdown.value = preferred();
      const updateText = box => {
        const select = box.querySelector('.trackroom-stream-select');
        const button = box.querySelector('.trackroom-stream-play');
        if (select && button) button.textContent = buttonText(select.value);
      };
      updateText(el);
      dropdown.addEventListener('change', () => {
        try { localStorage.setItem(STORAGE,dropdown.value); } catch {}
        document.querySelectorAll('.trackroom-stream-select').forEach(s => {
          if (s !== dropdown) s.value = dropdown.value;
          updateText(s.closest('[data-trackroom-stream]'));
        });
      });
    });
  }
  function play(track, provider) {
    if (!enabled || !track?.title || !track?.artist) return false;
    if (!SERVICES.some(s => s[0] === provider)) return false;
    const p = new URLSearchParams({
      provider, title:String(track.title).slice(0,160), artist:String(track.artist).slice(0,160),
      musicUrl:String(track.musicUrl || '').slice(0,900)
    });
    // Android WebView's main-frame navigation interceptor handles this private URI.
    window.location.assign(`trackroom-native://play?${p.toString()}`);
    return true;
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-trackroom-stream-play]');
    if (!button || !enabled) return;
    const root = button.closest('[data-trackroom-stream]');
    const provider = root?.querySelector('.trackroom-stream-select')?.value || preferred();
    let track = null;
    if (root?.closest('#bubbleDetail')) {
      const id = window.TrackroomRoomStreamSelectedId?.();
      track = window.TrackroomRoomStreamSongById?.(id);
    } else if (root?.closest('#roomPlaybackOverlay')) {
      track = window.TrackroomRoomStreamActiveSong?.();
    }
    if (!track) return;
    event.preventDefault();
    window.dispatchEvent(new CustomEvent('trackroom:external-stream', {detail:{provider,track}}));
    play(track, provider);
  });
  window.addEventListener('trackroom:native-result', event => {
    const data = event.detail || {};
    if (typeof data.message === 'string') {
      const e = document.querySelector('#streamNativeStatus');
      if (e) e.textContent = data.message;
      // app.js toast function is lexical; expose a callback via a second window event if desired.
      if (window.TrackroomNativeStatus) window.TrackroomNativeStatus(data.message, !data.ok);
    }
  });
  window.TrackroomStreaming = { enabled, controls, bind, play, preferred };
})();
