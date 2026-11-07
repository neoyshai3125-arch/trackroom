#!/usr/bin/env python3
"""TRACKROOM: music recommendations, password login and stored profile (Python stdlib)."""
import hashlib
import base64
import urllib.request
import urllib.error
import urllib.parse
import hmac
import json
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor
import os
import re
import unicodedata
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
from urllib.parse import urlparse, parse_qs

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
CATALOG_SECRET = os.environ.get('TRACKROOM_SELECTION_SECRET', '').encode('utf-8') or secrets.token_bytes(32)
SEARCH_REQUESTS = {}
SEARCH_LOCK = threading.Lock()
SPOTIFY_TOKEN = {'token': '', 'until': 0}
SPOTIFY_LOCK = threading.Lock()
SEARCH_CACHE = {}
CACHE_LOCK = threading.Lock()



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

def verify_persistent_storage():
    """Never silently create a disposable account database on Render Free.

    A missing DATABASE_URL used to look like users had been deleted after every
    restart, because the app started with a brand-new local SQLite database.
    Local development can still use SQLite when RENDER isn't set.
    """
    if os.environ.get('RENDER', '').lower() in ('true', '1') and not DATABASE_URL:
        raise RuntimeError(
            'TRACKROOM 데이터 보호: Render에서는 영구 PostgreSQL DATABASE_URL을 '
            '먼저 설정해 주세요. 임시 SQLite로 실행하면 회원과 방이 사라집니다.'
        )


def init_db():
    verify_persistent_storage()
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
            for column, kind in (
                ('source_platform', 'TEXT'), ('source_id', 'TEXT'),
                ('source_catalog', 'TEXT'), ('artwork_url', 'TEXT'),
                ('artwork_store_url', 'TEXT'), ('artwork_checked_at', 'INTEGER'),
                ('album_name', 'TEXT'), ('duration_ms', 'INTEGER'), ('isrc', 'TEXT')
            ):
                conn.execute(f'ALTER TABLE songs ADD COLUMN IF NOT EXISTS {column} {kind}')
            for table in ('users', 'sessions', 'rooms', 'members', 'songs', 'likes'):
                conn.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        else:
            conn.executescript(schema)
            columns = {row['name'] for row in conn.execute('PRAGMA table_info(songs)').fetchall()}
            for column, kind in (
                ('source_platform', 'TEXT'), ('source_id', 'TEXT'),
                ('source_catalog', 'TEXT'), ('artwork_url', 'TEXT'),
                ('artwork_store_url', 'TEXT'), ('artwork_checked_at', 'INTEGER'),
                ('album_name', 'TEXT'), ('duration_ms', 'INTEGER'), ('isrc', 'TEXT')
            ):
                if column not in columns:
                    conn.execute(f'ALTER TABLE songs ADD COLUMN {column} {kind}')


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
            'sourcePlatform': s['source_platform'], 'sourceCatalog': s['source_catalog'],
            'sourceId': s['source_id'], 'album': s['album_name'],
            'artworkUrl': s['artwork_url'], 'artworkStoreUrl': s['artwork_store_url'],
            'durationMs': s['duration_ms'],
            'isrc': s['isrc'],
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



def safe_artwork(url):
    """Only serve cover URLs sourced from known catalog CDNs."""
    try:
        u = urlparse(url)
        return (url if u.scheme == 'https' and
                (u.hostname == 'i.scdn.co' or u.hostname == 'mosaic.scdn.co' or
                 (u.hostname or '').endswith('.mzstatic.com')) else '')
    except (TypeError, ValueError):
        return ''



# iTunes artwork is matched *separately* from Last.fm search results.
# It is not Last.fm artwork; using Last.fm API-returned images is excluded
# under the Last.fm API terms. Only show an Apple match if title AND artist agree.
ARTWORK_LOOKUP_CACHE = {}
ARTWORK_LOOKUP_LOCK = threading.Lock()
# Apple documents approximately 20 iTunes Search API calls/minute.
APPLE_QUERY_LOCK = threading.Lock()
APPLE_NEXT_QUERY = [0.0]
APPLE_MIN_INTERVAL = 3.15


