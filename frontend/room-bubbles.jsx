import React from 'react';
import ReactDOM from 'react-dom';
import BubbleUI from 'react-bubble-ui';
import 'react-bubble-ui/dist/index.css';
import './room-bubbles.css';

// react-bubble-ui 1.1.2 does not expose its scroll container via a ref.
const scrollSelector = '._2MD0k';
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

function SongBubble({song, bubbleSize, selected, onSelect}) {
  return (
    <button type="button" className="music-bubble" data-song-id={song.id}
      aria-pressed={selected} aria-label={song.label} tabIndex={bubbleSize < 44 ? -1 : 0}
      style={{'--bubble-art': song.color}} onClick={event => onSelect(song.id, event)}>
      <span className="bubble-sphere" aria-hidden="true" dangerouslySetInnerHTML={{__html: song.artwork}} />
      {bubbleSize >= 63 && <span className="bubble-name" aria-hidden="true">{song.title}</span>}
    </button>
  );
}

function mount(host, {onSelect, onZoom}) {
  let songs = [];
  let selectedId = null;
  let zoom = 1;
  let drag = null;
  let pinch = null;
  let animation = 0;
  let sizingFrame = 0;
  let viewportSizing = null;
  let ignoreClickUntil = 0;
  let measuredWidth = 0;
  let measuredHeight = 0;
  const pointers = new Map();
  const scroller = () => host.querySelector(scrollSelector);

  function baseSize() {
    return clamp(Math.round(host.clientWidth * .275), 88, 163);
  }

  function minimumZoom() {
    const approxTileArea = .866 * (baseSize() * 1.07) ** 2;
    return clamp(Math.sqrt(host.clientWidth * host.clientHeight / (50 * approxTileArea)), .40, .68);
  }

  function scrollPoint(element) {
    return {
      x: element.scrollLeft / Math.max(1, element.scrollWidth - element.clientWidth),
      y: element.scrollTop / Math.max(1, element.scrollHeight - element.clientHeight)
    };
  }

  function stopAnimation() {
    cancelAnimationFrame(animation);
    animation = 0;
  }

  function onBubbleClick(id, event) {
    if (event.detail === 0 || performance.now() >= ignoreClickUntil) onSelect(id);
  }

  function updateViewportSizes() {
    sizingFrame = 0;
    const bubbles = [...host.querySelectorAll('.music-bubble')];
    const view = scroller();
    if (!viewportSizing || !view) {
      for (const bubble of bubbles) bubble.style.removeProperty('--viewport-bubble-scale');
      return;
    }
    const {size, minSize, edgeMinSize} = viewportSizing;
    const bounds = view.getBoundingClientRect();
    const innerEdge = Math.min(70, Math.min(bounds.width, bounds.height) * .19);
    const outerEdge = Math.min(23, innerEdge * .38);
    const nativeRange = Math.max(1, size - minSize);

    // The original React Bubble UI still places each tile. Reduce only the
    // extra overview enlargement near the visible viewport boundary.
    const scales = bubbles.map(bubble => {
      const tile = bubble.parentElement.getBoundingClientRect();
      if (!tile.width) return 1;
      const x = tile.left + tile.width / 2;
      const y = tile.top + tile.height / 2;
      const edgeDistance = Math.min(x - bounds.left, bounds.right - x, y - bounds.top, bounds.bottom - y);
      const t = clamp((edgeDistance - outerEdge) / Math.max(1, innerEdge - outerEdge), 0, 1);
      const weight = t * t * (3 - 2 * t);
      const nativeFocus = clamp((tile.width - minSize) / nativeRange, 0, 1);
      const unboosted = edgeMinSize + (size - edgeMinSize) * nativeFocus;
      const visibleDiameter = unboosted + (tile.width - unboosted) * weight;
      return Math.min(1, visibleDiameter / tile.width);
    });
    bubbles.forEach((bubble, index) => {
      bubble.style.setProperty('--viewport-bubble-scale', scales[index].toFixed(4));
    });
  }

  function queueViewportSizing() {
    if (!sizingFrame) sizingFrame = requestAnimationFrame(updateViewportSizes);
  }

  host.addEventListener('scroll', event => {
    if (viewportSizing && event.target.matches(scrollSelector)) queueViewportSizing();
  }, {capture: true, passive: true});

  function render({preserve = true} = {}) {
    const width = host.clientWidth;
    const height = host.clientHeight;
    measuredWidth = width;
    measuredHeight = height;
    if (!songs.length || !width || !height) {
      ReactDOM.unmountComponentAtNode(host);
      return;
    }
    const previous = scroller();
    const point = preserve && previous ? scrollPoint(previous) : null;
    const base = baseSize();
    const layoutSize = Math.round(base * zoom);
    const overviewZoom = minimumZoom();
    const overviewProgress = clamp((1 - zoom) / (1 - overviewZoom), 0, 1);
    const overviewBubbleScale = .87;
    const size = Math.round(layoutSize * (1 - (1 - overviewBubbleScale) * overviewProgress));
    const defaultMinSize = Math.max(10, Math.round(base * .21));
    const overviewMinSize = Math.round(base * overviewZoom * overviewBubbleScale * .95);
    // Interpolate the minimum diameter in pixels so distant bubbles grow during zoom-out.
    const minSize = Math.round(zoom >= 1
      ? defaultMinSize * zoom
      : defaultMinSize + (overviewMinSize - defaultMinSize) * overviewProgress);
    viewportSizing = zoom < 1
      ? {size, minSize, edgeMinSize: Math.round(defaultMinSize * zoom)}
      : null;
    const xRadius = Math.min(width * .30, size * (width >= 700 ? 1.16 : .91));
    const yRadius = Math.min(height * .31, size * .99);
    const options = {
      size,
      minSize,
      // Keep the lattice pitch while the smaller overview covers leave wider gaps.
      gutter: Math.max(4, Math.round(layoutSize * .065)) + layoutSize - size,
      numCols: Math.max(2, Math.ceil(Math.sqrt(songs.length)) + (songs.length < 3 ? 1 : 0)),
      xRadius,
      yRadius,
      cornerRadius: Math.min(xRadius, yRadius) * .82,
      fringeWidth: size * .86,
      gravitation: 4.5 * (1 - overviewProgress),
      compact: true,
      provideProps: true
    };
    ReactDOM.render(
      <BubbleUI className="trackroom-bubble-ui" options={options} style={{width:'100%', height:'100%'}}>
        {songs.map(song => <SongBubble key={song.id} song={song} selected={song.id === selectedId} onSelect={onBubbleClick} />)}
      </BubbleUI>,
      host
    );
    const next = scroller();
    if (point && next) {
      next.scrollTo(point.x * (next.scrollWidth - next.clientWidth), point.y * (next.scrollHeight - next.clientHeight));
    }
    queueViewportSizing();
  }

  function setZoom(value) {
    const next = clamp(value, minimumZoom(), 1.65);
    if (Math.abs(next - zoom) < .005) return;
    zoom = next;
    render();
    onZoom(zoom);
  }

  function centre(action = 'auto') {
    const view = scroller();
    if (view) view.scrollTo({
      left: (view.scrollWidth - view.clientWidth) / 2,
      top: (view.scrollHeight - view.clientHeight) / 2,
      behavior: action
    });
  }

  function reset() {
    stopAnimation();
    setZoom(1);
    centre(reducedMotion.matches ? 'auto' : 'smooth');
  }

  function focus(id) {
    stopAnimation();
    setZoom(1);
    const view = scroller();
    const bubble = [...host.querySelectorAll('[data-song-id]')].find(button => Number(button.dataset.songId) === id);
    if (!view || !bubble) return;
    const item = bubble.parentElement;
    const rect = item.getBoundingClientRect();
    const viewRect = view.getBoundingClientRect();
    const transform = new DOMMatrixReadOnly(item.style.transform);
    view.scrollTo({
      left: view.scrollLeft + rect.x + rect.width / 2 - transform.e - (viewRect.x + viewRect.width / 2),
      top: view.scrollTop + rect.y + rect.height / 2 - transform.f - (viewRect.y + viewRect.height / 2),
      behavior: reducedMotion.matches ? 'auto' : 'smooth'
    });
  }

  function setSongs(newSongs, selection) {
    stopAnimation();
    songs = newSongs;
    selectedId = selection;
    render();
  }

  function setSelected(id) {
    if (id === selectedId) return;
    selectedId = id;
    if (songs.length) render();
  }

  function clear() {
    stopAnimation();
    cancelAnimationFrame(sizingFrame);
    sizingFrame = 0;
    viewportSizing = null;
    songs = [];
    selectedId = null;
    zoom = 1;
    pointers.clear();
    drag = pinch = null;
    host.classList.remove('is-dragging');
    ReactDOM.unmountComponentAtNode(host);
    onZoom(zoom);
  }

  function pan(dx, dy) {
    const view = scroller();
    if (view) view.scrollBy(dx, dy);
  }

  function startMomentum(vx, vy) {
    if (reducedMotion.matches) return;
    vx = clamp(vx, -1.4, 1.4);
    vy = clamp(vy, -1.4, 1.4);
    const start = performance.now();
    let previous = start;
    function step(now) {
      const t = clamp((now - start) / 260, 0, 1);
      const time = Math.min(33, now - previous);
      const speed = (1 - t) ** 2;
      previous = now;
      pan(vx * speed * time, vy * speed * time);
      animation = t < 1 ? requestAnimationFrame(step) : 0;
    }
    animation = requestAnimationFrame(step);
  }

  host.addEventListener('pointerdown', event => {
    const view = scroller();
    if (!view || event.button !== 0 || pointers.size >= 2) return;
    stopAnimation();
    pointers.set(event.pointerId, {x:event.clientX, y:event.clientY});
    if (pointers.size === 1) {
      drag = {x:event.clientX, y:event.clientY, left:view.scrollLeft, top:view.scrollTop,
        lastX:event.clientX, lastY:event.clientY, lastTime:event.timeStamp, moved:false, vx:0, vy:0};
    } else {
      const [a, b] = pointers.values();
      pinch = {distance:Math.max(10, Math.hypot(a.x-b.x,a.y-b.y)), zoom};
      drag = null;
      for (const id of pointers.keys()) host.setPointerCapture(id);
    }
  });

  host.addEventListener('pointermove', event => {
    if (!pointers.has(event.pointerId)) return;
    const view = scroller();
    if (!view) return;
    pointers.set(event.pointerId, {x:event.clientX, y:event.clientY});
    if (pinch && pointers.size === 2) {
      const [a, b] = pointers.values();
      setZoom(pinch.zoom * Math.hypot(a.x-b.x,a.y-b.y) / pinch.distance);
      return;
    }
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 6) return;
    if (!drag.moved) {
      host.setPointerCapture(event.pointerId);
      host.classList.add('is-dragging');
      drag.moved = true;
    }
    const dt = Math.max(9, event.timeStamp - drag.lastTime);
    drag.vx = drag.vx * .45 + (drag.lastX - event.clientX) / dt * .55;
    drag.vy = drag.vy * .45 + (drag.lastY - event.clientY) / dt * .55;
    drag.lastTime = event.timeStamp;
    drag.lastX = event.clientX;
    drag.lastY = event.clientY;
    view.scrollTo(drag.left-dx, drag.top-dy);
  });

  function release(event) {
    if (!pointers.delete(event.pointerId)) return;
    if (pinch || drag?.moved) ignoreClickUntil = performance.now() + 160;
    if (drag?.moved && event.type === 'pointerup' && event.timeStamp - drag.lastTime < 90) {
      startMomentum(drag.vx, drag.vy);
    }
    if (!pointers.size) pinch = null;
    drag = null;
    host.classList.remove('is-dragging');
  }

  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) host.addEventListener(type, release);
  host.addEventListener('pointerleave', event => {
    if (!host.hasPointerCapture(event.pointerId)) release(event);
  });
  host.addEventListener('wheel', event => {
    if (!songs.length) return;
    event.preventDefault();
    stopAnimation();
    if (event.deltaX || event.shiftKey) pan(event.deltaX || event.deltaY, event.shiftKey ? 0 : event.deltaY);
    else if (event.deltaY) setZoom(zoom * (event.deltaY > 0 ? .9 : 1.1));
  }, {passive:false});
  host.addEventListener('dragstart', event => event.preventDefault());

  new ResizeObserver(() => {
    if (host.clientWidth === measuredWidth && host.clientHeight === measuredHeight) return;
    zoom = Math.max(minimumZoom(), zoom);
    render();
    onZoom(zoom);
  }).observe(host);

  return {setSongs, setSelected, clear, reset, focus, pan, zoomBy: factor => setZoom(zoom * factor)};
}

window.TrackroomRoomBubbles = {mount};
