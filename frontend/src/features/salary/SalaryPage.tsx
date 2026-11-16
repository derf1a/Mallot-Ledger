/**
 * Salary — 급여명세서 기록과 분석. 숫자는 모두 코드(백엔드 app/salary)가 계산한다.
 * 위에서부터: 올해 숫자(지급 · 실수령 · 실효 세율 · 4대보험 비율 · 연말정산 추정) → 달마다 흐름(실수령 · 4대보험 · 세금 누적 막대)
 * → 명세서 목록(펼치면 검산: 2026 요율 · 실지급액 · 가계부 입금). 기록은 직접 넣거나 명세서 이미지(OCR · Vision)로.
 */
import { Fragment, useState } from 'react'
import { StatTile } from '../../shared/charts'
import { fmtPct, won } from '../../shared/format'
import { useReadOnly } from '../../shared/readOnly'
import { useLoad } from '../../shared/useLoad'
import { Columns, type Col } from '../insights/charts'
import { DEDUCTION_FIELDS, salaryApi, type SalaryView, type Slip } from './api'
import ContractCard from './ContractCard'
import SlipForm from './SlipForm'

const SEGS = [
  { key: 'net', name: '실수령', color: 'var(--series-1)' },
  { key: 'social', name: '4대보험', color: 'var(--series-3)' },
  { key: 'taxes', name: '소득세 · 지방세', color: 'var(--series-2)' },
] as const
const THIS_YEAR = new Date().getFullYear()

export default function SalaryPage() {
  const readOnly = useReadOnly()
  const [year, setYear] = useState<number>(THIS_YEAR)
  const { data, error, reload } = useLoad(() => salaryApi.view(year), [year])
  const [editing, setEditing] = useState<Slip | 'new' | null>(null)
  const years = Array.from(new Set([THIS_YEAR, ...(data?.years ?? [])])).sort((a, b) => b - a)

  return (
    <section className="page salary">
      <div className="page-header">
        <h1>급여</h1>
        <div className="page-header-actions">
          <select value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="연도">
            {years.map((y) => <option key={y} value={y}>{y}년</option>)}
          </select>
          {!readOnly && <button className="primary" onClick={() => setEditing('new')}>명세서 기록</button>}
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {data?.notes.map((n) => <p key={n} className="muted small">{n}</p>)}
      <ContractCard year={year} readOnly={readOnly} onChanged={reload} />
      {data && data.slips.length === 0 && (
        <article className="card">
          <p className="muted">
            {year}년 급여명세서가 아직 없어요. 명세서를 기록하면 실수령 · 4대보험 · 세금 흐름, 2026 요율 검산, 연말정산 환급 추정을 볼 수 있어요.
            명세서 이미지를 올리면 OCR(Unlimited-OCR-2) 또는 Vision 으로 칸을 채워 줘요.
          </p>
        </article>
      )}
      {data && data.slips.length > 0 && (
        <>
          <Tiles d={data} />
          <article className="card">
            <h2>달마다</h2>
            <Columns ariaLabel="달마다 실수령 · 4대보험 · 세금" cols={cols(data)} />
            <p className="chart-legend small">{SEGS.map((s) => <span key={s.key}><i style={{ background: s.color }} />{s.name}</span>)}</p>
          </article>
          {data.estimate && <Estimate d={data} />}
          <article className="card">
            <h2>명세서</h2>
            <ul className="slip-list">
              {[...data.slips].reverse().map((s) => <SlipRow key={s.id} s={s} readOnly={readOnly} onEdit={() => setEditing(s)}
                onDelete={async () => { if (confirm(`${s.pay_month} ${s.kind_ko} 명세서를 지울까요?`)) { await salaryApi.remove(s.id); reload() } }} />)}
            </ul>
          </article>
        </>
      )}
      {editing && <SlipForm slip={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} onSaved={reload} />}
    </section>
  )
}

function cols(d: SalaryView): Col[] {
  return d.months.map((m) => ({
    key: m.month, label: `${Number(m.month.slice(5))}월`,
    segs: SEGS.map((s) => ({ key: s.key, name: s.name, color: s.color, value: m[s.key] })),
    tip: <><b>{m.month}</b><br />지급 {won(m.gross)} · 실수령 {won(m.net)}<br />4대보험 {won(m.social)} · 세금 {won(m.taxes)}</>,
  }))
}

