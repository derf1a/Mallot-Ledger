# 인터넷에 열기 · 휴대폰에서 쓰기

관리자(나)는 어디서든 비밀번호로 로그인해 모든 화면을 쓰고, 손님은 공유 링크로 **같은 화면을 읽기만** 한다.

| 누가 | 들어오는 길 | 볼 수 있는 것 |
|---|---|---|
| 관리자 | 주소 → 비밀번호 로그인 (7일 유지) | 모든 화면 · 설정 · 기록 · 가져오기 |
| 손님 | 공유 링크 `…/share?k=키` (30일 유지) | 관리자와 같은 화면 — Home · Spending · Budget · Fixed · Salary · Insights · 설정 값 (거래 · 금액 · 급여 포함, 읽기만) |
| 그 밖 | — | 로그인 화면만. API 는 401 |

손님에게 막는 것:

- **바꾸기 전부.** 거래 · 고정비 · 예산 · 급여명세서 기록과 설정 · 가져오기 · 캡쳐 판독 · 보고서 만들기 — 서버가 손님의 쓰기 요청(POST · PUT · DELETE)을 모두 403 으로 막고, 화면도 입력칸을 감추거나 잠근다.
- **키 · 주소 · 통째 내려받기.** vLLM · OCR 서버 주소, DB 파일 경로는 서버가 빼고 보낸다. DB 백업(`/api/system/backup`)은 읽기도 막는다.
- **공유.** 공유 링크 · 키를 보는 API 와 Settings > 공유 · 접근 탭이 없다. `/docs` 도 닫힌다.

받은 링크를 손님이 다시 전달하면 그 사람도 들어온다 (링크가 곧 열쇠). 끝내려면 공유 끄기나 새 키.

### Mallot Invest 와 따로

같은 도메인(`invest.mallot-ai.com` · `ledger.mallot-ai.com`)을 쓰지만 로그인은 완전히 따로다.

- 쿠키 이름이 다르고(`mlg_admin` · `mlg_viewer` ↔ `mia_admin` · `mia_viewer`), 쿠키는 하위 도메인에만 붙는다(Domain 속성 없음).
- 서명 키도 각자의 비밀번호 · 공유 키 · `data/session_secret` 에서 만든다.
- 그래서 투자 쪽 손님 링크 · 로그인으로는 가계부에 들어오지 못하고, 그 반대도 같다 (`tests/test_auth.py`).
- 관리자 비밀번호도 따로 정한다.
- 왔다 갔다: 사이드바 아래 **⇄ Mallot Invest** 로 짝 앱에 간다 (주소는 `ledger.` ↔ `invest.` 로 지금 주소에서 만든다). 투자 쪽에도 같은 링크가 있다.
- 맨 도메인 고르기 화면 · 세 주소를 받는 터널 하나 · systemd 유닛은 별도 저장소 **mallot-home** 이 맡는다.
  거기서는 이 앱을 `SHARE_TUNNEL=0`(서버만)으로 띄운다. 이 문서의 터널 설정은 가계부만 혼자 열 때 쓴다.
- **휴대폰 앱 'Mallot':** 맨 도메인을 열고 공유 → 홈 화면에 추가(아이폰) · 앱 설치(안드로이드)하면 'Mallot' 아이콘이 생기고 고르기 화면에서 시작한다.
  두 앱은 다른 하위 도메인이라 앱 안의 브라우저 화면으로 열리고, 사이드바 아래 **⌂ Mallot 홈** 으로 돌아온다.

## 2. 띄우기

```bash
make share
```

1. 프론트를 빌드한다.
2. 백엔드를 `127.0.0.1:8200` 에 로그인 필수(`MLG_PUBLIC=1`)로 띄운다 (Mallot Invest 는 8100).
3. Cloudflare 터널을 연다.

내 도메인 설정이 없으면 계정 없이 쓰는 **임시 주소**(`https://…trycloudflare.com`)를 받는다. 이 주소는 다시 켤 때마다 바뀐다. 지금 주소는 `data/share-url.txt` 에 있다.

