"""v6.9.4: the entire record is the scratch input surface."""
from pathlib import Path
import unittest
R = Path(__file__).resolve().parents[1]
class TestFullDiscScrub(unittest.TestCase):
    def test_full_circle_hit_area_and_pause_button_stacking(self):
        css=(R/'public/room-bubbles.css').read_text()
        self.assertIn('.room-playback-dial {',css)
        segment=css[css.rindex('/* v6.9.4:'):]
        self.assertIn('inset: 0;', segment)
        self.assertIn('pointer-events: auto;', segment)
        self.assertIn('touch-action: none;', segment)
        self.assertIn('z-index: 4;', segment)
        self.assertNotIn('--room-scratch-rotation', segment)
        self.assertNotIn('pointer-events: stroke;',segment)
    def test_relative_angle_and_pointer_capture(self):
        js=(R/'public/app.js').read_text()
        self.assertIn('shortestPlaybackTurn(angle, current.angle)',js)
        self.assertIn('current.position + change / (2 * Math.PI) * duration',js)
        self.assertNotIn('roomPlaybackRotation',js)
        self.assertIn('dial.setPointerCapture(event.pointerId)',js)
        self.assertIn('if (commit) dashboard.seekPreview(position)',js)
        self.assertIn('current.moved',js)
        self.assertIn("event.key === 'Home'",js)
    def test_version_and_hit_target_description(self):
        html=(R/'public/index.html').read_text()
        sw=(R/'public/sw.js').read_text()
        self.assertIn('앨범 커버를 돌려 재생 위치 조절',html)
        self.assertIn('v6.9.7</span>',html)
        self.assertIn("'trackroom-shell-v6.9.7'",sw)
if __name__=='__main__': unittest.main()
