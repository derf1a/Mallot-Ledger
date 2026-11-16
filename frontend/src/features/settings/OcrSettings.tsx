/** 설정 > OCR — Unlimited-OCR-2 서버 상태와 판독 시험. 주소 · 키 · 판독 방식은 .env 로만 바꾼다 (docs/ocr.md). */
import { useState } from 'react'
import { useReadOnly } from '../../shared/readOnly'
import { useLoad } from '../../shared/useLoad'
import { ocrApi, type OcrRead } from './api'

const MODE_KO = {
  auto: 'auto — OCR 서버가 있으면 OCR → LLM 정리, 안 되면 Vision',
  ocr: 'ocr — OCR 만 (서버가 안 되면 판독 실패)',
  vision: 'vision — OCR 을 쓰지 않고 Vision LLM 이 이미지를 직접 읽음',
} as const

export default function OcrSettings() {
  const readOnly = useReadOnly()
  const { data: st, error, reload } = useLoad(() => ocrApi.status(), [])
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [read, setRead] = useState<OcrRead | null>(null)
  const [fail, setFail] = useState<string | null>(null)
  const test = async () => {
    if (!file) return
    setBusy(true)
    setFail(null)
    setRead(null)
    try {
      setRead(await ocrApi.test(file))
    } catch (e) {
      setFail((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      {error && <p className="error">{error}</p>}
      <article className="card">
        <h2>캡쳐 판독 OCR — Unlimited-OCR-2</h2>
        <p className="muted small">
          카드 · 은행 앱 캡쳐와 급여명세서를 읽을 때 OCR(baidu/Unlimited-OCR-2, MIT)이 글자를 읽고, LLM 은 그 글만 보고 거래 · 명세서 칸으로 나눠요.
          모델은 GPU 가 있는 곳에서 SGLang 으로 띄우고 주소를 <code>.env</code> 에 넣어요. 주소가 없으면 Vision LLM 이 이미지를 직접 읽어요.
        </p>
        {st && (
          <dl className="kv">
            <dt>판독 방식</dt>
            <dd>{MODE_KO[st.mode]}</dd>
            <dt>지금 쓰는 경로</dt>
            <dd>{st.enabled ? `OCR(${st.model}) → LLM 정리` : 'Vision LLM'}</dd>
            <dt>OCR 서버</dt>
            <dd>
              {!st.configured ? '주소 없음 (MLG_OCR_URL)'
                : st.reachable ? <>연결됨 {st.served?.length ? <span className="muted">· {st.served.join(', ')}</span> : null}</>
                  : <span className="error">연결 안 됨 — {st.error}</span>}
            </dd>
            {st.url && (<><dt>주소</dt><dd className="mono">{st.url}</dd></>)}
            <dt>crop_mode</dt>
            <dd>{st.crop_mode === null ? '보내지 않음 (omit)' : st.crop_mode ? '켜짐 — 한 쪽을 잘게 나눠 읽음 (세로로 긴 캡쳐에 맞음)' : '꺼짐'}</dd>
            <dt>.env</dt>
            <dd className="mono small">{st.env_keys.join(' · ')}</dd>
          </dl>
        )}
        <div className="form-actions">
          <button onClick={reload}>다시 확인</button>
        </div>
      </article>
      {!readOnly && (
        <article className="card">
          <h2>판독 시험</h2>
          <p className="muted small">이미지 한 장을 OCR 로만 읽어 글을 보여 줘요. 거래로 저장하지 않아요.</p>
          <div className="form-actions">
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <button className="primary" disabled={!file || busy || !st?.configured} onClick={test}>{busy ? '읽는 중…' : 'OCR 로 읽기'}</button>
          </div>
          {fail && <p className="error">{fail}</p>}
          {read && (
            <>
              <p className="muted small">{read.model} · {(read.duration_ms / 1000).toFixed(1)}초{read.tokens ? ` · ${read.tokens} 토큰` : ''}</p>
              <pre className="ocr-text">{read.text}</pre>
            </>
          )}
        </article>
      )}
    </>
  )
}