- 공유기 포트를 열 필요가 없다. 터널은 이 컴퓨터에서 Cloudflare 쪽으로 나가는 연결이다.
- 관리자 비밀번호 없이 터널을 거쳐 온 요청은 서버가 막는다 (`Cf-Connecting-IP` · `X-Forwarded-For` 를 보고 403).
- Mac 에서 띄우면 잠들지 않게 한다: 시스템 설정 > 배터리(에너지) > "전원 어댑터 연결 시 자동으로 잠자기 방지", 또는 `caffeinate -s make share`.
- 리눅스 서버에서는 systemd 로 띄운다 (재부팅 · 오류 때 다시 켜짐) — [scripts/mallot-ledger.service](../scripts/mallot-ledger.service):

```bash
sudo cp scripts/mallot-ledger.service /etc/systemd/system/   # User · 경로를 내 것으로 고친 뒤
sudo systemctl enable --now mallot-ledger
sudo systemctl restart mallot-ledger                         # 새 코드 반영 — share.sh 를 손으로 다시 띄우지 않는다
```

손으로 `make share` 를 또 띄우면 systemd 가 띄운 것과 포트를 다툰다. 다시 켤 때는 언제나 `systemctl restart`.

## 3. 내 도메인으로 고정 주소

먼저 도메인을 Cloudflare 에 추가해 둔다 (네임서버가 Cloudflare 여야 한다).

```bash
cloudflared tunnel login                      # 브라우저에서 도메인을 고른다 → ~/.cloudflared/cert.pem
make tunnel-setup HOST=ledger.example.com     # 터널 mallot-ledger 만들기 + DNS + ~/.cloudflared/mallot-ledger.yml
make share                                    # 이제 https://ledger.example.com 으로 열린다
```

- 더 막고 싶으면 Cloudflare Zero Trust > Access 로 관리자 이메일만 들어오게 할 수도 있다.
- 그 경우 손님 링크(`/share`, `/api/auth/share/enter`, `/api/auth/me`)는 Access 에서 빼야 손님이 들어온다.

## 4. 손님에게 공유

관리자 화면 **Settings > 공유 · 접근** 에서 한다.

1. **공유 켜기**
2. 링크 복사, 또는 QR 코드
3. 공유를 끝내려면 **공유 끄기** (바로 끊긴다) 나 **새 키 만들기** (이전 링크와 이미 들어온 손님이 모두 끊긴다)

## 5. 아이폰(크롬 · 사파리)에서

- **손님으로:** 공유 링크를 열면 관리자와 같은 화면이 읽기 전용으로 열린다.
- **관리자로:** 같은 주소(`https://…/`)를 열고 비밀번호로 로그인한다.
  - 손님으로 들어와 있었다면 메뉴 아래쪽 "관리자 로그인"을 누른다.
  - 휴대폰 화면에서는 메뉴가 왼쪽 위 ☰ 로 바뀐다.
- **앱처럼 쓰기:** 공유 버튼 → 홈 화면에 추가하면 아이콘이 생기고, 주소창 없이 앱처럼 열린다.
- **캡쳐 입력:** 관리자로 로그인하면 Spending 의 캡쳐 입력 · Salary 의 명세서 이미지로 휴대폰 스크린샷을 바로 올릴 수 있다.

## 보안 메모

- 쿠키는 HttpOnly · SameSite=Strict, https 면 Secure. 서명 비밀은 `MLG_SESSION_SECRET` 또는 `data/session_secret`(권한 600, git 제외)에 둔다.
- 다른 사이트의 페이지가 이 앱으로 보내는 쓰기 요청은 Origin 검사로 막는다.
- 로그인 · 공유 · 접근 규칙은 [backend/app/auth](../backend/app/auth) 에 있다.
- 손님이 보면 안 되는 값을 새 API 에 더할 때는 `app/core/access.is_viewer(request)` 로 빼고 보낸다.
