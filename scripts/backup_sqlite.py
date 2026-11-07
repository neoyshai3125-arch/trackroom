#!/usr/bin/env python3
"""Create a consistent backup of a LOCAL SQLite file (including WAL changes)."""
import argparse
import sqlite3
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description='TRACKROOM 로컬 SQLite 안전 백업')
    p.add_argument('source', help='백업할 기존 SQLite 파일')
    p.add_argument('output', help='백업 파일을 저장할 경로')
    a = p.parse_args()
    source, target = Path(a.source).expanduser().resolve(), Path(a.output).expanduser().resolve()
    if not source.is_file():
        p.error('원본 SQLite 파일을 찾을 수 없음')
    if source == target or target.exists():
        p.error('원본을 덮거나 기존 백업을 덮어쓸 수 없어. 새 백업 파일명을 지정해 줘.')
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True) as current:
        with sqlite3.connect(target) as backup:
            current.backup(backup)
    print(f'백업 저장 완료: {target}')
    print('이 파일에는 비밀번호 해시/세션이 포함될 수 있으니 절대 GitHub에 올리지 마.')

if __name__ == '__main__':
    main()
