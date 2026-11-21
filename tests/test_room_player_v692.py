"""Static contract for TRACKROOM v6.9.8 playback controls and PWA assets."""
from pathlib import Path
from unittest import TestCase
from html.parser import HTMLParser
ROOT = Path(__file__).resolve().parents[1]

class ElementCount(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = {}
    def handle_starttag(self, tag, attributes):
        attr = dict(attributes)
        if 'id' in attr:
            self.ids[attr['id']] = self.ids.get(attr['id'], 0) + 1

class TestRoomPlayerV693(TestCase):
    def test_single_reused_bar_and_external_nav(self):
        markup = (ROOT / 'public/index.html').read_text()
        parser = ElementCount(); parser.feed(markup)
        for key in ('roomPreviewBar','roomPlaybackPrevious','roomPlaybackNext','roomPlaybackToggle','roomPlaybackOverlay'):
            self.assertEqual(parser.ids.get(key),1,key)
        self.assertIn('room-playback-wheel', markup)
        self.assertIn('id="roomPlaybackDial"',markup)
        self.assertIn('id="roomPlaybackHandle"',markup)
        self.assertIn('aria-label="다음 곡 셔플"', markup)
        self.assertIn('v6.9.8</span>',markup)

    def test_app_reuses_same_player_not_duplicate_audio(self):
        script=(ROOT/'public/app.js').read_text()
        self.assertIn('overlay.appendChild(bar)',script)
        self.assertIn('overlay.parentElement.insertBefore(bar, overlay)',script)
        self.assertIn("playbackOverlay.addEventListener('close', restoreRoomPreviewBar)",script)
        self.assertIn('initRoomPlaybackDial();',script)
        self.assertIn('dashboard.seekPreview(position)',script)
        self.assertIn("$('roomPlaybackPrevious').addEventListener('click', () => roomPreviewAction('previous'))",script)
        self.assertIn("$('roomPlaybackNext').addEventListener('click', () => roomPreviewAction('next'))",script)

    def test_visual_geometry_and_version(self):
        css=(ROOT/'public/room-bubbles.css').read_text()
        self.assertIn('1.14',css)
        self.assertIn('*.76',css.replace(' ',''))
        self.assertIn('.room-playback-side',css)
        self.assertIn('.room-playback-overlay[open] > .room-preview-bar',css)
        self.assertIn('background: transparent;',css)
        sw=(ROOT/'public/sw.js').read_text()
        self.assertIn('trackroom-shell-v6.9.8',sw)
