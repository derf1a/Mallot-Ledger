/**
 * 고정비·저금 — 분석 기간의 주수입 배분(저금·고정 지출·변동비·남는 돈 100% 막대)과 정기지출 항목별 계획 vs 실제.
 * 숫자는 코드가 계산한 통계(stats.fixed). 실제 = 정기지출에 연결된 결제를 정기지출 화면과 같은 기간 배정으로 모은 것.
 * 색은 돈의 성격(저금 파랑·고정 지출 주황·변동비 보라)만, 글자는 글자색. 칸에 올리거나 포커스하면 금액·비중.
 */
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { percent, won } from '../../shared/format'
import { useTip } from '../../shared/ui/useTip'
import type { FixedItem, FixedStats } from './api'

interface Seg {
  key: string
  label: string
  amount: number
  color: string
  cls: string
}

export default function FixedSaving({ f }: { f: FixedStats }) {
  const a = f.allocation
  const saving = f.items.filter((i) => i.kind === 'saving')
  const fixed = f.items.filter((i) => i.kind === 'expense')
  return (
    <article className="card insights-wide fixed-card">
      <h2>고정비·저금 <span className="muted small">정기지출 계획 vs 분석 기간 실제 · 기간 평균</span></h2>
      {a ? <AllocationBar a={a} /> : <p className="muted small">설정에서 월 주수입을 넣으면 주수입 배분을 보여 줘요.</p>}
      <div className="fixed-lists">
        <ItemList title="저금·투자" items={saving} planned={f.planned.saving} actual={f.actual.saving} tone="amt-saving" />
        <ItemList title="고정 지출" items={fixed} planned={f.planned.fixed} actual={f.actual.fixed} tone="amt-fixed" />
      </div>
      <p className="muted small">
        항목은 처음 결제된 기간부터 세요. 계획 금액·출금일은 <Link to="/ledger/recurring">정기지출</Link>에서 고쳐요.
      </p>
    </article>
  )
}

function AllocationBar({ a }: { a: NonNullable<FixedStats['allocation']> }) {
  const { box, show, showAt, hide, node } = useTip()
  const segs: Seg[] = [
    { key: 'saving', label: '저금·투자', amount: a.saving, color: 'var(--c-saving)', cls: 'amt-saving' },
    { key: 'fixed', label: '고정 지출', amount: a.fixed, color: 'var(--c-fixed)', cls: 'amt-fixed' },
    { key: 'variable', label: '변동비', amount: a.variable, color: 'var(--c-variable)', cls: 'amt-variable' },
    { key: 'left', label: '남는 돈', amount: Math.max(a.left, 0), color: 'var(--border)', cls: 'muted' },
  ].filter((s) => s.amount > 0)
  const whole = Math.max(a.income, a.saving + a.fixed + a.variable)
  const tip = (s: Seg): ReactNode => (
    <span className="viz-tip-row">
      <i className="viz-tip-key" style={{ background: s.color }} />
      <strong className="num">{won(s.amount)}</strong>
      <span className="muted">{s.label} · 월 주수입의 {percent(s.amount, a.income)}%</span>
    </span>
  )
  return (
    <>
      <div className="stat-row">
        <div><span className="muted">월 주수입</span><strong className="pos">{won(a.income)}</strong></div>
        <div><span className="muted">저금·투자</span><strong className="amt-saving">{won(a.saving)}</strong></div>
        <div><span className="muted">고정 지출</span><strong className="amt-fixed">{won(a.fixed)}</strong></div>
        <div><span className="muted">변동비</span><strong className="amt-variable">{won(a.variable)}</strong></div>
        <div>
          <span className="muted">남는 돈</span>
          <strong className={a.left < 0 ? 'neg' : ''}>{won(a.left)}</strong>
        </div>
      </div>
      <div className="home-alloc" ref={box} onMouseLeave={hide} role="group" aria-label="주수입 배분 (분석 기간 평균)">
        <div className="stack-bar tall">
          {segs.map((s) => (
            <span key={s.key} tabIndex={0} className="stack-seg" aria-label={`${s.label} ${won(s.amount)}`}
              style={{ width: `${(s.amount / whole) * 100}%`, background: s.color }}
              onMouseMove={(e) => show(e, tip(s))} onFocus={(e) => showAt(e.currentTarget, tip(s))} onBlur={hide} />
          ))}
        </div>
        {node}
      </div>
      <ul className="legend">
        {segs.map((s) => (
          <li key={s.key}>
            <i style={{ background: s.color }} />
            {s.label} <span className={s.cls}>{won(s.amount)}</span>
            <span className="muted">· {percent(s.amount, a.income)}%</span>
          </li>
        ))}
        {a.left < 0 && <li className="neg">수입보다 {won(-a.left)} 더 나갔어요 (일회성 큰 지출 제외)</li>}
      </ul>
    </>
  )
}

function ItemList({ title, items, planned, actual, tone }: {
  title: string
  items: FixedItem[]
  planned: number
  actual: number
  tone: string
}) {
  if (!items.length) return null
  return (
    <section className="fixed-list">
      <h3>
        {title} <span className="muted small">계획 {won(planned)} · 실제 <b className={tone}>{won(actual)}</b></span>
      </h3>
      <div className="scroll-x">
        <table className="data-table small fixed-table">
          <thead>
            <tr><th scope="col">항목</th><th scope="col">계획</th><th scope="col">낸 기간 평균</th><th scope="col">낸 기간</th><th scope="col">비교 기간</th></tr>
          </thead>
          <tbody>
            {items.map((i) => {
              const short = i.planned > 0 && i.periods > 0 && i.paid_periods < i.periods
              const varied = i.paid_periods > 1 && i.max - i.min > Math.max(1000, i.paid_avg * 0.05)
              return (
                <tr key={i.id}>
                  <th scope="row">{i.name} <span className="muted">{i.group}</span></th>
                  <td className="num">{i.planned ? won(i.planned) : <span className="muted">없음</span>}</td>
                  <td className="num" title={varied ? `${won(i.min)} ~ ${won(i.max)}` : undefined}>
                    {i.paid_periods ? won(i.paid_avg) : <span className="muted">–</span>}
                    {varied && <span className="muted"> ↕</span>}
                  </td>
                  <td className="num">
                    {i.periods ? <span className={short ? 'chip warn-chip' : 'muted'}>{i.paid_periods}/{i.periods}</span> : <span className="muted">결제 없음</span>}
                  </td>
                  <td className="num">
                    {i.baseline_avg ? <Change now={i.paid_avg || i.window_avg} before={i.baseline_avg} /> : <span className="muted">–</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Change({ now, before }: { now: number; before: number }) {
  const d = Math.round(((now - before) / before) * 100)
  return <span className={d ? '' : 'muted'} title={`비교 기간 평균 ${won(before)}`}>{d > 0 ? '+' : ''}{d}%</span>
}
