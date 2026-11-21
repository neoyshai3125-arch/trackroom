from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
class TestDrawerStyleReliability(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.html=(ROOT/'public/index.html').read_text(encoding='utf-8')
    cls.css=(ROOT/'public/room-search-home.css').read_text(encoding='utf-8')
    cls.sw=(ROOT/'public/sw.js').read_text(encoding='utf-8')
  def test_inline_design_stays_available_if_stylesheet_404(self):
    self.assertIn('<style id="room-search-v698-critical">',self.html)
    self.assertIn('#addPanel .room-search-querybar',self.html)
    self.assertIn('#addPanel #catalogSearchForm .room-search-field > svg',self.html.replace('#addPanel .room-search-field > svg','#addPanel #catalogSearchForm .room-search-field > svg'))
    self.assertNotIn('<link rel="stylesheet" href="/room-search-home.css',self.html)
    self.assertNotIn('/room-search-home.css?v=',self.sw)
  def test_no_svg_size_regression(self):
    self.assertRegex(self.html,r'<svg width="20" height="20" viewBox="0 0 24 24"')
    self.assertIn('max-width: 22px',self.css)
    self.assertIn('max-width:18px',self.css)
  def test_no_room_state_dependency_for_add_panel(self):
    self.assertNotIn('body.room-active #addPanel',self.css)
    self.assertIn('#addPanel {',self.css)
    self.assertIn('background: linear-gradient(',self.css)
  def test_cache_version(self):
    self.assertIn('trackroom-shell-v6.9.9',self.sw)
    self.assertIn('v6.9.9</span>',self.html)
  def test_existing_controls_present(self):
    for key in ('catalogSearchForm','songQuery','catalogSearchMode','room-search-tabs','catalogResults','addSongForm','submitSong'):
      self.assertIn(key,self.html)
if __name__=='__main__':unittest.main()
