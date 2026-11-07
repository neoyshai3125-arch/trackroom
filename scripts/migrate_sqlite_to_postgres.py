#!/usr/bin/env python3
"""One-time, lossless migration of TRACKROOM's local SQLite database to Postgres.

Requires *actual access* to the old SQLite database file. Cannot fetch a
Render Free ephemeral SQLite file from the deployed site.

Usage: DATABASE_URL='postgresql://...' python scripts/migrate_sqlite_to_postgres.py /path/trackroom.sqlite3
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Parent tables first, to honor foreign keys and keep membership/likes.
TABLES = ('users', 'rooms', 'sessions', 'members', 'songs', 'likes')
# Never use dynamically sourced table names or field names in SQL.
VALID_FIELDS = {
    'users': ('id', 'username', 'password_salt', 'password_hash', 'nickname', 'platform', 'created_at'),
    'rooms': ('code', 'name', 'created_at'),
    'sessions': ('token_hash', 'user_id', 'expires_at'),
    'members': ('room_code', 'user_id', 'nickname', 'joined_at'),
    'songs': ('id', 'room_code', 'user_id', 'nickname', 'title', 'artist', 'music_url',
              'note', 'start_seconds', 'end_seconds', 'created_at', 'source_platform',
              'source_id', 'source_catalog', 'artwork_url', 'artwork_store_url',
              'artwork_checked_at', 'album_name', 'duration_ms', 'isrc'),
    'likes': ('song_id', 'user_id'),
}


def read_existing_sqlite(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f'SQLite 데이터베이스 파일을 찾지 못했어: {path}')
    # Read-only: never modify the source database.
    source = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    result = {}
    try:
        for table in TABLES:
            existing = source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not existing:
                raise RuntimeError(f'이 파일에는 TRACKROOM 필수 테이블이 없어: {table}')
            existing_columns = {col['name'] for col in source.execute(f'PRAGMA table_info({table})')}
            fields = tuple(field for field in VALID_FIELDS[table] if field in existing_columns)
            result[table] = (fields, [tuple(row[field] for field in fields)
                                     for row in source.execute(f'SELECT {", ".join(fields)} FROM {table}')])
    finally:
        source.close()
    return result


def perform_migration(data, connection):
    """Import to an EMPTY Postgres database in one transaction; never overwrite."""
    with connection.transaction():
        for table in TABLES:
            count = connection.execute(f'SELECT count(*) AS n FROM {table}').fetchone()[0]
            if count:
                raise RuntimeError(
                    f'대상 PostgreSQL {table} 테이블에 기존 데이터가 있어 이전을 중단했어. '
                    '중복 등록이나 덮어쓰기를 하지 않아. 기존 DB를 확인해 줘.'
                )
        for table in TABLES:
            fields, values = data[table]
            if not values:
                continue
            sql = f'INSERT INTO {table} ({", ".join(fields)}) VALUES ({", ".join(["%s"] * len(fields))})'
            with connection.cursor() as cursor:
                cursor.executemany(sql, values)
        # Explicitly inserted song IDs require resetting the BIGSERIAL sequence.
        connection.execute('''
            SELECT setval(
                pg_get_serial_sequence('songs', 'id'),
                GREATEST((SELECT COALESCE(MAX(id), 0) FROM songs), 1),
                (SELECT COUNT(*) > 0 FROM songs)
            )
        ''')
    return {table:len(data[table][1]) for table in TABLES}


def main(argv=None):
    parser = argparse.ArgumentParser(description='TRACKROOM SQLite → PostgreSQL 이전')
    parser.add_argument('sqlite_path', help='이미 백업해 둔 trackroom.sqlite3 파일 경로')
    args = parser.parse_args(argv)
    if not os.environ.get('DATABASE_URL'):
        parser.error('먼저 DATABASE_URL 환경 변수를 설정해야 해. (GitHub에 DB 비밀번호 업로드 금지)')
    data = read_existing_sqlite(args.sqlite_path)
    if not any(data[table][1] for table in ('users', 'rooms', 'songs')):
        raise SystemExit('SQLite 파일에 이전할 회원·방·곡이 없어. 빈 DB 이전을 중단해.')
    import server
    server.init_db()  # Creates/migrates tables without deleting existing rows.
    try:
        import psycopg
    except ImportError as error:
        raise SystemExit('먼저 pip install -r requirements.txt 실행 필요') from error
    with psycopg.connect(os.environ['DATABASE_URL'], sslmode='require') as connection:
        counts = perform_migration(data, connection)
    print('완료: 데이터가 PostgreSQL로 이전됐어. 원래 SQLite 파일은 변경하지 않았어.')
    print(' / '.join(f'{table}={count}' for table,count in counts.items()))


if __name__ == '__main__':
    main()
