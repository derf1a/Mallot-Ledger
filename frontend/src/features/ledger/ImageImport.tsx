import { useEffect, useRef, useState } from 'react'
import type { Category } from '../budget/api'
import { ledgerApi, type Draft, type TxType } from './api'
import { won } from '../../shared/format'
import Modal from '../../shared/ui/Modal'
import SourceBadge from './SourceBadge'

interface Props {
  files: File[]
  categories: Category[]
  onClose: () => void
  onSaved: () => void
}

interface Row extends Draft {
  include: boolean
  extraction_id: number
  draft_index: number
}

/** 캡쳐 이미지 → LLM 판독 → 사용자가 확인·수정 → 저장 */
export default function ImageImport({ files, categories, onClose, onSaved }: Props) {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [progress, setProgress] = useState(0)
  const [errors, setErrors] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const extractionIds = useRef<number[]>([])
  // 이미 저장(확정)한 판독 — 여러 장 저장 중 하나가 실패해 다시 누를 때 건너뛰고, 취소해도 버리지 않는다
  const confirmedIds = useRef<Set<number>>(new Set())

  // StrictMode 에서 effect 가 두 번 실행돼도 LLM 은 한 번만 호출한다
  const startedRef = useRef(false)
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    ;(async () => {
      const all: Row[] = []
      const errs: string[] = []
      for (const [i, file] of files.entries()) {
        try {
          const { extraction_id, drafts } = await ledgerApi.extract(file)
          extractionIds.current.push(extraction_id)
          all.push(...drafts.map((d, draft_index) => ({ ...d, include: d.duplicate_of === null, extraction_id, draft_index })))
        } catch (e) {
          errs.push(`${file.name}: ${(e as Error).message}`)
        }
        setProgress(i + 1)
      }
      setErrors(errs)
      setRows(all)
    })()
  }, [files])

  const update = (idx: number, patch: Partial<Row>) =>
    setRows((prev) => prev && prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))

  // 판독 결과를 저장하지 않고 닫으면 '버림'으로 기록한다 (판독 통계에 쓰임)
  const close = () => {
    for (const id of extractionIds.current) {
      if (!confirmedIds.current.has(id)) ledgerApi.discardExtraction(id).catch(() => undefined)
    }
    if (confirmedIds.current.size) onSaved()
    else onClose()
  }

  const save = async () => {
    if (!rows) return
    setSaving(true)
    try {
      // 판독 1회(이미지 1장)마다 초안별 포함 여부와 최종값을 보낸다 → 서버가 초안 대비 수정 내역을 기록
      for (const id of extractionIds.current) {
        if (confirmedIds.current.has(id)) continue
        const items = rows
          .filter((r) => r.extraction_id === id)
          .map(({ include, draft_index, extraction_id: _e, duplicate_of: _d, warnings: _w, ...r }) => ({
            draft_index,
            include,
            // '분류 필요' 해제는 사용자가 직접 고른 분류일 때만 (AI 추정은 해제하지 않음, 내 규칙은 서버가 판단)
            transaction: include ? { ...r, recurring_id: null, source: 'image' as const, reviewed: r.category_source === 'user' } : undefined,
          }))
        await ledgerApi.confirmExtraction(id, items)
        confirmedIds.current.add(id)
      }
      onSaved()
    } catch (e) {
      setErrors([(e as Error).message])
      setSaving(false)
    }
  }

  const selected = rows?.filter((r) => r.include).length ?? 0

  return (
    <Modal title="캡쳐로 입력" onClose={close} wide>
      {rows === null ? (
        <p className="muted">
          이미지를 판독하는 중… ({progress}/{files.length}) <br />한 장에 10초 정도 걸려요.
        </p>
      ) : (
        <>
          {errors.map((e) => (
            <p key={e} className="error">
              {e}
            </p>
          ))}
          {rows.length === 0 && <p className="muted">읽어낸 거래가 없어요.</p>}
          <div className="draft-list">
            {rows.map((r, idx) => (
              <div key={idx} className={`draft${r.include ? '' : ' excluded'}`}>
                <label className="check">
                  <input type="checkbox" checked={r.include} onChange={(e) => update(idx, { include: e.target.checked })} />
                  <strong>{r.merchant || '(이름 없음)'}</strong>
                  <span className={r.type === 'income' ? 'pos' : ''}>{won(r.amount)}</span>
                </label>
                {r.duplicate_of !== null && <p className="warn-text small">이미 같은 날짜·금액·가맹점 거래가 있어요 (중복 의심)</p>}
                {r.warnings.length > 0 && <p className="warn-text small">⚠ 확인 필요: {r.warnings.join(', ')}</p>}
                {r.category_source && r.category_source !== 'user' && (
                  <span className="badges">
                    <SourceBadge source={r.category_source} />
                  </span>
                )}
                <div className="draft-fields">
                  <input type="date" value={r.occurred_on} onChange={(e) => update(idx, { occurred_on: e.target.value })} />
                  <select
                    value={r.type === 'transfer' ? `transfer:${r.transfer_kind}` : r.type}
                    onChange={(e) => {
                      const [type, kind] = e.target.value.split(':') as [TxType, 'internal' | 'external' | undefined]
                      update(idx, { type, transfer_kind: kind ?? null })
                    }}
                  >
                    <option value="expense">지출</option>
                    <option value="income">수입</option>
                    <option value="refund">정산·환불 입금</option>
                    <option value="transfer:external">타 계좌 이체</option>
                    <option value="transfer:internal">내 계좌 간 이체 (±0)</option>
                  </select>
                  <input
                    type="number"
                    inputMode="numeric"
                    value={r.amount}
                    onChange={(e) => update(idx, { amount: Number(e.target.value) })}
                  />
                  <input value={r.merchant} onChange={(e) => update(idx, { merchant: e.target.value })} />
                  <select
                    value={r.category_id ?? ''}
                    disabled={r.type === 'income' || r.transfer_kind === 'internal'}
                    onChange={(e) => {
                      const id = e.target.value ? Number(e.target.value) : null
                      update(idx, { category_id: id, category_source: id === null ? null : 'user' })
                    }}
                  >
                    <option value="">{r.type === 'transfer' ? '기타 · 분류 필요' : '미분류'}</option>
                    {categories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.icon} {c.name}
                      </option>
                    ))}
                  </select>
                  <input value={r.payment_method} placeholder="결제수단" onChange={(e) => update(idx, { payment_method: e.target.value })} />
                </div>
              </div>
            ))}
          </div>
          <div className="form-actions">
            <button onClick={close}>취소</button>
            <button className="primary" disabled={saving || selected === 0} onClick={save}>
              {selected}건 저장
            </button>
          </div>
        </>
      )}
    </Modal>
  )
}
