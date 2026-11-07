# TRACKROOM v3 — 플랫폼 카탈로그 검색 후 추천곡 등록

TRACKROOM v2(회원가입/닉네임/사용 플랫폼/추천방/좋아요)를 유지하면서 **음원 검색 → 공식 카탈로그 곡 선택 → 추천** 기능을 추가했습니다.

## 추가된 기능

- 임의 제목/가수 직접 입력을 제거하고 **검색 결과에서 곡을 선택한 경우에만 등록**합니다.
- 검색에서 선택한 곡의 제목, 아티스트, 원본 링크, 제공자 ID, 앨범, 곡 길이, 앨범 커버 등을 데이터베이스에 기록합니다.
- 원본 플랫폼의 검색 결과를 서버에서 서명한 임시 선택 토큰으로 검증하므로, 클라이언트가 곡 제목을 조작하거나 임의 음원을 만들어 등록하는 요청을 거절합니다.
- 예전에 등록한 기존 추천곡과 로그인 정보는 DB가 유지되는 한 보존되며, 서버 시작 시 `songs` 테이블에 컬럼만 추가합니다.
- 재생은 지원하지 않습니다. 추천 구간(시작/종료 시각)은 기록만 합니다.

## 플랫폼별 지원 범위 (중요)

| 선택 플랫폼 | 실제 검색 | 필요한 준비 | 주의사항 |
|---|---|---|---|
| Apple Music / Apple | **iTunes Store 공개 검색**은 설정 없이 가능 | 없음 | iTunes Store 결과가 Apple Music 스트리밍 제공을 보장하지 않습니다. 정확한 Apple Music 카탈로그 검색은 아래 Developer Token 설정 필요 |
| Apple Music | 공식 Apple Music 카탈로그 검색 | `APPLE_MUSIC_DEVELOPER_TOKEN` | Apple Developer에서 MusicKit 키/토큰을 발급해야 합니다 |
| Spotify | 공식 Spotify 카탈로그 검색 | `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | Spotify Developer의 API 권한, Premium 개발자 계정, 개발 모드 5명 제한 등 적용. 해당 모드에서는 검색 요청이 권한 오류를 반환할 수도 있음 |
| 멜론/지니/FLO/벅스/YouTube Music | **미지원** | 공식 재생·검색 API 또는 제휴가 필요 | 실제 검색이 되지 않는데 되는 것처럼 표시하지 않습니다. 원하는 경우 Apple/iTunes 공개 카탈로그에서 곡을 찾아 추천할 수 있으나 국내 플랫폼의 보유 여부가 확인되는 것은 아닙니다 |

검색 결과가 있다는 것은 **그 카탈로그에 수록된 곡을 확인했다**는 뜻이지, 다른 플랫폼도 같은 음원을 제공한다는 보장은 아닙니다.

## 컴퓨터에서 실행

```bash
python server.py
```

`http://localhost:8000`에서 확인할 수 있습니다. 외부 라이브러리 없이 SQLite를 사용하는 로컬 모드에서 작동합니다.

자동 테스트(외부 네트워크 없이 카탈로그 응답을 모의로 테스트):

```bash
python -m unittest discover -s tests -v
```

## GitHub + Render 배포 (기존 주소 그대로)

1. ZIP 압축을 풀어서 안에 있는 `server.py`, `README.md`, `requirements.txt`, `public` 폴더와 테스트 파일을 기존 GitHub `trackroom` 저장소의 **최상위 경로에 같은 이름으로 업데이트**합니다. ZIP 파일 자체를 GitHub에 올리면 안 됩니다.
2. GitHub의 `main` 브랜치에 `Commit changes`를 누르면 Render 자동 배포가 동작합니다. 자동 배포를 꺼둔 경우 Render에서 `Manual Deploy → Deploy latest commit`을 선택하세요.
3. **Start Command:** `python server.py` (기존과 동일)
4. **Build Command:** SQLite 테스트만 할 경우 `echo "No dependencies"` 유지. 외부 PostgreSQL 사용 시 `pip install -r requirements.txt`.
5. `https://trackroom.onrender.com`에서 로그인 후 방 안의 **음원 검색**을 테스트합니다. 배포 URL이 다른 경우 자신의 실제 Render 주소를 사용합니다.

### Spotify 검색 설정(선택)

1. [Spotify for Developers](https://developer.spotify.com/dashboard)에 앱을 만들고 공식 API 정책과 사용 제한을 확인합니다.
2. Render → TRACKROOM → **Environment**에 `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` 환경변수 2개를 비공개로 추가합니다.
3. 재배포해 Spotify 검색 기능을 테스트합니다. 앱의 API 접근 유형에 따라 Spotify가 `403` 등을 반환할 수 있습니다. 이 경우 승인/권한 문제이며, Apple/iTunes 검색으로 대체하거나 Spotify의 허용된 로그인 흐름을 별도 개발해야 합니다.

### Apple Music 공식 카탈로그 검색 설정(선택)

Apple Developer/MusicKit의 개발자 토큰을 발급받아 Render Environment의 `APPLE_MUSIC_DEVELOPER_TOKEN`으로 설정하면, iTunes Store 검색 대신 **Apple Music 공식 카탈로그**를 조회합니다. 이 토큰은 만료일과 Apple 정책을 따릅니다. 토큰을 GitHub 저장소에 업로드하면 안 됩니다.

### 선택 결과 서명 키(선택)

Render Environment의 `TRACKROOM_SELECTION_SECRET`에 **길고 무작위인 비밀 문자열**을 넣으면 서버 재시작 후에도 선택 토큰(15분 만료)이 같은 키로 검증됩니다. 설정하지 않으면 서버 시작마다 새 키를 생성합니다. 이 키 역시 공개하지 않습니다.

## 사용자 데이터 보존 (중요)

Render의 무료 인스턴스 파일 시스템은 영구 저장이 아닙니다. **회원가입/닉네임/좋아요/방/추천곡을 보존하려면 외부 PostgreSQL 데이터베이스가 필요합니다.** 기존 v2의 `DATABASE_URL` 설정을 그대로 사용할 수 있습니다. 서버가 `songs` 테이블의 신규 컬럼을 자동으로 추가합니다. SQLite에서 PostgreSQL로 데이터가 자동 이전되지는 않습니다.

PostgreSQL 사용 시 Build Command를 `pip install -r requirements.txt`로 변경하고 `DATABASE_URL`을 Render의 비밀 환경변수로 설정합니다. 이용자 비밀번호나 비밀 키를 GitHub에 게시하지 마세요.

## 사이트 다음 단계

- 국내 스트리밍 업체의 공식 검색·매핑 연동 권한 확인
- 동일 곡 식별(ISRC 등) 기반 플랫폼 간 검색 매칭
- 무한 버블 캔버스 UI 전환 (현재 버전은 기존 추천 목록 디자인 유지)
- 이메일 인증, 비밀번호 재설정, CSRF 대책, 안전한 신고/차단 및 운영 기능 확충
