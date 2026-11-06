#!/usr/bin/env python3
"""Trackroom: stdlib-only, multi-user music recommendation room MVP."""
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / 'public'
DB_PATH = Path(os.environ.get('TRACKROOM_DB', str(ROOT / 'trackroom.sqlite3')))
PORT = int(os.environ.get('PORT', '8000'))
HOST = os.environ.get('HOST', '0.0.0.0')
ROOM_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS rooms (
          code TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS members (
          room_code TEXT NOT NULL REFERENCES rooms(code) ON DELETE CASCADE,
          user_id TEXT NOT NULL, nickname TEXT NOT NULL,
          joined_at TEXT NOT NULL,
          PRIMARY KEY(room_code, user_id)
        );
        CREATE TABLE IF NOT EXISTS songs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          room_code TEXT NOT NULL REFERENCES rooms(code) ON DELETE CASCADE,
          user_id TEXT NOT NULL, nickname TEXT NOT NULL,
          title TEXT NOT NULL, artist TEXT NOT NULL,
          music_url TEXT NOT NULL DEFAULT '',
          note TEXT NOT NULL DEFAULT '',
          start_seconds INTEGER, end_seconds INTEGER,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS likes (
          song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
          user_id TEXT NOT NULL,
          PRIMARY KEY(song_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS songs_room ON songs(room_code, id DESC);
        ''')


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


def validate_identity(data):
    user_id = required_string(data, 'userId', 100)
    nickname = required_string(data, 'nickname', 20)
    if not re.fullmatch(r'[A-Za-z0-9-]{8,100}', user_id):
        raise APIError('사용자 식별값이 올바르지 않습니다.')
    return user_id, nickname


def clean_code(code):
    code = code.upper()
    if not re.fullmatch(r'[A-HJ-NP-Z2-9]{8}', code):
        raise APIError('방 코드가 올바르지 않습니다.', 404)
    return code


def check_room(conn, code):
    room = conn.execute('SELECT * FROM rooms WHERE code = ?', (code,)).fetchone()
    if not room:
        raise APIError('방을 찾을 수 없습니다. 초대 코드를 확인해 주세요.', 404)
    return room


def check_member(conn, code, user_id):
    row = conn.execute('SELECT nickname FROM members WHERE room_code=? AND user_id=?', (code, user_id)).fetchone()
    if not row:
        raise APIError('방에 먼저 참여해 주세요.', 403)
    return row


def list_room(conn, code, user_id):
    room = check_room(conn, code)
    member_count = conn.execute('SELECT count(*) FROM members WHERE room_code=?', (code,)).fetchone()[0]
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
            'createdAt': s['created_at'], 'likeCount': s['like_count'],
            'liked': bool(s['liked'])
        } for s in song_rows]
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print(f'[{now()}] {self.address_string()} {fmt % args}', flush=True)

    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

    def send_static(self, file_path, content_type):
        path = PUBLIC / file_path
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

    def body(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 16000:
                raise APIError('요청 내용이 비어 있거나 너무 깁니다.')
            obj = json.loads(self.rfile.read(length))
            if not isinstance(obj, dict):
                raise ValueError()
            return obj
        except (ValueError, json.JSONDecodeError):
            raise APIError('JSON 요청 형식이 올바르지 않습니다.')

    def dispatch(self, method):
        parsed = urlparse(self.path)
        route = parsed.path
        if method == 'GET' and route == '/health':
            return self.send_json({'ok': True})
        if method == 'GET' and route in ('/', '/index.html'):
            return self.send_static('index.html', 'text/html; charset=utf-8')
        if method == 'GET' and route == '/style.css':
            return self.send_static('style.css', 'text/css; charset=utf-8')
        if method == 'GET' and route == '/app.js':
            return self.send_static('app.js', 'application/javascript; charset=utf-8')
        if method == 'GET' and route == '/favicon.svg':
            return self.send_static('favicon.svg', 'image/svg+xml')

        if method == 'POST' and route == '/api/rooms':
            data = self.body()
            name = required_string(data, 'name', 40)
            user_id, nickname = validate_identity(data)
            with db() as conn:
                for _ in range(10):
                    code = ''.join(secrets.choice(ROOM_ALPHABET) for _ in range(8))
                    if not conn.execute('SELECT 1 FROM rooms WHERE code=?', (code,)).fetchone():
                        break
                else:
                    raise APIError('방 코드를 만들지 못했습니다.', 503)
                conn.execute('INSERT INTO rooms VALUES (?,?,?)', (code, name, now()))
                conn.execute('INSERT INTO members VALUES (?,?,?,?)', (code, user_id, nickname, now()))
            return self.send_json({'code': code}, 201)

        match = re.fullmatch(r'/api/rooms/([^/]+)(?:/(join|songs)(?:/(\d+)(?:/(like))?)?)?', route)
        if match:
            code = clean_code(match.group(1))
            action, song_id, subaction = match.group(2), match.group(3), match.group(4)
            if method == 'GET' and action is None:
                user_id = parse_qs(parsed.query).get('userId', [''])[0]
                with db() as conn:
                    return self.send_json(list_room(conn, code, user_id))
            if method == 'POST' and action == 'join':
                data = self.body()
                user_id, nickname = validate_identity(data)
                with db() as conn:
                    check_room(conn, code)
                    conn.execute('''INSERT INTO members VALUES (?,?,?,?)
                        ON CONFLICT(room_code,user_id) DO UPDATE SET nickname=excluded.nickname''',
                        (code, user_id, nickname, now()))
                return self.send_json({'ok': True})
            if method == 'POST' and action == 'songs' and song_id is None:
                data = self.body()
                user_id, nickname = validate_identity(data)
                title = required_string(data, 'title', 120)
                artist = required_string(data, 'artist', 120)
                note = optional_string(data, 'note', 500)
                url = optional_string(data, 'musicUrl', 500)
                if url:
                    u = urlparse(url)
                    if u.scheme not in ('https', 'http') or not u.netloc or u.username or u.password:
                        raise APIError('음악 링크는 정상적인 http/https 주소여야 합니다.')
                start = data.get('startSeconds')
                end = data.get('endSeconds')
                if start is not None and (type(start) is not int or start < 0 or start > 36000):
                    raise APIError('시작 구간이 올바르지 않습니다.')
                if end is not None and (type(end) is not int or end < 0 or end > 36000):
                    raise APIError('종료 구간이 올바르지 않습니다.')
                if end is not None and start is None:
                    raise APIError('종료 구간을 지정하려면 시작 구간도 입력해야 합니다.')
                if start is not None and end is not None and end <= start:
                    raise APIError('종료 구간은 시작 구간보다 뒤여야 합니다.')
                with db() as conn:
                    check_room(conn, code)
                    check_member(conn, code, user_id)
                    conn.execute('''INSERT INTO songs (room_code,user_id,nickname,title,artist,music_url,note,start_seconds,end_seconds,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?)''', (code, user_id, nickname, title, artist, url, note, start, end, now()))
                return self.send_json({'ok': True}, 201)
            if song_id and subaction == 'like' and method == 'POST':
                data = self.body()
                user_id = required_string(data, 'userId', 100)
                with db() as conn:
                    check_member(conn, code, user_id)
                    song = conn.execute('SELECT id FROM songs WHERE id=? AND room_code=?', (song_id, code)).fetchone()
                    if not song:
                        raise APIError('추천곡을 찾을 수 없습니다.', 404)
                    old = conn.execute('SELECT 1 FROM likes WHERE song_id=? AND user_id=?', (song_id, user_id)).fetchone()
                    if old:
                        conn.execute('DELETE FROM likes WHERE song_id=? AND user_id=?', (song_id, user_id))
                    else:
                        conn.execute('INSERT INTO likes VALUES (?,?)', (song_id, user_id))
                return self.send_json({'liked': not bool(old)})
            if song_id and subaction is None and method == 'DELETE':
                data = self.body()
                user_id = required_string(data, 'userId', 100)
                with db() as conn:
                    song = conn.execute('SELECT user_id FROM songs WHERE id=? AND room_code=?', (song_id, code)).fetchone()
                    if not song:
                        raise APIError('추천곡을 찾을 수 없습니다.', 404)
                    if song['user_id'] != user_id:
                        raise APIError('내가 등록한 추천곡만 삭제할 수 있습니다.', 403)
                    conn.execute('DELETE FROM songs WHERE id=?', (song_id,))
                return self.send_json({'ok': True})
        raise APIError('요청한 주소를 찾을 수 없습니다.', 404)

    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def do_DELETE(self):
        self.handle_request('DELETE')

    def handle_request(self, method):
        try:
            self.dispatch(method)
        except APIError as e:
            self.send_json({'error': str(e)}, e.status)
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
    print(f'Trackroom 실행 중 → http://localhost:{PORT}', flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
