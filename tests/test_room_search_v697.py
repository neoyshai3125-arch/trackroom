"""Room add-song search uses the same controls and rows as the home discovery page."""
from html.parser import HTMLParser
from pathlib import Path
from unittest import TestCase
ROOT=Path(__file__).resolve().parents[1]

class Counter(HTMLParser):
    def __init__(self):
        super().__init__(); self.ids={}
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if attrs.get('id'): self.ids[attrs['id']]=self.ids.get(attrs['id'],0)+1

class TestRoomSearchMatchesHome(TestCase):
    def test_unique_forms_and_search_controls(self):
        html=(ROOT/'public/index.html').read_text()
        parser=Counter(); parser.feed(html)
        for name in ('catalogSearchForm','songQuery','catalogSearchMode','catalogPlatform',
                     'roomCatalogFilters','catalogSourceLink','catalogHint','catalogResults',
                     'selectedTrack','addSongForm','submitSong','dashSearchForm'):
            self.assertEqual(parser.ids.get(name),1,name)
        self.assertIn('class="catalog-search-form room-home-search"',html)
        self.assertIn('<option value="track">곡</option>',html)
        self.assertIn('<option value="artist">아티스트</option>',html)
        self.assertIn('<option value="album">앨범</option>',html)
        self.assertIn('/room-search-home.css?v=6.9.7',html)
    def test_results_use_home_row_structure_and_keep_room_actions(self):
        js=(ROOT/'public/app.js').read_text()
        for expected in ('catalog-result dash-row','catalog-artist-result dash-row',
                         'catalog-result-info dash-row-text','dash-row-chevron',
                         'data-catalog-action="${action}"','data-catalog-action="album"',
                         'renderSelected(song)','/api/rooms/${state.roomCode}/songs'):
            self.assertIn(expected,js)
        self.assertIn('current.position + change / (2 * Math.PI) * duration',js)
    def test_home_style_reuse_is_room_scoped_and_caches_bust(self):
        css=(ROOT/'public/room-search-home.css').read_text()
        self.assertIn('body.room-active #catalogSearchForm',css)
        self.assertIn('body.room-active #addPanel .catalog-result.dash-row',css)
        self.assertIn('background:var(--room-panel-purple)',css)
        sw=(ROOT/'public/sw.js').read_text()
        self.assertIn("trackroom-shell-v6.9.7",sw)
        self.assertIn('/room-search-home.css?v=6.9.7',sw)
