"""v6.9.9: circular seek remains, the artwork itself never spins."""
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]

class TestStationaryAlbumArt(TestCase):
    def test_scrub_updates_playback_without_rotating_image(self):
        js = (ROOT / 'public/app.js').read_text()
        self.assertIn('const change = shortestPlaybackTurn(angle, current.angle);', js)
        self.assertIn('current.position + change / (2 * Math.PI) * duration', js)
        self.assertIn('renderRoomPlaybackDial();', js)
        self.assertIn('if (commit) dashboard.seekPreview(position);', js)
        self.assertIn('dial.setPointerCapture(event.pointerId);', js)
        self.assertNotIn('roomPlaybackRotation', js)
        self.assertNotIn('room-scratch-rotation', js)

    def test_art_stays_fixed_in_both_stylesheets(self):
        for path in ('public/room-bubbles.css', 'frontend/room-bubbles.css'):
            css = (ROOT / path).read_text()
            self.assertIn('.room-playback-dial.scrubbing { cursor: grabbing; }', css)
            self.assertIn('.room-playback-cover > img,', css)
            self.assertNotIn('--room-scratch-rotation', css)

    def test_cache_and_visible_version(self):
        html = (ROOT / 'public/index.html').read_text()
        sw = (ROOT / 'public/sw.js').read_text()
        self.assertIn('v6.9.9</span>', html)
        self.assertIn('/app.js?v=6.9.9', html)
        self.assertIn('trackroom-shell-v6.9.9', sw)
        self.assertIn('/room-bubbles.css?v=6.9.9', sw)
