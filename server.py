#!/usr/bin/env python3
"""TRACKROOM: music recommendations, password login and stored profile (Python stdlib)."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / 'public'
DB_PATH = Path(os.environ.get('TRACKROOM_DB', str(ROOT / 'trackroom.sqlite3')))
DATABASE_URL = os.environ.get('DATABASE_URL', '')
PORT = int(os.environ.get('PORT', '8000'))
HOST = os.environ.get('HOST', '0.0.0.0')
ROOM_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
PLATFORMS = ('spotify', 'apple', 'melon', 'genie', 'flo', 'bugs', 'youtube', 'other', 'none')
SESSION_AGE = 60 * 60 * 24 * 30
ATTEMPTS = {}
ATTEMPTS_LOCK = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat()


class PgCompat:
    """Minimal DB-API compatibility so the same handlers work with PostgreSQL."""
    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, values=()):
        return self.conn.execute(query.replace('?', '%s'), values)


@contextmanager
def db():
    if DATABASE_URL:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError('DATABASE_URL을 사용하려면 pip install -r requirements.txt가 필요합니다.') from exc
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15, sslmode='require')
        try:
            with conn.transaction():
                yield PgCompat(conn)
        finally:
            conn.close()
        return
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    if not DATABASE_URL:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        if not DATABASE_URL:
            conn.execute('PRAGMA journal_mode=WAL')
        schema = '''
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
          password_salt TEXT NOT NULL, password_hash TEXT NOT NULL,
          nickname TEXT NOT NULL, platform TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
        CREATE TABLE IF NOT EXISTS rooms (
          code TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS members (
          room_code TEXT NOT NULL REFERENCES rooms(code) ON DELETE CASCADE,
          user_id TEXT NOT NULL, nickname TEXT NOT NULL,
          joined_at TEXT NOT NULL, PRIMARY KEY(room_code, user_id)
        );
        CREATE TABLE IF NOT EXISTS songs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          room_code TEXT NOT NULL REFERENCES rooms(code) ON DELETE CASCADE,
          user_id TEXT NOT NULL, nickname TEXT NOT NULL,
          title TEXT NOT NULL, artist TEXT NOT NULL,
          music_url TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
          start_seconds INTEGER, end_seconds INTEGER, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS likes (
          song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL, PRIMARY KEY(song_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS songs_room ON songs(room_code, id DESC);
        '''
        if DATABASE_URL:
            schema = schema.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY')
            for statement in schema.split(';'):
                if statement.strip():
                    conn.execute(statement)
            # Public API roles must not read/write password hashes or session records.
            for table in ('users', 'sessions', 'rooms', 'members', 'songs', 'likes'):
                conn.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        else:
            conn.executescript(schema)


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def required_string(data, key, limit):
    value = data.get(key, '')
    if not isinstance(value, str):
        raise APIError(f'{key} 값이 올바르지 않습니다.')
    value = value.strip()
    if not value or len(value) > limit:
        raise APIError(f'{key} 값은 1~{limit}자여야 합니다.')
    return value


def optional_string(data, key, limit):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit:
        raise APIError(f'{key} 값은 {limit}자 이하여야 합니다.')
    return value.strip()


def validated_platform(data):
    platform = data.get('platform', 'none')
    if platform not in PLATFORMS:
        raise APIError('음원 플랫폼을 선택해 주세요.')
    return platform


def validated_username(data):
    username = required_string(data, 'username', 24).lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,23}', username):
        raise APIError('아이디는 영문 소문자·숫자·._-를 사용해 3~24자로 입력해 주세요.')
    return username


def validated_password(data):
    password = data.get('password', '')
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise APIError('비밀번호는 10~128자로 입력해 주세요.')
    return password


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 400_000).hex()


def clean_code(code):
    code = code.upper()
    if not re.fullmatch(r'[A-HJ-NP-Z2-9]{8}', code):
        raise APIError('방 코드가 올바르지 않습니다.', 404)
    return code


def check_room(conn, code):
    room = conn.execute('SELECT * FROM rooms WHERE code=?', (code,)).fetchone()
    if not room:
        raise APIError('방을 찾을 수 없습니다. 초대 코드를 확인해 주세요.', 404)
    return room


def check_member(conn, code, user_id):
    if not conn.execute('SELECT 1 FROM members WHERE room_code=? AND user_id=?', (code, user_id)).fetchone():
        raise APIError('방에 먼저 참여해 주세요.', 403)


def user_data(user):
    return {'id': user['id'], 'username': user['username'],
            'nickname': user['nickname'], 'platform': user['platform']}


def list_room(conn, code, user_id):
    room = check_room(conn, code)
    check_member(conn, code, user_id)
    member_count = conn.execute('SELECT count(*) AS n FROM members WHERE room_code=?', (code,)).fetchone()['n']
    song_rows = conn.execute('''
        SELECT s.*, (SELECT count(*) FROM likes l WHERE l.song_id=s.id) AS like_count,
        EXISTS(SELECT 1 FROM likes l WHERE l.song_id=s.id AND l.user_id=?) AS liked
        FROM songs s WHERE s.room_code=? ORDER BY s.id DESC
    ''', (user_id, code)).fetchall()
    return {
        'room': {'code': room['code'], 'name': room['name'], 'createdAt': room['created_at'], 'memberCount': member_count},
        'songs': [{
            'id': s['id'], 'title': s['title'], 'artist': s['artist'],
            'nickname': s['nickname'], 'userId': s['user_id'],
            'musicUrl': s['music_url'], 'note': s['note'],
            'startSeconds': s['start_seconds'], 'endSeconds': s['end_seconds'],
            'createdAt': s['created_at'], 'likeCount': s['like_count'], 'liked': bool(s['liked'])
        } for s in song_rows]
    }


def check_rate_limit(ip):
    current = time.time()
    with ATTEMPTS_LOCK:
        attempts = [t for t in ATTEMPTS.get(ip, ()) if current - t < 600]
        if len(attempts) >= 15:
            raise APIError('로그인 시도가 너무 많아. 잠시 후 다시 시도해 줘.', 429)
        attempts.append(current)
        ATTEMPTS[ip] = attempts
        if len(ATTEMPTS) > 2000:
            for key in list(ATTEMPTS)[:500]:
                if all(current - t > 600 for t in ATTEMPTS[key]):
                    del ATTEMPTS[key]


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print(f'[{now()}] {self.address_string()} {fmt % args}', flush=True)

    def send_json(self, data, status=200, cookie=None):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(payload)

    def send_static(self, file_path, content_type):
        payload = (PUBLIC / file_path).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.end_headers()
        self.wfile.write(payload)

    def body(self):
        if self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
            raise APIError('JSON 요청만 지원합니다.', 415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 16000:
                raise APIError('요청 내용이 비어 있거나 너무 깁니다.')
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, json.JSONDecodeError):
            raise APIError('JSON 요청 형식이 올바르지 않습니다.')

    def session_token(self):
        try:
            cookie = SimpleCookie()
            cookie.load(self.headers.get('Cookie', ''))
            return cookie['tr_session'].value if 'tr_session' in cookie else None
        except Exception:
            return None

    def require_user(self):
        token = self.session_token()
        if not token or len(token) > 200:
            raise APIError('로그인이 필요합니다.', 401)
        digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
        with db() as conn:
            return_user = conn.execute('''
                SELECT u.id,u.username,u.nickname,u.platform FROM users u
                JOIN sessions s ON s.user_id=u.id
                WHERE s.token_hash=? AND s.expires_at>?
            ''', (digest, int(time.time()))).fetchone()
        if return_user is None:
            raise APIError('로그인이 만료됐어. 다시 로그인해 줘.', 401)
        return return_user

    def cookie_header(self, token, age):
        value = f'tr_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={age}'
        if self.headers.get('X-Forwarded-Proto', '').lower() == 'https':
            value += '; Secure'
        return value

    def login_response(self, user, status=200):
        token = secrets.token_urlsafe(40)
        digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
        with db() as conn:
            conn.execute('INSERT INTO sessions VALUES (?,?,?)', (digest, user['id'], int(time.time()) + SESSION_AGE))
        self.send_json({'user': user_data(user)}, status, self.cookie_header(token, SESSION_AGE))

    def dispatch(self, method):
        parsed = urlparse(self.path)
        route = parsed.path
        if method == 'GET' and route == '/health':
            return self.send_json({'ok': True})
        static = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/index.html': ('index.html', 'text/html; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8'),
                  '/app.js': ('app.js', 'application/javascript; charset=utf-8'),
                  '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
        if method == 'GET' and route in static:
            return self.send_static(*static[route])

        if route == '/api/auth/register' and method == 'POST':
            check_rate_limit(self.client_address[0])
            data = self.body()
            username = validated_username(data)
            password = validated_password(data)
            nickname = required_string(data, 'nickname', 20)
            platform = validated_platform(data)
            salt = secrets.token_hex(16)
            user_id = secrets.token_hex(16)
            with db() as conn:
                try:
                    conn.execute('''INSERT INTO users(id,username,password_salt,password_hash,nickname,platform,created_at)
                        VALUES(?,?,?,?,?,?,?)''',
                        (user_id, username, salt, password_hash(password, salt), nickname, platform, now()))
                except Exception as exc:
                    if isinstance(exc, sqlite3.IntegrityError) or getattr(exc, 'sqlstate', None) == '23505':
                        raise APIError('이미 사용 중인 아이디야. 다른 아이디를 입력해 줘.', 409) from exc
                    raise
                user = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            return self.login_response(user, 201)

        if route == '/api/auth/login' and method == 'POST':
            check_rate_limit(self.client_address[0])
            data = self.body()
            username = validated_username(data)
            password = data.get('password')
            if not isinstance(password, str) or len(password) > 128:
                raise APIError('아이디 또는 비밀번호가 올바르지 않아.', 401)
            with db() as conn:
                user = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            if not user or not hmac.compare_digest(password_hash(password, user['password_salt']), user['password_hash']):
                raise APIError('아이디 또는 비밀번호가 올바르지 않아.', 401)
            return self.login_response(user)

        if route == '/api/auth/me' and method == 'GET':
            return self.send_json({'user': user_data(self.require_user())})

        if route == '/api/auth/logout' and method == 'POST':
            token = self.session_token()
            if token:
                with db() as conn:
                    conn.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
            return self.send_json({'ok': True}, cookie=self.cookie_header('', 0))

        if route == '/api/auth/profile' and method == 'PATCH':
            user = self.require_user()
            data = self.body()
            nickname = required_string(data, 'nickname', 20)
            platform = validated_platform(data)
            with db() as conn:
                conn.execute('UPDATE users SET nickname=?,platform=? WHERE id=?', (nickname, platform, user['id']))
                conn.execute('UPDATE members SET nickname=? WHERE user_id=?', (nickname, user['id']))
                conn.execute('UPDATE songs SET nickname=? WHERE user_id=?', (nickname, user['id']))
                updated = conn.execute('SELECT id,username,nickname,platform FROM users WHERE id=?', (user['id'],)).fetchone()
            return self.send_json({'user': user_data(updated)})

        user = self.require_user() if route.startswith('/api/') else None
        if method == 'POST' and route == '/api/rooms':
            name = required_string(self.body(), 'name', 40)
            with db() as conn:
                for _ in range(10):
                    code = ''.join(secrets.choice(ROOM_ALPHABET) for _ in range(8))
                    if not conn.execute('SELECT 1 FROM rooms WHERE code=?', (code,)).fetchone():
                        break
                else:
                    raise APIError('방 코드를 만들지 못했습니다.', 503)
                conn.execute('INSERT INTO rooms VALUES (?,?,?)', (code, name, now()))
                conn.execute('INSERT INTO members VALUES (?,?,?,?)', (code, user['id'], user['nickname'], now()))
            return self.send_json({'code': code}, 201)

        match = re.fullmatch(r'/api/rooms/([^/]+)(?:/(join|songs)(?:/(\d+)(?:/(like))?)?)?', route)
        if match:
            code = clean_code(match.group(1))
            action, song_id, subaction = match.group(2), match.group(3), match.group(4)
            if method == 'GET' and action is None:
                with db() as conn:
                    return self.send_json(list_room(conn, code, user['id']))
            if method == 'POST' and action == 'join':
                with db() as conn:
                    check_room(conn, code)
                    conn.execute('''INSERT INTO members VALUES (?,?,?,?)
                      ON CONFLICT(room_code,user_id) DO UPDATE SET nickname=excluded.nickname''',
                      (code, user['id'], user['nickname'], now()))
                return self.send_json({'ok': True})
            if method == 'POST' and action == 'songs' and song_id is None:
                data = self.body()
                title = required_string(data, 'title', 120)
                artist = required_string(data, 'artist', 120)
                note = optional_string(data, 'note', 500)
                url = optional_string(data, 'musicUrl', 500)
                if url:
                    u = urlparse(url)
                    if u.scheme not in ('https', 'http') or not u.netloc or u.username or u.password:
                        raise APIError('음악 링크는 정상적인 http/https 주소여야 합니다.')
                start, end = data.get('startSeconds'), data.get('endSeconds')
                if start is not None and (type(start) is not int or not 0 <= start <= 36000):
                    raise APIError('시작 구간이 올바르지 않습니다.')
                if end is not None and (type(end) is not int or not 0 <= end <= 36000):
                    raise APIError('종료 구간이 올바르지 않습니다.')
                if end is not None and (start is None or end <= start):
                    raise APIError('종료 구간은 시작 구간보다 뒤여야 합니다.')
                with db() as conn:
                    check_room(conn, code)
                    check_member(conn, code, user['id'])
                    conn.execute('''INSERT INTO songs(room_code,user_id,nickname,title,artist,music_url,note,start_seconds,end_seconds,created_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?)''',
                      (code, user['id'], user['nickname'], title, artist, url, note, start, end, now()))
                return self.send_json({'ok': True}, 201)
            if song_id and subaction == 'like' and method == 'POST':
                self.body()
                with db() as conn:
                    check_member(conn, code, user['id'])
                    if not conn.execute('SELECT 1 FROM songs WHERE id=? AND room_code=?', (song_id, code)).fetchone():
                        raise APIError('추천곡을 찾을 수 없습니다.', 404)
                    old = conn.execute('SELECT 1 FROM likes WHERE song_id=? AND user_id=?', (song_id, user['id'])).fetchone()
                    if old:
                        conn.execute('DELETE FROM likes WHERE song_id=? AND user_id=?', (song_id, user['id']))
                    else:
                        conn.execute('INSERT INTO likes VALUES (?,?)', (song_id, user['id']))
                return self.send_json({'liked': not bool(old)})
            if song_id and subaction is None and method == 'DELETE':
                self.body()
                with db() as conn:
                    check_member(conn, code, user['id'])
                    song = conn.execute('SELECT user_id FROM songs WHERE id=? AND room_code=?', (song_id, code)).fetchone()
                    if not song:
                        raise APIError('추천곡을 찾을 수 없습니다.', 404)
                    if song['user_id'] != user['id']:
                        raise APIError('내가 등록한 추천곡만 삭제할 수 있습니다.', 403)
                    conn.execute('DELETE FROM songs WHERE id=?', (song_id,))
                return self.send_json({'ok': True})
        raise APIError('요청한 주소를 찾을 수 없습니다.', 404)

    def do_GET(self): self.handle_request('GET')
    def do_POST(self): self.handle_request('POST')
    def do_PATCH(self): self.handle_request('PATCH')
    def do_DELETE(self): self.handle_request('DELETE')

    def handle_request(self, method):
        try:
            self.dispatch(method)
        except APIError as error:
            self.send_json({'error': str(error)}, error.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            import traceback
            traceback.print_exc()
            try:
                self.send_json({'error': '서버에서 문제가 발생했습니다.'}, 500)
            except (BrokenPipeError, ConnectionResetError):
                pass


if __name__ == '__main__':
    init_db()
    print(f'TRACKROOM 실행 중 → http://localhost:{PORT}', flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
