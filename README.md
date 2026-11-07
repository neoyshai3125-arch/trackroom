# TRACKROOM v4 — Last.fm 음악 검색

기존 TRACKROOM 로그인, 닉네임/사용 음원 플랫폼 프로필, 추천방 생성·초대·참여, 추천 이유·구간 저장, 좋아요·삭제 기능을 유지하고 **Last.fm 검색창**을 기본 음원 등록 방식으로 연결한 버전입니다.

## 무엇이 바뀌었나

- 음악 추가에서 **Last.fm 공통 검색**을 사용합니다. Spotify, Apple Music 등 별도 로그인은 필요하지 않습니다.
- **곡 제목 검색 / 아티스트 검색**을 선택할 수 있습니다.
- 제목으로 검색하면 `track.search`, 아티스트로 검색하면 `artist.getTopTracks`를 이용합니다. 복합 검색어인 `아이유 밤편지`처럼 제목 검색 결과가 없으면 아티스트 + 곡 이름 조합도 일부 시도합니다.
- 검색 결과에서 곡을 선택해야만 등록 가능합니다. 선택값은 서버에서 서명하므로 임의 제목을 전송해 곡을 등록할 수 없습니다.
- Last.fm 원본 페이지 링크가 추천곡에 표시됩니다. **곡 정보 및 원본 링크만 이용**하고 Last.fm에서 제공되는 앨범 아트 이미지는 표시/저장하지 않습니다.
- 기존 로그인/추천방/좋아요, 기존 추천곡 목록, 회원의 프로필에 저장된 음원 플랫폼 설정은 그대로 유지됩니다.
- 실제 스트리밍 재생, 다운로드 및 자동 플랫폼 연결 기능은 없습니다.

## 초기 설정: Last.fm API Key

1. https://www.last.fm/api/account/create 로 이동해 Last.fm 계정으로 API 계정을 발급받으세요.
2. Render Dashboard → **TRACKROOM 서비스 → Environment → Add Environment Variable**
3. 이름 **`LASTFM_API_KEY`**, 값 **발급받은 API Key**를 입력해 저장하세요. **API Secret은 필요하지 않습니다.**
4. 이 키를 GitHub나 브라우저 스크립트에 직접 넣지 마세요.
5. `server.py`와 `public` 폴더의 3개 파일(`index.html`, `app.js`, `style.css`)을 기존 GitHub 저장소의 동일 경로에 교체한 뒤 Commit합니다.
6. Render에서 새 배포가 완료되면 로그인 후 추천방에서 **곡 제목 검색** 또는 **아티스트 검색**을 선택해 시험합니다.

### Render 설정

- Build Command: 기존 SQLite 구성이라면 `echo "No dependencies"`를 유지해도 됩니다.
- Start Command: `python server.py` 그대로 유지합니다.
- `DATABASE_URL`을 사용하는 PostgreSQL 구성이라면 Build Command에 `pip install -r requirements.txt`가 필요합니다.
- 무료 Render의 로컬 SQLite는 영구 저장이 아닙니다. 서버 재시작/재배포 시 회원정보와 방·추천곡이 사라질 수 있으므로 실사용에는 지속형 데이터베이스가 필요합니다.
- API 키 누락 시 검색창은 오류 내용을 보여주고 다른 기능은 계속 작동합니다.

### GitHub에 업로드할 파일 구조

ZIP을 **압축 해제한 안쪽 파일들**을 기존 저장소 최상위에 같은 경로로 반영하세요.

```text
trackroom/
├── server.py           ← 변경
├── README.md           ← 변경
├── requirements.txt    (변경 없음)
├── .gitignore          (변경 없음)
├── public/
│   ├── index.html      ← 변경
│   ├── app.js          ← 변경
│   ├── style.css       ← 변경
│   └── favicon.svg     (변경 없음)
└── tests/
    ├── test_server.py
    └── test_lastfm.py   ← 추가
```

GitHub에 `trackroom-lastfm-v4` 하위 폴더를 별도로 만들면 기존 배포 서버가 새 코드를 못 읽습니다. **파일 경로 그대로 교체**하세요. DB나 `.env` 파일을 업로드하지 마세요.

## 개발/테스트

```bash
python server.py
```

로컬 주소: http://localhost:8000. 실제 Last.fm 검색을 테스트할 때는 실행 전에 `LASTFM_API_KEY`를 환경변수로 설정해야 합니다.

모의 API 테스트(키 및 외부 네트워크 불필요):

```bash
python -m unittest discover -s tests -v
```

## 중요: Last.fm 이용 조건 및 결과 정확도

- Last.fm API 공식 문서: https://www.last.fm/api/show/track.search , https://www.last.fm/api/show/artist.getTopTracks
- API 약관: https://www.last.fm/api/tos
- **Last.fm API 이용약관 2.7은 Last.fm 데이터가 노출되는 공개 페이지에 대해 사전 서면 승인 조건을 명시합니다.** 이미 인터넷에 공개된 TRACKROOM에 올리기 전에 Last.fm으로부터 적절한 허락을 확인하세요. 비상업적 테스트라도 공개 서비스 운영 조건을 별도 확인해야 합니다.
- API 약관은 Last.fm 데이터의 출처 표시를 요구합니다. 화면에 **Powered by Last.fm**과 원본 곡 링크를 포함했습니다.
- **Last.fm 제공 앨범 이미지·오디오는 해당 데이터 사용허락에 포함된다고 가정하지 않습니다.** v4는 이 데이터를 표시하거나 저장하지 않으며, 버블 UI는 추후 별도로 적법하게 확보한 앨범 커버를 사용해야 합니다.
- Last.fm은 이용자 기여 기반 메타데이터 서비스이므로 **검색 결과가 있다고 해서 해당 곡이 공식 발매되었다는 절대적 보장은 없습니다.** 정확도가 중요한 경우 추후 다른 카탈로그와 교차검증해야 합니다.
- Last.fm은 상업적 또는 학술·연구 목적 이용 전에 별도 연락을 안내합니다: partners@last.fm
- API 요청 남용 방지를 위해 1인당 60초에 검색 25회 제한과 2분간 결과 캐시를 사용했습니다. Last.fm 자체의 별도 할당량/사용 제한이 우선 적용됩니다.
