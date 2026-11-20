"""Genre and storefront coverage through the signed public search routes."""
import importlib.util
from pathlib import Path
import tempfile
import threading
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from test_server import Client

spec = importlib.util.spec_from_file_location('trackroom_catalog_filters', Path(__file__).resolve().parents[1] / 'server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
app.APPLE_MIN_INTERVAL = 0


def result(track_id, genre, country='KR'):
    return {'kind': 'song', 'trackId': track_id, 'trackName': f'Song {track_id}',
            'artistName': 'Filter Artist', 'collectionName': 'Filter Album',
            'collectionId': 701, 'artistId': 901, 'primaryGenreName': genre,
            'trackViewUrl': f'https://music.apple.com/{country.lower()}/album/example/701?i={track_id}'}


class TestCatalogFilters(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        app.DB_PATH = Path(cls.temp_dir.name) / 'catalog-filter-test.sqlite3'
        app.init_db()
        cls.httpd = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.client = Client('http://127.0.0.1:' + str(cls.httpd.server_address[1]))
        cls.client.request('POST', '/api/auth/register', {
            'username': 'catalogfilters', 'password': 'filter-test-password',
            'nickname': '필터 검색', 'platform': 'apple'
        }, 201)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)
        cls.temp_dir.cleanup()

    def search(self, expected=200, **filters):
        params = {'platform': 'apple', 'kind': 'track', 'q': 'Search Genre Example', **filters}
        return self.client.request('GET', '/api/catalog/search?' + urlencode(params), expected=expected)

    def test_storefront_and_genre_are_applied_before_the_result_limit(self):
        calls = []

        def query(url, **kwargs):
            options = parse_qs(urlsplit(url).query)
            calls.append(options)
            if options['entity'] != ['song']:
                return {'results': []}
            country = options['country'][0]
            genres = ['Pop'] * 60 + ['ヒップホップ／ラップ', '힙합/랩', 'Hip-Hop/Rap'] * 20
            return {'results': [result(i + 1000, name, country) for i, name in enumerate(genres)]}

        with patch.object(app, 'request_json', side_effect=query):
            first = self.search(country='KR', genre='hip-hop')['results']
            same_store = self.search(country='KR', genre='pop')['results']
            other_store = self.search(country='JP', genre='hip-hop')['results']
            again = self.search(country='KR', genre='hip-hop')['results']

        self.assertEqual(len(first), 50)
        self.assertEqual(len(same_store), 50)
        self.assertEqual(first[0]['sourceId'], '1060')
        self.assertEqual(same_store[0]['sourceId'], '1000')
        self.assertTrue(all(row['storeCountry'] == 'KR' and row['genre'] != 'Pop' for row in first))
        self.assertTrue(all(row['storeCountry'] == 'JP' for row in other_store))
        self.assertEqual([row['sourceId'] for row in first], [row['sourceId'] for row in again])
        self.assertEqual([p['country'][0] for p in calls], ['KR', 'KR', 'JP'])

    def test_filtered_album_and_artist_keep_working_on_their_original_storefront(self):
        calls = []
        artist = {'wrapperType': 'artist', 'artistId': 901, 'artistName': 'Filter Artist',
                  'primaryGenreName': 'Jazz', 'artistLinkUrl': 'https://music.apple.com/gb/artist/filter-artist/901'}
        album = {'wrapperType': 'collection', 'collectionId': 701, 'collectionName': 'Filter Album',
                 'artistName': 'Filter Artist', 'primaryGenreName': 'Jazz',
                 'collectionViewUrl': 'https://music.apple.com/gb/album/example/701'}

        def query(url, **kwargs):
            parts = urlsplit(url)
            if parts.hostname != 'itunes.apple.com':
                return {'data': []}
            options = parse_qs(parts.query)
            calls.append(options)
            if options['entity'] == ['musicArtist']:
                return {'results': [artist, {**artist, 'artistId': 92, 'primaryGenreName': 'Rock'}]}
            if options['entity'] == ['album']:
                return {'results': [album, {**album, 'collectionId': 72, 'collectionName': 'Rock Album',
                                             'primaryGenreName': 'Rock'}]}
            return {'results': [result(2000, 'Jazz', 'GB')]}

        with patch.object(app, 'request_json', side_effect=query):
            albums = self.search(country='GB', genre='jazz', kind='album')['results']
            self.assertEqual(len(albums), 1)
            album_tracks = self.client.request('POST', '/api/catalog/album-tracks',
                                               {'selectionToken': albums[0]['selectionToken']})['results']
            artists = self.search(country='GB', genre='jazz', kind='artist')['results']
            self.assertEqual(len(artists), 1)
            artist_tracks = self.client.request('POST', '/api/catalog/artist-tracks',
                                                {'selectionToken': artists[0]['selectionToken']})['results']
        self.assertTrue(album_tracks and artist_tracks)
        self.assertTrue(all(p['country'] == ['GB'] for p in calls))

    def test_invalid_or_unavailable_filters_do_not_call_the_provider(self):
        with patch.object(app, 'request_json') as query:
            self.search(expected=422, country='ZZ')
            self.search(expected=422, genre='made-up')
            self.search(expected=422, platform='spotify', genre='rock')
        query.assert_not_called()
