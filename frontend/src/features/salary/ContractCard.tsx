/**
 * 연봉 기준 — 연봉 구성(소비 분석 > 절세의 총급여 계산기와 같은 값)을 보여 주고 고친다, 그리고 명세서가 없는 달을 연봉으로 채운다.
 * 채우기: 가계부의 정기 급여 입금으로 실수령을 넣고 세금 · 다른 공제를 거꾸로 낸 초안을 먼저 보여 주고, 고른 달만 저장한다 (추정 표시).
 */
import { useState } from 'react'
import Modal from '../../shared/ui/Modal'
import { won } from '../../shared/format'
import { useLoad } from '../../shared/useLoad'
import type { SalaryParts } from '../insights/api'
import SalaryCalculator from '../insights/SalaryCalculator'
import { salaryApi, type Plan } from './api'

export default function ContractCard({ year, readOnly, onChanged }: { year: number; readOnly: boolean; onChanged: () => void }) {
  const { data: c, reload } = useLoad(() => salaryApi.contract(), [])
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  if (!c) return null
  const m = c.monthly
  const save = async (parts: SalaryParts) => {
    setBusy(true)
    try { await salaryApi.saveContract(parts); setEditing(false); reload(); onChanged() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const openPlan = async () => {
    setError(null)
    try {
      const p = await salaryApi.plan(year)
      setPlan(p)
      const now = new Date().toISOString().slice(0, 7)  // 이번 달은 입금이 들어온 뒤에 — 기본으로 빼 둔다
      setPicked(new Set(p.drafts.filter((d) => d.deposit !== null || d.pay_month < now).map((d) => d.pay_month)))
    } catch (e) { setError((e as Error).message) }
  }
  const apply = async () => {
    if (!plan) return
    setBusy(true)
    try { await salaryApi.applyPlan(year, [...picked].sort()); setPlan(null); onChanged() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <article className="card contract-card">
      <h2>연봉 기준</h2>
      {!c.parts ? (
        <p className="muted small">연봉 구성을 넣으면 한 달 실수령 · 4대보험 · 세금을 추정하고, 명세서가 없는 달을 가계부 입금과 맞춰 채워요.</p>
      ) : (
        <div className="contract-grid">
          <div><span className="muted small">총급여 (세전 · 비과세 뺀 것)</span><strong className="num big">{won(c.gross_salary)}</strong></div>
          {m && (
            <dl className="kv">
              <dt>한 달 정기 급여</dt><dd>{won(m.taxable + m.nontaxable)} <span className="muted small">과세 {won(m.taxable)} · 비과세 {won(m.nontaxable)}</span></dd>
              <dt>4대보험</dt><dd>{won(m.social)}</dd>
              <dt>세금(추정)</dt><dd>{won(m.income_tax + m.local_income_tax)} <span className="muted small">연간 결정세액 ÷ 12 대략값</span></dd>
              <dt>실수령(추정)</dt><dd><b>{won(m.net)}</b></dd>
            </dl>
          )}
          {c.lines && (
            <ul className="contract-lines small">
              {c.lines.lines.map((l) => <li key={l.key}>{l.label} <span className="num">{won(l.income)}</span>{l.taxfree ? <span className="muted"> (비과세 {won(l.taxfree)})</span> : null}</li>)}
            </ul>
          )}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {!readOnly && (
        <div className="form-actions">
          <button onClick={() => setEditing(true)}>{c.parts ? '연봉 구성 고치기' : '연봉 구성 넣기'}</button>
          {c.parts && <button className="primary" onClick={openPlan}>연봉으로 {year}년 채우기</button>}
        </div>
      )}
      <p className="muted small">소비 분석 &gt; 절세의 총급여 계산기와 같은 값이에요 — 여기서 고치면 절세 계산도 같이 바뀌어요.</p>

      {editing && (
        <Modal title="연봉 구성" onClose={() => setEditing(false)} wide>
          <SalaryCalculator value={c.parts} children_={c.parts?.young_children ?? 0} busy={busy} onUse={(parts) => save(parts)} />
        </Modal>
      )}
      {plan && (
        <Modal title={`연봉으로 ${plan.year}년 채우기`} onClose={() => setPlan(null)} wide>
          {plan.note ? <p className="muted">{plan.note}</p> : (
            <div className="plan">
              <p className="small muted">
                명세서가 없는 달만 만들어요{plan.skipped.length ? ` (이미 있는 ${plan.skipped.length}달은 그대로)` : ''}.
                {plan.regular_name ? ` 가계부의 '${plan.regular_name}' 입금을 실수령으로 넣었어요.` : ' 가계부에서 정기 급여 입금을 찾지 못해 모두 추정이에요.'}
                {plan.calibrated_by ? ` 다른 공제는 실제 명세서(${plan.calibrated_by})에 맞췄어요.` : ' 실제 명세서를 하나 올리면 세금과 다른 공제를 더 정확히 가를 수 있어요.'}
              </p>
              <div className="table-scroll">
                <table className="data-table">
                  <thead><tr><th /><th>달</th><th>입금일</th><th>지급</th><th>4대보험</th><th>세금</th><th>기타 공제</th><th>실수령</th><th>근거</th></tr></thead>
                  <tbody>
                    {plan.drafts.map((d) => {
                      const on = picked.has(d.pay_month)
                      return (
                        <tr key={d.pay_month} className={on ? '' : 'muted'}>
                          <td><input type="checkbox" checked={on} aria-label={`${d.pay_month} 넣기`}
                            onChange={() => { const n = new Set(picked); if (on) n.delete(d.pay_month); else n.add(d.pay_month); setPicked(n) }} /></td>
                          <td className="mono">{d.pay_month}</td>
                          <td className="mono small">{d.paid_on?.slice(5) ?? '—'}</td>
                          <td className="num">{won(d.taxable_pay + d.nontaxable_pay)}</td>
                          <td className="num">{won(d.national_pension + d.health_insurance + d.long_term_care + d.employment_insurance)}</td>
                          <td className="num">{won(d.income_tax + d.local_income_tax)}</td>
                          <td className="num">{d.other_deductions ? won(d.other_deductions) : '—'}</td>
                          <td className="num"><b>{won(d.net)}</b></td>
                          <td className="small plan-basis">{d.basis}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              {plan.others.length > 0 && (
                <>
                  <h3 className="small">정기 급여가 아닌 큰 입금</h3>
                  <p className="muted small">소급분 · 일시금 · 상여면 명세서 기록에서 종류를 골라 따로 넣어 주세요 (보험금 같은 건 넘기면 돼요).</p>
                  <ul className="small">{plan.others.map((o) => <li key={o.id}>{o.occurred_on} · {o.merchant} · <span className="num">{won(o.amount)}</span></li>)}</ul>
                </>
              )}
              <div className="form-actions">
                <button onClick={() => setPlan(null)}>닫기</button>
                <button className="primary" disabled={busy || picked.size === 0} onClick={apply}>{picked.size}달 기록 (추정 표시)</button>
              </div>
            </div>
          )}
        </Modal>
      )}
    </article>
  )
}