function Tiles({ d }: { d: SalaryView }) {
  const t = d.totals!
  const r = d.rates!
  return (
    <div className="tile-row">
      <StatTile label={`${d.year}년 지급 합계`} value={won(t.gross_pay)} hint={`과세 ${won(t.taxable_pay)} · 비과세 ${won(t.nontaxable_pay)}`} />
      <StatTile label="실수령" value={won(t.net)} hint={r.take_home !== null ? `지급의 ${fmtPct(r.take_home)}` : undefined} />
      <StatTile label="실효 세율" value={r.tax !== null ? fmtPct(r.tax) : '–'} hint={`소득세 · 지방세 ${won(t.taxes)}`} />
      <StatTile label="4대보험" value={r.social !== null ? fmtPct(r.social) : '–'} hint={won(t.social)} />
      {d.change && (
        <StatTile label="정기 급여 변화" value={`${d.change.diff >= 0 ? '+' : ''}${won(d.change.diff)}`}
          hint={`${d.change.from} → ${d.change.to}${d.change.rate !== null ? ` (${d.change.rate >= 0 ? '+' : ''}${fmtPct(d.change.rate)})` : ''}`} />
      )}
    </div>
  )
}

function Estimate({ d }: { d: SalaryView }) {
  const e = d.estimate!
  const p = d.projection!
  return (
    <article className="card salary-estimate">
      <h2>연말정산 추정</h2>
      <p className={`big ${e.refund >= 0 ? 'pos' : 'neg'}`}><b>{e.text}</b></p>
      <dl className="kv">
        <dt>올해 총급여(추정)</dt>
        <dd>{won(e.gross_salary)} <span className="muted small">— 기록 {p.covered_months}달 + 기록 없는 {p.filled_months}달 × 최근 정기 급여 {won(p.avg_regular_taxable)}</span></dd>
        <dt>원천징수(추정)</dt>
        <dd>{won(e.withheld)} <span className="muted small">소득세 + 지방소득세</span></dd>
        <dt>결정세액(추정)</dt>
        <dd>{won(e.decided)} <span className="muted small">{e.basis_ko}</span></dd>
      </dl>
      {p.note && <p className="small warn-text">{p.note}</p>}
      <p className="muted small">
        세법 · 요율은 {d.rules_year}년 기준이고 부양가족 · 의료비 · 기부금은 넣지 않은 대략값이에요. 공제를 늘릴 방법은 Insights 의 절세 카드에서 볼 수 있어요.
      </p>
    </article>
  )
}

function SlipRow({ s, readOnly, onEdit, onDelete }: { s: Slip; readOnly: boolean; onEdit: () => void; onDelete: () => void }) {
  const bad = s.checks.filter((c) => c.ok === false).length
  return (
    <li className="slip-row">
      <details>
        <summary>
          <span className="slip-month">{s.pay_month}</span>
          <span className="chip small">{s.kind_ko}</span>
          {s.source === 'image' && <span className="chip small muted-chip">이미지</span>}
          {s.source === 'estimate' && <span className="chip small muted-chip">연봉 추정</span>}
          <span className="slip-net num">{won(s.net)}</span>
          <span className="muted small">지급 {won(s.gross_pay)} · 공제 {won(s.deductions)}</span>
          {bad > 0 && <span className="chip warn-chip small">검산 {bad}</span>}
          {s.deposit_note && <span className="chip muted-chip small">입금 없음</span>}
        </summary>
        <div className="slip-detail">
          <dl className="kv">
            {s.employer && (<><dt>회사</dt><dd>{s.employer}</dd></>)}
            {s.paid_on && (<><dt>지급일</dt><dd>{s.paid_on}</dd></>)}
            {DEDUCTION_FIELDS.filter(([k]) => s[k]).map(([k, label]) => <Fragment key={k}><dt>{label}</dt><dd className="num">{won(s[k])}</dd></Fragment>)}
            {s.take_home_rate !== null && (<><dt>실수령 비율</dt><dd>{fmtPct(s.take_home_rate)}</dd></>)}
          </dl>
          {s.checks.length > 0 && (
            <ul className="slip-checks">
              {s.checks.map((c) => <li key={c.key} className={c.ok === false ? 'bad' : c.ok ? 'ok' : 'unknown'}>{c.ok === false ? '✗' : c.ok ? '✓' : '·'} {c.text}</li>)}
            </ul>
          )}
          <p className="small">{s.deposit ? `가계부 입금 확인 — ${s.deposit.occurred_on} ${s.deposit.merchant}` : s.deposit_note}</p>
          {s.memo && <p className="muted small">{s.memo}</p>}
          {!readOnly && (
            <div className="form-actions">
              <button onClick={onEdit}>고치기</button>
              <button className="danger-text" onClick={onDelete}>지우기</button>
            </div>
          )}
        </div>
      </details>
    </li>
  )
}
