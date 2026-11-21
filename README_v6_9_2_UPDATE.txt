TRACKROOM v6.9.2 — 방 재생 화면 버튼 / 하단 재생바 업데이트

대상: TRACKROOM v6.9.1이 적용된 기존 GitHub 저장소
업데이트 유형: 프런트엔드 변경만, DB·계정·방 데이터는 수정하지 않음.

적용 방법
1. ZIP을 압축 해제합니다.
2. GitHub 저장소 main 브랜치 맨 위에서 Add file → Upload files를 누릅니다.
3. ZIP에 들어 있는 public 폴더와 frontend, tests 폴더를 기존 저장소 루트에 같은 경로로 업로드합니다.
   - 기존 public/index.html, public/app.js, public/room-bubbles.css, public/sw.js를 교체
   - frontend/room-bubbles.css를 교체(나중에 번들 재빌드해도 스타일 유지)
   - tests/test_pwa_v65.py를 교체하고 tests/test_room_player_v692.py를 추가
   - README_v6_9_2_UPDATE.txt는 배포에는 필수는 아닙니다.
4. Commit changes 후 Render에서 최신 커밋이 Live 상태인지 확인합니다.
5. 설치된 TRACKROOM 앱을 완전히 닫았다 열고 방 메뉴 버전 v6.9.2를 확인합니다.

변경 내역
- 방 탐색: 재생 중인 버블은 주변 버블의 약 1.5배. 버블 안의 이전/재생/다음 아이콘은 테두리 없는 투명 버튼.
- 확대 재생 화면: 재생/일시정지는 커버 원 중앙에, 이전/다음은 원 밖 좌우에 표시.
- 이전 버튼은 직전 재생곡으로, 다음 버튼은 무작위 추천곡으로 이동.
- 확대 모달 안에서도 기존의 동일한 하단 재생바가 표시되어 곡명, 재생 제어, 위치 탐색을 계속 사용할 수 있음.
- 배경이나 닫기 버튼을 누르면 방으로 돌아가며 재생은 유지.
- 서비스 워커 캐시 이름/파일 주소를 v6.9.2로 바꿔 PWA 갱신.

주의
- 사용자, 방, 노래 정보를 저장하는 server.py나 DATABASE_URL은 변경하지 마세요.
- Apple 미리듣기가 제공되는 곡에서만 앱 내 오디오 재생이 가능합니다.
- 외부 환경(Render/휴대폰)의 실제 동작은 배포 후 확인해야 합니다.
