# TRACKROOM — 음악 추천방 + 계정/프로필 버전

**2026-11-06 업데이트:** 로그인 아이디·비밀번호 회원가입, 로그인 유지, 프로필(닉네임/음원 플랫폼) 저장과 수정, 로그아웃 기능을 추가했습니다. 추천방·초대 링크·노래 추천·좋아요·본인 추천곡 삭제는 유지됩니다.

> ⚠️ **꼭 읽어주세요: Render 무료 Web Service의 로컬 SQLite 파일은 서버가 잠들거나 재배포되면 없어집니다.** 회원가입 정보를 장기 보관하려면 Render의 무료 웹서버와 **별도의 외부 PostgreSQL 데이터베이스**를 연결하세요. PostgreSQL 연결 전의 가입 정보는 임시 테스트 데이터입니다. 비밀번호 찾기 기능이 없으니 실사용 계정과 동일한 비밀번호를 사용하지 마세요.

## 1. 기능

- 아이디(영문·숫자 3~24자), 비밀번호(10자 이상), 닉네임, 스트리밍 플랫폼을 선택하여 회원가입
- 비밀번호는 PBKDF2-HMAC-SHA256으로 무작위 salt와 함께 해시로 저장
- HTTP-only SameSite 쿠키 기반 로그인 유지(30일, 서버 보관 세션)
- 프로필 변경 시 과거에 등록한 추천곡 표시 닉네임도 함께 갱신
- 추천방 만들기·참여하기·곡 등록·좋아요·삭제는 서버에서 인증한 계정 기준 처리
- Spotify·Apple Music·멜론·지니·FLO·벅스·YouTube Music·기타/미설정 선택
- **음원 서비스 선택은 프로필 선호도 기록일 뿐 실제 스트리밍 서비스 계정 연결은 아닙니다.**

## 2. 내 컴퓨터에서 테스트

Python 3.9 이상이라면 외부 라이브러리 없이 로컬 SQLite로 작동합니다.

```bash
python server.py
```

브라우저에서 `http://localhost:8000`에 접속하세요.

자동 테스트:

```bash
python -m unittest discover -s tests -v
```

## 3. 기존 GitHub + Render 사이트 업데이트

1. 기존 GitHub 저장소의 루트에 `server.py`, `README.md`, `requirements.txt`, `.gitignore`와 `public/` 폴더를 새 버전으로 업데이트하세요. **zip 파일 자체를 올리면 안 됩니다.**
2. Render의 기존 Web Service가 GitHub의 `main` 브랜치에 연결되어 있다면 새 커밋 후 자동 재배포됩니다. 필요 시 `Manual Deploy → Deploy latest commit`을 누르세요.
3. Render Start Command는 기존대로 `python server.py` 입니다.
4. SQLite로 *임시 테스트*만 한다면 Build Command는 기존 `echo "No dependencies"`를 유지해도 됩니다.
5. 외부 PostgreSQL을 사용한다면 Build Command를 `pip install -r requirements.txt`로 변경하세요.

**기존 익명 버전 주의:** 이전 `tr_user_id`는 비밀번호로 인증된 계정이 아니었으므로 자동으로 새 계정에 귀속하지 않습니다. 기존 익명 사용자가 등록한 글을 새 계정으로 삭제할 수 없습니다. 시험용 방을 새로 만드는 것을 권장합니다.

## 4. 무료 Render + 외부 PostgreSQL로 프로필과 방 정보 보존

연동을 실제로 하려면 Supabase 같은 PostgreSQL 호스팅 서비스에 데이터베이스를 먼저 만듭니다.

1. Supabase에서 새 프로젝트를 만들고 데이터베이스 암호를 별도 보관합니다.
2. 프로젝트의 `Connect`에서 **Session pooler** 연결 문자열을 복사합니다. IPv4 환경인 Render에서 사용할 수 있는 연결 방식입니다.
3. Render → TRACKROOM Web Service → `Environment` → 새 환경변수:

   - **Key:** `DATABASE_URL`
   - **Value:** 복사한 `postgresql://...` 접속 문자열 (예시가 아니라 실제 프로젝트 정보)

4. Render → `Settings` → `Build Command`를 `pip install -r requirements.txt` 로 변경합니다.
5. `Start Command`는 `python server.py` 그대로 둡니다.
6. 재배포하면 최초 실행 때 PostgreSQL에 계정·세션·방·추천곡 테이블이 자동으로 만들어집니다. 초기화는 방 정보를 삭제하지 않고 `CREATE TABLE IF NOT EXISTS`로 진행됩니다. PostgreSQL에서는 모든 테이블에 RLS를 활성화하여 익명 REST API 접근을 막습니다.

**중요:** `DATABASE_URL`은 비밀번호가 포함된 비밀 값입니다. GitHub, 대화 내용, 브라우저 코드 또는 스크린샷에 공개하지 말고 반드시 Render `Environment`의 비밀 변수로만 입력하세요.

**기존 SQLite에 쌓인 내용은 PostgreSQL로 자동 이동하지 않습니다.** 전환 전은 테스트용 데이터로 취급하세요.

## 5. 보안 및 운영 범위

이 버전은 소규모 시범운영용입니다. 기본적인 해시 비밀번호, 로그인 세션, 로그인 시도 제한, 방 권한·글 소유권 확인을 구현했습니다. 그러나 공개 서비스에는 이메일 확인, 비밀번호 재설정, 계정 삭제, 신고·차단, CSRF/악용 대응 강화, 백업, 개인정보처리방침 등이 더 필요합니다.

폴더 구성:

```text
trackroom-mvp/
├── server.py
├── requirements.txt
├── .gitignore
├── README.md
├── public/
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── favicon.svg
└── tests/
    └── test_server.py
```
