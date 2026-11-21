"""Regression checks for v6.9.9 design and existing song-add behavior."""
from pathlib import Path
from html.parser import HTMLParser
import unittest

ROOT=Path(__file__).resolve().parents[1]

class PageInspector(HTMLParser):
    def __init__(self):
        super().__init__();self.ids={};self.stack=[];self.forms=[];self.bad_nesting=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs: self.ids[attrs['id']]=self.ids.get(attrs['id'],0)+1
        if tag=='form':
            if self.forms: self.bad_nesting.append(attrs.get('id','unknown'))
            self.forms.append(attrs.get('id'))
    def handle_endtag(self,tag):
        if tag=='form' and self.forms:self.forms.pop()

class TestAddMusicDrawerDesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(ROOT/'public/index.html').read_text()
        cls.js=(ROOT/'public/app.js').read_text()
        cls.css=(ROOT/'public/room-search-home.css').read_text()
    def test_single_controls_and_no_nested_forms(self):
        parsed=PageInspector();parsed.feed(self.html)
        self.assertFalse(parsed.bad_nesting)
        for control in ('catalogSearchForm','songQuery','catalogSearchMode','catalogResultSort',
                        'searchStatus','catalogResults','selectedTrack','selectedSongLinks',
                        'roomCatalogFilters','catalogPlatform','catalogSourceLink','catalogHint',
                        'note','startTime','endTime','submitSong','addSongForm'):
            self.assertEqual(parsed.ids.get(control),1,control)
    def test_preview_design_elements_present(self):
        for fragment in ('음악 추가하기','방에 공유할 곡을 찾아보세요','room-search-field',
                         'room-search-tabs','data-catalog-mode="track"','data-catalog-mode="artist"',
                         'data-catalog-mode="album"','room-result-topline','room-add-footer',
                         'room-song-extras','선택한 곡 추가하기'):
            self.assertIn(fragment,self.html)
        for fragment in ('#addPanel','background:var(--room-panel-purple)',
                         '.catalog-result.dash-row.is-selected','.catalog-result.is-selected .catalog-choose.room-result-pick',
                         '#addPanel #addSongForm.room-add-footer', '@media(max-width:640px)'):
            self.assertIn(fragment,self.css)
    def test_workflow_preserved(self):
        for fragment in ('/api/catalog/search?', '/api/catalog/album-tracks',
                         '/api/catalog/artist-tracks', '/api/rooms/${state.roomCode}/songs',
                         'renderSelected(song)', 'selectedTrack.selectionToken',
                         'roomSearchFilters.params()', 'catalogSourceLink',
                         "$('selectedSongLinks').innerHTML", 'aria-pressed'):
            self.assertIn(fragment,self.js)
        self.assertIn('syncSearchTabs()',self.js)
        self.assertIn("'change', {bubbles:true}",self.js)
        self.assertIn('const startSeconds = parseTime',self.js)
        self.assertIn('const endSeconds = parseTime',self.js)
    def test_cache_version(self):
        sw=(ROOT/'public/sw.js').read_text()
        self.assertIn('trackroom-shell-v6.9.9',sw)
        self.assertIn('<style id="room-search-v698-critical">',self.html)
        self.assertIn('v6.9.9</span>',self.html)
