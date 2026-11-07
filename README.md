# TRACKROOM v5.2 — 앨범 커버 복원 패치

Last.fm 검색은 그대로 유지하고, 결과의 **곡 제목과 아티스트**를 Apple의 공개 iTunes Search API에 매칭하여 앨범 커버를 표시합니다. Last.fm에서 받은 이미지를 직접 사용하지 않습니다.

## 적용되는 기능

- Last.fm 검색 결과에 iTunes에서 **동일 곡/아티스트로 확인된** 이미지가 있으면 썸네일 표시
- 결과 선택 후 등록 시 이미지가 없다면 한 번 더 개별 매칭 시도
- 무한 버블 캔버스의 기존 이미지 표시 코드 유지
- **이전에 등록한 Last.fm 곡**을 위해 캔버스 오른쪽의 `▧` 버튼 추가: 클릭 한 번에 최대 4곡 검사 및 채우기. 커버가 없는 곡이 더 있다면 다시 클릭할 수 있습니다.
- Apple 스토어 원본 링크를 상세 카드에 추가
- 매칭 불가 / Apple API 오류 시 **잘못된 사진을 임의로 붙이지 않고** 기존 기본 아이콘 유지. Last.fm 검색/등록 기능 자체는 영향 없음.

## 설치 (기존 GitHub 저장소)

`trackroom-artwork-v5.2-update-only.zip`에 포함된 다음 파일들을 **같은 경로에 교체**하고 `Commit changes` 하세요.

```
server.py
public/app.js
public/index.html
public/style.css
```

Render는 `python server.py` 그대로, 기존 `LASTFM_API_KEY` 그대로 사용합니다. 새 API 키는 필요하지 않습니다.

> 데이터 보존: Render 무료 서비스의 재배포/재시작 과정에서 SQLite 데이터가 사라질 수 있습니다. 기존 정보가 중요하면 먼저 영구 DB를 연결해야 합니다.

> 권리 주의: 이 코드는 개발/검증용입니다. iTunes Search API는 이미지의 홍보 목적 사용과 Apple 스토어 연결 및 공식 배지 등의 조건을 요구합니다. Last.fm API에서는 이미지·아트워크 재사용이 제외됩니다. 테스트용 Render URL도 외부에서 접속할 수 있으므로 공개 서비스에서는 권한을 추가 검토하고 공식 배지 및 제휴 조건을 충족해야 합니다.

## 테스트

```
python -m unittest discover -s tests -v
```

이 테스트는 API의 실제 검색 결과가 아닌 모의 응답을 사용해 정확한 곡 매칭과 서버 등록을 검증합니다. **실제 Apple/iTunes 검색 성공은 배포 후 확인해야 합니다.**
