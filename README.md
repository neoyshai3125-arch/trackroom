# TRACKROOM v6.0 — 회원·추천방 영구 저장 + 아티스트 프로필 검색

이 버전은 v5.9의 **아티스트 검색 → 아티스트 프로필 선택 → 그 아티스트의 곡 목록**과 v5.8 이하의 음악 검색/앨범 화면/버블 UI를 유지합니다.

## 왜 업데이트할 때 회원가입을 다시 해야 했나?

Render **Free Web Service의 파일 시스템은 일시적**입니다. TRACKROOM이 기본값 `trackroom.sqlite3`에 저장하면 **배포, 재시작, 15분 유휴 후 sleep** 때문에 데이터가 사라집니다. GitHub에 `*.sqlite3`를 커밋해도 실사용 데이터를 동기화할 수 없습니다.

이 버전은 **Render에서 `DATABASE_URL`(PostgreSQL)이 없는 경우 아예 서버 시작을 차단**하여, 빈 데이터베이스가 만들어지는 걸 막습니다. PC에서 로컬 실행할 때만 SQLite를 기본값으로 사용할 수 있습니다.

## 처음 한 번만 설정: 영구 PostgreSQL 데이터베이스

1. [Neon](https://neon.com/)에서 계정을 만들고 새 **PostgreSQL 프로젝트** 생성. Render에서 가까운 지역(가능하면 Asia / Seoul)을 선택할 수 있으면 선택하세요.
2. Neon 프로젝트의 **Connect** 버튼 → **Pooled connection string** 복사. `postgresql://...`로 시작하는 문자열입니다. **암호가 포함되어 있으므로 절대 GitHub, 채팅, 스크린샷에 노출하지 마세요.**
3. **Render 대시보드 → TRACKROOM Web Service → Environment → Add Environment Variable**:
   - Key: `DATABASE_URL`
   - Value: Neon의 Postgres 접속 문자열 **전체**
   - 기존 `LASTFM_API_KEY` 등은 그대로 유지.
4. 이 ZIP의 `server.py`, `requirements.txt`, `public/app.js`, `public/index.html`, `public/style.css` 및 `scripts/`(마이그레이션 도구 필요 시)를 GitHub 저장소에 반영.
5. Render의 **Settings → Build Command**를 `pip install -r requirements.txt`로 변경. 기존의 `echo "No dependencies"`를 유지하면 PostgreSQL 드라이버가 없어 실패합니다.
6. **Start Command**는 `python server.py` 그대로. GitHub 업데이트를 배포하고 Render `Live` 확인.
7. 사이트의 `https://<내-사이트>/health`에 접속해서 `{"ok":true,"storage":"postgresql"}`이 표시되는지 확인.

이후 업데이트에서는 **같은 `DATABASE_URL`을 유지하고 코드만 변경**하세요. 회원·방·추천곡·좋아요는 데이터베이스에 저장되고, 코드를 재배포해도 없어지지 않습니다. 무료 Neon에도 사용량 제한이 있으므로 중요한 DB는 주기적으로 별도 백업을 권장합니다.

> 주의: Render의 **무료 PostgreSQL**은 생성 후 30일이 지나면 만료됩니다. 오랫동안 유지하려면 Neon이나 지속 운영되는 유료 PostgreSQL을 추천합니다.

## 이전 회원 및 방 데이터를 그대로 옮기려면

**기존 `trackroom.sqlite3` 파일이 필요합니다.** 이 파일에는 사용자명·비밀번호 해시·세션·방·가입자·곡·좋아요가 모두 들어 있습니다.

Render Free 서버에서 실행 중인 SQLite는 배포 또는 재시작 전 미리 추출해야 합니다. Render Free에는 보통 Shell 기능이 없어 **현재 웹사이트에서 `server.py`를 교체하거나 `DATABASE_URL`만 설정하는 방식으로 기존 SQLite를 자동 이동할 수 없습니다.** 이전에 백업한 파일이나 로컬 사본이 있다면 아래 도구로 모두 이전 가능합니다.

```bash
# 로컬에 있던 SQLite를 백업 (원본 수정 없음)
python scripts/backup_sqlite.py trackroom.sqlite3 trackroom-backup.sqlite3

# 데이터베이스 접속 URL을 환경 변수로 설정 (커밋 금지)
# Linux/macOS:
export DATABASE_URL='postgresql://USER:PASSWORD@HOST/DB?sslmode=require'
# Windows PowerShell:
# $env:DATABASE_URL='postgresql://USER:PASSWORD@HOST/DB?sslmode=require'

pip install -r requirements.txt
python scripts/migrate_sqlite_to_postgres.py trackroom-backup.sqlite3
```

- PostgreSQL 대상 테이블이 **비어 있을 때만** 이전하므로, 이미 저장한 회원정보를 지우거나 덮어쓰지 않습니다.
- 회원 ID/비밀번호 해시/세션/방 코드/곡 ID/좋아요 관계를 유지하고, 곡 ID 자동증가 시퀀스를 재설정합니다.
- 새 버전에서 `init_db()`는 테이블이 없으면 만들고, 누락된 열을 추가하지만 기존 회원·방·곡을 삭제하지 않습니다.
- **기존 SQLite 파일이 사라졌다면 자동 복구할 수 없습니다.** DB 전체가 아니라 화면에서 보이는 곡/방 목록만 남아 있다면 일부 내용은 수작업으로 복원할 수 있지만, 계정 비밀번호 해시까지 복구할 수는 없습니다.

## 절대 순서를 바꾸지 마세요

- 이전 데이터가 있다면, **먼저 원본 SQLite 백업 확보** 및 복원 가능성 확인 → Neon 준비 → (백업이 있을 경우) 이전 실행 → GitHub/Render 배포.
- 업데이트 코드만 먼저 배포하면 Render Free의 SQLite에 남아 있던 기존 정보가 사라질 위험이 큽니다.
- 데이터 이전을 못한 상태로 새 Neon을 연결하면 **새 DB이므로 기존 회원과 방이 보이지 않습니다.** 백업 이전 없이 데이터가 보존되었다고 오해하지 마세요.

## 파일 구성

- `server.py`: 기존 API + PostgreSQL 저장 + 안전한 시작 제한
- `requirements.txt`: PostgreSQL 드라이버(`psycopg`)
- `public/`: v5.9 아티스트 프로필/앨범/버블 UI 포함
- `scripts/backup_sqlite.py`: 접속 가능한 로컬 SQLite를 안전하게 복사
- `scripts/migrate_sqlite_to_postgres.py`: 비어 있는 PostgreSQL에 로컬 DB 전량 이전
- `tests/`: 기존 + 영구 저장 관련 자동 테스트

## 검증

`python -m unittest discover -s tests -q` 및 `node --check public/app.js` 통과. 실제 Neon 접속 및 Render 배포는 사용자 데이터베이스 비밀키가 없으므로 확인하지 못했습니다.
