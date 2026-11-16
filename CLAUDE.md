# Mallot Ledger — 개발 안내

Mallot(개인 자산관리 앱)의 가계부만 떼어 낸 공개 저장소. 사용 설명은 [README.md](README.md), 구조는 [docs/architecture.md](docs/architecture.md).
투자 쪽은 별도 저장소 Mallot Invest Agent (`~/mia`) — 같은 뼈대(core · llm · runs · auth)를 쓰지만 코드 · DB · 로그인은 따로다.

## 규칙

- **공개 저장소다.** 실제 거래 · 급여 · 계좌번호 · 카드 이름 · API 키 · DB · `data/` · 뱅크샐러드 내보내기(xlsx · zip) · 캡쳐 이미지는 절대 커밋하지 않는다.
  - 커밋 훅(`make hooks`)과 CI 의 `scripts/check-secrets.sh` 가 막는다.
  - 샘플 · 테스트 값은 지어낸다 (홍길동 · 김밥천국 · 테스트상사).
- **커밋 · PR 에 Claude 공동 작성자 줄이나 "Generated with" 줄을 넣지 않는다.** 기여자는 저장소 주인만 나와야 한다.
- 작업 하나 = 브랜치 하나(`feat/` · `fix/` · `refactor/` · `docs/` · `ci/`) → 작은 커밋(Conventional Commits) → PR → CI 통과 → merge commit 으로 머지.
- 커밋 전에 `make test`(비밀값 · pytest · oxlint · tsc · vite build).
- 실제 LLM · OCR 을 부르는 확인 스크립트는 커밋하지 않는다 (scratchpad 에만). 가짜 LLM · 가짜 OCR 서버를 쓰는 pytest 는 괜찮다.
- 주석 · 화면 글은 한국어.

## 실행

| 명령 | 내용 |
|---|---|
| `make install` | uv · npm 의존성 + 커밋 훅 |
| `make dev` | 백엔드 :8200(--reload) + 프론트 :3200 |
| `make serve` | 프론트 빌드 → 백엔드 하나로 :8200 |
| `make test` | 비밀값 검사 + pytest + 프론트 린트 · 타입 · 빌드 |

- 환경 변수 접두사는 `MLG_` 다 (DB `MLG_DB_PATH`, OCR `MLG_OCR_URL` · `MLG_OCR_MODE`, `MLG_SERVICES=0` 이면 서비스 스레드 끔).
- 이 컴퓨터의 실서버는 systemd `mallot-ledger.service` 다. 다시 켤 때는 `sudo systemctl restart mallot-ledger` — `share.sh` 를 손으로 또 띄우지 않는다.

## 구조 규칙 (tests/test_architecture.py)

- 공용 계층 `core` · `llm` · `runs` 는 기능을 모듈 맨 위에서 불러오지 않는다 (함수 안에서 늦게 부르는 건 된다 — 예: `core.db` 의 `merchant_key`).
- 라우터(`api*.py`)는 다른 모듈이 불러오지 않는다. 같이 쓸 함수는 로직 모듈에 둔다.
- 스키마는 `app/core/migrations.py` 끝에 새 단계로만 더한다 (v1 은 Mallot 가계부 테이블의 마지막 모양 — `import_mallot` 이 기댄다).

## 지켜야 할 것

- 숫자(합계 · 검산 · 세금 · 보험료)는 코드가 계산한다. LLM 은 판독(이미지 · OCR 글 → 칸)과 사실 번호로만 근거를 다는 보고서에만.
- 새 LLM 호출은 `llm.client.structured` · `agentic` 으로만 부르고, 기능 키를 `llm.client.FEATURES` 에 더한다 (이미지를 보면 `IMAGE_FEATURES` 에도).
- OCR · vLLM 주소와 키는 `.env` 로만 — 화면 · API 로 바꾸게 하지 않는다 (캡쳐 · 명세서가 다른 서버로 가지 않게).
- 손님(읽기 전용)에게 보내면 안 되는 값은 `core.access.is_viewer(request)` 로 뺀다. 통째로 막을 GET 은 `auth/guard.VIEWER_CLOSED`.
- 세법 · 요율은 `insights/tax_rules.py` · `salary/rules.py` 에 출처와 함께 둔다. 해가 바뀌면 그 두 파일과 `RULES_YEAR` 를 고친다.
