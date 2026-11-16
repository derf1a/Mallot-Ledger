/** 급여명세서 입력 · 수정 — 직접 넣거나, 명세서 이미지를 OCR(Unlimited-OCR-2) · Vision 으로 읽어 칸을 채운 뒤 고쳐 저장한다 */
import { useState } from 'react'
import Modal from '../../shared/ui/Modal'
import { won } from '../../shared/format'
import { DEDUCTION_FIELDS, salaryApi, type Slip, type SlipInput, type SlipKind } from './api'

const KINDS: { key: SlipKind; label: string }[] = [
  { key: 'regular', label: '정기 급여' }, { key: 'bonus', label: '상여' }, { key: 'retro', label: '소급분' }, { key: 'other', label: '기타' },
]

const thisMonth = () => new Date().toISOString().slice(0, 7)

const emptySlip = (): SlipInput => ({
  pay_month: thisMonth(), paid_on: null, kind: 'regular', employer: '', taxable_pay: 0, nontaxable_pay: 0, national_pension: 0,
  health_insurance: 0, long_term_care: 0, employment_insurance: 0, income_tax: 0, local_income_tax: 0, other_deductions: 0,
  net_pay: null, items: [], memo: '', source: 'manual',
})

const toInput = (s: Slip): SlipInput => ({
  pay_month: s.pay_month, paid_on: s.paid_on, kind: s.kind, employer: s.employer, taxable_pay: s.taxable_pay,
  nontaxable_pay: s.nontaxable_pay, national_pension: s.national_pension, health_insurance: s.health_insurance,
  long_term_care: s.long_term_care, employment_insurance: s.employment_insurance, income_tax: s.income_tax,
  local_income_tax: s.local_income_tax, other_deductions: s.other_deductions, net_pay: s.net_pay, items: s.items, memo: s.memo,
  source: s.source,
})

function Amount({ label, value, onChange, hint }: { label: string; value: number | null; onChange: (v: number | null) => void; hint?: string }) {
  return (
    <label className="field">
      <span>{label}{hint && <span className="muted small"> {hint}</span>}</span>
      <input inputMode="numeric" value={value === null ? '' : value.toLocaleString('ko-KR')}
        onChange={(e) => {
          const raw = e.target.value.replace(/[^\d-]/g, '')
          onChange(raw === '' || raw === '-' ? null : Number(raw))
        }} />
    </label>
  )
}

export default function SlipForm({ slip, onClose, onSaved }: { slip?: Slip; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState<SlipInput>(slip ? toInput(slip) : emptySlip())
  const [busy, setBusy] = useState<'read' | 'save' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [readNote, setReadNote] = useState<string | null>(null)
  const set = (patch: Partial<SlipInput>) => setV({ ...v, ...patch })
  const gross = v.taxable_pay + v.nontaxable_pay
  const deductions = DEDUCTION_FIELDS.reduce((a, [k]) => a + (v[k] ?? 0), 0)

  const read = async (file: File) => {
    setBusy('read')
    setError(null)
    try {
      const d = await salaryApi.extract(file)
      setV({ ...v, ...d, memo: v.memo, source: 'image' })
      setReadNote(`${d.via === 'ocr' ? 'OCR(Unlimited-OCR-2) → LLM' : 'Vision LLM'} 으로 읽었어요 — 숫자를 확인하고 저장하세요${d.note ? ` · ${d.note}` : ''}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  const save = async () => {
    setBusy('save')
    setError(null)
    try {
      await (slip ? salaryApi.update(slip.id, v) : salaryApi.create(v))
      onSaved()
      onClose()
    } catch (e) {
      setError((e as Error).message)
      setBusy(null)
    }
  }

  return (
    <Modal title={slip ? '급여명세서 고치기' : '급여명세서 기록'} onClose={onClose} wide>
      <div className="slip-form">
        {!slip && (
          <label className="slip-read">
            <span>명세서 이미지로 채우기</span>
            <input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy !== null}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) read(f) }} />
            {busy === 'read' && <span className="muted small">읽는 중…</span>}
          </label>
        )}
        {readNote && <p className="muted small">{readNote}</p>}
        <div className="slip-grid">
          <label className="field"><span>귀속 월</span>
            <input type="month" value={v.pay_month} onChange={(e) => set({ pay_month: e.target.value })} /></label>
          <label className="field"><span>지급일</span>
            <input type="date" value={v.paid_on ?? ''} onChange={(e) => set({ paid_on: e.target.value || null })} /></label>
          <label className="field"><span>종류</span>
            <select value={v.kind} onChange={(e) => set({ kind: e.target.value as SlipKind })}>
              {KINDS.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
            </select></label>
          <label className="field"><span>회사</span>
            <input value={v.employer} maxLength={60} onChange={(e) => set({ employer: e.target.value })} /></label>
        </div>
        <h3 className="small">지급</h3>
        <div className="slip-grid">
          <Amount label="과세 지급액" value={v.taxable_pay} onChange={(n) => set({ taxable_pay: Math.max(0, n ?? 0) })} />
          <Amount label="비과세" hint="식대 등" value={v.nontaxable_pay} onChange={(n) => set({ nontaxable_pay: Math.max(0, n ?? 0) })} />
        </div>
        <h3 className="small">공제</h3>
        <div className="slip-grid">
          {DEDUCTION_FIELDS.map(([k, label]) => (
            <Amount key={k} label={label} value={v[k]} onChange={(n) => set({ [k]: n ?? 0 } as Partial<SlipInput>)} />
          ))}
        </div>
        <div className="slip-grid">
          <Amount label="실지급액" hint={`비우면 ${won(gross - deductions)}`} value={v.net_pay} onChange={(n) => set({ net_pay: n })} />
          <label className="field"><span>메모</span>
            <input value={v.memo} maxLength={500} onChange={(e) => set({ memo: e.target.value })} /></label>
        </div>
        <p className="small">지급 {won(gross)} − 공제 {won(deductions)} = <b>{won(gross - deductions)}</b>
          {v.net_pay !== null && v.net_pay !== gross - deductions && <span className="error"> · 실지급액과 {won(v.net_pay - (gross - deductions))} 차이</span>}
        </p>
        {v.items.length > 0 && (
          <details className="small"><summary>명세서 줄 {v.items.length}개</summary>
            <ul className="slip-items">{v.items.map((it, i) => <li key={i}>{it.label} <span className="num">{won(it.amount)}</span></li>)}</ul>
          </details>
        )}
        {error && <p className="error">{error}</p>}
        <div className="form-actions">
          <button onClick={onClose}>닫기</button>
          <button className="primary" disabled={busy !== null || !v.pay_month} onClick={save}>{busy === 'save' ? '저장 중…' : '저장'}</button>
        </div>
      </div>
    </Modal>
  )
}
