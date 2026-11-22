# TRACKROOM v6.10.0 — Android MediaSession 연동 개발 버전

이 ZIP은 TRACKROOM v6.9.9를 기반으로 외부 안드로이드 스트리밍 앱의 재생 정보를 읽어 앱 화면에 반영하는 **개발용 소스**입니다. 완성 APK가 아니며 Android SDK/Gradle을 사용한 빌드 및 멜론 실기기 검증은 아직 실시하지 않았습니다.

## 구현된 기능

- `TrackroomNotificationListener`: Android 사용자가 **설정에서 직접 허용**하는 알림 접근 서비스. 알림의 제목/내용은 읽지 않으며, 다른 앱의 미디어 세션 조회 자격으로만 이용합니다.
- `ExternalMediaSessions`: 사용자 선택 음악 앱(멜론, 지니, FLO, 벅스, YouTube Music, Spotify)의 MediaSession만 선택하여 현재 곡 제목, 아티스트, 앨범명, 재생/정지 상태, 재생 위치, 길이, 지원 명령을 전달합니다. 곡 재생 중인 정확한 위치는 재생 속도/마지막 갱신 시간을 기준으로 표시합니다.
- TRACKROOM 웹의 음악 상세/원형 재생 화면에 '앱 재생 상태 동기화' 패널 추가. 현재 연결 상태와 음악 정보, 재생/일시정지/이전/다음/시간 이동 버튼을 표시합니다.
- **사용자가 '음악 앱에서 재생'을 누른 경우에만** 원형 플레이어 및 하단 바가 외부 앱의 음악 정보/재생 위치를 따라갑니다. 기존 30초 미리듣기는 멈추며, 원형 드래그를 통한 재생 위치 조정도 외부 앱이 지원하는 경우에만 전송합니다. 앨범 커버는 회전하지 않습니다. 외부 곡이 현재 추천곡과 다르면 잘못된 앨범 커버를 표시하지 않습니다.
- `playFromSearch`가 `PlaybackState.ACTION_PLAY_FROM_SEARCH`로 **광고된 경우에만** 곡+아티스트 재생을 요청합니다. 이는 곡 지정 재생을 확정하는 기능이 **아니며** 앱이 무시하거나 다른 음원을 재생할 수 있습니다. 지원하지 않으면 기존과 마찬가지로 앱/곡 페이지를 열어 직접 재생하도록 돕습니다.
- 기존 v6.9.9 Spotify 인증 및 API 연결 코드는 유지합니다. 단, Spotify의 개발자 권한/상용화 정책을 확인해야 합니다.

## 설치/검증

1. 웹 코드 적용: `public`, `frontend`, `tests` 폴더를 기존 TRACKROOM GitHub 저장소 루트의 같은 위치에 덮어쓰고 새 파일도 추가합니다. `public/native-streaming.js`, `public/native-streaming.css`, `public/app.js`, `public/index.html`, `public/sw.js`를 빠짐없이 업로드합니다. README 파일은 웹사이트에 필수는 아닙니다.
2. GitHub Commit → Render 배포 Live → 앱을 재실행. 방 메뉴에 **v6.10.0** 표시 확인.
3. Android Studio로 `android/` 폴더를 **별도 Android 프로젝트**로 열어 Gradle Sync. 이 프로젝트는 AGP 8.9.2 / Kotlin 2.0.21 / JDK 17 / Android SDK 35 / Gradle 8.11.1 조합을 기준으로 작성했습니다. 소스 패키지에는 Gradle wrapper 실행 바이너리가 포함되어 있지 않으므로, 로컬 Gradle 또는 wrapper 생성이 필요할 수 있습니다.
4. USB 디버깅으로 갤럭시에서 앱 실행. 첫 실행 시 TRACKROOM의 기존 **HTTPS 배포 주소**를 정확하게 입력합니다. PWA로만 설치한 앱에서는 Android 네이티브 MediaSession 기능을 이용할 수 없습니다.
5. 방에서 추천곡을 선택한 뒤 '내 스트리밍 앱으로 듣기'에서 `멜론`을 선택합니다. '안드로이드 알림 접근 권한 연결' → Android 설정 → **TRACKROOM 음악 재생 상태 연결**을 허용합니다. 이 설정은 일반 권한 팝업이 아닌 별도 시스템 설정입니다.
6. 멜론 앱을 열어 아무 곡이나 직접 재생하고 TRACKROOM으로 복귀합니다. 곡명/아티스트/재생 상태/현재 시간이 들어오는지 확인합니다. 직접 정지·재생·탐색 버튼을 눌러 멜론 상태가 반영되는지 확인합니다.
7. 멜론에서 `METEOR · 창모`를 수동으로 재생하여 정보가 올바른지 확인합니다. `이 추천곡 재생 요청` 버튼은 멜론이 지원 명령을 제공할 때만 나타납니다. 표시되더라도 눌렀을 때 실제 정확한 곡이 재생되는지 확인해야 합니다.
8. 갤럭시의 안드로이드 버전, 멜론 버전, TRACKROOM 연결 상태와 문제가 나타난 단계를 기록합니다. 특별히 알림 접근 권한이 표시되지 않으면 앱이 '제한된 설정'으로 설치된 것인지도 확인합니다.

## 제약 및 개인정보 보호

- Android의 알림 접근 권한은 **원래 다른 알림에 대한 광범위한 접근을 허용할 수 있는 권한**입니다. TRACKROOM은 실제로는 음악 앱의 MediaSession API만 이용하고, 알림 텍스트/메시지/음원/계정 토큰을 수집하지 않습니다.
- 음악 세션 메타데이터는 **사용자가 앱을 보고 있을 때** 앱 WebView에만 전달합니다. 이번 버전은 서버 업로드, 계정별 청취 기록 저장, 다른 방 이용자에게 방송/동기화 기능을 추가하지 않았습니다.
- 사용자 선택 앱이 MediaSession을 제공하지 않거나 현재 실행 중인 세션이 없으면 정보를 읽을 수 없습니다. 권한이 있어도 세션 검색 기능이 지원되지 않을 수 있습니다.
- PlaybackState가 `playFromSearch`, `seekTo`, `skipToNext` 등을 제공하지 않으면 해당 명령을 수행하지 않습니다. 성공 메시지는 **명령 전달**을 뜻하며 실제 재생 성공을 보장하지 않습니다.
- 정확한 음원 ID 매핑, 타 스트리밍 앱 자동 재생, Android 백그라운드 상시 감지, 다른 사용자와 실시간 동기화, iOS 연동, Play Store 배포 심사 대응은 아직 구현하지 않았습니다.
- 이 파일에는 서버 전체 저장소의 다른 파일(`server.py`, `home.js`, `style.css` 등)은 포함되지 않으므로 기존 파일을 삭제하지 마세요.
- 정확한 실제 지원 여부와 버그는 휴대폰에서 직접 검증해야 합니다.

## 공식 참고

- https://developer.android.com/reference/android/media/session/MediaSessionManager
- https://developer.android.com/reference/android/media/session/MediaController
- https://developer.android.com/reference/android/media/session/MediaController.TransportControls
- https://developer.android.com/reference/android/media/session/PlaybackState
- https://developer.android.com/reference/android/service/notification/NotificationListenerService
