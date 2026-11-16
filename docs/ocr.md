# 캡쳐 판독 OCR — Unlimited-OCR-2

카드 · 은행 앱 캡쳐(Spending > 캡쳐 입력)와 급여명세서 이미지(Salary > 명세서 기록)를 읽는 방법은 두 가지다.

| 판독 경로 | 하는 일 | 언제 |
|---|---|---|
| **OCR → LLM 정리** | [Unlimited-OCR-2](https://huggingface.co/baidu/Unlimited-OCR-2)(Baidu, 2026-10, 약 3B, MIT)가 이미지를 글로 읽는다. LLM 은 그 글만 보고 거래 · 명세서 칸으로 나눈다 | `.env` 에 OCR 서버 주소가 있을 때 |
| **Vision LLM** | Claude 가 이미지를 직접 본다 (Mallot 에서 쓰던 방식) | 주소가 없을 때 · OCR 서버가 안 될 때(auto) |

OCR 경로의 장점:

- LLM 에는 이미지가 아닌 글만 간다. 그래서 정리 단계(`ocr_structure`)를 로컬 LLM · vLLM 으로도 보낼 수 있다 (Settings > LLM > 경로).
- 판독 기록(`extraction_logs.ocr_text`)에 OCR 글이 남는다. 그래서 OCR 이 틀렸는지, 정리가 틀렸는지 나눠 볼 수 있다.

## 1. 모델 띄우기 (GPU 가 있는 곳)

모델 카드 기준 테스트 환경은 NVIDIA A800-80GB 이고, CPU 실행은 안내가 없다. 3.3B · bf16 가중치만 6GB 남짓이라 GPU(VRAM 12GB 이상 권장)에서 띄운다.
이 앱을 돌리는 작은 서버(예: CPU 2 · 메모리 7GB VM)에서는 돌리지 않는다.

모델 카드는 맞춤 SGLang 빌드를 권한다. 설치 · 전체 실행 옵션은 카드의 안내를 따른다. 가장 짧은 실행:

```bash
python -m sglang.launch_server \
  --model-path baidu/Unlimited-OCR-2 \
  --served-model-name Unlimited-OCR-2 \
  --chat-template unlimited-ocr \
  --host 0.0.0.0 --port 10000
```

OpenAI 호환 `/v1/chat/completions` 가 열린다. 집 밖 GPU 서버라면 Tailscale 같은 사설망이나 인증 프록시 뒤에 둔다. 키를 걸었다면 `MLG_OCR_API_KEY` 에 넣는다.

## 2. 앱에 연결 (.env)

```bash
MLG_OCR_URL=http://gpu-box:10000/v1
MLG_OCR_MODEL=Unlimited-OCR-2       # 서버의 --served-model-name
MLG_OCR_API_KEY=                    # 서버에 키를 걸었으면
MLG_OCR_MODE=auto                   # auto · ocr · vision
MLG_OCR_CROP_MODE=1                 # 1: 한 쪽을 잘게 나눠 읽음(gundam, 세로로 긴 캡쳐에 맞음) · 0: 한 장 통째로(base) · omit: 보내지 않음
```

- 주소 · 키는 `.env` 로만 바꾼다. 화면에서 바꿀 수 있으면 캡쳐 이미지(카드 내역 · 급여명세서)를 다른 서버로 보내게 만들 수 있어서다.
- 서버를 다시 켜면 반영된다 (`sudo systemctl restart mallot-ledger`).
- **Settings > OCR** 에서 연결 상태를 보고, 이미지 한 장을 OCR 로만 읽어 볼 수 있다 (저장 안 함).

| MLG_OCR_MODE | OCR 서버 있음 | OCR 서버 없음 · 오류 |
|---|---|---|
| `auto` (기본) | OCR → LLM 정리 | Vision 으로 다시 읽음 (판독 기록 `note` 에 남김) |
| `ocr` | OCR → LLM 정리 | 판독 실패 |
| `vision` | Vision | Vision |

## 3. 정확도 비교

확인(저장)한 판독 기록은 정답이 된다. 같은 이미지를 다른 경로로 다시 읽어 칸별 정확도를 잰다.

```bash
make eval ARGS="--via ocr --limit 20"     # OCR → LLM
make eval ARGS="--via vision --limit 20"  # Vision
```

판독 기록의 `model` 은 `Unlimited-OCR-2+claude-…` 처럼 OCR 과 정리 모델을 같이 적는다. `prompt_version` 은 OCR 경로가 `…ocr1` 이다.

## 코드

- [backend/app/ocr/client.py](../backend/app/ocr/client.py) — 요청 모양 · 판독 방식 · 상태
- [backend/app/capture/extractor.py](../backend/app/capture/extractor.py) — `OcrLlmExtractor` (캡쳐 → 거래)
- [backend/app/salary/extract.py](../backend/app/salary/extract.py) — 급여명세서 → 칸

## 확인한 것 · 못 한 것

- 이 저장소의 테스트는 가짜 OCR 서버로 요청 모양 · 판독 방식 · 오류 처리 · 판독 기록을 확인한다 (`tests/test_ocr.py`).
- 실제 모델 출력 형식은 모델 카드에도 다 적혀 있지 않다. 그래서 OCR 글을 그대로 LLM 에 넘기고 칸 나누기는 LLM 이 한다.
- `crop_mode` 를 요청 본문 맨 위에 넣는다(카드의 서버 요청 플래그). 서버 빌드가 이 칸을 모르면 `MLG_OCR_CROP_MODE=omit` 으로 둔다.