def artwork_key(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    value = re.sub(r'\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring)\b[^\)\]]*[\)\]]', '', value)
    return re.sub(r'[^\w]+', '', value, flags=re.UNICODE)


def song_version(title):
    """Distinguish actual live/acoustic/remix versions from studio songs.

    Remastered years and 'official audio' labels are cosmetic metadata, but
    remix/live/acoustic variants may have completely different artwork.
    """
    text = unicodedata.normalize('NFKC', str(title or '')).casefold()
    kinds = {
        'live': r'\b(?:live|concert|unplugged)\b|라이브|현장',
        'remix': r'\b(?:remix|rework|sped up|slowed)\b|리믹스',
        'acoustic': r'\b(?:acoustic|piano version)\b|어쿠스틱',
        'instrumental': r'\b(?:instrumental|inst\.?)\b|연주곡',
    }
    return {name for name, rx in kinds.items() if re.search(rx, text, re.I)}


def clean_title(title):
    """Conservative editorial suffix cleanup; never rewrite the base title."""
    text = unicodedata.normalize('NFKC', str(title or '')).casefold()
    text = re.sub(r'\s*[\(\[][^)\]]*(?:remaster(?:ed)?|\d{4} version|official (?:audio|video)|lyric video|feat\.?|featuring)[^)\]]*[\)\]]', '', text, flags=re.I)
    text = re.sub(r'\s*[-–]\s*(?:remaster(?:ed)?(?:\s*\d{4})?|official audio|audio only)\s*$', '', text, flags=re.I)
    return artwork_key(text)


def close_title(found, wanted):
    a, b = clean_title(found), clean_title(wanted)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Avoid risky partial matches for short names like 'I', 'D', 'Blue'.
    if min(len(a), len(b)) < 5:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def artist_forms(value):
    """Name components only (never substring 'IU' within 'LUI')."""
    raw = str(value or '').strip()
    forms = {artwork_key(raw)}
    # Parenthesized stage names: 아이유 (IU), BTS (방탄소년단)
    forms.update(artwork_key(m) for m in re.findall(r'[\(\[]([^)]{2,45})[\)\]]', raw))
    # Featured acts, joint collaborations; base credit remains preferred.
    for name in re.split(r'\s+(?:feat\.?|ft\.?|featuring|with|and|x)\s+|\s*[,/&+]\s*', raw, flags=re.I):
        forms.add(artwork_key(name))
    return {f for f in forms if f}


def same_artist(found, wanted):
    if not found or not wanted:
        return False
    a, b = artist_forms(found), artist_forms(wanted)
    if a & b:
        return True
    # Forgive small spelling differences for longer names, not short artists.
    return any(min(len(x), len(y)) >= 7 and SequenceMatcher(None,x,y).ratio() >= 0.91
               for x in a for y in b)


# Conservative official stage-name variants to support Korean/English search
# without pretending that arbitrary titles can be machine-translated reliably.
ARTIST_ALIASES = {
    '아이유': ('IU',), '방탄소년단': ('BTS',), '블랙핑크': ('BLACKPINK',),
    '태연': ('TAEYEON',), '지코': ('ZICO',), '트와이스': ('TWICE',),
    '세븐틴': ('SEVENTEEN',), '뉴진스': ('NewJeans',),
    '데이식스': ('DAY6',), '르세라핌': ('LE SSERAFIM',),
    '에스파': ('aespa',), '엔하이픈': ('ENHYPEN',),
    '스트레이 키즈': ('Stray Kids',), '엑소': ('EXO',),
}


def lastfm_aliases(track):
    """Canonical Last.fm URL slugs often retain English/romanized names."""
    titles = [str(track.get('title') or '').strip()]
    artists = [str(track.get('artist') or '').strip()]
    url = str(track.get('musicUrl') or '')
    try:
        parsed = urlparse(url)
        if parsed.hostname in ('last.fm', 'www.last.fm') and '/_/' in parsed.path:
            prefix, song = parsed.path.split('/_/', 1)
            slug_title = urllib.parse.unquote_plus(song.split('/', 1)[0]).strip()
            slug_artist = urllib.parse.unquote_plus(prefix.split('/music/', 1)[-1].strip('/')).strip()
            if 2 <= len(slug_title) <= 120:
                titles.append(slug_title)
            if 2 <= len(slug_artist) <= 120:
                artists.append(slug_artist)
    except (ValueError, TypeError):
        pass
    for alias, english in ARTIST_ALIASES.items():
        if any(artwork_key(name) in (artwork_key(alias), *(artwork_key(x) for x in english)) for name in artists):
            artists.extend((alias, *english))
    return list(dict.fromkeys(t for t in titles if t)), list(dict.fromkeys(a for a in artists if a))


MB_ALIAS_CACHE = {}
MB_ALIAS_LOCK = threading.Lock()
MB_REQUEST_LOCK = threading.Lock()
MB_LAST_REQUEST = [0.0]


def musicbrainz_variants(title, artist):
    """Find catalog-recorded multilingual variants, not guessed translations.

    MusicBrainz indexes official recording aliases, including some translated
    names. Requests are optional and conservatively rate-limited to 1/second.
    """
    cache_key = (artwork_key(title), artwork_key(artist))
    if not all(cache_key):
        return [], []
    current = time.time()
    with MB_ALIAS_LOCK:
        existing = MB_ALIAS_CACHE.get(cache_key)
        if existing and existing[0] > current:
            return existing[1]
    term = f'recording:"{str(title)[:100].replace(chr(34), "")}" AND artist:"{str(artist)[:100].replace(chr(34), "")}"'
    url = 'https://musicbrainz.org/ws/2/recording/?' + urllib.parse.urlencode({
        'query':term, 'fmt':'json', 'limit':5
    })
    titles, artists = [], []
    try:
        with MB_REQUEST_LOCK:
            elapsed = time.monotonic() - MB_LAST_REQUEST[0]
            if elapsed < 1.1: time.sleep(1.1 - elapsed)
            MB_LAST_REQUEST[0] = time.monotonic()
            data = request_json(url, headers={'User-Agent':'TRACKROOM/0.5 (https://trackroom.onrender.com)'}, timeout=5)
        for record in data.get('recordings', [])[:5]:
            if not isinstance(record, dict) or int(record.get('score') or 0) < 90:
                continue
            variants = [record.get('title','')]
            variants += [alias.get('name','') for alias in record.get('aliases', []) if isinstance(alias, dict)]
            possible_artists=[]
            for credit in record.get('artist-credit', []):
                if isinstance(credit, dict):
                    possible_artists.extend([credit.get('name',''), (credit.get('artist') or {}).get('name','')])
            # Query contains BOTH title and artist; use highly ranked records only.
            titles.extend(v for v in variants if v and len(v) <= 120)
            artists.extend(v for v in possible_artists if v and len(v) <= 120)
    except (APIError, ValueError, TypeError, AttributeError, TimeoutError) as exc:
        print(f'[TRACKROOM artwork] MusicBrainz multilingual alias lookup failed: {exc}', flush=True)
    value = (list(dict.fromkeys(titles)), list(dict.fromkeys(artists)))
    with MB_ALIAS_LOCK:
        if len(MB_ALIAS_CACHE) > 1000: MB_ALIAS_CACHE.clear()
        MB_ALIAS_CACHE[cache_key] = (time.time()+12*3600, value)
    return value


def apple_results(term, country='US', limit=100, attribute=None, raise_on_error=False):
    params = {'term':term, 'country':country, 'media':'music', 'entity':'song', 'limit':limit}
    if attribute:
        params['attribute'] = attribute
    url = 'https://itunes.apple.com/search?' + urllib.parse.urlencode(params)
    try:
        # Limit calls across threads, not just for one user's search.
        with APPLE_QUERY_LOCK:
            delay = max(0.0, APPLE_NEXT_QUERY[0] - time.monotonic())
            if delay:
                time.sleep(delay)
            APPLE_NEXT_QUERY[0] = time.monotonic() + APPLE_MIN_INTERVAL
        data = request_json(url, headers={'User-Agent':'TRACKROOM/0.5'}, timeout=5)
        return data.get('results',[]) if isinstance(data,dict) else []
    except (APIError, ValueError, TypeError) as exc:
        print(f'[TRACKROOM artwork] Apple {country} artwork query failed: {exc}', flush=True)
        if raise_on_error:
            raise APIError('Apple 커버 검색에 연결하지 못했어. 잠시 후 다시 시도해 줘.', 503) from exc
        return []


def best_artwork_candidate(tracks, items, aliases, accepted):
    """Prefer high-confidence title+artist matches; reject wrong versions."""
    for i, track in enumerate(tracks):
        titles, artists = aliases[i]
        best = None
        best_score = -1.0
        for item in items:
            if not isinstance(item,dict) or item.get('kind') != 'song':
                continue
            artist_name = item.get('artistName','')
            if not any(same_artist(artist_name, a) for a in artists):
                continue
            title_name = item.get('trackName','')
            # No live/remix cover for an unrelated studio recording.
            if not any(song_version(t) == song_version(title_name) for t in titles):
                continue
            score = max((close_title(title_name, t) for t in titles), default=0)
            if score < (0.83 if len(clean_title(title_name)) >= 7 else 0.95):
                continue
            art = safe_artwork(item.get('artworkUrl100',''))
            link = item.get('trackViewUrl','')
            if not art or not isinstance(link,str):
                continue
            try:
                u = urlparse(link)
            except (ValueError,TypeError):
                continue
            if u.scheme != 'https' or u.hostname not in ('itunes.apple.com','music.apple.com'):
                continue
            if score > best_score:
                best = {'url': art, 'storeUrl':link,
                        'album':str(item.get('collectionName') or '')[:120]}
                best_score = score
        if best and (i not in accepted or best_score > accepted[i][0]):
            accepted[i] = (best_score,best)


def itunes_matches(tracks, query, max_calls=2, limit=150, allow_fallback=True, expand_multilingual=False):
    """Apple cover verification, varied queries and guarded fuzzy matching.

    Query expansion: Last.fm canonical URL, bilingual stage names, optionally
    MusicBrainz recording aliases. No blind English machine translation.
    """
    if not tracks: return {}
    aliases = [lastfm_aliases(t) for t in tracks]
    accepted = {}
    # First pass: broad query for the list (US/JP). No per-song external calls.
    for country in ('US','JP')[:max_calls]:
        best_artwork_candidate(tracks, apple_results(query,country,limit), aliases, accepted)
        if len(accepted) == len(tracks): break

    if allow_fallback and len(accepted) < len(tracks):
        # For the first few misses, search individually using translated/aliased
        # metadata and both common Asian/Western store catalogs.
        missing = [i for i in range(len(tracks)) if i not in accepted][:4]
        def lookup_single(i):
            titles, artists = aliases[i]
            variants = [(titles[-1], artists[-1])]
            if expand_multilingual:
                variants.append((titles[0],artists[0]))
            one={}
            for title, artist in list(dict.fromkeys(variants))[:2]:
                for country in ('US','JP'):
                    rows = apple_results(f'{title} {artist}', country, 80)
                    best_artwork_candidate([tracks[i]], rows, [(titles,artists)], one)
                    if one: return i, one[0]
            # MusicBrainz provides human-maintained alternate names, not
            # unverified machine translation; consult for selected items only.
            if expand_multilingual and i in missing[:2]:
                extra_titles, extra_artists = musicbrainz_variants(titles[0], artists[0])
                titles.extend(extra_titles)
                artists.extend(extra_artists)
                for title in extra_titles[:2]:
                    for country in ('US','JP'):
                        rows = apple_results(f'{title} {artists[-1]}',country,60)
                        best_artwork_candidate([tracks[i]], rows, [(titles,artists)], one)
                        if one: return i, one[0]
            return i, None
        # Parallelize independent store lookups, but avoid large bursts.
        with ThreadPoolExecutor(max_workers=min(3,len(missing) or 1)) as executor:
            for idx, found in executor.map(lookup_single, missing):
                if found: accepted[idx]=found
    return {i: cover for i,(score,cover) in accepted.items()}


def enrich_lastfm_results(results, query):
    # Only one broad query per storefront here. A generic artist/title query
    # cannot fairly cover every Last.fm result; missing covers are resolved
    # separately, one specific title at a time, without blocking the list.
    found = itunes_matches(results, query, allow_fallback=False)
    for i, meta in found.items():
        results[i]['artworkUrl'] = meta['url']
        results[i]['artworkStoreUrl'] = meta['storeUrl']
        results[i]['album'] = meta['album']
    return results


def find_itunes_cover(title, artist, force=False):
    """One selected/previously saved track, with optional manual retry."""
    key = (artwork_key(title), artwork_key(artist))
    if not all(key):return {}
    if not force:
        with ARTWORK_LOOKUP_LOCK:
            old = ARTWORK_LOOKUP_CACHE.get(key)
            if old and old[0] > time.time():
                return old[1]
    item = {'title': title, 'artist': artist}
    aliases = [lastfm_aliases(item)]
    found = {}
    # Exact song-title search finds Korean songs that do not appear in the
    # first results of an artist-wide query. Compare BOTH title and artist.
    # Search JP and US storefronts separately; neither is the KR Music store.
    for country in ('JP', 'US'):
        candidates = apple_results(title, country, 200, 'songTerm', raise_on_error=True)
        best_artwork_candidate([item], candidates, aliases, found)
        if 0 in found and found[0][0] >= 0.999:
            break
    if not found:
        # Some search indexes tokenize title alone poorly. Use title+artist.
        for country in ('JP', 'US'):
            candidates = apple_results(f'{title} {artist}', country, 120, raise_on_error=True)
            best_artwork_candidate([item], candidates, aliases, found)
            if found:
                break
    match = found.get(0, (None, {}))[1]
    with ARTWORK_LOOKUP_LOCK:
        if len(ARTWORK_LOOKUP_CACHE)>1000:ARTWORK_LOOKUP_CACHE.clear()
        # Shorter miss cache than successful match, so a new catalog result can appear.
        ARTWORK_LOOKUP_CACHE[key]=(time.time()+(6*3600 if match else 30*60),match)
    return match

def request_json(url, headers=None, data=None, method=None, timeout=8):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise APIError('음원 검색 요청이 많아. 잠시 후 다시 검색해 줘.', 429) from exc
        if exc.code in (401, 403):
            raise APIError('음원 플랫폼 API 인증 또는 이용 권한을 확인해 줘.', 503) from exc
        raise APIError('음원 플랫폼에서 결과를 불러오지 못했어.', 502) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise APIError('음원 플랫폼에 연결할 수 없어. 다시 시도해 줘.', 502) from exc


def spotify_access_token():
    client_id, secret = os.environ.get('SPOTIFY_CLIENT_ID'), os.environ.get('SPOTIFY_CLIENT_SECRET')
    if not client_id or not secret:
        raise APIError('Spotify 검색은 아직 설정되지 않았어. 관리자에게 Spotify API 연결을 요청해 줘.', 503)
    with SPOTIFY_LOCK:
        if time.time() < SPOTIFY_TOKEN['until'] and SPOTIFY_TOKEN['token']:
            return SPOTIFY_TOKEN['token']
        auth = base64.b64encode(f'{client_id}:{secret}'.encode()).decode()
        obj = request_json('https://accounts.spotify.com/api/token',
                           headers={'Authorization': 'Basic ' + auth,
                                    'Content-Type': 'application/x-www-form-urlencoded'},
                           data=b'grant_type=client_credentials', method='POST')
        token = obj.get('access_token')
        if not token:
            raise APIError('Spotify 인증 정보를 확인해 줘.', 503)
        SPOTIFY_TOKEN.update(token=token, until=time.time() + int(obj.get('expires_in', 3600)) - 90)
        return token


SEARCH_RESULT_LIMIT = 50
# These are *localized titles*, not machine translations. Keep special aliases
# small and explicit; a public iTunes Store search has no translation endpoint.
SEARCH_ALIASES = {
    '괴수의 꽃노래': '怪獣の花唄',
    '怪獣の花唄': '괴수의 꽃노래',
}


def apple_search_request(query, country, entity='song', limit=120, attribute=None):
    """All public iTunes searches share Apple's modest request-rate budget."""
    params = {'term':query, 'media':'music', 'entity':entity, 'country':country,
              'limit': min(int(limit), 200)}
    if attribute: params['attribute'] = attribute
    return apple_results_raw(params)


def apple_results_raw(params):
    url = 'https://itunes.apple.com/search?' + urllib.parse.urlencode(params)
    with APPLE_QUERY_LOCK:
        pause = max(0.0, APPLE_NEXT_QUERY[0] - time.monotonic())
        if pause: time.sleep(pause)
        APPLE_NEXT_QUERY[0] = time.monotonic() + APPLE_MIN_INTERVAL
    return request_json(url, headers={'User-Agent':'TRACKROOM/0.56'}).get('results', [])


def normalize_apple_record(row, country, item_type='track'):
    if not isinstance(row,dict): return None
    if item_type == 'album':
        sid = row.get('collectionId')
        title = row.get('collectionName') or ''
        artist = row.get('artistName') or ''
        link = row.get('collectionViewUrl') or ''
        if not (str(sid).isdigit() and title and artist): return None
        result = {'itemType':'album', 'sourcePlatform':'apple', 'sourceCatalog':'itunes_store',
                  'sourceId':str(sid), 'title':title[:120], 'artist':artist[:120],
                  'album':title[:120], 'albumId':str(sid), 'storeCountry':country, 'musicUrl':link[:500],
                  'artworkUrl':safe_artwork(row.get('artworkUrl100','')),
                  'durationMs':None, 'isrc':'', 'releaseDate':row.get('releaseDate','')}
    else:
        if row.get('kind') != 'song' or not str(row.get('trackId','')).isdigit(): return None
        link=row.get('trackViewUrl') or ''
        result={'itemType':'track','sourcePlatform':'apple','sourceCatalog':'itunes_store',
                'sourceId':str(row['trackId']), 'title':str(row.get('trackName') or '')[:120],
                'artist':str(row.get('artistName') or '')[:120],
                'album':str(row.get('collectionName') or '')[:120],
                'albumId':str(row.get('collectionId') or ''), 'storeCountry':country,
                'musicUrl':link[:500], 'artworkUrl':safe_artwork(row.get('artworkUrl100','')),
                'durationMs':row.get('trackTimeMillis') or None, 'isrc':'',
                'releaseDate':row.get('releaseDate','')}
    try: u=urlparse(link)
    except (ValueError,TypeError): return None
    if not (u.scheme == 'https' and u.hostname in ('itunes.apple.com','music.apple.com')):return None
    if not (result['title'] and result['artist']): return None
    return result



def normalize_apple_artist(row, country):
    """The public iTunes artist resource has no guaranteed portrait image."""
    if not isinstance(row, dict) or row.get('wrapperType') != 'artist':
        return None
    artist_id = str(row.get('artistId') or '')
    name = row.get('artistName') or ''
    link = row.get('artistLinkUrl') or ''
    if not (artist_id.isdigit() and isinstance(name,str) and name.strip()
            and isinstance(link,str)):
        return None
    url = urlparse(link)
    if url.scheme != 'https' or url.hostname not in ('itunes.apple.com', 'music.apple.com'):
        return None
    return {
        'itemType':'artist', 'sourcePlatform':'apple', 'sourceCatalog':'itunes_store',
        'sourceId': artist_id, 'title':name.strip()[:120], 'artist':name.strip()[:120],
        'album':'', 'storeCountry':country, 'musicUrl':link[:500],
        'genre':str(row.get('primaryGenreName') or '')[:80],
        'artworkUrl':'', 'durationMs':None, 'isrc':''
    }


def search_artists(platform, query):
    """Return artist *profiles*, never song suggestions."""
    if platform == 'apple':
        pairs=[]
        for country in ('US','JP'):
            rows=apple_search_request(query,country,'musicArtist',80,'artistTerm')
            pairs.extend((country,row) for row in rows if isinstance(row,dict))
        artists=[]
        seen=set()
        for country,row in blend_storefronts(pairs):
            item=normalize_apple_artist(row,country)
            if not item or item['sourceId'] in seen:continue
            seen.add(item['sourceId'])
            item['searchRank']=len(artists)
            artists.append(item)
            if len(artists)>=SEARCH_RESULT_LIMIT:break
        return artists
    if platform == 'lastfm':
        obj=lastfm_api('artist.search', artist=query, limit=SEARCH_RESULT_LIMIT)
        matches=(obj.get('results') or {}).get('artistmatches') or {}
        rows=matches.get('artist') or []
        if isinstance(rows,dict): rows=[rows]
        if not isinstance(rows,list): rows=[]
        artists=[]
        seen=set()
        for row in rows:
            if not isinstance(row,dict):continue
            name,link=row.get('name'),row.get('url')
            if not (isinstance(name,str) and name.strip() and isinstance(link,str)):continue
            link=link.replace('http://','https://',1)
            if not valid_lastfm_url(link):continue
            key=artwork_key(name)
            if key in seen:continue
            seen.add(key)
            sid=str(row.get('mbid') or '').strip() or ('url-' + hashlib.sha256(link.encode()).hexdigest()[:32])
            artists.append({
                'itemType':'artist','sourcePlatform':'lastfm','sourceCatalog':'lastfm',
                'sourceId':sid,'title':name.strip()[:120],'artist':name.strip()[:120],
                'album':'','musicUrl':link[:500],'artworkUrl':'','genre':'',
                'searchRank':len(artists),'durationMs':None,'isrc':''})
            if len(artists)>=SEARCH_RESULT_LIMIT:break
        return artists
    raise APIError('아티스트 검색을 지원하지 않는 플랫폼이야.',422)


def apple_artist_lookup(artist_id, country, sort=None):
    params={'id':artist_id,'entity':'song','country':country,'limit':200}
    if sort:params['sort']=sort
    with APPLE_QUERY_LOCK:
        delay=max(0.0, APPLE_NEXT_QUERY[0]-time.monotonic())
        if delay:time.sleep(delay)
        APPLE_NEXT_QUERY[0]=time.monotonic()+APPLE_MIN_INTERVAL
    url='https://itunes.apple.com/lookup?' + urllib.parse.urlencode(params)
    return request_json(url,headers={'User-Agent':'TRACKROOM/0.59'},timeout=10).get('results',[])


def artist_tracks(artist):
    """Artist ID scoped lookup, filtering out unrelated contributors/identical names."""
    if artist.get('itemType') != 'artist':
        raise APIError('아티스트 프로필을 먼저 선택해 줘.',422)
    if artist.get('sourcePlatform') == 'apple':
        aid=str(artist.get('sourceId') or '')
        country=artist.get('storeCountry','US')
        if not aid.isdigit() or country not in ('US','JP'):
            raise APIError('유효한 아티스트 정보를 다시 선택해 줘.',422)
        # Combine leading catalog songs and recent releases; don't let the first
        # 50 popular entries prevent new songs from ever appearing.
        buckets=[]
        for sort in (None,'recent'):
            songs=[]
            used=set()
            for row in apple_artist_lookup(aid,country,sort):
                if not isinstance(row,dict) or row.get('kind') != 'song':continue
                candidate_aid=str(row.get('artistId') or '')
                # IDs are authoritative. Only fall back to exact names when absent.
                if candidate_aid and candidate_aid != aid:continue
                if not candidate_aid and artwork_key(row.get('artistName')) != artwork_key(artist['artist']):continue
                item=normalize_apple_record(row,country)
                if not item or item['sourceId'] in used:continue
                used.add(item['sourceId'])
                songs.append(item)
                if len(songs)>=SEARCH_RESULT_LIMIT:break
            buckets.append(songs)
        results=[]
        seen=set()
        for bucket in buckets:
            for item in bucket:
                if item['sourceId'] in seen:continue
                seen.add(item['sourceId'])
                item['searchRank']=len(results)
                results.append(item)
        return results
    if artist.get('sourcePlatform') == 'lastfm':
        # Last.fm's artist.getTopTracks is scoped to the selected artist.
        result=lastfm_api('artist.getTopTracks',artist=artist['artist'],limit=SEARCH_RESULT_LIMIT,autocorrect=0)
        data=(result.get('toptracks') or {}).get('track') or []
        if isinstance(data,dict):data=[data]
        if not isinstance(data,list):data=[]
        tracks=[]
        seen=set()
        for row in data:
            if not isinstance(row,dict):continue
            name=row.get('name')
            owner=row.get('artist') or artist['artist']
            owner=owner.get('name') or owner.get('#text') or '' if isinstance(owner,dict) else owner
            link=row.get('url') or ''
            if not (isinstance(name,str) and name.strip() and isinstance(owner,str)
                    and artwork_key(owner)==artwork_key(artist['artist'])
                    and isinstance(link,str)):
                continue
            link=link.replace('http://','https://',1)
            if not valid_lastfm_url(link):continue
            key=artwork_key(name)
            if key in seen:continue
            seen.add(key)
            source_id=str(row.get('mbid') or '').strip() or ('url-' + hashlib.sha256(link.encode()).hexdigest()[:32])
            tracks.append({'itemType':'track','sourcePlatform':'lastfm','sourceCatalog':'lastfm',
                'sourceId':source_id,'title':name[:120],'artist':owner[:120],
                'album':'','musicUrl':link[:500],'artworkUrl':'','durationMs':None,'isrc':'',
                'searchRank':len(tracks)})
            if len(tracks)>=SEARCH_RESULT_LIMIT:break
        return tracks
    raise APIError('이 검색 엔진에서는 아티스트 곡 조회를 지원하지 않아.',422)


def apple_dedupe_key(record):
    # Cross-country results often use different store IDs for the same release.
    # Keep albums distinct: studio, remaster, compilation versions are not equal.
    return (record.get('itemType'), artwork_key(record['title']),
            artwork_key(record['artist']), artwork_key(record.get('album') or record['title']))


def blend_storefronts(pairs):
    """Mix US and JP instead of letting the first country's 50 items crowd out JP."""
    us=[p for p in pairs if p[0]=='US']
    jp=[p for p in pairs if p[0]=='JP']
    extra=[p for p in pairs if p[0] not in ('US','JP')]
    combined=[]
    for i in range(max(len(us),len(jp))):
        if i<len(us): combined.append(us[i])
        if i<len(jp): combined.append(jp[i])
    return combined+extra


def merge_apple_results(pairs, max_results=SEARCH_RESULT_LIMIT):
    unique={}
    for rank, (country, row) in enumerate(blend_storefronts(pairs)):
        kind = 'album' if (row.get('wrapperType') == 'collection' or row.get('collectionType') == 'Album' or ('collectionId' in row and 'trackId' not in row)) else 'track'
        item = normalize_apple_record(row, country, kind)
        if not item: continue
        key=apple_dedupe_key(item)
        if key in unique:
            # Retain first entry and its rank; fill missing image from another storefront.
            if not unique[key].get('artworkUrl') and item.get('artworkUrl'):
                unique[key]['artworkUrl']=item['artworkUrl']
            continue
        item['searchRank']=rank
        unique[key]=item
        if len(unique) >= max_results: break
    return list(unique.values())


def apple_catalog_search(query, search_mode='track'):
    if search_mode == 'album':
        return search_albums('apple', query)
    # Combine both countries even when US already returned results, because
    # Japanese releases frequently do not appear in the US iTunes catalogue.
    pairs=[]
    for country in ('US','JP'):
        rows=apple_search_request(query,country,'song',150,
                                  'artistTerm' if search_mode == 'artist' else None)
        pairs.extend((country,r) for r in rows if isinstance(r,dict))
    results=merge_apple_results(pairs)
    # A title such as MONOLITH may be indexed as an album even when its tracks
    # are missing from an ordinary song search. Try a well-matched album once.
    if search_mode == 'track':
        known_alias = SEARCH_ALIASES.get(query.strip())
        variants = [known_alias] if known_alias else []
        # If a compound query is not indexed, try its components as fallback.
        if not results and len(query.split()) > 1:
            variants.extend([query.split()[0], ' '.join(query.split()[1:])])
        for alias in [v for v in variants if v and v != query][:2]:
            extra_pairs=[]
            for country in ('JP','US'):
                extra_pairs.extend((country,r) for r in apple_search_request(alias,country,'song',100)
                                   if isinstance(r,dict))
            # Prefer a known localized spelling even when the original query
            # already returned 50 less relevant matches.
            pairs = extra_pairs + pairs if alias == known_alias else pairs + extra_pairs
            results=merge_apple_results(pairs)
            if len(results) >= SEARCH_RESULT_LIMIT and not known_alias: break
        # Search for same-titled albums; expand only the closest exact album.
        # This fixes missing tracks without indiscriminately injecting unrelated
        # albums into generic queries, and preserves the original song titles.
        if len(results) < 25 and (not results or (query.isascii() and len(query.split()) <= 2)):
            album_pairs=[]
            for country in ('US','JP'):
                album_pairs += [(country, r) for r in apple_search_request(query,country,'album',40)
                                if isinstance(r,dict)]
            matching_albums=[a for a in merge_apple_results(album_pairs,60) if a.get('itemType') == 'album']
            query_key=artwork_key(query)
            exact_albums=[album for album in matching_albums
                          if artwork_key(album['title']) == query_key]
            # For a mixed artist+album query, require album and artist name to
            # both appear as full tokens in the query before expanding.
            if not exact_albums and ' ' in query:
                exact_albums=[a for a in matching_albums if
                              artwork_key(a['title']) in query_key and
                              artwork_key(a['artist']) in query_key]
            if len(exact_albums) == 1:
                album=exact_albums[0]
                try:
                    tracks=fetch_album_tracks(album)
                    for t in tracks:
                        t.setdefault('releaseDate',album.get('releaseDate',''))
                    results=merge_apple_results(pairs,120)
                    seen={apple_dedupe_key(r) for r in results}
                    for t in tracks:
                        if apple_dedupe_key(t) not in seen:
                            t['searchRank']=len(results)
                            results.append(t)
                            seen.add(apple_dedupe_key(t))
                except (APIError,ValueError) as exc:
                    print(f'[TRACKROOM search] Album expansion failed: {exc}',flush=True)
    return results[:SEARCH_RESULT_LIMIT]


def search_catalog(platform, query, search_mode='track'):
    """Search the requested provider; never fall back silently to another catalog."""
    if platform == 'lastfm':
        api_key = os.environ.get('LASTFM_API_KEY', '').strip()
        if not api_key:
            raise APIError('Last.fm API 키가 설정되지 않았어. 관리자에게 LASTFM_API_KEY 설정을 요청해 줘.', 503)
        def call_lastfm(method, **arguments):
            params = {'method': method, 'api_key': api_key, 'format': 'json', **arguments}
            url = 'https://ws.audioscrobbler.com/2.0/?' + urllib.parse.urlencode(params)
            obj = request_json(url, headers={'User-Agent': 'TRACKROOM/0.4 (https://trackroom.onrender.com)'})
            if obj.get('error'):
                code = obj.get('error')
                if code == 29:
                    raise APIError('Last.fm 검색 요청이 많아. 잠시 후 다시 검색해 줘.', 429)
                if code in (10, 26):
                    raise APIError('Last.fm API 키가 올바르지 않거나 비활성화됐어.', 503)
                raise APIError('Last.fm 검색 결과를 가져오지 못했어.', 502)
            return obj
        def as_list(value):
            return value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        def make_result(t):
            title = t.get('name', '')
            artist_value = t.get('artist', '')
            artist = artist_value.get('name', '') if isinstance(artist_value, dict) else artist_value
            raw_url = t.get('url', '')
            if not isinstance(title, str) or not isinstance(artist, str) or not isinstance(raw_url, str):
                return None
            music_url = raw_url.replace('http://', 'https://', 1)
            parsed = urlparse(music_url)
            if parsed.scheme != 'https' or parsed.hostname not in ('www.last.fm', 'last.fm') or not parsed.path.startswith('/music/'):
                return None
            if not title.strip() or not artist.strip():
                return None
            # Last.fm often leaves MBIDs empty; the canonical Last.fm link is a stable fallback ID.
            mbid = str(t.get('mbid') or '').strip()
            source_id = mbid or 'url-' + hashlib.sha256(music_url.encode('utf-8')).hexdigest()[:32]
            return {'sourcePlatform': 'lastfm', 'sourceCatalog': 'lastfm',
                    'sourceId': source_id, 'title': title.strip()[:120],
                    'artist': artist.strip()[:120], 'album': '',
                    'musicUrl': music_url[:500], 'artworkUrl': '', 'artworkStoreUrl': '',
                    'durationMs': None, 'isrc': ''}
        def unpack(obj, method):
            if method == 'track.search':
                return as_list((obj.get('results') or {}).get('trackmatches', {}).get('track'))
            return as_list((obj.get('toptracks') or {}).get('track'))
        # The UI offers explicit song/artist search so searches for 'IU' return IU's tracks.
        if search_mode == 'artist':
            items = unpack(call_lastfm('artist.getTopTracks', artist=query, autocorrect=1, limit=65), 'artist.getTopTracks')
        else:
            items = unpack(call_lastfm('track.search', track=query, limit=75), 'track.search')
        if not items and search_mode == 'track' and ' ' in query:
            # Handle common searches like '아이유 밤편지' without requiring an exact song title.
            tokens = query.split()
            for split_at in range(1, min(len(tokens), 4)):
                obj = call_lastfm('track.search', artist=' '.join(tokens[:split_at]),
                                  track=' '.join(tokens[split_at:]), limit=75)
                items = unpack(obj, 'track.search')
                if items:
                    break
        results, seen = [], set()
        for item in items:
            result = make_result(item)
            if not result:
                continue
            key = (result['title'].casefold(), result['artist'].casefold())
            if key in seen:
                continue
            seen.add(key)
            result['searchRank']=len(results)
            results.append(result)
            if len(results) >= SEARCH_RESULT_LIMIT:
                break
        return enrich_lastfm_results(results, query)
    if platform == 'spotify':
        token = spotify_access_token()
        url = 'https://api.spotify.com/v1/search?' + urllib.parse.urlencode({
            'q': query, 'type': 'track', 'market': 'KR', 'limit': 10})
        obj = request_json(url, {'Authorization': 'Bearer ' + token})
        tracks = obj.get('tracks', {}).get('items', [])
        results = []
        for t in tracks:
            item_url = (t.get('external_urls') or {}).get('spotify', '')
            if not re.fullmatch(r'https://open\.spotify\.com/track/[a-zA-Z0-9]{15,30}(?:\?.*)?', item_url):
                continue
            images = (t.get('album') or {}).get('images') or []
            results.append({'sourcePlatform': 'spotify', 'sourceCatalog': 'spotify',
                'sourceId': str(t.get('id','')), 'title': t.get('name',''),
                'artist': ', '.join(a.get('name', '') for a in t.get('artists', [])),
                'album': (t.get('album') or {}).get('name', ''),
                'musicUrl': item_url, 'artworkUrl': safe_artwork(images[0].get('url', '')) if images else '',
                'durationMs': t.get('duration_ms') or None,
                'isrc': (t.get('external_ids') or {}).get('isrc', '')})
        return results
    if platform == 'apple':
        developer_token = os.environ.get('APPLE_MUSIC_DEVELOPER_TOKEN', '').strip()
        if developer_token:
            url = 'https://api.music.apple.com/v1/catalog/kr/search?' + urllib.parse.urlencode({
                'term': query, 'types': 'songs', 'limit': 50})
            obj = request_json(url, {'Authorization': 'Bearer ' + developer_token})
            result = []
            for t in obj.get('results', {}).get('songs', {}).get('data', []):
                attr = t.get('attributes') or {}
                artwork_template = (attr.get('artwork') or {}).get('url', '')
                art = artwork_template.replace('{w}', '300').replace('{h}', '300')
                item_url = attr.get('url', '')
                if urlparse(item_url).hostname != 'music.apple.com':
                    continue
                result.append({'sourcePlatform':'apple','sourceCatalog':'apple_music',
                    'sourceId':str(t.get('id', '')), 'title':attr.get('name',''),
                    'artist':attr.get('artistName',''), 'album':attr.get('albumName', ''),
                    'albumId': str(next((a.get('id','') for a in
                                     ((t.get('relationships') or {}).get('albums') or {}).get('data', [])
                                     if a.get('id')), '')),
                    'storeCountry':'KR', 'musicUrl':item_url, 'artworkUrl':safe_artwork(art),
                    'durationMs':attr.get('durationInMillis') or None,
                    'isrc':attr.get('isrc', ''), 'releaseDate':attr.get('releaseDate',''),
                    'searchRank':len(result)})
            return result
        return apple_catalog_search(query, search_mode)
    raise APIError('이 음원 플랫폼은 공식 사이트 내 검색을 아직 지원하지 않아. 다른 검색 제공원을 선택해 줘.', 422)


def lastfm_api(method, **arguments):
    """Read-only Last.fm API helper; no user Last.fm login is needed."""
    key = os.environ.get('LASTFM_API_KEY', '').strip()
    if not key:
        raise APIError('Last.fm API 키가 설정되지 않았어.', 503)
    url = 'https://ws.audioscrobbler.com/2.0/?' + urllib.parse.urlencode({
        'method':method, 'api_key':key, 'format':'json', **arguments
    })
    data = request_json(url, headers={'User-Agent':'TRACKROOM/0.5 (https://trackroom.onrender.com)'})
    if not isinstance(data, dict):
        raise APIError('Last.fm 응답을 확인할 수 없어.', 502)
    if data.get('error'):
        code = data['error']
        raise APIError('Last.fm 요청이 너무 많아. 잠시 후 다시 시도해 줘.' if code == 29
                       else 'Last.fm API 키를 확인해 줘.' if code in (10, 26)
                       else 'Last.fm에서 앨범 정보를 가져오지 못했어.',
                       429 if code == 29 else 503 if code in (10, 26) else 502)
    return data


def valid_lastfm_url(url):
    try:
        parsed = urlparse(url)
        return (parsed.scheme == 'https' and parsed.hostname in ('last.fm','www.last.fm')
                and parsed.path.startswith('/music/'))
    except (ValueError, TypeError):
        return False


def search_albums(platform, query):
    """Return album choices, not creatable song choices."""
    if platform == 'apple':
        pairs=[]
        for country in ('US','JP'):
            rows=apple_search_request(query,country,'album',125)
            pairs.extend((country,row) for row in rows if isinstance(row,dict))
        # Treat the search engine's order as a relevance-based popularity proxy.
        return [a for a in merge_apple_results(pairs) if a['itemType'] == 'album']
    if platform == 'lastfm':
        albums = (lastfm_api('album.search', album=query, limit=70).get('results') or {}).get('albummatches') or {}
        rows = albums.get('album') or []
        rows = rows if isinstance(rows, list) else [rows] if isinstance(rows,dict) else []
        result=[]
        for row in rows:
            if not isinstance(row,dict): continue
            title, artist = row.get('name',''), row.get('artist','')
            link = row.get('url','')
            if not (isinstance(title,str) and isinstance(artist,str) and title and artist
                    and isinstance(link,str) and valid_lastfm_url(link.replace('http://','https://',1))):
                continue
            link=link.replace('http://','https://',1)
            aid = str(row.get('mbid') or '') or ('url-' + hashlib.sha256(link.encode()).hexdigest()[:32])
            result.append({'itemType':'album','sourcePlatform':'lastfm','sourceCatalog':'lastfm',
                           'sourceId':aid,'title':title[:120],'artist':artist[:120],
                           'album':title[:120],'musicUrl':link[:500],
                           'artworkUrl':'','durationMs':None,'isrc':'','searchRank':len(result)})
            if len(result)==SEARCH_RESULT_LIMIT:break
        return result
    raise APIError('앨범 검색을 지원하지 않는 플랫폼이야.',422)


def fetch_album_tracks(album):
    """Expand an authenticated search result into selectable *tracks*."""
    if album.get('sourcePlatform') == 'apple':
        album_id = str(album.get('sourceId',''))
        country = album.get('storeCountry','US')
        if not (album_id.isdigit() and country in ('US','JP')):
            raise APIError('앨범 정보를 다시 검색해 줘.',422)
        # Search API rate limit also applies to lookup requests.
        with APPLE_QUERY_LOCK:
            delay = max(0.0, APPLE_NEXT_QUERY[0] - time.monotonic())
            if delay: time.sleep(delay)
            APPLE_NEXT_QUERY[0] = time.monotonic() + APPLE_MIN_INTERVAL
        url = 'https://itunes.apple.com/lookup?' + urllib.parse.urlencode({
            'id':album_id,'entity':'song','country':country,'limit':200})
        rows = request_json(url,headers={'User-Agent':'TRACKROOM/0.5'},timeout=8).get('results', [])
        results=[]
        for row in rows:
            if not isinstance(row,dict) or row.get('kind') != 'song': continue
            track_id, link = row.get('trackId'), row.get('trackViewUrl','')
            if not (str(track_id).isdigit() and isinstance(link,str) and
                    urlparse(link).hostname in ('itunes.apple.com','music.apple.com')): continue
            results.append({'itemType':'track','sourcePlatform':'apple','sourceCatalog':'itunes_store',
                            'sourceId':str(track_id),'title':row.get('trackName','')[:120],
                            'artist':row.get('artistName','')[:120],
                            'album':row.get('collectionName','')[:120],
                            'albumId':str(row.get('collectionId') or album_id),
                            'storeCountry':country, 'musicUrl':link[:500],
                            'artworkUrl':safe_artwork(row.get('artworkUrl100','')) or album.get('artworkUrl',''),
                            'durationMs':row.get('trackTimeMillis') or None,'isrc':'',
                            'releaseDate':row.get('releaseDate',''),
                            'trackNumber':row.get('trackNumber',0)})
        return [t for t in results if t['title'] and t['artist']]
    if album.get('sourcePlatform') == 'lastfm':
        response = lastfm_api('album.getinfo', artist=album['artist'], album=album['title'], autocorrect=1)
        tracks = (response.get('album') or {}).get('tracks') or {}
        rows = tracks.get('track') or []
        rows = rows if isinstance(rows,list) else [rows] if isinstance(rows,dict) else []
        results=[]
        for row in rows:
            if not isinstance(row,dict): continue
            title = row.get('name','')
            raw_artist = row.get('artist') or album['artist']
            artist = raw_artist.get('name') or raw_artist.get('#text') or album['artist'] if isinstance(raw_artist,dict) else raw_artist
            link = row.get('url','')
            if not (isinstance(title,str) and isinstance(artist,str) and isinstance(link,str)):continue
            link = link.replace('http://','https://',1)
            if not (title and artist and valid_lastfm_url(link)):continue
            song_id = str(row.get('mbid') or '') or ('url-' + hashlib.sha256(link.encode()).hexdigest()[:32])
            results.append({'itemType':'track','sourcePlatform':'lastfm','sourceCatalog':'lastfm',
                            'sourceId':song_id,'title':title[:120],'artist':artist[:120],
                            'album':album['title'][:120], 'musicUrl':link[:500],
                            'artworkUrl':'','durationMs':None,'isrc':'','searchRank':len(results)})
        return results
    raise APIError('앨범 검색 결과가 올바르지 않아.',422)



def album_for_search_track(track):
    """Return the actual album and its tracklist from one signed search result.

    iTunes track results contain collectionId; this must be preserved in the
    signed payload so the cover opens the correct edition, not a title guess.
    Last.fm uses track.getInfo to discover the album, then album.getInfo.
    """
    if track.get('itemType', 'track') == 'album':
        album = track
    elif track.get('sourcePlatform') == 'apple' and track.get('sourceCatalog') == 'itunes_store':
        album_id = str(track.get('albumId') or '')
        country = track.get('storeCountry', 'US')
        if not (album_id.isdigit() and country in ('US', 'JP')):
            # Backward compatibility for signed search results made before v5.8.
            # Resolve by track ID; NEVER guess by album title alone.
            tid = str(track.get('sourceId') or '')
            if not tid.isdigit():
                raise APIError('앨범 ID가 없어. 곡을 다시 검색해 줘.', 422)
            with APPLE_QUERY_LOCK:
                pause = max(0.0, APPLE_NEXT_QUERY[0] - time.monotonic())
                if pause: time.sleep(pause)
                APPLE_NEXT_QUERY[0] = time.monotonic() + APPLE_MIN_INTERVAL
            data = request_json('https://itunes.apple.com/lookup?' + urllib.parse.urlencode({
                'id': tid, 'country': country}),
                headers={'User-Agent':'TRACKROOM/0.58'}, timeout=8)
            match = next((item for item in data.get('results', [])
                          if str(item.get('trackId', '')) == tid), None)
            album_id = str((match or {}).get('collectionId') or '')
            if not album_id.isdigit():
                raise APIError('이 곡의 앨범 정보를 찾을 수 없어.', 404)
        album = {
            'itemType':'album', 'sourcePlatform':'apple', 'sourceCatalog':'itunes_store',
            'sourceId': album_id, 'albumId': album_id, 'storeCountry': country,
            'title': track.get('album') or '', 'artist': track['artist'],
            'album': track.get('album') or '',
            'artworkUrl': track.get('artworkUrl') or '',
            'musicUrl': track.get('artworkStoreUrl') or track['musicUrl']
        }
    elif track.get('sourcePlatform') == 'lastfm':
        info = lastfm_api('track.getInfo', artist=track['artist'], track=track['title'], autocorrect=1)
        actual = info.get('track') or {}
        parent = actual.get('album') or {}
        name = parent.get('title') or ''
        artist = parent.get('artist') or track['artist']
        url = str(parent.get('url') or '').replace('http://','https://',1)
        if not (isinstance(name,str) and name.strip() and
                isinstance(artist,str) and artist.strip() and valid_lastfm_url(url)):
            raise APIError('Last.fm에 이 곡의 앨범 연결 정보가 없어. 앨범명으로 검색해 줘.',404)
        album = {
            'itemType':'album','sourcePlatform':'lastfm','sourceCatalog':'lastfm',
            'sourceId':str(parent.get('mbid') or ('url-' + hashlib.sha256(url.encode()).hexdigest()[:32])),
            'title':name[:120], 'artist':artist[:120], 'album':name[:120],
            'musicUrl':url[:500], 'artworkUrl':track.get('artworkUrl') or ''
        }
    else:
        raise APIError('이 검색 서비스에서는 앨범 바로 가기를 아직 지원하지 않아.',422)

    tracks = fetch_album_tracks(album)
    if not tracks:
        raise APIError('앨범은 찾았지만 수록곡 목록을 가져오지 못했어.',404)
    # Verify the exact track-to-album link for Apple (not fuzzy title matching).
    # This protects against mismatched artwork/card association.
    if (track.get('itemType') != 'album' and track.get('sourcePlatform') == 'apple'
            and track.get('sourceCatalog') == 'itunes_store'
            and not any(str(t.get('sourceId')) == str(track.get('sourceId')) for t in tracks)):
        raise APIError('선택한 곡이 해당 앨범의 수록곡으로 확인되지 않아.',404)
    tracks.sort(key=lambda item: int(item.get('trackNumber') or 0))
    album_info = {
        'title':album['title'], 'artist':album['artist'],
        'artworkUrl':album.get('artworkUrl') or next((t.get('artworkUrl') for t in tracks if t.get('artworkUrl')), ''),
        'musicUrl':album.get('musicUrl',''), 'trackCount':len(tracks),
    }
    return album_info, tracks


def sign_selection(track, user_id):
    selected = dict(track)
    selected['exp'] = int(time.time()) + 15 * 60
    selected['uid'] = user_id
    payload = base64.urlsafe_b64encode(json.dumps(selected, ensure_ascii=False, separators=(',', ':')).encode()).rstrip(b'=')
    digest = hmac.new(CATALOG_SECRET, payload, hashlib.sha256).hexdigest()
    return payload.decode('ascii') + '.' + digest


def verify_selection(token, user_id):
    if not isinstance(token, str) or not 10 < len(token) < 6000 or token.count('.') != 1:
        raise APIError('검색 결과에서 실제 음원을 선택해 줘.')
    payload, signature = token.split('.', 1)
    computed = hmac.new(CATALOG_SECRET, payload.encode('ascii', errors='ignore'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, computed):
        raise APIError('선택한 음원 정보가 유효하지 않아. 다시 검색해 줘.')
    try:
        song = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except (ValueError, TypeError):
        raise APIError('선택한 음원 정보가 올바르지 않아.')
    if song.get('uid') != user_id or song.get('exp', 0) < time.time():
        raise APIError('음원 선택이 만료됐어. 다시 검색해 줘.')
    if song.get('sourcePlatform') not in ('spotify', 'apple', 'lastfm') or not song.get('sourceId'):
        raise APIError('선택한 음악 정보를 확인할 수 없어.')
    if not song.get('title') or not song.get('artist') or not song.get('musicUrl'):
        raise APIError('선택한 음악 정보를 확인할 수 없어.')
    return song


def search_rate_limit(user_id):
    with SEARCH_LOCK:
        t = time.time()
        recent = [when for when in SEARCH_REQUESTS.get(user_id, ()) if t - when < 60]
        if len(recent) >= 25:
            raise APIError('검색을 너무 자주 했어. 잠시 후 다시 시도해 줘.', 429)
        recent.append(t)
        SEARCH_REQUESTS[user_id] = recent
        if len(SEARCH_REQUESTS) > 2500:
            SEARCH_REQUESTS.clear()



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
            with db() as conn:
                conn.execute('SELECT 1').fetchone()
            return self.send_json({'ok': True, 'storage': 'postgresql' if DATABASE_URL else 'sqlite'})
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
        # Resolve album art progressively after song search. Only a signed
        # Last.fm result from this user can be resolved, so callers cannot
        # turn the endpoint into an arbitrary Apple search proxy.
        if method == 'POST' and route == '/api/catalog/cover':
            token = self.body().get('selectionToken')
            selection = verify_selection(token, user['id'])
            if selection.get('sourcePlatform') != 'lastfm':
                raise APIError('Last.fm 검색 결과에만 커버 조회를 사용할 수 있어.', 422)
            search_rate_limit(user['id'])
            if not selection.get('artworkUrl'):
                cover = find_itunes_cover(selection['title'], selection['artist'])
                if cover:
                    selection['artworkUrl'] = cover['url']
                    selection['artworkStoreUrl'] = cover['storeUrl']
                    selection['album'] = cover['album']
            return self.send_json({
                'found': bool(selection.get('artworkUrl')),
                'artworkUrl': selection.get('artworkUrl', ''),
                'artworkStoreUrl': selection.get('artworkStoreUrl', ''),
                'album': selection.get('album', ''),
                'selectionToken': sign_selection(selection, user['id'])
            })

        if method == 'POST' and route == '/api/catalog/artist-tracks':
            selection = verify_selection(self.body().get('selectionToken'), user['id'])
            if selection.get('itemType') != 'artist':
                raise APIError('아티스트 검색에서 프로필을 선택해 줘.',422)
            search_rate_limit(user['id'])
            tracks = artist_tracks(selection)
            return self.send_json({'artistInfo':{
                'title':selection['title'],'genre':selection.get('genre',''),
                'musicUrl':selection.get('musicUrl',''), 'trackCount':len(tracks),
                'sourceCatalog':selection.get('sourceCatalog','')},
                'results':[{**song,'selectionToken':sign_selection(song,user['id'])} for song in tracks]})

        if method == 'POST' and route == '/api/catalog/album-tracks':
            selection = verify_selection(self.body().get('selectionToken'), user['id'])
            if selection.get('itemType') != 'album':
                raise APIError('앨범 검색 결과를 먼저 선택해 줘.',422)
            search_rate_limit(user['id'])
            album_info, tracks = album_for_search_track(selection)
            return self.send_json({'results':[{**song, 'selectionToken':sign_selection(song,user['id'])}
                                              for song in tracks], 'album':selection['title'], 'albumInfo':album_info})

        if method == 'POST' and route == '/api/catalog/track-album':
            selection = verify_selection(self.body().get('selectionToken'), user['id'])
            if selection.get('itemType') in ('album','artist'):
                raise APIError('먼저 곡 검색 결과를 선택해 줘.', 422)
            search_rate_limit(user['id'])
            album_info, tracks = album_for_search_track(selection)
            return self.send_json({'albumInfo':album_info,
                                   'results':[{**song, 'selectionToken':sign_selection(song,user['id'])}
                                              for song in tracks]})

        if method == 'GET' and route == '/api/catalog/search':
            params = parse_qs(parsed.query)
            platform = params.get('platform', [''])[0]
            search_mode = params.get('kind', ['track'])[0]
            query = params.get('q', [''])[0].strip()
            if not 2 <= len(query) <= 80:
                raise APIError('검색어는 2~80자로 입력해 줘.')
            if platform not in ('spotify', 'apple', 'lastfm'):
                raise APIError('이 플랫폼에서는 아직 사이트 내 검색을 제공하지 않아.', 422)
            if search_mode not in ('track','artist','album'):
                raise APIError('검색 유형이 올바르지 않아.', 422)
            search_rate_limit(user['id'])
            # Keep this cache short and not tied to a Spotify user session.
            key = (platform, search_mode, query.casefold())
            with CACHE_LOCK:
                cached = SEARCH_CACHE.get(key)
            if cached and cached[0] > time.time():
                tracks = cached[1]
            else:
                if search_mode == 'artist':
                    tracks = search_artists(platform, query)
                elif search_mode == 'album':
                    tracks = search_albums(platform, query)
                elif platform == 'lastfm':
                    tracks = search_catalog(platform, query, search_mode)
                else:
                    tracks = search_catalog(platform, query if search_mode != 'artist' else query, search_mode)
                tracks = [t for t in tracks if t.get('sourceId') and t.get('title') and t.get('artist') and t.get('musicUrl')]
                with CACHE_LOCK:
                    SEARCH_CACHE[key] = (time.time() + 180, tracks[:SEARCH_RESULT_LIMIT])
                    if len(SEARCH_CACHE) > 200:
                        SEARCH_CACHE.clear()
            response = []
            for song in tracks[:SEARCH_RESULT_LIMIT]:
                response.append({**song, 'selectionToken': sign_selection(song, user['id'])})
            return self.send_json({'results': response, 'catalog':
                response[0]['sourceCatalog'] if response else
                ('apple_music' if platform == 'apple' and os.environ.get('APPLE_MUSIC_DEVELOPER_TOKEN') else
                 'itunes_store' if platform == 'apple' else 'lastfm' if platform == 'lastfm' else 'spotify')})
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

        # Recover covers for songs added before artwork matching was enabled.
        # Explicit action to avoid dozens of surprise API calls on every page load.
        match_covers = re.fullmatch(r'/api/rooms/([^/]+)/covers/restore', route)
        if match_covers and method == 'POST':
            restore_request = self.body()
            force = restore_request.get('retry') is True
            code = clean_code(match_covers.group(1))
            with db() as conn:
                check_room(conn, code)
                check_member(conn, code, user['id'])
                pending = conn.execute('''SELECT id,title,artist FROM songs WHERE room_code=?
                    AND source_platform='lastfm' AND (artwork_url IS NULL OR artwork_url='')
                    AND (artwork_checked_at IS NULL OR artwork_checked_at < ? OR ?=1)
                    ORDER BY COALESCE(artwork_checked_at,0) ASC, id DESC LIMIT 4''',
                    (code, int(time.time())-86400, int(force))).fetchall()
            count = 0
            for song in pending:
                cover = find_itunes_cover(song['title'], song['artist'], force=True) if force else find_itunes_cover(song['title'], song['artist'])
                with db() as conn:
                    if cover:
                        conn.execute('''UPDATE songs SET artwork_url=?, artwork_store_url=?,
                            album_name=CASE WHEN (album_name IS NULL OR album_name='') THEN ? ELSE album_name END,
                            artwork_checked_at=? WHERE id=? AND room_code=? AND (artwork_url IS NULL OR artwork_url='')''',
                            (cover['url'], cover['storeUrl'], cover['album'], int(time.time()), song['id'], code))
                        count += 1
                    else:
                        conn.execute('UPDATE songs SET artwork_checked_at=? WHERE id=? AND room_code=?',
                                     (int(time.time()), song['id'], code))
            return self.send_json({'updated':count, 'checked':len(pending)})

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
                selection = verify_selection(data.get('selectionToken'), user['id'])
                if selection.get('itemType') in ('album','artist'):
                    raise APIError('프로필이나 앨범 전체가 아니라 곡을 선택해 줘.',422)
                title, artist = selection['title'][:120], selection['artist'][:120]
                url = selection['musicUrl'][:500]
                if selection['sourcePlatform'] == 'lastfm' and not selection.get('artworkUrl'):
                    cover = find_itunes_cover(title, artist)
                    if cover:
                        selection['artworkUrl'] = cover['url']
                        selection['artworkStoreUrl'] = cover['storeUrl']
                        selection['album'] = cover['album']
                note = optional_string(data, 'note', 500)
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
                    conn.execute('''INSERT INTO songs(room_code,user_id,nickname,title,artist,music_url,note,start_seconds,end_seconds,created_at,
                      source_platform,source_id,source_catalog,artwork_url,album_name,duration_ms,isrc,artwork_store_url)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (code, user['id'], user['nickname'], title, artist, url, note, start, end, now(),
                       selection['sourcePlatform'], selection['sourceId'], selection['sourceCatalog'],
                       selection.get('artworkUrl','')[:500], selection.get('album','')[:120],
                       selection.get('durationMs'), selection.get('isrc','')[:32],
                       selection.get('artworkStoreUrl','')[:500]))
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
    print(f'TRACKROOM 실행 중 → http://localhost:{PORT} (영구 저장소: {"PostgreSQL" if DATABASE_URL else "로컬 SQLite"})', flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
