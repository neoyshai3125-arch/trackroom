# TRACKROOM v6.5 — PWA 홈 화면 설치

기준: TRACKROOM v6.4 (최소 배율 52%, 약 50곡 한눈에 보기).

## 추가 기능
- Android Chrome/삼성 인터넷에서 홈 화면에 TRACKROOM 설치
- iPhone/iPad에서 공유 → 홈 화면에 추가 후 앱 형태로 실행
- 앱 아이콘(192/512 PNG, adaptive/maskable 512, iPhone 180)
- 주소 표시줄 없이 앱 형태로 표시(기기 및 브라우저 지원에 따라 다름)
- 시작 화면 + 기존 방/회원/추천곡 유지, 새로 가입할 필요 없음
- 메인 화면의 `홈 화면에 TRACKROOM 설치` 버튼과 추천방 왼쪽 메뉴의 `TRACKROOM 앱 설치`
- `beforeinstallprompt` 지원 브라우저는 설치창, 미지원 브라우저는 직접 설치 안내
- 기본 정적 화면 파일만 캐시하는 서비스 워커. 인터넷 끊김 안내 페이지.

중요: **오프라인에서 음악/로그인/추천곡 조회는 불가능**. 이 데이터는 기존 서버에서 조회함. 서버와 Neon 데이터베이스는 변경하거나 이전하지 않음.

## 업데이트 ZIP 설치법 (GitHub 저장소 루트 기준)
기존 파일 4개 교체:
- `server.py`
- `public/index.html`
- `public/app.js`
- `public/style.css`

새 파일과 디렉터리 추가:
- `public/manifest.webmanifest`
- `public/sw.js`
- `public/offline.html`
- `public/icons/icon-192.png`
- `public/icons/icon-512.png`
- `public/icons/icon-maskable-512.png`
- `public/icons/apple-touch-icon.png`

다른 파일은 변경하지 않음. `requirements.txt`, `DATABASE_URL` 및 기존 Neon 데이터 유지.

GitHub에서 올바른 경로로 업로드/커밋 → Render 자동 배포 Live → 브라우저 새로고침.
실수로 ZIP의 `public` 디렉터리를 기존 `public` 디렉터리 **안**에 중첩해서 올리지 마세요.

## 설치하기
- Android: TRACKROOM 사이트 접속 → `홈 화면에 TRACKROOM 설치` → 설치 승인. 설치창이 나오지 않으면 Chrome 메뉴(⋮) → `앱 설치` / `홈 화면에 추가`.
- iPhone: Safari 등 지원 브라우저에서 TRACKROOM 사이트 접속 → 공유 → `홈 화면에 추가` → `웹 앱으로 열기`(선택 항목이 있을 경우) → 추가.

## 확인
- `/manifest.webmanifest` 접속시 앱 설정 JSON
- `/sw.js` 접속시 PWA 서비스 워커 JS
- `/icons/icon-192.png` 접속시 앱 아이콘
- `/health`에서 storage가 postgresql인지 확인 (기존 설정 유지)

앱을 설치해도 기존 웹사이트와 동일한 Render 서버·Neon DB를 사용합니다. 다만 iPhone에서는 홈 화면 앱의 쿠키가 브라우저와 다를 수 있어 **최초 1회 다시 로그인**해야 할 수 있습니다. 새 계정을 만들 필요는 없습니다.
