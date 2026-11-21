# TRACKROOM Android 스트리밍 연동 v6.9.9 — 개발용 프로토타입

기존 TRACKROOM 웹사이트를 WebView로 불러오고, 곡을 누르면 사용자가 선택한 음원 앱으로 연결합니다. 이 코드는 **완성 APK가 아닌 Android Studio 프로젝트 소스**이며, 실제 Spotify 개발자 인증 및 실기기 검증은 아직 진행되지 않았습니다.

## 이번 버전 기능 범위

| 서비스 | 이 버전에서 하는 일 | 자동 재생 여부 |
| --- | --- | --- |
| Spotify | OAuth PKCE 연결 → Spotify 카탈로그에서 곡 검색 → 사용자가 정확한 버전 선택 → Web API 재생 명령 전달 | **조건부 가능** (Premium, 인증, 활성 재생 기기, API 권한 및 정책 준수 필요) |
| 멜론 / 지니 / FLO / 벅스 / YouTube Music | TRACKROOM에 해당 서비스의 **정확한 HTTPS 곡 주소가 이미 저장된 경우** 곡 주소 열기; 그렇지 않으면 해당 앱을 열고 검색용 곡명·가수명을 클립보드로 복사 | **아직 불가능** (서비스별 승인·공개 재생 인터페이스 미확인) |

자동 재생을 지원하지 않는 서비스에 잘못된 임의의 곡 ID나 비공식 딥링크를 전송하지 않습니다. 기존 30초 Apple 미리듣기는 유지되며, 앱 전용 `내 스트리밍 앱으로 듣기` 버튼에서 외부 앱 연동을 선택할 수 있습니다. 기존 가입자 DB, 서버, 음악 데이터 구조는 수정하지 않습니다.

## 설정 순서

1. ZIP 압축 해제 후 `public`, `frontend`, `tests` 폴더를 기존 GitHub 저장소의 같은 경로로 업로드/덮어쓰고 Render에서 최신 배포 상태를 확인합니다. `public/native-streaming.js`, `public/native-streaming.css`도 **새로 업로드**해야 합니다.
2. 컴퓨터의 **Android Studio**에서 압축 폴더의 `android/`를 별도 프로젝트로 엽니다. Android SDK 35와 JDK 17을 설치하고 Gradle 동기화를 합니다. 기기/에뮬레이터에 실행합니다.
3. 앱 첫 실행 시 기존 TRACKROOM의 **실제 HTTPS 배포 주소**를 입력합니다. 주소와 로그인 상태는 이후 앱에 저장됩니다. 웹사이트 안에서 앱에만 나타나는 보라색 재생 선택 UI를 확인합니다.
4. Spotify 재생을 시험하려면 [Spotify for Developers](https://developer.spotify.com/dashboard)에 테스트용 앱을 등록하고 Client ID를 발급받으세요. 앱 리디렉션 URI에 **`http://127.0.0.1/callback`** (포트 없는 loopback URI)를 등록합니다. 공식 문서는 loopback에서 요청 시 임의 포트를 붙일 수 있도록 허용합니다. Client Secret은 앱에 입력하거나 포함하지 않습니다.
5. Spotify **Premium** 계정 및 개발 앱의 허용 사용자 목록을 확인합니다. 스마트폰에 Spotify 앱을 설치·로그인하고 **Spotify 앱에서 아무 곡이나 한 번 실행해 활성 재생 기기를 만든 뒤**, TRACKROOM에서 `Spotify`를 선택하여 재생을 눌러보세요.
6. 첫 연결 시 Spotify 계정 승인 브라우저 창이 열립니다. 승인 후 `Spotify 연결이 완료됐어요` 페이지가 뜨면 TRACKROOM 앱으로 돌아오세요. Spotify 검색 결과가 뜨면 정확한 곡을 선택하여 재생 명령을 보냅니다.

**참고:** Spotify Web API는 2026년 개발 모드 계정 및 사용자 제한이 있으며, Spotify의 개발자 정책은 상업적 스트리밍 통합을 제한합니다. TRACKROOM을 실제로 상용 출시하려면 Spotify 측 별도 허가/제휴와 최신 정책 검토가 선행되어야 합니다. 멜론·지니·FLO·벅스 등도 서비스 제공자가 외부 앱 재생 명령을 허용하는 공식 계약/API가 필요할 수 있습니다.

## 어떻게 연결되는가

- 브라우저 `public/native-streaming.js`는 `TRACKROOMAndroid/0.1` User-Agent가 있는 경우에만 곡별 서비스 선택 UI를 표시합니다.
- 사용자가 `앱에서 듣기`를 누르면 top-frame에서 `trackroom-native://play?title=...&artist=...&provider=...` URI를 네비게이션합니다. `MainActivity.kt`는 **등록한 TRACKROOM의 HTTPS 출처**에서만 이 이벤트를 받아 실행합니다.
- 별도의 무제한 `addJavascriptInterface`는 사용하지 않습니다. 외부 페이지는 WebView 안에서 실행되지 않고 Android 브라우저로 이동합니다.
- Spotify 연결은 시스템 브라우저에서 OAuth PKCE 인증을 수행하고 `127.0.0.1` 임시 로컬 콜백 서버로 인증을 돌려받습니다. 오디오 파일이나 재생 권한을 TRACKROOM 서버로 전송하지 않습니다.
- 앱 인증 토큰은 현재 프로토타입의 앱 전용 SharedPreferences에 보관됩니다. **정식 출시 전 Android Keystore 또는 동등한 보안 저장 방식으로 교체하고 로그아웃/연결 해제 및 토큰 폐기 UI를 반드시 추가해야 합니다.**

## 제약과 테스트 상태

- 이 패키지는 **서버 전체 저장소가 아니라 v6.9.8 위에 적용하는 부분 업데이트**입니다. 필수 기존 `style.css`, `home.js`, `room-bubbles.js`, `catalog-filters.js` 등은 기존 저장소에서 유지돼야 합니다.
- 현재 개발 환경에는 Android SDK 및 Gradle 실행기가 없어 APK 빌드와 실기기·Spotify 실제 계정 테스트는 진행하지 못했습니다. 정적 JS 구문 확인 및 부분 업데이트 회귀 테스트만 가능합니다.
- Spotify 재생은 성공 응답을 받았다는 사실만 확인할 수 있고, 앱이 실제로 음원을 소리 내어 재생 중인지는 아직 TRACKROOM으로 동기화되지 않습니다. 그 기능은 이후 MediaSession 연동 단계입니다.
- 멜론 등 다른 앱의 **곡 지정 자동 재생은 현재 미구현**입니다. 버튼은 앱/곡 페이지를 열어주는 수준이며 성공 메시지도 자동 재생을 주장하지 않습니다.
- 홈 화면의 기존 탐색 카드와 UI 소스 (`public/home.js`)는 이 ZIP에 포함되지 않아 이번에는 **추천방 선택곡·확대 재생 화면에만 버튼을 적용**했습니다.

## 공식 참고

- https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
- https://developer.spotify.com/documentation/web-api/concepts/redirect_uri
- https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback
- https://developer.spotify.com/documentation/web-api/concepts/quota-modes
- https://developer.spotify.com/policy
- https://developer.android.com/develop/ui/views/layout/webapps/webview
