"""Integration tests: use a temporary database and local HTTP port."""
import http.cookiejar
import importlib.util
import json
import socket
import tempfile
import threading
from unittest.mock import patch
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('trackroom', ROOT / 'server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class Client:
    def __init__(self, base):
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, method, path, payload=None, expected=200):
        body = json.dumps(payload).encode('utf-8') if payload is not None else None
        req = urllib.request.Request(self.base + path, method=method, data=body,
                                     headers={'Content-Type': 'application/json'} if body is not None else {})
        try:
            response = self.opener.open(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            obj = json.loads(response.read())
            if response.status != expected:
                raise AssertionError(f'{method} {path}: expected {expected}, got {response.status}: {obj}')
            return obj


class TestAuthAndRooms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        app.DB_PATH = Path(cls.temp.name) / 'testing.sqlite3'
        app.init_db()
        cls.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_address[1])
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def test_registration_login_profile_and_permissions(self):
        a, b, anon = Client(self.base), Client(self.base), Client(self.base)
        self.assertIn('로그인', anon.request('GET', '/api/auth/me', expected=401)['error'])
        user = a.request('POST', '/api/auth/register', {
            'username': 'listener_1', 'password': 'test-password123',
            'nickname': '첫청취자', 'platform': 'spotify'
        }, 201)['user']
        self.assertEqual(user['platform'], 'spotify')
        self.assertNotIn('password_hash', user)
        self.assertEqual(a.request('GET', '/api/auth/me')['user']['nickname'], '첫청취자')
        self.assertEqual(b.request('POST', '/api/auth/register', {
            'username': 'listener_1', 'password': 'test-password123', 'nickname': '중복', 'platform': 'melon'
        }, 409)['error'][:2], '이미')
        b.request('POST', '/api/auth/register', {
            'username': 'listener_2', 'password': 'test-password987', 'nickname': '두번째', 'platform': 'melon'
        }, 201)
        room = a.request('POST', '/api/rooms', {'name': '오노추방'}, 201)['code']
        self.assertEqual(b.request('GET', f'/api/rooms/{room}', expected=403)['error'], '방에 먼저 참여해 주세요.')
        b.request('POST', f'/api/rooms/{room}/join', {})
        # A user can't invent songs or forge catalog metadata.
        self.assertIn('검색', a.request('POST', f'/api/rooms/{room}/songs', {
            'title':'가짜노래', 'artist':'가짜가수'}, 400)['error'])
        verified = {'sourcePlatform':'apple', 'sourceCatalog':'itunes_store',
            'sourceId':'123456', 'title':'공식 노래', 'artist':'실제 아티스트',
            'album':'앨범', 'musicUrl':'https://itunes.apple.com/kr/album/test/id123456?i=123456',
            'artworkUrl':'https://is1-ssl.mzstatic.com/image/test.jpg',
            'durationMs':180000, 'isrc':''}
        with patch.object(app, 'search_catalog', return_value=[verified]) as stub:
            result = a.request('GET', '/api/catalog/search?platform=apple&q=%EA%B3%B5%EC%8B%9D')
        stub.assert_called_once()
        selected = result['results'][0]
        self.assertEqual(selected['sourceId'], '123456')
        a.request('POST', f'/api/rooms/{room}/songs', {
            'selectionToken': selected['selectionToken'],
            'title':'임의로_조작한_제목', 'artist':'조작한_가수',
            'startSeconds': 80, 'endSeconds': 110,
            'userId': b.request('GET', '/api/auth/me')['user']['id'], 'nickname': '위조'
        }, 201)
        songs = b.request('GET', f'/api/rooms/{room}')['songs']
        self.assertEqual(songs[0]['nickname'], '첫청취자')
        self.assertEqual(songs[0]['title'], '공식 노래')
        self.assertEqual(songs[0]['sourceId'], '123456')
        self.assertEqual(songs[0]['userId'], user['id'])
        song_id = songs[0]['id']
        self.assertEqual(b.request('DELETE', f'/api/rooms/{room}/songs/{song_id}', {}, 403)['error'],
                         '내가 등록한 추천곡만 삭제할 수 있습니다.')
        b.request('POST', f'/api/rooms/{room}/songs/{song_id}/like', {})
        self.assertEqual(a.request('GET', f'/api/rooms/{room}')['songs'][0]['likeCount'], 1)
        profile = a.request('PATCH', '/api/auth/profile', {'nickname': '변경됨', 'platform': 'apple'})['user']
        self.assertEqual(profile['platform'], 'apple')
        self.assertEqual(b.request('GET', f'/api/rooms/{room}')['songs'][0]['nickname'], '변경됨')
        a.request('POST', '/api/auth/logout', {})
        a.request('GET', '/api/auth/me', expected=401)
        a.request('POST', '/api/auth/login', {'username': 'listener_1', 'password': 'wrongpass'}, expected=401)
        self.assertEqual(a.request('POST', '/api/auth/login', {
            'username': 'LISTENER_1', 'password': 'test-password123'
        })['user']['nickname'], '변경됨')
        a.request('DELETE', f'/api/rooms/{room}/songs/{song_id}', {})
        self.assertEqual(a.request('GET', f'/api/rooms/{room}')['songs'], [])

    def test_input_validation_and_html(self):
        a = Client(self.base)
        self.assertEqual(a.request('GET', '/health')['ok'], True)
        req = urllib.request.urlopen(self.base + '/')
        self.assertIn(b'authOverlay', req.read())
        self.assertEqual(a.request('POST', '/api/auth/register', {
            'username': 'invaliduser', 'password': '123', 'nickname': 'X', 'platform': 'spotify'
        }, 400)['error'][:4], '비밀번호')
        self.assertIn('음원 플랫폼', a.request('POST', '/api/auth/register', {
            'username': 'validuser', 'password': 'abc123456789', 'nickname': 'X', 'platform': 'fake'
        }, 400)['error'])
        self.assertEqual(a.request('POST', '/api/rooms', {'name': 'x'}, 401)['error'], '로그인이 필요합니다.')

    def test_search_requires_login_and_supported_platform(self):
        anon = Client(self.base)
        self.assertEqual(anon.request('GET', '/api/catalog/search?platform=apple&q=hello', expected=401)['error'], '로그인이 필요합니다.')
        logged = Client(self.base)
        logged.request('POST', '/api/auth/register', {
            'username': 'music_searcher', 'password': 'testingpassword123',
            'nickname': '음악탐색', 'platform': 'melon'
        }, 201)
        self.assertEqual(logged.request('GET', '/api/catalog/search?platform=melon&q=hello', expected=422)['error'],
                         '이 플랫폼에서는 아직 사이트 내 검색을 제공하지 않아.')
        fake = {'sourcePlatform':'apple','sourceCatalog':'itunes_store','sourceId':'x123',
                'title':'진짜 음악', 'artist':'진짜 가수','musicUrl':'https://itunes.apple.com/kr/test'}
        with patch.object(app,'search_catalog',return_value=[fake]):
            chosen = logged.request('GET','/api/catalog/search?platform=apple&q=%EC%9D%8C%EC%95%85')['results'][0]
        room = logged.request('POST','/api/rooms',{'name':'검색 검증'},201)['code']
        token = chosen['selectionToken']
        self.assertEqual(logged.request('POST',f'/api/rooms/{room}/songs',{'selectionToken':token[:-3]+'abc'},400)['error'][:3], '선택한')
        # The track selection belongs to the user who performed the catalog search.
        other = Client(self.base)
        other.request('POST','/api/auth/register',{'username':'other_searcher','password':'password000000',
                                               'nickname':'다른사람','platform':'apple'},201)
        other.request('POST',f'/api/rooms/{room}/join',{})
        self.assertEqual(other.request('POST',f'/api/rooms/{room}/songs',{'selectionToken':token},400)['error'][:5], '음원 선택')


if __name__ == '__main__':
    unittest.main(verbosity=2)
