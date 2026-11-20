import tempfile
import threading
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from test_server import Client, app


class TestHome(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.previous_path = app.DB_PATH
        app.DB_PATH = Path(cls.directory.name) / 'home.sqlite3'
        app.init_db()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        app.DB_PATH = cls.previous_path
        cls.directory.cleanup()

    def register(self, name):
        client = Client(self.base)
        user = client.request('POST', '/api/auth/register', {
            'username': name, 'nickname': name, 'password': 'test-password-123', 'platform': 'apple'
        }, expected=201)['user']
        return client, user

    def test_home_lists_only_joined_rooms_and_actual_recent_and_liked_tracks(self):
        Client(self.base).request('GET', '/api/home', expected=401)
        member, user = self.register('homefirst')
        outsider, other = self.register('homeother')
        code = member.request('POST', '/api/rooms', {'name': '기존 추천방'}, expected=201)['code']
        private = outsider.request('POST', '/api/rooms', {'name': '다른 방'}, expected=201)['code']
        with app.db() as conn:
            for room, person, title in [(code, user, '첫 곡'), (code, user, '새 곡'), (private, other, '다른 방 곡')]:
                conn.execute('INSERT INTO songs(room_code,user_id,nickname,title,artist,created_at) VALUES(?,?,?,?,?,?)',
                             (room, person['id'], person['nickname'], title, '음악가', app.now()))
            track = conn.execute('SELECT id FROM songs WHERE title=?', ('첫 곡',)).fetchone()
            conn.execute('INSERT INTO likes VALUES (?,?)', (track['id'], user['id']))
        dashboard = member.request('GET', '/api/home')
        self.assertEqual([room['code'] for room in dashboard['rooms']], [code])
        self.assertEqual([song['title'] for song in dashboard['recentSongs']], ['새 곡', '첫 곡'])
        self.assertEqual([song['title'] for song in dashboard['popularSongs']], ['첫 곡'])
        self.assertEqual(dashboard['recentSongs'][0]['room']['name'], '기존 추천방')

    def test_preview_accepts_catalog_metadata_and_never_arbitrary_hosts(self):
        member, _ = self.register('homepreview')
        media_url = 'https://audio-ssl.itunes.apple.com/itunes-assets/clip.m4a'
        row = {'trackId': 10071, 'kind': 'song', 'trackName': 'Test song', 'artistName': 'Test artist',
               'trackViewUrl': 'https://music.apple.com/us/song/example/10071',
               'previewUrl': media_url}
        with patch.object(app, 'request_json', return_value={'results': [row]}):
            self.assertEqual(member.request('GET', '/api/catalog/preview?trackId=10071')['track']['previewUrl'], media_url)
        row['previewUrl'] = 'https://example.org/audio.m4a'
        row['trackId'] = 10072
        with patch.object(app, 'request_json', return_value={'results': [row]}):
            member.request('GET', '/api/catalog/preview?trackId=10072', expected=404)
        member.request('GET', '/api/catalog/preview?trackId=bad', expected=422)

    def test_room_preview_checks_membership_and_matches_the_saved_version(self):
        member, user = self.register('previewmember')
        outsider, _ = self.register('previewoutside')
        code = member.request('POST', '/api/rooms', {'name': '미리듣기'}, expected=201)['code']
        with app.db() as conn:
            conn.execute('INSERT INTO songs(room_code,user_id,nickname,title,artist,created_at) VALUES(?,?,?,?,?,?)',
                         (code, user['id'], user['nickname'], 'Blue Night', 'Ari', app.now()))
            song = conn.execute('SELECT id FROM songs WHERE room_code=?', (code,)).fetchone()
        endpoint = f"/api/rooms/{code}/songs/{song['id']}/preview"
        track = {'trackId': 511, 'kind': 'song', 'trackName': 'Blue Night', 'artistName': 'Ari',
                 'trackViewUrl': 'https://music.apple.com/us/song/blue-night/511',
                 'previewUrl': 'https://audio-ssl.itunes.apple.com/itunes-assets/511.m4a'}
        wrong = {**track, 'trackId': 512, 'trackName': 'Blue Night (Live)',
                 'previewUrl': 'https://audio-ssl.itunes.apple.com/itunes-assets/512.m4a'}
        with patch.object(app, 'apple_search_request', return_value=[wrong, track]) as provider:
            outsider.request('GET', endpoint, expected=403)
            provider.assert_not_called()
            result = member.request('GET', endpoint)['track']
            self.assertEqual(result['sourceId'], '511')
            self.assertEqual(result['previewUrl'], track['previewUrl'])
            member.request('GET', endpoint)
            provider.assert_called_once()
