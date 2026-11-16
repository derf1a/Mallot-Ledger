# 진입점. 실제 동작은 scripts/*.sh 에 있다.
.PHONY: help install hooks dev serve share tunnel-setup admin-password test check-secrets import-mallot import eval

help: ## 명령 목록
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'

install: hooks ## 백엔드(uv)·프론트(npm) 의존성 설치 + git 훅
	cd backend && uv sync
	@if [ -d frontend ]; then cd frontend && npm install; fi

hooks: ## 커밋마다 비밀값 검사 (pre-commit)
	@git config core.hooksPath .githooks && echo "[hooks] .githooks 사용"

dev: ## 개발 모드: 백엔드 :8200 + 프론트 :3200 (Ctrl+C로 둘 다 종료)
	@scripts/dev.sh

serve: ## 프론트 빌드 후 백엔드 하나로 서빙 (http://localhost:8200)
	@scripts/serve.sh

share: ## 인터넷에 열기: 로그인 필수 서버 + Cloudflare 터널 (내 도메인 설정이 없으면 임시 주소)
	@scripts/share.sh

tunnel-setup: ## 내 도메인 고정 주소 만들기 (HOST=ledger.example.com, 먼저 cloudflared tunnel login)
	@scripts/tunnel-setup.sh "$(HOST)"

admin-password: ## 관리자 비밀번호 정하기 (.env 에 해시로)
	@cd backend && uv run python -m app.auth.passwd

test: ## 비밀값 검사 + pytest + 프론트 린트·타입체크·빌드
	@scripts/test.sh

check-secrets: ## 추적 중인 파일 전체에서 비밀값 찾기
	@scripts/check-secrets.sh

import-mallot: ## Mallot DB 의 가계부 데이터 옮기기 (DB=~/Mallot/data/wt.db, 이미지도: ARGS=--images)
	@cd backend && uv run python -m app.ledger.import_mallot "$(DB)" $(ARGS)

import: ## 뱅크샐러드 가계부 내보내기(xlsx/zip) 가져오기 (FILE=경로)
	@cd backend && uv run python -m app.importer.cli "$(FILE)" $(ARGS)

eval: ## 캡쳐 판독 재평가 — 확인된 판독을 다시 읽어 정확도 비교 (ARGS="--via ocr --limit 20")
	@cd backend && uv run python -m app.capture.eval_cli $(ARGS)
